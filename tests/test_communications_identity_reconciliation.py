from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from soma.communications.contracts.identity_review import IdentityReviewRequest
from soma.communications.contracts.common import TrackableIdentity, UNKNOWN_CHRONOLOGY
from soma.communications.contracts.message import ProviderMessageIdentity
from soma.communications.domain.communication import canonical_message_identity
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS
from soma.communications.jobs.identity_reconciliation import CommunicationIdentityReconciliationWorker
from soma.communications.repositories.communications import insert_retained
from soma.communications.repositories.identity import resolve_identity
from soma.communications.repositories.links import create_link, require_retained_message
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.identity_reconciliation import CommunicationIdentityReconciliationService
from soma.communications.services.identity_review import CommunicationIdentityReviewService
from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import receipt
from test_communications_identity import insert_scope, message
from test_communications_identity_providers import providers
from test_communications_identity_review import observe
from test_objectives_tasks_objectives import _create_single_task_objective


def setup_pair(database, *, owners=None):
    path, factory = database
    with sqlite3.connect(path) as db:
        scope = insert_scope(db)
    chosen, donor = new_uuid4(), new_uuid4()
    identities = []
    holds = []
    for comm, key in ((chosen, b"selected-key"), (donor, b"donor-key")):
        transient = message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", key))
        evidence = canonical_message_identity(scope, transient, ())
        identities.append(evidence)
        hold = new_uuid4()
        holds.append(hold)
        with UnitOfWork(factory) as writer:
            insert_retained(writer, comm, scope, transient, evidence, (), identity_state="PROVIDER_STABLE", now=100)
            writer.connection.execute("INSERT INTO communication_retention VALUES(?,'RETAINED',NULL,NULL,?,1,100)", (comm, hold))
            writer.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'COLLISION_REVIEW',?,'ACTIVE',100,NULL)", (hold, comm, hold))
    jobs = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=lambda: 1100)
    owner = CommunicationIdentityReconciliationService(factory, owners or providers(), jobs, clock=lambda: 1100)
    return path, factory, scope, chosen, donor, identities, holds, jobs, owner


def reviewed(owner, scope, chosen, donor, decision):
    value = IdentityReviewRequest(scope, 1, decision, chosen, 1, donor, 1, None).to_value()
    preview = owner.preview(value)
    return {**value, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"]}, preview


def run(owner, jobs, request):
    queued = owner.enqueue(request)
    claim = jobs.claim_next(new_uuid4(), 1100)
    assert claim.job_id == queued["job_id"]
    return owner.execute_claim(claim), queued, claim


def target(factory, name, *, start=100):
    _, objective = _create_single_task_objective(factory, name=name, start_utc=start, end_utc=start+100)
    with ReadSnapshot(factory) as reader:
        return next(providers().target_snapshot(reader, "OBJECTIVE", objective.objective_id))


def link(factory, communication_id, identity, *, chronology=None):
    with UnitOfWork(factory) as writer:
        retained = require_retained_message(writer, communication_id)
        if chronology is not None:
            retained.update(chronology_known=1, chronology_utc=chronology, chronology_source_kind="SENT_TIME", direction="SENT")
        return create_link(writer, retained, target_type=identity.target_type, target_id=identity.target_id,
            target_revision=identity.target_revision, now=100, command_id=receipt(writer), origin="REVIEWED", reason="TEST_REVIEWED_LINK",
            match={"matched_identity_kind": identity.identity_kind, "matched_identity_value": identity.normalized_value,
                   "match_rule_id": "COMM_REVIEWED_MANUAL_V1", "match_rule_version": 1, "confidence_basis": "REVIEWED_MANUAL"})[0]


def test_pair_consolidation_preserves_canonical_history_chronology_and_shared_target_link(communication_database):
    path, factory, scope, chosen, donor, identities, _, jobs, owner = setup_pair(communication_database)
    shared, only = target(factory, "Shared target"), target(factory, "Donor-only target", start=86500)
    selected_link = link(factory, chosen, shared, chronology=80)
    donor_shared = link(factory, donor, shared)
    donor_only = link(factory, donor, only, chronology=90)
    request, preview = reviewed(owner, scope, chosen, donor, "CONSOLIDATE_LINKS_AND_ALIASES")
    assert (preview["closed_link_count"], preview["created_link_count"], preview["attached_alias_count"], preview["closed_hold_count"]) == (2, 1, 1, 2)
    result, queued, claim = run(owner, jobs, request)
    assert owner.execute_claim(claim) == result
    assert owner.enqueue(request) == queued
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT communication_id,subject,body_text,content_revision FROM communications ORDER BY communication_id").fetchall() == [(item, "Subject", "body\ntext", 1) for item in sorted((chosen, donor))]
        assert db.execute("SELECT communication_link_id FROM communication_links WHERE communication_id=? AND target_id=? AND state='ACTIVE'", (chosen, shared.target_id)).fetchone() == (selected_link,)
        assert db.execute("SELECT state FROM communication_links WHERE communication_link_id IN (?,?)", (donor_shared, donor_only)).fetchall() == [("CLOSED",), ("CLOSED",)]
        assert db.execute("SELECT effective_chronology_utc,effective_chronology_source_kind,direction,origin,confidence_basis FROM communication_links WHERE communication_id=? AND target_id=? AND state='ACTIVE'", (chosen, only.target_id)).fetchone() == (90, "SENT_TIME", "SENT", "REVIEWED", "REVIEWED_MANUAL")
        assert db.execute("SELECT state FROM communication_retention WHERE communication_id=?", (donor,)).fetchone() == ("ORPHAN_PENDING_PURGE",)
        assert db.execute("SELECT state FROM communication_retention WHERE communication_id=?", (chosen,)).fetchone() == ("RETAINED",)
        assert db.execute("SELECT state,attempt_count FROM durable_jobs WHERE job_id=?", (queued["job_id"],)).fetchone() == ("completed", 1)
        assert db.execute("SELECT inspected,estimated_total FROM communication_job_counters WHERE job_id=?", (queued["job_id"],)).fetchone() == (2, 2)
        assert db.execute("SELECT count(*) FROM communication_identity_review_results WHERE result_type='communication_link_event'").fetchone() == (3,)
        assert db.execute("SELECT count(*) FROM communication_forward_coverage").fetchone() == (0,)
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, identities[1]).communication_id == chosen


