from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import pytest

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.queries.rfc_hard_delete import RfcHardDeleteQueryService
from soma.tickets.rfc_hard_delete import RfcHardDeleteService
from soma.tickets.rfcs import RfcService


@dataclass
class _Classifier:
    status: object
    calls: list = field(default_factory=list)

    def classify_hard_delete_dependency(self, reader, rfc_id):
        self.calls.append(reader)
        assert reader.connection.in_transaction
        if isinstance(self.status, Exception):
            raise self.status
        return self.status

    has_accepted_source_provenance = classify_hard_delete_dependency


@dataclass
class _ProofProvider:
    bindings: dict = field(default_factory=dict)
    consumed: set = field(default_factory=set)
    calls: int = 0

    def issue(self, preview, rfc_id):
        token = new_uuid4()
        self.bindings[token] = ("tickets.rfc.hard_delete", "rfc", rfc_id,
                                preview.rfc_revision, preview.eligibility_fingerprint)
        return token

    def validate_and_consume(self, uow, proof, expected_action, target, base_revision, preview_fingerprint):
        self.calls += 1
        assert isinstance(uow, UnitOfWork)
        assert uow.connection.execute("SELECT count(*) FROM command_receipts WHERE command_type='HardDeleteRfc'").fetchone() == (0,)
        if not isinstance(proof, str) or proof in self.consumed:
            raise ValueError("invalid proof")
        assert self.bindings[proof] == (expected_action, target.target_type, target.target_id,
                                        base_revision, preview_fingerprint)
        self.consumed.add(proof)
        return object()


@pytest.fixture
def deletion(initialized_database):
    path, factory_for_path = initialized_database
    factory = factory_for_path(path)
    providers = [_Classifier("NO"), _Classifier("CLEAR"), _Classifier("CLEAR"), _Classifier("CLEAR")]
    proof = _ProofProvider()
    queries = RfcHardDeleteQueryService(factory, *providers)
    service = RfcHardDeleteService(factory, *providers, proof)
    return factory, providers, proof, queries, service


def _create(factory, *, context="manual", number="NC00000000000001"):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no=number, creation_context=context,
    )


def _counts(factory):
    with ReadSnapshot(factory) as reader:
        return tuple(reader.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("rfcs", "command_receipts", "audit_events", "audit_event_results", "command_receipt_results"))


def _request(rfc, preview, token, command_id=None):
    return dict(command_id=command_id or new_uuid4(), rfc_id=rfc.rfc_id,
                base_revision=preview.rfc_revision, eligibility_fingerprint=preview.eligibility_fingerprint,
                deliberate_action_proof=token)


