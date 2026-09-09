from __future__ import annotations

import pytest

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import PersistenceFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract


def _writer() -> AuditWriter:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="test.response_factory",
            action_version=1,
            payload_schema="ResponseFactoryAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="ResponseFactoryAuditV1",
                version=1,
                required_fields=frozenset({"entity_id"}),
                allowed_fields=frozenset({"entity_id"}),
            ),
        )
    )
    return AuditWriter(registry)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_table(factory) -> None:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TABLE response_factory_probe("
            "entity_id TEXT PRIMARY KEY,value_text TEXT NOT NULL"
            ") STRICT"
        )


def test_response_factory_runs_after_mutation_and_never_on_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    _create_table(factory)
    command_id = new_uuid4()
    entity_id = new_uuid4()
    prepare_count = [0]
    response_count = [0]
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="ResponseFactoryProbe",
        target_type="probe",
        target_id=entity_id,
        semantic_payload={"value_text": "original"},
    )

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        prepare_count[0] += 1

        def apply(inner: UnitOfWork) -> AuditEventInput:
            inner.connection.execute(
                "INSERT INTO response_factory_probe(entity_id,value_text) VALUES (?, 'original')",
                (entity_id,),
            )
            return AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="test.response_factory",
                action_version=1,
                actor_kind="local_user",
                target_type="probe",
                target_id=entity_id,
                command_id=command_id,
                payload_schema="ResponseFactoryAuditV1",
                payload_version=1,
                payload={"entity_id": entity_id},
                resulting_event_refs=(AuditResultRef("probe", entity_id),),
            )

        def build_response(inner: UnitOfWork):
            response_count[0] += 1
            row = inner.connection.execute(
                "SELECT value_text FROM response_factory_probe WHERE entity_id=?",
                (entity_id,),
            ).fetchone()
            assert row is not None
            return {"entity_id": entity_id, "value_text": str(row[0])}

        return PreparedMutation(
            False,
            "probe",
            entity_id,
            apply,
            response_schema="ResponseFactoryProbeV1",
            response_version=1,
            response_factory=build_response,
        )

    boundary = CommandBoundary(factory, _writer())
    first = boundary.execute(envelope, prepare)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE response_factory_probe SET value_text='later' WHERE entity_id=?",
            (entity_id,),
        )
    replay = boundary.execute(envelope, prepare)

    assert prepare_count == [1]
    assert response_count == [1]
    assert first.response == replay.response == {
        "entity_id": entity_id,
        "value_text": "original",
    }
    assert replay.replayed is True


def test_response_factory_failure_rolls_back_all_authoritative_writes(initialized_database) -> None:
    factory = _factory(initialized_database)
    _create_table(factory)
    command_id = new_uuid4()
    entity_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="FailingResponseFactoryProbe",
        target_type="probe",
        target_id=entity_id,
        semantic_payload={},
    )

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        def apply(inner: UnitOfWork) -> AuditEventInput:
            inner.connection.execute(
                "INSERT INTO response_factory_probe(entity_id,value_text) VALUES (?, 'original')",
                (entity_id,),
            )
            return AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="test.response_factory",
                action_version=1,
                actor_kind="local_user",
                target_type="probe",
                target_id=entity_id,
                command_id=command_id,
                payload_schema="ResponseFactoryAuditV1",
                payload_version=1,
                payload={"entity_id": entity_id},
                resulting_event_refs=(AuditResultRef("probe", entity_id),),
            )

        def fail_response(inner: UnitOfWork):
            raise PersistenceFailure("injected response projection failure")

        return PreparedMutation(
            False,
            "probe",
            entity_id,
            apply,
            response_schema="ResponseFactoryProbeV1",
            response_version=1,
            response_factory=fail_response,
        )

    with pytest.raises(PersistenceFailure):
        CommandBoundary(factory, _writer()).execute(envelope, prepare)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute("SELECT count(*) FROM response_factory_probe").fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()
