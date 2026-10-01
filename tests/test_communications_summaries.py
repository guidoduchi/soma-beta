from dataclasses import replace
import sqlite3

import pytest

from soma.communications.contracts.common import Chronology, TrackableIdentity, UNKNOWN_CHRONOLOGY
from soma.communications.queries.summaries import CommunicationPanelProjectionProvider, CommunicationSummaryProvider, SummaryQueries
from soma.communications.repositories.summaries import freeze_in_uow
from soma.communications.services.matching import CommunicationMatchingService
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes

from test_communications_housekeeping import seed
from test_communications_processing_requests import setup_processing, deep_request
from test_communications_queries import add_link


class Owners:
    def __init__(self, values=()):
        self.values = list(values)
        self.reversed = False

    def target_snapshot(self, reader, kind, target):
        return (item for item in self.values if (item.target_type, item.target_id) == (kind, target))

    def current_revision(self, reader, kind, target):
        return 1

    def validate_reassociation(self, reader, kind, target, revision):
        return "VALID" if self.reversed else "INVALID"


def test_summary_counts_canonical_messages_once_and_uses_latest_known_ties(communication_database):
    path, factory = communication_database
    target = new_uuid4()
    messages = [seed(path, pending=False) for _ in range(5)]
    with sqlite3.connect(path) as db:
        for message, direction, instant, source in zip(messages,
                ("RECEIVED", "SENT", "UNKNOWN", "RECEIVED", "SENT"), (200, 200, 200, None, 100),
                ("RECEIVED_TIME", "SENT_TIME", "OTHER_PROVIDER_TIME", "UNKNOWN", "SENT_TIME")):
            db.execute("UPDATE communications SET direction=?,chronology_known=?,chronology_utc=?,chronology_source_kind=? WHERE communication_id=?",
                       (direction, int(instant is not None), instant, source, message))
            add_link(db, message, target)
            add_link(db, message, new_uuid4())
        add_link(db, messages[0], target, state="CLOSED")
        latest = db.execute("SELECT chronology_source_kind FROM communications WHERE chronology_utc=200 ORDER BY communication_id DESC LIMIT 1").fetchone()[0]
    queries = SummaryQueries(factory, Owners())
    summary = queries.get_entity_summary({"target_type": "OBJECTIVE", "target_id": target})
    assert (summary["received_count"], summary["sent_count"], summary["unknown_count"]) == (2, 2, 1)
    assert summary["last_direction"] == "MIXED"
    assert summary["last_interaction"] == Chronology(True, 200, latest).to_response()
    assert summary["body_navigation_available"] is True
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_links SET state='CLOSED',closed_at_utc=300 WHERE communication_id=? AND state='ACTIVE'", (messages[1],))
    assert queries.get_entity_summary({"target_type": "OBJECTIVE", "target_id": target})["last_direction"] == "UNKNOWN"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET chronology_known=0,chronology_utc=NULL,chronology_source_kind='UNKNOWN'")
    summary = queries.get_entity_summary({"target_type": "OBJECTIVE", "target_id": target})
    assert summary["last_interaction"] == UNKNOWN_CHRONOLOGY.to_response()
    assert summary["last_direction"] == "UNKNOWN"


def coverage_case(database, *, unknown=False, deep=False):
    identity = TrackableIdentity("OBJECTIVE", new_uuid4(), 1, "OBJECTIVE_TRACKING", "MW-00000001",
        UNKNOWN_CHRONOLOGY if unknown else Chronology(True, 100, "OTHER_PROVIDER_TIME"))
    path, factory, source, scan_owners, service, previews, _ = setup_processing(database, [identity])
    if deep:
        value = deep_request(source)
        preview = previews.preview_deep_scan(value)
        result = service.start_deep_scan({**value, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"],
            "deliberate_action_proof": "approved-test-proof"})
    else:
        result = service.start_processing({"command_id": new_uuid4(), "source_scope_id": source, "source_scope_revision": 1})
    claim = service._jobs.claim_next(new_uuid4(), 2_000_000_000)
    assert claim.job_id == result["job_id"]
    CommunicationMatchingService(factory, scan_owners, service._jobs).prepare_run(claim)
    with sqlite3.connect(path) as db:
        folder = db.execute("SELECT source_folder_id FROM communication_source_folders WHERE enabled=1").fetchone()[0]
    owners = Owners([identity])
    query = SummaryQueries(factory, owners)
    return path, factory, source, folder, claim.job_id, owners, query, {"target_type": "OBJECTIVE", "target_id": identity.target_id}


def segment(db, source, folder, job, lower, upper, state="BOUNDED_COMPLETE"):
    serialize = lambda value: canonical_json_bytes(None if value is None else Chronology(True, value, "OTHER_PROVIDER_TIME").to_response()).decode()
    db.execute("INSERT INTO communication_historical_coverage_segments VALUES(?,?,?,?,?,?,?,1)",
        (new_uuid4(), source, folder, serialize(lower), serialize(upper), state, job))


def forward(db, source, folder, *, millis=300000, state="COMPLETE_TO_HIGH_WATER"):
    db.execute("INSERT INTO communication_forward_coverage VALUES(?,?,'test-1','COMPOSITE','safe_token',?,?,1,1)",
        (source, folder, millis, state))


