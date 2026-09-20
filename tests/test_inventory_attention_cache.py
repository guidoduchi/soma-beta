from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.queries.attention_history import InventoryAttentionHistoryQuery
from test_inventory_requests_rma import _prepare_submitted_request
from test_inventory_warehouse_replay import _current_members, _members, _submitted_tag


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def test_t028_unassigned_rma_attention_is_command_time_projection(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need, service, request_id, revision = _prepare_submitted_request(
        factory,
        official_sr="97100111",
        request_quantity=2,
        target_count=1,
        bom="ATTN-RMA-MATCH",
    )
    batch = service.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=revision,
        rows=(
            RmaAuthorizationIntent("C0000000111", "ATTN-RMA-MATCH"),
            RmaAuthorizationIntent("C0000000112", "ATTN-RMA-NO-MATCH"),
        ),
        accepted_at_utc=3_000,
    )
    unassigned_id = str(batch["created_rmas"][1]["rma_id"])

    page = InventoryAttentionHistoryQuery(factory).attention(
        attention_kind="rma_assignment_conflict",
        as_of_utc=3_000,
    )
    assert page["exact_total"] == 1
    assert [item["target_id"] for item in page["items"]] == [unassigned_id]
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT target_kind,target_id,attention_kind,severity "
            "FROM inventory_attention_projection "
            "WHERE attention_kind='rma_assignment_conflict'"
        ).fetchone()
        assert tuple(row) == (
            "rma",
            unassigned_id,
            "rma_assignment_conflict",
            "action_required",
        )


def test_t052_t054_t066_rejected_return_stays_actionable_when_tag_archived(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    tags, submitted, _rmas = _submitted_tag(factory)
    tag_id = str(submitted["fault_tag_id"])
    submitted_members = _members(submitted)
    rejected_id = submitted_members[0].fault_tag_membership_id

    tags.record_warehouse_receipt(
        command_id=new_uuid4(),
        memberships=submitted_members,
    )
    pending = InventoryAttentionHistoryQuery(factory).attention(
        attention_kind="warehouse_final_decision_pending",
        as_of_utc=4_000,
    )
    assert pending["exact_total"] == 2

    current = _current_members(factory, tag_id)
    tags.record_warehouse_final_decision(
        command_id=new_uuid4(),
        memberships=(current[0],),
        decision="rejected",
        explicit_confirmation=True,
        reason_code="warehouse rejection",
    )
    current = _current_members(factory, tag_id)
    remaining = tuple(
        item for item in current if item.fault_tag_membership_id != rejected_id
    )
    assert len(remaining) == 1
    tags.record_warehouse_final_decision(
        command_id=new_uuid4(),
        memberships=remaining,
        decision="accepted",
        explicit_confirmation=True,
    )

    attention = InventoryAttentionHistoryQuery(factory)
    resend = attention.attention(
        attention_kind="warehouse_rejected_resend_required",
        as_of_utc=4_001,
    )
    assert resend["exact_total"] == 1
    assert resend["items"][0]["target_id"] == rejected_id
    open_returns = attention.attention(
        attention_kind="return_obligation_open",
        as_of_utc=4_001,
    )
    assert open_returns["exact_total"] == 1

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT state,revision,rejected_count,accepted_count "
            "FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchone()
        assert str(projection[0]) == "terminal_with_rejected"
        assert int(projection[2]) == 1
        assert int(projection[3]) == 1
        tag_revision = int(projection[1])

    with ReadSnapshot(factory) as snapshot:
        fingerprint_before_archive = str(
            snapshot.connection.execute(
                "SELECT input_fingerprint FROM inventory_attention_projection "
                "WHERE target_id=? AND attention_kind='warehouse_rejected_resend_required'",
                (rejected_id,),
            ).fetchone()[0]
        )

    tags.archive_or_restore_fault_tag(
        command_id=new_uuid4(),
        fault_tag_id=tag_id,
        base_revision=tag_revision,
        action="archive",
        reason_code="retain terminal history",
    )
    archived = attention.attention(
        attention_kind="warehouse_rejected_resend_required",
        as_of_utc=4_002,
    )
    assert archived["exact_total"] == 1
    assert archived["items"][0]["target_id"] == rejected_id
    with ReadSnapshot(factory) as snapshot:
        fingerprint_after_archive = str(
            snapshot.connection.execute(
                "SELECT input_fingerprint FROM inventory_attention_projection "
                "WHERE target_id=? AND attention_kind='warehouse_rejected_resend_required'",
                (rejected_id,),
            ).fetchone()[0]
        )
    assert fingerprint_after_archive != fingerprint_before_archive
