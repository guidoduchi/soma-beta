from __future__ import annotations

import json
import sqlite3

import pytest

from soma.communications.contracts.common import Chronology, TrackableIdentity, UNKNOWN_CHRONOLOGY
from soma.communications.contracts.source import ProviderCheckpoint
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS
from soma.communications.queries.coverage import CoverageQueries
from soma.communications.queries.previews import CommunicationPreviews
from soma.communications.services.processing import CommunicationProcessingService
from soma.communications.services.source_config import SourceConfigurationService
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry

from test_communications_source_config import ReadOnlyAdapter, configure, request


class Identities:
    def __init__(self, values):
        self.values = values
        self.fail = False

    def snapshot(self, reader):
        if self.fail:
            raise AssertionError("Immutable replay must precede current owner reads")
        return iter(self.values)


class Proofs:
    def __init__(self):
        self.calls = 0

    def validate_and_consume(self, uow, proof, action, target, revision, fingerprint):
        self.calls += 1
        if proof != "approved-test-proof":
            return None
        uow.connection.execute("INSERT INTO test_proof_consumptions VALUES(?)", (fingerprint,))
        return {"action_code": action, "target": target, "base_revision": revision, "preview_fingerprint": fingerprint}


def setup_processing(database, values=None):
    path, factory = database
    adapter = ReadOnlyAdapter()
    configured, _ = configure(SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter), request())
    adapter.fail = True
    targets = Identities(values if values is not None else [TrackableIdentity("SERVICE_REQUEST", new_uuid4(), 1, "OFFICIAL_SR", "123456789", Chronology(True, 100, "OTHER_PROVIDER_TIME"))])
    jobs = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS))
    proofs = Proofs()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE test_proof_consumptions(fingerprint TEXT PRIMARY KEY)")
    service = CommunicationProcessingService(factory, targets, jobs, adapter=adapter, proof_provider=proofs)
    previews = CommunicationPreviews(factory, adapter, targets)
    return path, factory, configured["target_id"], targets, service, previews, proofs


def test_processing_coalesces_with_truthful_request_audit_and_replays_without_source_or_owner_reads(communication_database):
    path, _, scope, targets, service, _, _ = setup_processing(communication_database)
    payload = {"command_id": new_uuid4(), "source_scope_id": scope, "source_scope_revision": 1}
    first = service.start_processing(payload)
    second = service.start_processing({**payload, "command_id": new_uuid4()})
    assert first == {"job_id": second["job_id"], "coalesced": False, "job_kind": "ORDINARY"}
    assert second["coalesced"] is True
    targets.fail = True
    assert service.start_processing(payload) == first
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM communication_job_scopes").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE action_type='communications.processing.requested'").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM communication_forward_coverage").fetchone()[0] == 0


def test_no_targets_or_unknown_start_cannot_enqueue_or_open_mail_content(communication_database):
    path, _, scope, targets, service, _, _ = setup_processing(communication_database, [])
    payload = {"command_id": new_uuid4(), "source_scope_id": scope, "source_scope_revision": 1}
    with pytest.raises(SomaError) as raised:
        service.start_processing(payload)
    assert raised.value.code == "COMM_NO_TRACKABLE_TARGETS"
    targets.values = [TrackableIdentity("SERVICE_REQUEST", new_uuid4(), 1, "OFFICIAL_SR", "123456789", UNKNOWN_CHRONOLOGY)]
    with pytest.raises(SomaError) as raised:
        service.start_processing(payload)
    assert raised.value.code == "COMM_COVERAGE_BOUNDARY_UNKNOWN"
    with sqlite3.connect(path) as connection:
        folder = connection.execute("SELECT source_folder_id FROM communication_source_folders WHERE source_scope_id=?", (scope,)).fetchone()[0]
        connection.execute("INSERT INTO communication_forward_coverage VALUES(?,?,?,'COMPOSITE','position_token',1234567890123,'PARTIAL',1,100)", (scope, folder, "test-1"))
    result = service.start_processing(payload)
    assert result["job_kind"] == "ORDINARY"
    with sqlite3.connect(path) as connection:
        stored = json.loads(connection.execute("SELECT scope_json FROM communication_job_scopes").fetchone()[0])
    assert stored["lower_bound"] is None


