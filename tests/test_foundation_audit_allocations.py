from __future__ import annotations

import json

import pytest

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import ObjectContract
from soma.inventory.audit_registry import build_inventory_audit_registry
from soma.product_line_sla.audit_registry import build_product_line_sla_audit_registry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _receipt(uow: UnitOfWork, command_id: str, command_type: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            command_id,
            command_type,
            "0" * 64,
            "audit_allocation_test",
            None,
            1,
            None,
            None,
        ),
    )


def _uuid_for(ordinal: int) -> str:
    return f"{ordinal:08x}-0000-4000-8000-{ordinal:012x}"


def test_sla_batch_allocation_accepts_500_audit_result_refs(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = build_product_line_sla_audit_registry()
    contract = registry.resolve(
        "sla.service_request.batch_classification_applied",
        1,
    )
    assert contract.payload_contract.max_utf8_bytes == 32_768

    ids = [_uuid_for(index + 1) for index in range(500)]
    payload = {
        "batch_correlation_id": "reviewed-batch",
        "requested_count": 500,
        "eligible_count": 500,
        "applied_count": 500,
        "unchanged_count": 0,
        "rejected_count": 0,
        "preview_fingerprint": "a" * 64,
        "result_refs": ids,
    }
    command_id = new_uuid4()
    audit_id = new_uuid4()
    writer = AuditWriter(registry)
    with UnitOfWork(factory) as uow:
        _receipt(uow, command_id, "TestSlaBatchAuditAllocation")
        writer.write(
            uow,
            AuditEventInput(
                audit_event_id=audit_id,
                action_type="sla.service_request.batch_classification_applied",
                action_version=1,
                actor_kind="test",
                target_type="service_request_batch",
                target_id="reviewed-batch",
                command_id=command_id,
                payload_schema="BatchClassificationAuditV1",
                payload_version=1,
                payload=payload,
                resulting_event_refs=tuple(
                    AuditResultRef("sr_classification_event", identity)
                    for identity in ids
                ),
            ),
        )

    with ReadSnapshot(factory) as snapshot:
        stored = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE audit_event_id=?",
            (audit_id,),
        ).fetchone()
        assert stored is not None
        assert 16_384 < len(str(stored[0]).encode("utf-8")) < 32_768
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_event_results WHERE audit_event_id=?",
            (audit_id,),
        ).fetchone()[0] == 500


def test_sla_batch_allocation_rejects_501_audit_result_refs(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = build_product_line_sla_audit_registry()
    ids = [_uuid_for(index + 1) for index in range(500)]
    command_id = new_uuid4()
    extra = AuditResultRef("sr_classification_event", _uuid_for(501))

    with pytest.raises(SomaError) as raised:
        with UnitOfWork(factory) as uow:
            _receipt(uow, command_id, "TestSlaBatchAuditOverflow")
            AuditWriter(registry).write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.service_request.batch_classification_applied",
                    action_version=1,
                    actor_kind="test",
                    target_type="service_request_batch",
                    target_id="reviewed-batch",
                    command_id=command_id,
                    payload_schema="BatchClassificationAuditV1",
                    payload_version=1,
                    payload={
                        "batch_correlation_id": "reviewed-batch",
                        "requested_count": 500,
                        "eligible_count": 500,
                        "applied_count": 500,
                        "unchanged_count": 0,
                        "rejected_count": 0,
                        "preview_fingerprint": "a" * 64,
                        "result_refs": ids,
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef("sr_classification_event", identity)
                        for identity in ids
                    )
                    + (extra,),
                ),
            )
    assert raised.value.code == "AUDIT_PAYLOAD_INVALID"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None