def test_coverage_requires_eligibility_identity_and_contiguous_range_to_precise_checkpoint(communication_database):
    path, _, source, folder, job, owners, queries, target = coverage_case(communication_database)
    with sqlite3.connect(path) as db:
        forward(db, source, folder, millis=300001)
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"
    with sqlite3.connect(path) as db:
        segment(db, source, folder, job, 100, 200)
        segment(db, source, folder, job, 200, 300)
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"
    with sqlite3.connect(path) as db:
        segment(db, source, folder, job, 300, 301)
    assert queries.get_entity_summary(target)["coverage_state"] == "COMPLETE"
    owners.values[0] = replace(owners.values[0], target_revision=2)
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"
    owners.values[0] = replace(owners.values[0], target_revision=1)
    owners.values.append(replace(owners.values[0], identity_kind="OBJECTIVE_ALIAS", normalized_value="new-alias"))
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"


def test_coverage_reduces_every_folder_unknown_before_partial(communication_database):
    path, _, source, folder, job, _, queries, target = coverage_case(communication_database)
    with sqlite3.connect(path) as db:
        forward(db, source, folder, state="PARTIAL")
        segment(db, source, folder, job, 100, 300, "PARTIAL")
    assert queries.get_entity_summary(target)["coverage_state"] == "PARTIAL"
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_source_folders VALUES(?,?,'unproved','Unproved','OTHER',1,1)", (new_uuid4(), source))
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"


def test_reviewed_full_scan_proves_unknown_eligibility_without_inventing_timestamp(communication_database):
    path, _, source, folder, job, owners, queries, target = coverage_case(communication_database, unknown=True, deep=True)
    with sqlite3.connect(path) as db:
        segment(db, source, folder, job, None, None)
    result = queries.get_entity_summary(target)
    assert result["coverage_state"] == "COMPLETE"
    assert result["last_interaction"] == UNKNOWN_CHRONOLOGY.to_response()
    assert owners.values[0].effective_from == UNKNOWN_CHRONOLOGY
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET revision=2")
    assert queries.get_entity_summary(target)["coverage_state"] == "UNKNOWN"


def test_freeze_sequence_same_second_is_transactional_immutable_and_bodyless(communication_database):
    path, factory = communication_database
    target, events = new_uuid4(), [new_uuid4(), new_uuid4()]
    provider = CommunicationSummaryProvider(Owners())
    summary = {"target_type": "SERVICE_REQUEST", "target_id": target, "received_count": 2, "sent_count": 1, "unknown_count": 1,
        "last_interaction": Chronology(True, 200, "RECEIVED_TIME").to_response(), "last_direction": "MIXED", "coverage_state": "COMPLETE"}
    with UnitOfWork(factory) as writer:
        first = freeze_in_uow(writer, summary, events[0], 300)
        assert freeze_in_uow(writer, summary, events[0], 300) == first
    with pytest.raises(RuntimeError), UnitOfWork(factory) as writer:
        freeze_in_uow(writer, {**summary, "received_count": 3}, events[1], 300)
        raise RuntimeError("owner failure after freeze")
    with ReadSnapshot(factory) as reader:
        assert provider.terminal_summary(reader, "SERVICE_REQUEST", target) == first
    with UnitOfWork(factory) as writer:
        second = freeze_in_uow(writer, {**summary, "received_count": 3}, events[1], 300)
    assert first["summary_revision"] == 1 and second["summary_revision"] == 2
    with ReadSnapshot(factory) as reader:
        assert provider.terminal_summary(reader, "SERVICE_REQUEST", target) == second
        panel = CommunicationPanelProjectionProvider(provider).panel(reader, "SERVICE_REQUEST", target)
    assert panel["terminal_frozen"] is True and panel["recent_messages"] == {"items": [], "next_cursor": None}
    assert panel["summary"]["received_count"] == 3 and panel["summary"]["body_navigation_available"] is False
    assert panel["summary"]["coverage_state"] == "COMPLETE"
    provider._identities.reversed = True
    with ReadSnapshot(factory) as reader:
        reversed_summary = provider.entity_summary(reader, "SERVICE_REQUEST", target)
        assert provider.terminal_summary(reader, "SERVICE_REQUEST", target) == second
    assert reversed_summary["coverage_state"] == "UNKNOWN" and "COMM_RECONSTRUCTION_REQUIRED" in reversed_summary["warnings"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communications").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE communication_terminal_summaries SET summary_revision=3")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM communication_terminal_summaries")


def test_summary_and_panel_bounds_and_indexed_range_order(communication_database):
    path, factory = communication_database
    target, owners = new_uuid4(), Owners()
    queries = SummaryQueries(factory, owners)
    for request in ({"target_type": "OBJECTIVE", "target_id": target, "extra": True}, {"target_type": "TASK", "target_id": target}):
        with pytest.raises(ValidationError):
            queries.get_entity_summary(request)
    panel = CommunicationPanelProjectionProvider(CommunicationSummaryProvider(owners))
    with ReadSnapshot(factory) as reader, pytest.raises(ValidationError):
        panel.panel(reader, "OBJECTIVE", target, limit=51)
    with sqlite3.connect(path) as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT lower_bound_json FROM communication_historical_coverage_segments "
            "WHERE source_scope_id=? AND source_folder_id=? ORDER BY json_extract(lower_bound_json,'$.utc_epoch_seconds'),coverage_segment_id",
            (new_uuid4(), new_uuid4())).fetchall()
        assert any("idx_comm_hist_time_range" in row[3] for row in plan)
        assert all("TEMP B-TREE" not in row[3] for row in plan)