def deep_request(scope):
    return {"source_scope_id": scope, "source_scope_revision": 1, "folder_keys": ["inbox"], "lower_bound": None, "upper_bound": None}


def test_deep_scan_persists_exact_reviewed_fingerprint_without_proof_and_replay_does_not_consume_again(communication_database):
    path, _, scope, _, service, previews, proofs = setup_processing(communication_database)
    value = deep_request(scope)
    preview = previews.preview_deep_scan(value)
    assert preview["confirmation_class"] == "DELIBERATE_DEEP_SCAN"
    assert preview["estimated_messages"] is None and preview["estimated_bytes"] is None
    payload = {**value, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"], "deliberate_action_proof": "approved-test-proof"}
    result = service.start_deep_scan(payload)
    assert service.start_deep_scan({**payload, "deliberate_action_proof": None}) == result
    assert proofs.calls == 1
    with sqlite3.connect(path) as connection:
        saved = connection.execute("SELECT scope_json,preview_fingerprint FROM communication_job_scopes WHERE job_id=?", (result["job_id"],)).fetchone()
        durable = connection.execute("SELECT payload_json FROM durable_jobs WHERE job_id=?", (result["job_id"],)).fetchone()[0]
        assert saved[1] == preview["preview_fingerprint"]
        assert "approved-test-proof" not in saved[0] + durable + str(connection.execute("SELECT payload_json FROM audit_events").fetchall())
        assert connection.execute("SELECT COUNT(*) FROM communication_historical_coverage_segments").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE communication_job_scopes SET preview_fingerprint=NULL WHERE job_id=?", (result["job_id"],))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE communication_job_scopes SET config_revision=NULL WHERE job_id=?", (result["job_id"],))


def test_deep_scan_stale_coverage_precedes_proof_and_audit_failure_rolls_consumption_and_job_back(communication_database, monkeypatch):
    path, _, scope, _, service, previews, proofs = setup_processing(communication_database)
    value = deep_request(scope)
    preview = previews.preview_deep_scan(value)
    payload = {**value, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"], "deliberate_action_proof": "approved-test-proof"}
    with sqlite3.connect(path) as connection:
        folder = connection.execute("SELECT source_folder_id FROM communication_source_folders WHERE source_scope_id=?", (scope,)).fetchone()[0]
        connection.execute("INSERT INTO communication_historical_coverage_segments VALUES(?,?,?,?,?,?,?,?)", (new_uuid4(), scope, folder, '{}', '{}', 'UNKNOWN', new_uuid4(), 100))
    with pytest.raises(SomaError) as raised:
        service.start_deep_scan(payload)
    assert raised.value.code == "COMM_STALE" and proofs.calls == 0
    payload["preview_fingerprint"] = previews.preview_deep_scan(value)["preview_fingerprint"]
    def fail(*args):
        raise RuntimeError("injected request audit failure")
    monkeypatch.setattr(service._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        service.start_deep_scan(payload)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM communication_job_scopes").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM test_proof_consumptions").fetchone()[0] == 0
        assert connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (payload["command_id"],)).fetchone() is None


def test_backfill_selects_all_owner_identifiers_for_target_and_binds_revisions_without_rewinding(communication_database):
    path, _, scope, targets, service, previews, _ = setup_processing(communication_database)
    target = targets.values[0]
    value = {"source_scope_id": scope, "source_scope_revision": 1, "target_identity_ids": [target.target_id],
             "lower_bound": Chronology(True, 1, "OTHER_PROVIDER_TIME").to_response(),
             "upper_bound": Chronology(True, 86401, "OTHER_PROVIDER_TIME").to_response()}
    first = previews.preview_targeted_backfill(value)
    assert first["confirmation_class"] == "AUTO_BOUNDED"
    targets.values.append(TrackableIdentity(target.target_type, target.target_id, 1, "SR_ALIAS", "987654321", target.effective_from))
    second = previews.preview_targeted_backfill(value)
    assert first["preview_fingerprint"] != second["preview_fingerprint"]
    payload = {**value, "command_id": new_uuid4(), "preview_fingerprint": first["preview_fingerprint"]}
    with pytest.raises(SomaError) as raised:
        service.start_targeted_backfill(payload)
    assert raised.value.code == "COMM_STALE"
    payload["preview_fingerprint"] = second["preview_fingerprint"]
    result = service.start_targeted_backfill(payload)
    assert result["job_kind"] == "TARGETED_BACKFILL"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM communication_forward_coverage").fetchone()[0] == 0
    value["upper_bound"] = Chronology(True, 8 * 86400 + 1, "OTHER_PROVIDER_TIME").to_response()
    assert previews.preview_targeted_backfill(value)["confirmation_class"] == "REVIEW_CONFIRM"