def test_preview_reproduces_certified_golden_vector_and_uses_one_read_snapshot(deletion, monkeypatch):
    factory, providers, proof, queries, _ = deletion
    ids = iter(("00000000-0000-4000-8000-000000000001", new_uuid4()))
    monkeypatch.setattr("soma.tickets.rfcs.new_uuid4", lambda: next(ids))
    rfc = _create(factory)
    before = _counts(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    assert preview.eligible and preview.blockers == () and preview.rfc_revision == 1
    assert preview.eligibility_fingerprint == "306b168db4d51ded567e2b446dbc101729d8361ab6ade854f9e993d40f36dce4"
    assert {key: value.freshness_token for key, value in preview.provider_freshness.items()} == {
        "source_evidence": "3f942fb5138fe3c6602e91dace34759c10b182f08f2dfc322b06072c623a79a1",
        "tasks_objectives": "4f5657e3f3299bb12bf0022e1cd1c493493360c9824617560af770069ca3c835",
        "inventory": "c5aed512b944da1affabb715227490064c140ea713b8f62ef30734cd64ae550a",
        "communications": "f65ff0ff7acde3a69103c038374b0eeb57fcfd66f7f75fffd2334db2f5f6e1a3",
    }
    assert all(len(p.calls) == 1 and p.calls[0] is providers[0].calls[0] for p in providers)
    assert isinstance(providers[0].calls[0], ReadSnapshot)
    assert proof.calls == 0 and _counts(factory) == before
    assert set(preview.to_response()) == {"eligible", "rfc_revision", "eligibility_fingerprint", "blockers", "provider_freshness"}


@pytest.mark.parametrize("context", ["manual", "provisional"])
def test_delete_retains_evidence_before_delete_and_replays_without_owner_reads(deletion, monkeypatch, context):
    factory, providers, proof, queries, service = deletion
    rfc = _create(factory, context=context)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(preview, rfc.rfc_id)
    request = _request(rfc, preview, token)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TRIGGER test_delete_requires_audit BEFORE DELETE ON rfcs BEGIN "
            "SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_events a JOIN audit_event_results r "
            "ON r.audit_event_id=a.audit_event_id JOIN command_receipts c ON c.command_id=a.command_id "
            "WHERE a.action_type='ticket.rfc.hard_deleted' AND a.target_id=OLD.rfc_id "
            "AND r.result_type='hard_delete_evidence' AND r.result_id=a.audit_event_id) "
            "THEN RAISE(ABORT,'audit must precede delete') END; END"
        )
    result = service.hard_delete(**request)
    assert not result.replayed
    assert _counts(factory) == (0, 2, 2, 2, 2)
    assert all(isinstance(p.calls[-1], UnitOfWork) and p.calls[-1] is providers[0].calls[-1] for p in providers)
    with ReadSnapshot(factory) as reader:
        audit = reader.connection.execute(
            "SELECT audit_event_id,payload_json FROM audit_events WHERE command_id=?", (request["command_id"],)
        ).fetchone()
        assert audit[0] == result.hard_delete_evidence_id
        assert json.loads(audit[1]) == {"rfc_id": rfc.rfc_id, "rfc_no": rfc.rfc_no,
                                      "reviewed_revision": 1, "eligibility_fingerprint": preview.eligibility_fingerprint,
                                      "result": "deleted"}
        assert token not in audit[1]
    def fail_read(*args, **kwargs):
        pytest.fail("replay must not read current owner state")
    monkeypatch.setattr(service._queries, "load_identity", fail_read)
    replay = service.hard_delete(**{**request, "deliberate_action_proof": object()})
    assert replay.replayed and replay.to_response() == result.to_response()
    assert proof.calls == 1 and token in proof.consumed
    assert all(len(p.calls) == 2 for p in providers)
    for change in ({"rfc_id": new_uuid4()}, {"base_revision": 2}, {"eligibility_fingerprint": "0" * 64}):
        with pytest.raises(SomaError, match="IDEMPOTENCY_CONFLICT"):
            service.hard_delete(**{**request, **change})
    assert _counts(factory) == (0, 2, 2, 2, 2)


