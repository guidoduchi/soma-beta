from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from soma.communications.audit_registry import build_communications_audit_registry
from soma.communications.contracts.identity_review import IdentityReviewRequest
from soma.communications.contracts.message import ProviderMessageIdentity
from soma.communications.domain.communication import canonical_message_identity
from soma.communications.repositories.communications import insert_retained
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.identity_review import CommunicationIdentityReviewService
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import receipt
from test_communications_identity import insert_scope, message


def setup(communication_database):
    path, factory = communication_database
    with sqlite3.connect(path) as db:
        scope = insert_scope(db)
    original = message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"private-key"))
    identity = canonical_message_identity(scope, original, ())
    comm = new_uuid4()
    with UnitOfWork(factory) as writer:
        insert_retained(writer, comm, scope, original, identity, (), identity_state="PROVIDER_STABLE", now=100)
        writer.connection.execute("INSERT INTO communication_retention VALUES(?,'ORPHAN_PENDING_PURGE',100,200,NULL,1,100)", (comm,))
    owner = CommunicationIdentityReviewService(factory, clock=lambda: 1100)
    different = canonical_message_identity(scope, replace(original, subject="Conflicting Subject", body="PrivateVariantBody"), ())
    return path, factory, owner, scope, comm, identity, different


def observe(factory, owner, scope, comm, identity, *, now=1000):
    with UnitOfWork(factory) as writer:
        command = receipt(writer)
        result = owner.observe_provider_content_in_uow(writer, source_scope_id=scope, source_revision=1,
            communication_id=comm, identity=identity, command_id=command, now=now)
        for event in result.audits:
            AuditWriter(build_communications_audit_registry()).write(writer, event)
    return result


def preview(owner, scope, comm, evidence):
    value = IdentityReviewRequest(scope, 1, "KEEP_RETAINED_CONTENT", comm, 1, None, None, evidence).to_value()
    return {**value, "command_id": new_uuid4(), "preview_fingerprint": owner.preview_keep_retained_content(value)}


def test_exact_provider_conflict_preserves_content_deduplicates_variants_and_acknowledges_only_exact_objects(communication_database):
    path, factory, owner, scope, comm, original, variant = setup(communication_database)
    unchanged = observe(factory, owner, scope, comm, original)
    assert unchanged.disposition == "UNCHANGED" and unchanged.permits_matching and not unchanged.audits
    first = observe(factory, owner, scope, comm, variant)
    assert first.disposition == "REVIEW_REQUIRED" and not first.permits_matching
    again = observe(factory, owner, scope, comm, variant)
    assert again.review_evidence_id == first.review_evidence_id and not again.audits
    request = preview(owner, scope, comm, first.review_evidence_id)
    decision = owner.keep_retained_content(request)
    assert decision["status"] == "APPLIED"
    assert owner.keep_retained_content(request) == decision
    ack = observe(factory, owner, scope, comm, variant)
    assert ack.disposition == "ACKNOWLEDGED" and not ack.permits_matching and not ack.audits
    new_command = preview(owner, scope, comm, first.review_evidence_id)
    assert owner.keep_retained_content(new_command) == {**decision, "status": "NO_CHANGE"}
    # Deliberately keep the digest to exercise a collision: acknowledgement
    # requires the entire exact object, rather than accepting its hash alone.
    next_variant = replace(variant, fallback_canonical_json=variant.fallback_canonical_json.replace("Conflicting Subject", "Another Subject"))
    new = observe(factory, owner, scope, comm, next_variant)
    assert new.disposition == "REVIEW_REQUIRED" and new.review_evidence_id != first.review_evidence_id
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT subject,body_text,content_revision FROM communications WHERE communication_id=?", (comm,)).fetchone() == ("Subject", "body\ntext", 1)
        assert db.execute("SELECT count(*) FROM communications").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone()[0] == 1
        assert db.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 4)
        audits = db.execute("SELECT action_type,payload_json FROM audit_events").fetchall()
        assert [item[0] for item in audits].count("communications.identity.review_required") == 2
        assert [item[0] for item in audits].count("communications.orphan_grace.cancelled") == 2
        assert all("Conflicting" not in item[1] and "Private" not in item[1] and "private-key" not in item[1] for item in audits)