def test_inventory_bulk_allocation_accepts_2000_typed_payload_refs(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = build_inventory_audit_registry()
    contract = registry.resolve("inventory.bulk.accepted", 1)
    assert contract.payload_contract.max_utf8_bytes == 262_144
    assert contract.payload_contract.max_collection_items == 8_192

    payload_refs = [
        {"type": "fault_tag_membership_event", "id": _uuid_for(index + 1)}
        for index in range(2_000)
    ]
    command_id = new_uuid4()
    audit_id = new_uuid4()
    batch_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, command_id, "TestInventoryBulkAuditAllocation")
        AuditWriter(registry).write(
            uow,
            AuditEventInput(
                audit_event_id=audit_id,
                action_type="inventory.bulk.accepted",
                action_version=1,
                actor_kind="test",
                target_type="inventory_batch",
                target_id=batch_id,
                command_id=command_id,
                payload_schema="InventoryBulkAuditV1",
                payload_version=1,
                payload={
                    "batch_id": batch_id,
                    "action_kind": "warehouse_receipt",
                    "input_fingerprint": "b" * 64,
                    "target_count": 2_000,
                    "result_refs": payload_refs,
                    "result": "APPLIED",
                },
                resulting_event_refs=(
                    AuditResultRef("inventory_batch", batch_id),
                ),
            ),
        )

    with ReadSnapshot(factory) as snapshot:
        stored = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE audit_event_id=?",
            (audit_id,),
        ).fetchone()
        assert stored is not None
        payload_json = str(stored[0])
        assert 131_072 < len(payload_json.encode("utf-8")) < 262_144
        assert len(json.loads(payload_json)["result_refs"]) == 2_000
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_event_results WHERE audit_event_id=?",
            (audit_id,),
        ).fetchone()[0] == 1


def test_unlisted_audit_action_cannot_widen_foundation_payload_limit(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="test.unreviewed_large_audit",
            action_version=1,
            payload_schema="UnreviewedLargeAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="UnreviewedLargeAuditV1",
                version=1,
                required_fields=frozenset({"value"}),
                allowed_fields=frozenset({"value"}),
                max_utf8_bytes=65_536,
            ),
        )
    )

    accepted_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, accepted_command, "TestUnreviewedAuditOrdinarySize")
        AuditWriter(registry).write(
            uow,
            AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="test.unreviewed_large_audit",
                action_version=1,
                actor_kind="test",
                target_type="test",
                command_id=accepted_command,
                payload_schema="UnreviewedLargeAuditV1",
                payload_version=1,
                payload={"value": "small"},
            ),
        )

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as raised:
        with UnitOfWork(factory) as uow:
            _receipt(uow, rejected_command, "TestUnreviewedAuditAllocation")
            AuditWriter(registry).write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="test.unreviewed_large_audit",
                    action_version=1,
                    actor_kind="test",
                    target_type="test",
                    command_id=rejected_command,
                    payload_schema="UnreviewedLargeAuditV1",
                    payload_version=1,
                    payload={"value": "x" * 16_384},
                ),
            )
    assert raised.value.code == "AUDIT_PAYLOAD_INVALID"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (rejected_command,),
        ).fetchone() is None


def test_ordinary_audit_action_rejects_more_than_128_result_refs(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="test.ordinary_audit",
            action_version=1,
            payload_schema="OrdinaryAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="OrdinaryAuditV1",
                version=1,
                required_fields=frozenset({"value"}),
                allowed_fields=frozenset({"value"}),
                max_utf8_bytes=1_024,
            ),
        )
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as raised:
        with UnitOfWork(factory) as uow:
            _receipt(uow, command_id, "TestOrdinaryAuditRefBound")
            AuditWriter(registry).write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="test.ordinary_audit",
                    action_version=1,
                    actor_kind="test",
                    target_type="test",
                    command_id=command_id,
                    payload_schema="OrdinaryAuditV1",
                    payload_version=1,
                    payload={"value": "small"},
                    resulting_event_refs=tuple(
                        AuditResultRef("test", _uuid_for(index + 1))
                        for index in range(129)
                    ),
                ),
            )
    assert raised.value.code == "AUDIT_PAYLOAD_INVALID"