def test_transfer_rejects_differing_missing_purged_or_cross_scope_evidence_and_digest_collision(communication_database):
    path, _, scope, chosen, donor, _, _, _, owner = setup_pair(communication_database)
    value = IdentityReviewRequest(scope, 1, "ATTACH_PROVIDER_IDENTITY", chosen, 1, donor, 1, None).to_value()
    with sqlite3.connect(path) as db:
        original = db.execute("SELECT fallback_canonical_json FROM communications WHERE communication_id=?", (donor,)).fetchone()[0]
        db.execute("UPDATE communications SET fallback_canonical_json=? WHERE communication_id=?", (original.replace("Subject", "Different"), donor))
    with pytest.raises(SomaError) as failure:
        owner.preview(value)
    assert failure.value.code == "COMM_IDENTITY_COLLISION"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET fallback_canonical_json=NULL WHERE communication_id=?", (donor,))
    with pytest.raises(SomaError):
        owner.preview(value)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET fallback_canonical_json=? WHERE communication_id=?", (original, donor))
        other_scope = insert_scope(db)
        db.execute("UPDATE communications SET source_scope_id=? WHERE communication_id=?", (other_scope, donor))
    with pytest.raises(SomaError) as failure:
        owner.preview(value)
    assert failure.value.code == "COMM_STALE"


def test_keep_separate_does_not_transfer_or_require_equal_content(communication_database):
    path, _, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET fallback_canonical_json='{}' WHERE communication_id=?", (donor,))
    request, preview = reviewed(owner, scope, chosen, donor, "KEEP_SEPARATE")
    assert preview["attached_alias_count"] == preview["closed_link_count"] == 0
    run(owner, jobs, request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_identity_aliases").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_retention WHERE state='ORPHAN_PENDING_PURGE'").fetchone() == (2,)