@pytest.mark.parametrize("provider_index", range(4))
@pytest.mark.parametrize("status", ["BLOCKED", "INDETERMINATE", "clear", None, [], RuntimeError("private provider detail")])
def test_provider_failures_are_closed_in_preview_and_writer_before_proof(deletion, provider_index, status):
    factory, providers, proof, queries, service = deletion
    rfc = _create(factory)
    reviewed = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(reviewed, rfc.rfc_id)
    providers[provider_index].status = "YES" if provider_index == 0 and status == "BLOCKED" else status
    before = _counts(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    assert not preview.eligible and len(preview.blockers) == 1
    expected = "BLOCKED" if status == "BLOCKED" else "INDETERMINATE"
    provider_id = ("source_evidence", "tasks_objectives", "inventory", "communications")[provider_index]
    assert preview.provider_freshness[provider_id].status == expected
    assert preview.blockers[0].source == provider_id
    assert preview.eligibility_fingerprint != reviewed.eligibility_fingerprint
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_BLOCKED"):
        service.hard_delete(**_request(rfc, reviewed, token))
    assert proof.calls == 0 and _counts(factory) == before


@pytest.mark.parametrize("change", ["revision", "fingerprint"])
def test_stale_preview_does_not_consume_proof(deletion, change):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(preview, rfc.rfc_id)
    request = _request(rfc, preview, token)
    if change == "revision":
        with UnitOfWork(factory) as uow:
            uow.connection.execute("UPDATE rfcs SET revision=2 WHERE rfc_id=?", (rfc.rfc_id,))
    else:
        request["eligibility_fingerprint"] = "0" * 64
    before = _counts(factory)
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_PREVIEW_STALE"):
        service.hard_delete(**request)
    assert proof.calls == 0 and _counts(factory) == before


@pytest.mark.parametrize("invalid", [True, None, 3, {"confirmed": True}, "expired-or-consumed"])
def test_invalid_proof_does_not_mutate_database(deletion, invalid):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    before = _counts(factory)
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_CONFIRMATION_REQUIRED"):
        service.hard_delete(**_request(rfc, preview, invalid))
    assert proof.calls == 1 and _counts(factory) == before


@pytest.mark.parametrize("phase", ["audit", "audit_ref", "delete", "result", "commit"])
def test_failure_after_proof_rolls_back_all_database_work_but_proof_stays_consumed(deletion, monkeypatch, phase):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(preview, rfc.rfc_id)
    before = _counts(factory)
    if phase == "commit":
        def fail_commit(self):
            self.rollback()
            raise SomaError("PERSISTENCE_FAILURE", "injected commit failure")
        monkeypatch.setattr(UnitOfWork, "commit", fail_commit)
    else:
        table, operation, condition = {
            "audit": ("audit_events", "INSERT", "NEW.action_type='ticket.rfc.hard_deleted'"),
            "audit_ref": ("audit_event_results", "INSERT", "NEW.result_type='hard_delete_evidence'"),
            "delete": ("rfcs", "DELETE", "1"),
            "result": ("command_receipt_results", "INSERT", "NEW.response_schema='HardDeleteRfcResultV1'"),
        }[phase]
        with UnitOfWork(factory) as uow:
            uow.connection.execute(f"CREATE TRIGGER test_fail BEFORE {operation} ON {table} WHEN {condition} "
                                   "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    with pytest.raises((SomaError, sqlite3.IntegrityError)):
        service.hard_delete(**_request(rfc, preview, token))
    assert token in proof.consumed and _counts(factory) == before
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_CONFIRMATION_REQUIRED"):
        service.hard_delete(**_request(rfc, preview, token))
    assert _counts(factory) == before


def test_no_change_cannot_run_after_audit_mutation():
    with pytest.raises(ValidationError):
        PreparedMutation(True, None, None, response_schema="Test", response={},
                         after_audit=lambda uow: None).validate()


def test_audit_contract_rejects_confirmation_secrets(deletion):
    factory, _, _, _, _ = deletion
    contract = build_tickets_audit_registry().resolve("ticket.rfc.hard_deleted", 1)
    assert contract.payload_contract.allowed_fields == frozenset({
        "rfc_id", "rfc_no", "reviewed_revision", "eligibility_fingerprint", "result"})
    payload = {"rfc_id": new_uuid4(), "rfc_no": "NC00000000000001", "reviewed_revision": 1,
               "eligibility_fingerprint": "a" * 64, "result": "deleted"}
    for key in ("confirmation_context_id", "challenge_id", "proof", "session_id"):
        with pytest.raises(ValidationError):
            contract.payload_contract.validate({**payload, key: "secret"})
    for key, value in (("rfc_id", None), ("rfc_no", "NC１２３４５６７８９０１２３４"),
                       ("reviewed_revision", True), ("eligibility_fingerprint", "A" * 64), ("result", "archived")):
        with pytest.raises(SomaError, match="AUDIT_PAYLOAD_INVALID"):
            contract.sensitivity_validator({**payload, key: value})


def _append_audit(uow, command_id, rfc_id, *, action="ticket.test.history", schema="TestAuditV1", payload=None):
    uow.connection.execute(
        "INSERT INTO audit_events(audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,"
        "target_type,target_id,command_id,payload_schema,payload_version,payload_json) "
        "VALUES (?, ?, 1, 0, 'local_user', 'rfc', ?, ?, ?, 1, ?)",
        (new_uuid4(), action, rfc_id, command_id, schema, json.dumps(payload or {})),
    )


@pytest.mark.parametrize("kind,code", [
    ("revision", "RFC_REVISION_NOT_INITIAL"),
    ("archived", "RFC_ARCHIVE_STATE_NOT_ACTIVE"),
    ("source", "RFC_SOURCE_PROJECTION_PRESENT"),
    ("hierarchy_parent", "RFC_HIERARCHY_HISTORY_PRESENT"),
    ("hierarchy_child", "RFC_HIERARCHY_HISTORY_PRESENT"),
    ("sr", "RFC_SR_RELATIONSHIP_HISTORY_PRESENT"),
    ("device", "RFC_DEVICE_REFERENCE_HISTORY_PRESENT"),
    ("note_current", "RFC_WORKING_NOTE_HISTORY_PRESENT"),
    ("note_removed", "RFC_WORKING_NOTE_HISTORY_PRESENT"),
    ("cascade_trigger", "RFC_TERMINAL_CASCADE_HISTORY_PRESENT"),
    ("cascade_member", "RFC_TERMINAL_CASCADE_HISTORY_PRESENT"),
    ("cascade_wfm", "RFC_TERMINAL_CASCADE_HISTORY_PRESENT"),
    ("archive_request", "RFC_ARCHIVE_HISTORY_PRESENT"),
    ("archive_member", "RFC_ARCHIVE_HISTORY_PRESENT"),
    ("archive_event", "RFC_ARCHIVE_HISTORY_PRESENT"),
    ("audit", "RFC_PROTECTED_AUDIT_HISTORY_PRESENT"),
])
def test_each_local_history_guard_blocks_without_deleting_or_rewriting_history(deletion, kind, code):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    other = _create(factory, number="NC00000000000002")
    reviewed = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(reviewed, rfc.rfc_id)
    with UnitOfWork(factory) as uow:
        db = uow.connection
        command_id = db.execute("SELECT command_id FROM command_receipts LIMIT 1").fetchone()[0]
        if kind == "revision":
            db.execute("UPDATE rfcs SET revision=2 WHERE rfc_id=?", (rfc.rfc_id,))
        elif kind == "archived":
            db.execute("UPDATE rfcs SET local_archive_state='archived' WHERE rfc_id=?", (rfc.rfc_id,))
        elif kind == "source":
            db.execute("INSERT INTO rfc_current_source_projection(rfc_id) VALUES (?)", (rfc.rfc_id,))
        elif kind.startswith("hierarchy"):
            parent, child = (rfc.rfc_id, other.rfc_id) if kind == "hierarchy_parent" else (other.rfc_id, rfc.rfc_id)
            db.execute("INSERT INTO rfc_hierarchy_edges VALUES (?, ?, ?, 'superseded', 0, 1, ?, ?)",
                       (new_uuid4(), parent, child, command_id, command_id))
        elif kind == "sr":
            sr_id = new_uuid4()
            db.execute("INSERT INTO service_requests VALUES (?, '12345678', NULL, 1, 0, 0)", (sr_id,))
            db.execute("INSERT INTO sr_rfc_links VALUES (?, ?, ?, 'unlinked', 0, 1, ?, ?, NULL)",
                       (new_uuid4(), sr_id, rfc.rfc_id, command_id, command_id))
        elif kind == "device":
            device_id = new_uuid4()
            db.execute("INSERT INTO device_references VALUES (?, 'Device', 1, 0, 0)", (device_id,))
            db.execute("INSERT INTO rfc_device_reference_links VALUES (?, ?, ?, 'unlinked', 0, 1, ?, ?)",
                       (new_uuid4(), rfc.rfc_id, device_id, command_id, command_id))
        elif kind == "note_current":
            user_id = new_uuid4()
            db.execute("INSERT INTO local_user_profiles VALUES (?, 1, 'User', 1, 0, 0)", (user_id,))
            db.execute("INSERT INTO rfc_working_notes VALUES (?, ?, ?, 'Note', 1, 0, 0, ?)",
                       (new_uuid4(), rfc.rfc_id, user_id, command_id))
        elif kind == "note_removed":
            # Note audit targets its removed note identity, not the RFC's own target index.
            _append_audit(uow, command_id, new_uuid4(), action="ticket.working_note.removed",
                          schema="WorkingNoteAuditV1", payload={"owner_type": "rfc", "owner_id": rfc.rfc_id})
        elif kind.startswith("cascade"):
            proposal_id = new_uuid4()
            trigger_id = rfc.rfc_id if kind == "cascade_trigger" else other.rfc_id
            db.execute("INSERT INTO rfc_terminal_cascade_proposals VALUES "
                       "(?, ?, 'epoch', 'terminal_closed', 'evidence', 'exact_rfc', ?, 'executed', 2, 0, ?, 1, ?, NULL, NULL)",
                       (proposal_id, trigger_id, "a" * 64, command_id, command_id))
            if kind == "cascade_member":
                db.execute("INSERT INTO rfc_terminal_cascade_rfc_members VALUES (?, ?, 1, 'subordinate', 0)",
                           (proposal_id, rfc.rfc_id))
            elif kind == "cascade_wfm":
                db.execute("INSERT INTO rfc_terminal_cascade_wfm_members VALUES (?, ?, ?, 1, 'TK00000000000001', 0)",
                           (proposal_id, new_uuid4(), rfc.rfc_id))
        elif kind.startswith("archive"):
            operation_id = new_uuid4()
            requested_id = rfc.rfc_id if kind == "archive_request" else other.rfc_id
            db.execute("INSERT INTO rfc_archive_operations VALUES (?, ?, 'exact_rfc', ?, 0, ?)",
                       (operation_id, requested_id, "a" * 64, command_id))
            if kind in {"archive_member", "archive_event"}:
                db.execute("INSERT INTO rfc_archive_operation_members VALUES (?, ?, 1, 2, 0)", (operation_id, rfc.rfc_id))
            if kind == "archive_event":
                db.execute("UPDATE rfcs SET revision=2 WHERE rfc_id=?", (rfc.rfc_id,))
                db.execute("INSERT INTO rfc_archive_events VALUES (?, ?, 'restored', ?, 2, 0, ?)",
                           (new_uuid4(), rfc.rfc_id, operation_id, command_id))
        else:
            _append_audit(uow, command_id, rfc.rfc_id)
    before = _counts(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    assert not preview.eligible and code in [blocker.code for blocker in preview.blockers]
    expected_error = "RFC_HARD_DELETE_PREVIEW_STALE" if preview.rfc_revision != reviewed.rfc_revision else "RFC_HARD_DELETE_BLOCKED"
    with pytest.raises(SomaError, match=expected_error):
        service.hard_delete(**_request(rfc, reviewed, token))
    assert _counts(factory) == before and proof.calls == 0
    assert queries.preview(rfc_id=rfc.rfc_id).to_response() == preview.to_response()


@pytest.mark.parametrize("kind", ["missing", "duplicate", "malformed", "wrong_identity", "wrong_revision", "adopted"])
def test_only_single_valid_local_creation_audit_permits_deletion(deletion, kind):
    factory, _, proof, queries, service = deletion
    other = _create(factory, number="NC00000000000002")
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        command_id = uow.connection.execute("SELECT command_id FROM command_receipts LIMIT 1").fetchone()[0]
        uow.connection.execute("INSERT INTO rfcs VALUES (?, 'NC00000000000001', NULL, 'active', 1, 0, 0)", (rfc_id,))
        payload = {"rfc_id": rfc_id, "rfc_no": "NC00000000000001", "creation_context": "manual",
                   "customer_org_id": None, "resulting_revision": 1}
        if kind == "malformed":
            del payload["customer_org_id"]
        if kind == "wrong_identity":
            payload["rfc_id"] = other.rfc_id
        if kind == "wrong_revision":
            payload["resulting_revision"] = True
        if kind == "adopted":
            payload["creation_context"] = "accepted_source_adoption"
        if kind != "missing":
            for _ in range(2 if kind == "duplicate" else 1):
                _append_audit(uow, command_id, rfc_id, action="ticket.rfc.identity_created_or_adopted",
                              schema="RfcIdentityAuditV1", payload=payload)
    preview = queries.preview(rfc_id=rfc_id)
    assert not preview.eligible and preview.blockers[0].code == "RFC_CREATION_CONTEXT_NOT_LOCAL"
    before = _counts(factory)
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_BLOCKED"):
        service.hard_delete(command_id=new_uuid4(), rfc_id=rfc_id, base_revision=1,
                            eligibility_fingerprint=preview.eligibility_fingerprint, deliberate_action_proof=True)
    assert proof.calls == 0 and _counts(factory) == before


def test_unexpected_foreign_key_preserves_dependent_row_and_rolls_back_delete(deletion):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    with UnitOfWork(factory) as uow:
        uow.connection.execute("CREATE TABLE test_unexpected_dependency(rfc_id TEXT REFERENCES rfcs(rfc_id) ON DELETE RESTRICT)")
        uow.connection.execute("INSERT INTO test_unexpected_dependency VALUES (?)", (rfc.rfc_id,))
    preview = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(preview, rfc.rfc_id)
    before = _counts(factory)
    with pytest.raises(sqlite3.IntegrityError):
        service.hard_delete(**_request(rfc, preview, token))
    assert _counts(factory) == before and token in proof.consumed
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT rfc_id FROM test_unexpected_dependency").fetchall() == [(rfc.rfc_id,)]


def test_preview_snapshot_is_stable_across_concurrent_change_then_writer_blocks(deletion, monkeypatch):
    factory, providers, proof, queries, service = deletion
    rfc = _create(factory)
    original = providers[0].has_accepted_source_provenance
    def mutate_after_snapshot_read(reader, rfc_id):
        if isinstance(reader, ReadSnapshot):
            with UnitOfWork(factory) as uow:
                uow.connection.execute("UPDATE rfcs SET local_archive_state='archived' WHERE rfc_id=?", (rfc_id,))
            assert reader.connection.execute("SELECT local_archive_state FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() == ("active",)
        return original(reader, rfc_id)
    monkeypatch.setattr(providers[0], "has_accepted_source_provenance", mutate_after_snapshot_read)
    reviewed = queries.preview(rfc_id=rfc.rfc_id)
    assert reviewed.eligible
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_BLOCKED"):
        service.hard_delete(**_request(rfc, reviewed, proof.issue(reviewed, rfc.rfc_id)))
    assert proof.calls == 0


@pytest.mark.parametrize("binding_index", range(5))
def test_proof_must_match_exact_action_target_revision_and_fingerprint(deletion, binding_index):
    factory, _, proof, queries, service = deletion
    rfc = _create(factory)
    preview = queries.preview(rfc_id=rfc.rfc_id)
    token = proof.issue(preview, rfc.rfc_id)
    wrong = list(proof.bindings[token])
    wrong[binding_index] = "wrong-binding"
    proof.bindings[token] = tuple(wrong)
    before = _counts(factory)
    with pytest.raises(SomaError, match="RFC_HARD_DELETE_CONFIRMATION_REQUIRED"):
        service.hard_delete(**_request(rfc, preview, token))
    assert _counts(factory) == before and token not in proof.consumed


def test_blockers_follow_closed_local_then_provider_order(deletion):
    factory, providers, _, queries, _ = deletion
    rfc = _create(factory, context="accepted_source_adoption")
    with UnitOfWork(factory) as uow:
        uow.connection.execute("UPDATE rfcs SET revision=2,local_archive_state='archived' WHERE rfc_id=?", (rfc.rfc_id,))
        uow.connection.execute("INSERT INTO rfc_current_source_projection(rfc_id) VALUES (?)", (rfc.rfc_id,))
    for provider in providers:
        provider.status = "INDETERMINATE"
    preview = queries.preview(rfc_id=rfc.rfc_id)
    assert [blocker.code for blocker in preview.blockers] == [
        "RFC_CREATION_CONTEXT_NOT_LOCAL", "RFC_REVISION_NOT_INITIAL", "RFC_ARCHIVE_STATE_NOT_ACTIVE",
        "RFC_SOURCE_PROJECTION_PRESENT", "RFC_PROTECTED_AUDIT_HISTORY_PRESENT",
        "RFC_SOURCE_PROVENANCE_INDETERMINATE", "RFC_TASKS_OBJECTIVES_INDETERMINATE",
        "RFC_INVENTORY_INDETERMINATE", "RFC_COMMUNICATIONS_INDETERMINATE",
    ]
    assert all(len(p.calls) == 1 for p in providers)


def test_missing_target_has_no_provider_or_proof_effects(deletion):
    factory, providers, proof, queries, service = deletion
    rfc_id = new_uuid4()
    before = _counts(factory)
    with pytest.raises(SomaError, match="NOT_FOUND"):
        queries.preview(rfc_id=rfc_id)
    with pytest.raises(SomaError, match="NOT_FOUND"):
        service.hard_delete(command_id=new_uuid4(), rfc_id=rfc_id, base_revision=1,
                            eligibility_fingerprint="a" * 64, deliberate_action_proof=True)
    assert _counts(factory) == before and proof.calls == 0 and not any(p.calls for p in providers)
