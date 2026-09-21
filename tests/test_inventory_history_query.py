from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.inventory.queries.attention_history import InventoryAttentionHistoryQuery
from test_inventory_requests_rma import _factory, _prepare_submitted_request


def _before(left: dict[str, object], right: dict[str, object]) -> bool:
    left_time = int(left["recorded_at_utc"])
    right_time = int(right["recorded_at_utc"])
    if left_time != right_time:
        return left_time > right_time
    left_authority = str(left["authority_kind"])
    right_authority = str(right["authority_kind"])
    if left_authority != right_authority:
        return left_authority < right_authority
    return str(left["immutable_event_or_relation_id"]) > str(
        right["immutable_event_or_relation_id"]
    )


def test_history_cursor_preserves_equal_second_authority_rows(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need, _service, request_id, _revision = _prepare_submitted_request(
        factory,
        official_sr="97100120",
        request_quantity=1,
        target_count=1,
        bom="HISTORY-TIE",
    )

    # Append two immutable corrections on one second to exercise the identity
    # tie-break without rewriting accepted history.
    command_id = new_uuid4()
    event_ids = sorted((new_uuid4(), new_uuid4()), reverse=True)
    with UnitOfWork(factory) as uow:
        target_event_id = str(
            uow.connection.execute(
                "SELECT request_event_id FROM spare_request_lifecycle_events "
                "WHERE spare_request_id=? ORDER BY recorded_at_utc,request_event_id LIMIT 1",
                (request_id,),
            ).fetchone()[0]
        )
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,"
            "target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?,'TestInventoryHistoryTie',?,'spare_request',?,5000,NULL,NULL)",
            (command_id, "f" * 64, request_id),
        )
        for event_id in event_ids:
            uow.connection.execute(
                "INSERT INTO spare_request_lifecycle_events(request_event_id,"
                "spare_request_id,event_kind,effective_at_utc,target_event_id,reason_code,"
                "evidence_kind,evidence_id,recorded_at_utc,command_id) "
                "VALUES (?,?,'correction',NULL,?,'history_cursor_test',NULL,NULL,5000,?)",
                (event_id, request_id, target_event_id, command_id),
            )

    query = InventoryAttentionHistoryQuery(factory)
    cursor = None
    items: list[dict[str, object]] = []
    while True:
        page = query.history(
            target_kind="spare_request",
            target_id=request_id,
            cursor=cursor,
            limit=1,
        )
        items.extend(page["items"])
        cursor = page["continuation"]
        if cursor is None:
            break

    assert len(items) >= 5
    identities = [
        (item["authority_kind"], item["immutable_event_or_relation_id"])
        for item in items
    ]
    assert len(identities) == len(set(identities))
    assert all(_before(left, right) for left, right in zip(items, items[1:]))
    assert {item["authority_kind"] for item in items} >= {
        "application_audit_reference",
        "domain_lifecycle_event",
        "relationship_change",
    }
    assert any(item["source_ref"] is not None for item in items)
    tied = [
        str(item["immutable_event_or_relation_id"])
        for item in items
        if item["recorded_at_utc"] == 5000
        and item["authority_kind"] == "domain_lifecycle_event"
    ]
    assert tied == event_ids


def test_history_cursor_binds_target_and_rejects_timestamp_only_shape(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need, _service, request_id, _revision = _prepare_submitted_request(
        factory,
        official_sr="97100121",
        request_quantity=1,
        target_count=1,
        bom="HISTORY-CURSOR",
    )
    query = InventoryAttentionHistoryQuery(factory)
    first = query.history(
        target_kind="spare_request",
        target_id=request_id,
        limit=1,
    )
    assert first["continuation"] is not None

    with pytest.raises(ValidationError, match="cursor contract"):
        query.history(
            target_kind="fault_tag",
            target_id=request_id,
            cursor=first["continuation"],
            limit=1,
        )
    with pytest.raises(ValidationError, match="cursor fields"):
        query.history(
            target_kind="spare_request",
            target_id=request_id,
            cursor={"after_recorded_at_utc": 5000},
            limit=1,
        )


@pytest.mark.parametrize(
    "target_kind",
    (
        "device_part_unit",
        "spare_need",
        "spare_request",
        "rma",
        "spare_part_unit",
        "physical_consequence",
        "fault_tag",
        "fault_tag_membership",
    ),
)
def test_history_supports_every_inventory_authority_family(
    initialized_database,
    target_kind: str,
) -> None:
    query = InventoryAttentionHistoryQuery(_factory(initialized_database))
    assert query.history(target_kind=target_kind, target_id=new_uuid4()) == {
        "items": [],
        "continuation": None,
    }