def test_reconciliation_retains_content_variant_and_export_holds(communication_database):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    content_owner = CommunicationIdentityReviewService(factory, clock=lambda: 1100)
    variant = canonical_message_identity(scope, message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"donor-key"), subject="Variant"), ())
    found = observe(factory, content_owner, scope, donor, variant)
    export = new_uuid4()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',1000,NULL)", (export, donor, new_uuid4()))
    request, _ = reviewed(owner, scope, chosen, donor, "CONSOLIDATE_LINKS_AND_ALIASES")
    run(owner, jobs, request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT protection_hold_id FROM communication_protection_holds WHERE state='ACTIVE' ORDER BY protection_hold_id").fetchall() == [(item,) for item in sorted((export, found.protection_hold_id))]
        assert db.execute("SELECT state FROM communication_retention WHERE communication_id=?", (donor,)).fetchone() == ("RETAINED",)
        assert db.execute("SELECT decision_event_id FROM communication_identity_review_evidence").fetchone() == (None,)


def test_reconciliation_reassigns_alias_without_mutating_old_rows_and_orders_same_second_decisions(communication_database):
    path, factory, scope, chosen, donor, identities, _, jobs, owner = setup_pair(communication_database)
    extra = canonical_message_identity(scope, message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"extra-key")), ())
    old_alias = new_uuid4()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_identity_aliases VALUES(?,?,?,?,1,100,?)", (old_alias, donor, extra.provider_kind, extra.provider_digest, extra.provider_bytes))
    first, _ = reviewed(owner, scope, chosen, donor, "ATTACH_PROVIDER_IDENTITY")
    run(owner, jobs, first)
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, extra).communication_id == chosen
    second, _ = reviewed(owner, scope, donor, chosen, "ATTACH_PROVIDER_IDENTITY")
    run(owner, jobs, second)
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, extra).communication_id == donor
        assert resolve_identity(reader, scope, identities[0]).communication_id == donor
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT communication_id,alias_evidence_bytes FROM communication_identity_aliases WHERE identity_alias_id=?", (old_alias,)).fetchone() == (donor, extra.provider_bytes)
        for sql in ("UPDATE communication_identity_alias_assignments SET assignment_revision=100", "DELETE FROM communication_identity_alias_assignments", "UPDATE communication_identity_review_requests SET preview_fingerprint='x'", "DELETE FROM communication_identity_review_requests"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_stale_preview_or_active_different_group_cannot_enqueue_and_stale_execution_rolls_back(communication_database):
    path, _, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    request, _ = reviewed(owner, scope, chosen, donor, "ATTACH_PROVIDER_IDENTITY")
    queued = owner.enqueue(request)
    assert owner.enqueue({**request, "command_id": new_uuid4()})["coalesced"]
    distinct, _ = reviewed(owner, scope, chosen, donor, "KEEP_SEPARATE")
    with pytest.raises(SomaError) as failure:
        owner.enqueue(distinct)
    assert failure.value.code == "COMM_JOB_ACTIVE"
    claim = jobs.claim_next(new_uuid4(), 1100)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET revision=2 WHERE source_scope_id=?", (scope,))
    with pytest.raises(SomaError):
        owner.execute_claim(claim)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM durable_jobs WHERE job_id=?", (queued["job_id"],)).fetchone() == ("running",)
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_identity_alias_assignments").fetchone() == (0,)


def test_audit_failure_rolls_back_transfers_retention_checkpoint_and_job_completion(communication_database, monkeypatch):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    original = link(factory, donor, target(factory, "Rollback target"))
    request, _ = reviewed(owner, scope, chosen, donor, "CONSOLIDATE_LINKS_AND_ALIASES")
    queued = owner.enqueue(request)
    claim = jobs.claim_next(new_uuid4(), 1100)
    def fail(*args):
        raise RuntimeError("injected reconciliation audit failure")
    monkeypatch.setattr(owner._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        owner.execute_claim(claim)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,revision FROM communication_links WHERE communication_link_id=?", (original,)).fetchone() == ("ACTIVE", 1)
        assert db.execute("SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?", (queued["job_id"],)).fetchone() == ("running", None)
        assert db.execute("SELECT count(*) FROM communication_identity_aliases").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM communication_retention WHERE revision=1").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone() == (0,)
    monkeypatch.undo()
    owner.execute_claim(claim)


def test_provider_assignment_survives_purge_but_purged_evidence_cannot_authorize_new_transfer(communication_database):
    path, factory, scope, chosen, donor, identities, _, jobs, owner = setup_pair(communication_database)
    request, _ = reviewed(owner, scope, chosen, donor, "ATTACH_PROVIDER_IDENTITY")
    result, _, _ = run(owner, jobs, request)
    with sqlite3.connect(path) as db:
        revision, due = db.execute("SELECT revision,purge_due_utc FROM communication_retention WHERE communication_id=?", (chosen,)).fetchone()
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=chosen, selected_revision=revision, now_utc=due)
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, identities[1]).communication_id == chosen
    value = IdentityReviewRequest(scope, 1, "ATTACH_PROVIDER_IDENTITY", chosen, 2, donor, 1, None).to_value()
    with pytest.raises(SomaError) as failure:
        owner.preview(value)
    assert failure.value.code == "COMM_CONTENT_PURGED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT identity_review_event_id FROM communication_identity_review_events").fetchone() == (result["identity_review_event_id"],)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