def test_coverage_preserves_provider_precision_and_reports_unknown_historical_intervals(communication_database):
    path, factory, scope, _, _, _, _ = setup_processing(communication_database)
    with sqlite3.connect(path) as connection:
        folder = connection.execute("SELECT source_folder_id FROM communication_source_folders WHERE source_scope_id=?", (scope,)).fetchone()[0]
        connection.execute("INSERT INTO communication_forward_coverage VALUES(?,?,?,'COMPOSITE','position_token',1234567890123,'COMPLETE_TO_HIGH_WATER',1,100)", (scope, folder, "test-1"))
        for state in ("BOUNDED_COMPLETE", "UNKNOWN"):
            connection.execute("INSERT INTO communication_historical_coverage_segments VALUES(?,?,?,?,?,?,?,?)", (new_uuid4(), scope, folder, '{}', '{}', state, new_uuid4(), 100))
    value = CoverageQueries(factory).get_coverage({"source_scope_id": scope})
    assert value["folders"][0]["high_water"]["provider_time_source_epoch_ms"] == 1234567890123
    assert value["folders"][0]["historical_state"] == "UNKNOWN"
    assert value["warnings"] == ["COMM_COVERAGE_INCOMPLETE"]


def test_provider_ranges_use_pure_adapter_ordering_and_never_lexical_token_order(communication_database):
    _, _, scope, targets, service, previews, _ = setup_processing(communication_database)
    calls = []
    # Token spelling reverses lexical order. Only adapter authority may compare.
    def compare(lower, upper):
        calls.append((lower, upper))
        return "BEFORE"
    service._adapter.compare_checkpoints = compare
    lower, upper = ProviderCheckpoint("POSITION", "z", None), ProviderCheckpoint("POSITION", "a", None)
    request = {"source_scope_id": scope, "source_scope_revision": 1, "target_identity_ids": [targets.values[0].target_id],
               "lower_bound": lower.to_response(), "upper_bound": upper.to_response()}
    assert previews.preview_targeted_backfill(request)["confirmation_class"] == "REVIEW_CONFIRM"
    assert calls == [(lower, upper)]
    service._adapter.compare_checkpoints = lambda lower, upper: "INDETERMINATE"
    with pytest.raises(ValidationError):
        previews.preview_targeted_backfill(request)
    with pytest.raises(ValidationError):
        previews.preview_deep_scan({**deep_request(scope), "lower_bound": upper.to_response(), "upper_bound": lower.to_response()})


def test_backfill_missing_or_ambiguous_target_uuid_fails_closed(communication_database):
    _, _, scope, targets, _, previews, _ = setup_processing(communication_database)
    target = targets.values[0]
    value = {"source_scope_id": scope, "source_scope_revision": 1, "target_identity_ids": [new_uuid4()],
             "lower_bound": Chronology(True, 1, "OTHER_PROVIDER_TIME").to_response(),
             "upper_bound": Chronology(True, 2, "OTHER_PROVIDER_TIME").to_response()}
    with pytest.raises(SomaError) as raised:
        previews.preview_targeted_backfill(value)
    assert raised.value.code == "COMM_TARGET_STALE"
    targets.values.append(TrackableIdentity("OBJECTIVE", target.target_id, 1, "OBJECTIVE_REFERENCE", "MW-00000001", target.effective_from))
    with pytest.raises(SomaError) as raised:
        previews.preview_targeted_backfill({**value, "target_identity_ids": [target.target_id]})
    assert raised.value.code == "COMM_TARGET_STALE"