def test_acknowledgement_closes_only_its_hold_and_retains_other_variant_or_export_protection(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    first = observe(factory, owner, scope, comm, variant)
    second_variant = replace(variant, fallback_digest="e" * 64, fallback_canonical_json=variant.fallback_canonical_json.replace("Conflicting Subject", "Second Subject"))
    second = observe(factory, owner, scope, comm, second_variant)
    export = new_uuid4()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',1000,NULL)", (export, comm, new_uuid4()))
    owner.keep_retained_content(preview(owner, scope, comm, first.review_evidence_id))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT protection_hold_id FROM communication_protection_holds WHERE state='ACTIVE' ORDER BY protection_hold_id").fetchall() == [(item,) for item in sorted((export, second.protection_hold_id))]
        assert db.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 2)


def test_content_review_purge_minimizes_evidence_and_replays_immutable_decision(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    found = observe(factory, owner, scope, comm, variant)
    request = preview(owner, scope, comm, found.review_evidence_id)
    result = owner.keep_retained_content(request)
    with sqlite3.connect(path) as db:
        revision, due = db.execute("SELECT revision,purge_due_utc FROM communication_retention").fetchone()
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=revision, now_utc=due)
    assert owner.keep_retained_content(request) == result
    with pytest.raises(SomaError):
        preview(owner, scope, comm, found.review_evidence_id)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT fallback_canonical_json,provider_identity_bytes,decision_event_id FROM communication_identity_review_evidence").fetchone() == (None, b"private-key", result["identity_review_event_id"])
        for sql in ("DELETE FROM communication_identity_review_evidence", "UPDATE communication_identity_review_evidence SET provider_identity_bytes=x'00'",
                    "UPDATE communication_identity_review_evidence SET fallback_canonical_json='{}'", "UPDATE communication_identity_review_events SET decision='KEEP_SEPARATE'",
                    "DELETE FROM communication_identity_review_events", "DELETE FROM communication_identity_review_results"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_content_acknowledgement_stale_preview_and_source_fail_without_partial_changes(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    found = observe(factory, owner, scope, comm, variant)
    request = preview(owner, scope, comm, found.review_evidence_id)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',1000,NULL)", (new_uuid4(), comm, new_uuid4()))
    with pytest.raises(SomaError, match="preview changed"):
        owner.keep_retained_content(request)
    request = preview(owner, scope, comm, found.review_evidence_id)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET revision=2 WHERE source_scope_id=?", (scope,))
    with pytest.raises(SomaError, match="configuration changed"):
        owner.keep_retained_content(request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT decision_event_id FROM communication_identity_review_evidence").fetchone() == (None,)
        assert db.execute("SELECT state FROM communication_protection_holds WHERE protection_hold_id=?", (found.protection_hold_id,)).fetchone() == ("ACTIVE",)
        assert db.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone() is None


def test_content_conflict_detection_and_decision_roll_back_with_caller_or_audit_failure(communication_database, monkeypatch):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    with pytest.raises(RuntimeError), UnitOfWork(factory) as writer:
        owner.observe_provider_content_in_uow(writer, source_scope_id=scope, source_revision=1,
            communication_id=comm, identity=variant, command_id=receipt(writer), now=1000)
        raise RuntimeError("caller failed after conflict capture")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_identity_review_evidence").fetchone() == (0,)
        assert db.execute("SELECT state,revision FROM communication_retention").fetchone() == ("ORPHAN_PENDING_PURGE", 1)
    found = observe(factory, owner, scope, comm, variant)
    request = preview(owner, scope, comm, found.review_evidence_id)
    def fail(*args):
        raise RuntimeError("review audit failed")
    monkeypatch.setattr(owner._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        owner.keep_retained_content(request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT decision_event_id FROM communication_identity_review_evidence").fetchone() == (None,)
        assert db.execute("SELECT state FROM communication_protection_holds").fetchone() == ("ACTIVE",)
        assert db.execute("SELECT count(*) FROM communication_identity_review_events").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_identity_review_results").fetchone() == (0,)


def test_detection_requires_writer_receipt_and_exact_provider_evidence_and_closed_decision_shape(communication_database):
    _, factory, owner, scope, comm, _, variant = setup(communication_database)
    with ReadSnapshot(factory) as reader, pytest.raises(IntegrityFailure):
        owner.observe_provider_content_in_uow(reader, source_scope_id=scope, source_revision=1,
            communication_id=comm, identity=variant, command_id=new_uuid4(), now=1000)
    with UnitOfWork(factory) as writer, pytest.raises(IntegrityFailure):
        owner.observe_provider_content_in_uow(writer, source_scope_id=scope, source_revision=1,
            communication_id=comm, identity=variant, command_id=new_uuid4(), now=1000)
    with UnitOfWork(factory) as writer, pytest.raises(SomaError):
        owner.observe_provider_content_in_uow(writer, source_scope_id=scope, source_revision=1,
            communication_id=comm, identity=replace(variant, provider_bytes=b"wrong"), command_id=receipt(writer), now=1000)
    with pytest.raises(ValidationError):
        IdentityReviewRequest(scope, 1, "KEEP_RETAINED_CONTENT", comm, 1, new_uuid4(), 1, new_uuid4())
    with pytest.raises(ValidationError):
        IdentityReviewRequest(scope, 1, "KEEP_SEPARATE", comm, 1, comm, 1, None)


def test_content_review_preview_work_does_not_grow_with_sibling_hold_collection(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    found = observe(factory, owner, scope, comm, variant)
    request = IdentityReviewRequest(scope, 1, "KEEP_RETAINED_CONTENT", comm, 1, None, None, found.review_evidence_id)

    def measured():
        steps = []
        with ReadSnapshot(factory) as reader:
            reader.connection.set_progress_handler(lambda: steps.append(1) or 0, 100)
            owner._content_preview(reader, request)
        return len(steps)

    baseline = measured()
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',1000,NULL)",
            ((new_uuid4(), comm, new_uuid4()) for _ in range(10000)))
    assert measured() <= baseline + 10


def test_acknowledgement_binds_current_configuration_and_preserves_captured_provenance(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    found = observe(factory, owner, scope, comm, variant)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET revision=2 WHERE source_scope_id=?", (scope,))
    value = IdentityReviewRequest(scope, 2, "KEEP_RETAINED_CONTENT", comm, 1, None, None, found.review_evidence_id).to_value()
    result = owner.keep_retained_content({**value, "command_id": new_uuid4(), "preview_fingerprint": owner.preview_keep_retained_content(value)})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT source_revision FROM communication_identity_review_evidence").fetchone() == (1,)
        assert db.execute("SELECT source_revision FROM communication_identity_review_events WHERE identity_review_event_id=?", (result["identity_review_event_id"],)).fetchone() == (2,)


def test_new_evidence_cannot_borrow_an_existing_acknowledgement(communication_database):
    path, factory, owner, scope, comm, _, variant = setup(communication_database)
    found = observe(factory, owner, scope, comm, variant)
    event = owner.keep_retained_content(preview(owner, scope, comm, found.review_evidence_id))["identity_review_event_id"]
    evidence, hold = new_uuid4(), new_uuid4()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'COLLISION_REVIEW',?,'ACTIVE',1200,NULL)", (hold, comm, evidence))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO communication_identity_review_evidence VALUES(?,?,?,?,?,?,?,?,?,?,1,1200,?)",
                (evidence, comm, scope, 1, hold, variant.provider_kind, variant.provider_digest, variant.provider_bytes,
                 variant.fallback_digest, variant.fallback_canonical_json, event))