class TargetOwner:
    def __init__(self):
        self.revision = 1
        self.eligible = True

    def current_revision(self, reader, kind, identity):
        return self.revision

    def validate_reassociation(self, reader, kind, identity, revision):
        return "VALID" if self.eligible and revision == self.revision else "INVALID"


def test_reconciliation_pages_large_link_group_and_preserves_complete_bounded_result_references(communication_database):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database, owners=TargetOwner())
    for ordinal in range(131):
        identity = TrackableIdentity("OBJECTIVE", new_uuid4(), 1, "OBJECTIVE_COMMUNICATION_REFERENCE", f"MW-{ordinal:08d}", UNKNOWN_CHRONOLOGY)
        link(factory, donor, identity, chronology=ordinal)
    request, preview = reviewed(owner, scope, chosen, donor, "CONSOLIDATE_LINKS_AND_ALIASES")
    assert preview["closed_link_count"] == preview["created_link_count"] == 131
    result, _, _ = run(owner, jobs, request)
    assert len(str(result)) < 200
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_links WHERE communication_id=? AND state='ACTIVE'", (chosen,)).fetchone() == (131,)
        assert db.execute("SELECT count(*) FROM communication_links WHERE communication_id=? AND state='CLOSED'", (donor,)).fetchone() == (131,)
        assert db.execute("SELECT count(*) FROM communication_identity_review_results WHERE result_type='communication_link_event'").fetchone() == (262,)
        payload = db.execute("SELECT payload_json FROM audit_events WHERE action_type='communications.identity.decided'").fetchone()[0]
        assert '131' in payload and len(payload) < 500


def test_owner_terminal_or_revision_changes_and_new_content_holds_invalidate_reviewed_scope(communication_database):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database, owners=TargetOwner())
    identity = TrackableIdentity("SERVICE_REQUEST", new_uuid4(), 1, "SERVICE_REQUEST_OFFICIAL", "123456789", UNKNOWN_CHRONOLOGY)
    link(factory, donor, identity)
    request, _ = reviewed(owner, scope, chosen, donor, "CONSOLIDATE_LINKS_AND_ALIASES")
    owner.enqueue(request)
    claim = jobs.claim_next(new_uuid4(), 1100)
    owner._identities.eligible = False
    with pytest.raises(SomaError) as failure:
        owner.execute_claim(claim)
    assert failure.value.code == "COMM_TARGET_STALE"
    owner._identities.eligible = True
    owner._identities.revision = 2
    with pytest.raises(SomaError) as failure:
        owner.execute_claim(claim)
    assert failure.value.code == "COMM_STALE"
    owner._identities.revision = 1
    variant = canonical_message_identity(scope, message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"donor-key"), subject="New variant"), ())
    observe(factory, CommunicationIdentityReviewService(factory), scope, donor, variant)
    with pytest.raises(SomaError) as failure:
        owner.execute_claim(claim)
    assert failure.value.code == "COMM_STALE"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone() == (0,)


def test_recovery_keeps_exact_request_and_cancelled_claim_never_transfers_identity(communication_database):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    request, _ = reviewed(owner, scope, chosen, donor, "ATTACH_PROVIDER_IDENTITY")
    queued = owner.enqueue(request)
    old = jobs.claim_next(new_uuid4(), 1100)
    jobs.recover_stale_claims(new_uuid4(), 1100)
    new = jobs.claim_next(new_uuid4(), 1100)
    assert new.job_id == old.job_id and new.attempt_ordinal == 2
    with pytest.raises(JobClaimConflict):
        owner.execute_claim(old)
    with UnitOfWork(factory) as writer:
        jobs.cancel(writer, queued["job_id"], new.job_type, 1, {"command_id": receipt(writer)})
    worker = CommunicationIdentityReconciliationWorker(owner, jobs, clock=lambda: 1100)
    with pytest.raises(JobClaimConflict):
        worker.run(new)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM durable_jobs").fetchone() == ("cancelled",)
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'").fetchone() == (2,)


