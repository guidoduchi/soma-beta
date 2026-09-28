from __future__ import annotations

from typing import Any

import soma.reference.application.customer_service as customer_service_module

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.queries.references import ReferenceQueries


class _TracedFactory:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.statements: list[str] = []

    def open_authoritative(self, **kwargs):
        connection = self._inner.open_authoritative(**kwargs)
        connection.set_trace_callback(self.statements.append)
        return connection


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _select_count(statements: list[str]) -> int:
    return sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def _plan_text(connection: Any, sql: str, params: tuple[object, ...]) -> str:
    rows = connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return "\n".join(str(row[3]) for row in rows)


def test_t032_contact_detail_select_budget_is_constant_and_pages_use_supporting_indexes(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Set Based Contact",
    )

    traced_empty = _TracedFactory(factory)
    empty = ReferenceQueries(traced_empty).get_reference_by_id(
        reference_type="contact",
        reference_id=contact.contact_id,
        channel_limit=50,
    )
    assert empty.projection["channels"] == ()
    empty_selects = _select_count(traced_empty.statements)

    with UnitOfWork(factory) as uow:
        for ordinal in range(25):
            channel_id = new_uuid4()
            value = f"set-based-{ordinal:02d}@example.com"
            uow.connection.execute(
                "INSERT INTO contact_channels("
                "contact_channel_id,contact_id,channel_kind,value_text,match_key,"
                "lifecycle_state,revision,created_at_utc,updated_at_utc"
                ") VALUES (?,?,'email',?,?,'active',1,?,?)",
                (
                    channel_id,
                    contact.contact_id,
                    value,
                    value,
                    100 + ordinal,
                    100 + ordinal,
                ),
            )

    traced_many = _TracedFactory(factory)
    populated = ReferenceQueries(traced_many).get_reference_by_id(
        reference_type="contact",
        reference_id=contact.contact_id,
        channel_limit=50,
    )
    assert len(populated.projection["channels"]) == 25
    assert _select_count(traced_many.statements) == empty_selects
    assert empty_selects == 5

    with ReadSnapshot(factory) as snapshot:
        contact_list_plan = _plan_text(
            snapshot.connection,
            "SELECT contact_id,name,name_match_key,revision,lifecycle_state "
            "FROM contacts WHERE lifecycle_state='active' "
            "ORDER BY name_match_key,contact_id LIMIT ?",
            (51,),
        )
        channel_page_plan = _plan_text(
            snapshot.connection,
            "SELECT contact_channel_id,channel_kind,value_text,lifecycle_state,revision,"
            "created_at_utc,updated_at_utc FROM contact_channels "
            "WHERE contact_id=? AND lifecycle_state='active' "
            "ORDER BY channel_kind,created_at_utc,contact_channel_id LIMIT ?",
            (contact.contact_id, 51),
        )
        affiliation_history_plan = _plan_text(
            snapshot.connection,
            "SELECT contact_affiliation_id,customer_org_id,is_current,opened_at_utc,"
            "closed_at_utc,opened_command_id,closed_command_id "
            "FROM contact_affiliations WHERE contact_id=? "
            "ORDER BY opened_at_utc,contact_affiliation_id LIMIT ?",
            (contact.contact_id, 51),
        )

    assert "idx_contacts_active_name_match" in contact_list_plan
    assert "idx_contact_channels_contact" in channel_page_plan
    assert "idx_contact_affiliation_history" in affiliation_history_plan
    assert "USE TEMP B-TREE" not in contact_list_plan
    assert "USE TEMP B-TREE" not in channel_page_plan
    assert "USE TEMP B-TREE" not in affiliation_history_plan


def test_t035_review_commit_validation_uses_bounded_point_and_indexed_count_work(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    service = CustomerReferenceService(factory)
    service.create_customer_organization(
        command_id=new_uuid4(),
        name="Existing Claimant",
        account_code="REVIEW-COST-001",
    )
    target = service.create_customer_organization(
        command_id=new_uuid4(),
        name="Reviewed Target",
    )
    preview = service.preview_account_code_review(
        raw_account_code="REVIEW-COST-001",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=target.customer_org_id,
    )

    statements: list[str] = []
    original_validate = customer_service_module.validate_account_code_review

    def traced_validate(connection, **kwargs):
        connection.set_trace_callback(statements.append)
        try:
            return original_validate(connection, **kwargs)
        finally:
            connection.set_trace_callback(None)

    monkeypatch.setattr(
        customer_service_module,
        "validate_account_code_review",
        traced_validate,
    )
    service.confirm_customer_account_code_shared_claim(
        command_id=new_uuid4(),
        customer_org_id=target.customer_org_id,
        base_revision=1,
        account_code="REVIEW-COST-001",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="verified_shared_provider_claim",
    )

    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 5
    assert sum("reference_metadata" in statement for statement in selects) == 1
    assert sum("customer_organizations" in statement for statement in selects) == 1
    assert sum("COUNT(*)" in statement.upper() for statement in selects) == 2
    assert not any("ORDER BY customer_org_id" in statement for statement in selects)
    assert not any(".fetchall" in statement.lower() for statement in selects)

    with ReadSnapshot(factory) as snapshot:
        count_plan = _plan_text(
            snapshot.connection,
            "SELECT count(*) FROM customer_org_identifiers "
            "WHERE identifier_type='customer_account_code' AND match_key=? "
            "AND lifecycle_state='active'",
            ("review-cost-001",),
        )
        point_plan = _plan_text(
            snapshot.connection,
            "SELECT match_key FROM customer_org_identifiers "
            "WHERE customer_org_id=? AND identifier_type='customer_account_code' "
            "AND lifecycle_state='active'",
            (target.customer_org_id,),
        )

    assert "idx_customer_active_identifier_value" in count_plan
    assert "uq_customer_org_active_identifier_type" in point_plan
    assert "USE TEMP B-TREE" not in count_plan
    assert "USE TEMP B-TREE" not in point_plan
