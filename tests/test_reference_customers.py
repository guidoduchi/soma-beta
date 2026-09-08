from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService


def _connection(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path).open_authoritative(read_only=True, require_wal=True)


def test_equal_customer_names_are_distinct_and_create_replay_is_stable(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    command_id = new_uuid4()
    first = service.create_customer_organization(command_id=command_id, name="Acme Corp")
    replay = service.create_customer_organization(command_id=command_id, name="Acme Corp")
    other = service.create_customer_organization(command_id=new_uuid4(), name="Acme Corp")

    assert first.customer_org_id == replay.customer_org_id
    assert replay.replayed is True
    assert other.customer_org_id != first.customer_org_id

    connection = _connection(initialized_database)
    try:
        assert connection.execute("SELECT count(*) FROM customer_organizations").fetchone()[0] == 2
        keys = connection.execute("SELECT DISTINCT name_match_key FROM customer_organizations").fetchall()
        assert [row[0] for row in keys] == ["acme corp"]
    finally:
        connection.close()


def test_normal_account_code_set_refuses_to_steal_existing_claim(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    source = service.create_customer_organization(
        command_id=new_uuid4(), name="Source", account_code="ACC-100"
    )
    target = service.create_customer_organization(command_id=new_uuid4(), name="Target")

    with pytest.raises(SomaError) as exc:
        service.set_customer_account_code(
            command_id=new_uuid4(),
            customer_org_id=target.customer_org_id,
            base_revision=1,
            account_code="acc-100",
        )
    assert exc.value.code == "ACCOUNT_CODE_CONFLICT_REVIEW"

    connection = _connection(initialized_database)
    try:
        rows = connection.execute(
            "SELECT customer_org_id, lifecycle_state FROM customer_org_identifiers "
            "WHERE match_key='acc-100'"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [(source.customer_org_id, "active")]
    finally:
        connection.close()


def test_reviewed_shared_claim_preserves_explicit_ambiguity(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    source = service.create_customer_organization(
        command_id=new_uuid4(), name="Source", account_code="ACC-200"
    )
    target = service.create_customer_organization(command_id=new_uuid4(), name="Target")

    preview = service.preview_account_code_review(
        raw_account_code="acc-200",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=target.customer_org_id,
    )
    assert preview.claimant_count == 1
    result = service.confirm_customer_account_code_shared_claim(
        command_id=new_uuid4(),
        customer_org_id=target.customer_org_id,
        base_revision=1,
        account_code="ACC-200",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="verified_shared_provider_claim",
    )
    assert result.no_change is False

    connection = _connection(initialized_database)
    try:
        claimants = connection.execute(
            "SELECT customer_org_id FROM customer_org_identifiers "
            "WHERE match_key='acc-200' AND lifecycle_state='active' ORDER BY customer_org_id"
        ).fetchall()
        assert {row[0] for row in claimants} == {source.customer_org_id, target.customer_org_id}
        assert len(claimants) == 2
    finally:
        connection.close()


def test_account_code_review_goes_stale_on_reference_generation_change(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    service.create_customer_organization(command_id=new_uuid4(), name="Source", account_code="ACC-300")
    target = service.create_customer_organization(command_id=new_uuid4(), name="Target")
    preview = service.preview_account_code_review(
        raw_account_code="ACC-300",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=target.customer_org_id,
    )

    service.create_customer_organization(command_id=new_uuid4(), name="Unrelated generation change")
    with pytest.raises(SomaError) as exc:
        service.confirm_customer_account_code_shared_claim(
            command_id=new_uuid4(),
            customer_org_id=target.customer_org_id,
            base_revision=1,
            account_code="ACC-300",
            review_snapshot_hash=preview.review_snapshot_hash,
            reason_category="verified_shared_provider_claim",
        )
    assert exc.value.code == "REVIEW_CONTEXT_STALE"


def test_reviewed_reassignment_supersedes_source_without_erasing_history(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    source = service.create_customer_organization(
        command_id=new_uuid4(), name="Source", account_code="ACC-400"
    )
    shared = service.create_customer_organization(command_id=new_uuid4(), name="Shared")
    shared_preview = service.preview_account_code_review(
        raw_account_code="ACC-400",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=shared.customer_org_id,
    )
    service.confirm_customer_account_code_shared_claim(
        command_id=new_uuid4(),
        customer_org_id=shared.customer_org_id,
        base_revision=1,
        account_code="ACC-400",
        review_snapshot_hash=shared_preview.review_snapshot_hash,
        reason_category="verified_shared_provider_claim",
    )
    destination = service.create_customer_organization(command_id=new_uuid4(), name="Destination")

    preview = service.preview_account_code_review(
        raw_account_code="ACC-400",
        proposed_action="REASSIGN_CLAIM",
        target_customer_org_id=destination.customer_org_id,
        from_customer_org_id=source.customer_org_id,
    )
    service.reassign_customer_account_code(
        command_id=new_uuid4(),
        from_customer_org_id=source.customer_org_id,
        from_base_revision=1,
        to_customer_org_id=destination.customer_org_id,
        to_base_revision=1,
        account_code="ACC-400",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="provider_ownership_corrected",
    )

    connection = _connection(initialized_database)
    try:
        current = connection.execute(
            "SELECT customer_org_id FROM customer_org_identifiers "
            "WHERE match_key='acc-400' AND lifecycle_state='active' ORDER BY customer_org_id"
        ).fetchall()
        assert {row[0] for row in current} == {shared.customer_org_id, destination.customer_org_id}
        history = connection.execute(
            "SELECT lifecycle_state, superseded_command_id FROM customer_org_identifiers "
            "WHERE customer_org_id=? ORDER BY created_at_utc, customer_org_identifier_id",
            (source.customer_org_id,),
        ).fetchall()
        assert len(history) == 1
        assert history[0][0] == "superseded"
        assert history[0][1] is not None
    finally:
        connection.close()


def test_customer_audit_payload_does_not_duplicate_names_or_raw_codes(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = CustomerReferenceService(factory_for_path(database_path))
    service.create_customer_organization(
        command_id=new_uuid4(), name="Secret-ish Customer Label", account_code="RAW-CODE-777"
    )
    connection = _connection(initialized_database)
    try:
        payloads = [str(row[0]) for row in connection.execute("SELECT payload_json FROM audit_events").fetchall()]
        assert payloads
        joined = "\n".join(payloads)
        assert "Secret-ish Customer Label" not in joined
        assert "RAW-CODE-777" not in joined
        for payload in payloads:
            json.loads(payload)
    finally:
        connection.close()
