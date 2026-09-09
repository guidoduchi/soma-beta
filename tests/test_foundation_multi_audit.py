from __future__ import annotations

import pytest

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import ObjectContract


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _contract(action_type: str, schema: str) -> AuditActionContract:
    fields = frozenset({"value"})
    return AuditActionContract(
        action_type=action_type,
        action_version=1,
        payload_schema=schema,
        payload_version=1,
        payload_contract=ObjectContract(
            name=schema,
            version=1,
            required_fields=fields,
            allowed_fields=fields,
            max_depth=2,
            max_collection_items=4,
            max_utf8_bytes=1024,
        ),
    )


def _event(command_id: str, action_type: str, schema: str, value: str) -> AuditEventInput:
    return AuditEventInput(
        audit_event_id=new_uuid4(),
        action_type=action_type,
        action_version=1,
        actor_kind="test",
        target_type="test_probe",
        target_id=value,
        command_id=command_id,
        payload_schema=schema,
        payload_version=1,
        payload={"value": value},
    )


def _prepare_probe_table(factory) -> None:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TABLE IF NOT EXISTS foundation_multi_audit_probe(command_id TEXT PRIMARY KEY) STRICT"
        )


def _response(command_id: str) -> dict[str, object]:
    return {"command_id": command_id, "outcome": "APPLIED"}


def test_command_boundary_commits_multiple_packet_owned_audits_and_replays_without_reemission(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prepare_probe_table(factory)

    tickets_registry = AuditRegistry()
    tickets_registry.register(_contract("ticket.test_owner", "TicketTestAuditV1"))
    import_registry = AuditRegistry()
    import_registry.register(_contract("ticket_import.test_orchestration", "ImportTestAuditV1"))
    combined = AuditRegistry()
    combined.extend(tickets_registry)
    combined.extend(import_registry)

    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="TestMultiAudit",
        target_type="test_probe",
        target_id=command_id,
        semantic_payload={"value": "accepted"},
    )
    boundary = CommandBoundary(factory, AuditWriter(combined))

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        def apply(inner: UnitOfWork):
            inner.connection.execute(
                "INSERT INTO foundation_multi_audit_probe(command_id) VALUES (?)",
                (command_id,),
            )
            return (
                _event(command_id, "ticket.test_owner", "TicketTestAuditV1", "owner"),
                _event(command_id, "ticket_import.test_orchestration", "ImportTestAuditV1", "orchestration"),
            )

        return PreparedMutation(
            False,
            "test_probe",
            command_id,
            apply,
            response_schema="TestMultiAuditResultV1",
            response=_response(command_id),
        )

    result = boundary.execute(envelope, prepare)
    assert result.replayed is False
    assert result.no_change is False
    assert result.response == _response(command_id)

    replay = boundary.execute(
        envelope,
        lambda uow: pytest.fail("committed replay reached current-state preparation"),
    )
    assert replay.replayed is True
    assert replay.response == _response(command_id)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM foundation_multi_audit_probe WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        actions = snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=? ORDER BY action_type",
            (command_id,),
        ).fetchall()
        assert [str(row[0]) for row in actions] == [
            "ticket.test_owner",
            "ticket_import.test_orchestration",
        ]


def test_second_required_audit_failure_rolls_back_receipt_first_audit_and_domain_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prepare_probe_table(factory)

    registry = AuditRegistry()
    registry.register(_contract("ticket.test_owner", "TicketTestAuditV1"))
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="TestMultiAuditRollback",
        target_type="test_probe",
        target_id=command_id,
        semantic_payload={"value": "rollback"},
    )
    boundary = CommandBoundary(factory, AuditWriter(registry))

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        def apply(inner: UnitOfWork):
            inner.connection.execute(
                "INSERT INTO foundation_multi_audit_probe(command_id) VALUES (?)",
                (command_id,),
            )
            return (
                _event(command_id, "ticket.test_owner", "TicketTestAuditV1", "owner"),
                _event(command_id, "ticket_import.unregistered", "MissingAuditV1", "orchestration"),
            )

        return PreparedMutation(
            False,
            "test_probe",
            command_id,
            apply,
            response_schema="TestMultiAuditResultV1",
            response=_response(command_id),
        )

    with pytest.raises(SomaError) as excinfo:
        boundary.execute(envelope, prepare)
    assert excinfo.value.code == "AUDIT_ACTION_UNKNOWN"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM foundation_multi_audit_probe WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_registry_composition_rejects_duplicate_action_ownership() -> None:
    left = AuditRegistry()
    right = AuditRegistry()
    left.register(_contract("ticket.shared", "SharedAuditV1"))
    right.register(_contract("ticket.shared", "SharedAuditV1"))
    combined = AuditRegistry()
    combined.extend(left)
    with pytest.raises(SomaError) as excinfo:
        combined.extend(right)
    assert excinfo.value.code == "AUDIT_ACTION_DUPLICATE"
