from dataclasses import replace
import io
import sqlite3

import pytest

from soma.communications.contracts.common import Chronology, TrackableIdentity
from soma.communications.contracts.message import CommunicationParticipant, TransientAttachment
from soma.communications.services.matching import CommunicationMatchingService
from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_identity import message
from test_communications_processing_requests import setup_processing


def start(database, values):
    path, factory, source, owners, service, _, _ = setup_processing(database, values)
    owners.lookup = lambda reader, token: (item for item in owners.values if item.normalized_value == token)
    result = service.start_processing({"command_id": new_uuid4(), "source_scope_id": source, "source_scope_revision": 1})
    claim = service._jobs.claim_next(new_uuid4(), 2_000_000_000)
    assert claim.job_id == result["job_id"]
    matching = CommunicationMatchingService(factory, owners, service._jobs)
    return path, factory, owners, matching, claim


def identity(token, kind="OBJECTIVE_TRACKING"):
    return TrackableIdentity("OBJECTIVE", new_uuid4(), 1, kind, token, Chronology(True, 100, "OTHER_PROVIDER_TIME"))


def test_matching_uses_immutable_index_for_exact_subject_body_and_filenames_not_participants(communication_database):
    a, b = identity("MW-00000001"), identity("SR0000001", "SPARE_REQUEST_ALIAS")
    _, factory, owners, matching, claim = start(communication_database, [a, b])
    fingerprint = matching.prepare_run(claim)
    owners.fail = True
    assert matching.prepare_run(claim) == fingerprint
    transient = message(subject="MW-00000001 MW-00000001_suffix mw-00000001", body="(SR0000001)",
        participants=(CommunicationParticipant("TO", 0, "MW-00000001", None),),
        attachments=(TransientAttachment(0, "MW-00000001.pdf", None, 0, io.BytesIO()),))
    with ReadSnapshot(factory) as reader:
        found = tuple(matching.inspect(reader, claim.job_id, transient))
        assert [(item.field, item.offset, item.identity) for item in found] == [("subject", 0, a), ("body", 1, b), ("attachment:0", 0, a)]
    with UnitOfWork(factory) as writer:
        matching.require_current_candidates(writer, claim.job_id, a.normalized_value)
    owners.values.append(identity(a.normalized_value))
    with UnitOfWork(factory) as writer, pytest.raises(SomaError) as raised:
        matching.require_current_candidates(writer, claim.job_id, a.normalized_value)
    assert raised.value.code == "COMM_TARGET_STALE"


def test_matching_candidate_validation_checks_kind_revision_and_removal(communication_database):
    original = identity("MW-00000001")
    _, factory, owners, matching, claim = start(communication_database, [original])
    matching.prepare_run(claim)
    for current in ([], [replace(original, target_revision=2)], [replace(original, identity_kind="OTHER")]):
        owners.values = current
        with UnitOfWork(factory) as writer, pytest.raises(SomaError) as raised:
            matching.require_current_candidates(writer, claim.job_id, original.normalized_value)
        assert raised.value.code == "COMM_TARGET_STALE"


def test_matching_indexes_bound_batches_support_short_and_punctuated_tokens_and_discard_unmatched_content(communication_database):
    values = [identity(f"MW-{i:08d}") for i in range(600)] + [identity("a"), identity("odd / token")]
    path, factory, owners, matching, claim = start(communication_database, values)
    matching.prepare_run(claim)
    with ReadSnapshot(factory) as reader:
        found = tuple(matching.inspect(reader, claim.job_id, message(subject="a (odd / token)", body="UNMATCHED_SECRET_BODY")))
        assert [item.identity for item in found] == values[-2:]
        plan = reader.connection.execute("EXPLAIN QUERY PLAN SELECT token_length FROM communication_match_lengths WHERE job_id=? AND prefix=?", (claim.job_id, "MW-00000")).fetchall()
        assert any("SEARCH" in row[3] for row in plan)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT identity_count FROM communication_match_runs").fetchone()[0] == 602
        assert connection.execute("SELECT COUNT(*) FROM communications").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM communication_match_tokens WHERE token LIKE '%SECRET%'").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM communication_match_tokens WHERE job_id=?", (claim.job_id,))


def test_stale_claim_cannot_change_matching_registry(communication_database):
    path, factory, _, matching, claim = start(communication_database, [identity("MW-00000001")])
    with pytest.raises(JobClaimConflict):
        matching.prepare_run(replace(claim, run_id=new_uuid4()))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM communication_match_runs").fetchone()[0] == 0


def test_interrupted_preparation_is_rebuilt_without_combining_owner_snapshots(communication_database):
    values = [identity(f"MW-{i:08d}") for i in range(300)]
    path, factory, owners, matching, claim = start(communication_database, values)
    def interrupted(reader):
        yield from values[:260]
        raise RuntimeError("injected owner iterator interruption")
    owners.snapshot = interrupted
    with pytest.raises(RuntimeError):
        matching.prepare_run(claim)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state FROM communication_match_runs").fetchone()[0] == "PREPARING"
        assert connection.execute("SELECT COUNT(*) FROM communication_match_tokens").fetchone()[0] == 250
    owners.values = [replace(item, target_revision=2) for item in values]
    owners.snapshot = lambda reader: iter(owners.values)
    matching.prepare_run(claim)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT DISTINCT target_revision FROM communication_match_tokens").fetchall() == [(2,)]
        assert connection.execute("SELECT identity_count FROM communication_match_runs").fetchone()[0] == 300


def test_current_source_revision_is_required_before_reusing_a_matching_snapshot(communication_database):
    path, factory, _, matching, claim = start(communication_database, [identity("MW-00000001")])
    matching.prepare_run(claim)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communication_source_scopes SET revision=revision+1")
    with pytest.raises(SomaError) as raised:
        matching.prepare_run(claim)
    assert raised.value.code == "COMM_STALE"