def test_reconciliation_worker_uses_only_registered_retry_rules_and_omits_unsafe_exception_details(communication_database, monkeypatch):
    path, _, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    request, _ = reviewed(owner, scope, chosen, donor, "KEEP_SEPARATE")
    owner.enqueue(request)
    first = jobs.claim_next(new_uuid4(), 1100)
    worker = CommunicationIdentityReconciliationWorker(owner, jobs, clock=lambda: 1100)
    def transient(claim):
        raise SomaError("SOURCE_LOCKED", "SensitiveSubject private-key mail.pst")
    monkeypatch.setattr(owner, "execute_claim", transient)
    with pytest.raises(SomaError) as failure:
        worker.run(first)
    assert "Sensitive" not in str(failure.value)
    assert failure.value.__context__ is None and failure.value.__cause__ is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,next_attempt_at_utc,last_error_code FROM durable_jobs").fetchone() == ("retry_wait", 1130, "SOURCE_LOCKED")
    second = jobs.claim_next(new_uuid4(), 1130)
    jobs._clock = lambda: 1130
    worker._clock = lambda: 1130
    def unsafe(claim):
        raise RuntimeError("SensitiveSubject private-key mail.pst")
    monkeypatch.setattr(owner, "execute_claim", unsafe)
    with pytest.raises(SomaError) as failure:
        worker.run(second)
    assert failure.value.code == "COMM_DIAGNOSTIC_REDACTED" and "Sensitive" not in str(failure.value)
    assert failure.value.__context__ is None and failure.value.__cause__ is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,last_error_code FROM durable_jobs").fetchone() == ("failed", "COMM_DIAGNOSTIC_REDACTED")
        assert db.execute("SELECT attempt_count FROM durable_jobs").fetchone() == (2,)


def test_provider_key_owned_outside_reviewed_pair_cannot_be_taken(communication_database):
    path, _, scope, chosen, donor, identities, _, _, owner = setup_pair(communication_database)
    with sqlite3.connect(path) as db:
        from test_communications_identity import insert_message
        third = insert_message(db, scope, replace(identities[1], provider_digest=None, provider_kind=None, provider_bytes=None), "FALLBACK")
        db.execute("INSERT INTO communication_identity_aliases VALUES(?,?,?,?,1,100,?)",
            (new_uuid4(), third, identities[1].provider_kind, identities[1].provider_digest, identities[1].provider_bytes))
    value = IdentityReviewRequest(scope, 1, "ATTACH_PROVIDER_IDENTITY", chosen, 1, donor, 1, None).to_value()
    with pytest.raises(SomaError) as failure:
        owner.preview(value)
    assert failure.value.code == "COMM_IDENTITY_COLLISION"


def test_identical_incomplete_objects_are_not_canonical_identity_evidence(communication_database):
    path, _, scope, chosen, donor, _, _, _, owner = setup_pair(communication_database)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET fallback_canonical_json='{}'")
    value = IdentityReviewRequest(scope, 1, "CONSOLIDATE_LINKS_AND_ALIASES", chosen, 1, donor, 1, None).to_value()
    with pytest.raises(SomaError) as failure:
        owner.preview(value)
    assert failure.value.code == "COMM_IDENTITY_COLLISION"


def test_reconciliation_pages_aliases_while_preserving_donor_evidence_and_exact_lookup(communication_database):
    path, factory, scope, chosen, donor, _, _, jobs, owner = setup_pair(communication_database)
    evidence = [canonical_message_identity(scope, message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", f"key-{index}".encode())), ()) for index in range(131)]
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO communication_identity_aliases VALUES(?,?,?,?,1,100,?)",
            ((new_uuid4(), donor, item.provider_kind, item.provider_digest, item.provider_bytes) for item in evidence))
    request, preview = reviewed(owner, scope, chosen, donor, "ATTACH_PROVIDER_IDENTITY")
    assert preview["attached_alias_count"] == 132
    run(owner, jobs, request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_identity_aliases WHERE communication_id=?", (donor,)).fetchone() == (131,)
        assert db.execute("SELECT count(*) FROM communication_identity_aliases WHERE communication_id=?", (chosen,)).fetchone() == (132,)
        assert db.execute("SELECT count(*) FROM communication_identity_alias_assignments").fetchone() == (132,)
    with ReadSnapshot(factory) as reader:
        assert all(resolve_identity(reader, scope, item).communication_id == chosen for item in evidence)
