from __future__ import annotations

import hashlib

import pytest

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.application.command_receipts import CommittedCommandResult
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract, _measure


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


def test_prepared_mutation_requires_explicit_response_schema() -> None:
    prepared = PreparedMutation(
        True,
        None,
        None,
        response={"outcome": "NO_CHANGE"},
    )
    with pytest.raises(ValidationError, match="response schema must be declared explicitly"):
        prepared.validate()


def test_prepared_mutation_requires_exact_response_value_or_factory() -> None:
    prepared = PreparedMutation(
        True,
        None,
        None,
        response_schema="NoChangeProbeV1",
    )
    with pytest.raises(ValidationError, match="exact response value or same-UoW response factory"):
        prepared.validate()


def test_missing_exact_response_fails_before_command_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="MissingExactResponseProbe",
        target_type="probe",
        target_id=None,
        semantic_payload={},
    )

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        return PreparedMutation(
            True,
            None,
            None,
            response_schema="NoChangeProbeV1",
        )

    with pytest.raises(ValidationError, match="exact response value or same-UoW response factory"):
        CommandBoundary(factory, _writer()).execute(envelope, prepare)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


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



def _conservative_max_rfc_branch_response() -> dict[str, object]:
    max_integer = 9_223_372_036_854_775_807
    uuid_value = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    control = chr(1)

    source_projection = {
        "summary_text": control * 16_384,
        "summary_evidence_id": uuid_value,
        "external_created_at_utc": max_integer,
        "external_created_evidence_id": uuid_value,
        "creator_text": control * 2_048,
        "creator_evidence_id": uuid_value,
        "customer_account_number_text": control * 1_024,
        "customer_account_number_evidence_id": uuid_value,
        "customer_account_name_text": control * 4_096,
        "customer_account_name_evidence_id": uuid_value,
        "severity_text": control * 256,
        "severity_evidence_id": uuid_value,
        "status_text": "Cancelled",
        "status_class": "terminal_cancelled",
        "status_authority": "wfm_provisional",
        "status_evidence_id": uuid_value,
        "terminal_epoch_id": uuid_value,
        "owner_external_id_text": control * 2_048,
        "owner_external_id_evidence_id": uuid_value,
        "owner_name_text": control * 4_096,
        "owner_name_evidence_id": uuid_value,
        "l1_handler_name_text": control * 4_096,
        "l1_handler_name_evidence_id": uuid_value,
        "l2_handler_name_text": control * 4_096,
        "l2_handler_name_evidence_id": uuid_value,
        "last_update_utc": max_integer,
        "last_update_evidence_id": uuid_value,
        "revision": max_integer,
    }

    def detail(role: str, subordinate_count: int) -> dict[str, object]:
        return {
            "rfc_id": uuid_value,
            "rfc_no": "NC" + ("9" * 14),
            "revision": max_integer,
            "hierarchy_role": role,
            "customer_org_id": uuid_value,
            "local_archive_state": "archived",
            "source_projection": source_projection,
            "direct_service_request_count": max_integer,
            "device_reference_count": max_integer,
            "subordinate_count": subordinate_count,
            "warnings": ["RFC_CUSTOMER_REFERENCE_ARCHIVED"],
        }

    continuation = {
        "version": 1,
        "query_id": "GetRfcBranch",
        "sort_registry_id": "RFC_BRANCH_CHILD_ID_ASC_V1",
        "last_key_tuple": [uuid_value],
        "filter_fingerprint": "f" * 64,
        "null_order": "not_applicable",
    }
    return {
        "root": detail("root", max_integer),
        "subordinates": [detail("subordinate", 0) for _ in range(100)],
        "continuation": continuation,
        "branch_fingerprint": "f" * 64,
    }


def test_rfc_branch_reviewed_allocation_matches_normative_worst_case_derivation() -> None:
    response = _conservative_max_rfc_branch_response()
    text, _digest, normalized = CommandBoundary._encode_response(
        response,
        response_schema="RfcBranchV1",
        response_version=1,
    )

    assert len(text.encode("utf-8")) == 23_288_983
    assert _measure(normalized)[:2] == (4, 4_151)


def test_rfc_branch_reviewed_allocation_enforces_exact_schema_version_and_bounds() -> None:
    bounds = CommandBoundary._response_bounds("RfcBranchV1", 1)
    assert (bounds.max_bytes, bounds.max_depth, bounds.max_collection_items) == (
        33_554_432,
        8,
        8_192,
    )

    with pytest.raises(
        ValidationError,
        match="unsupported command response schema/version",
    ):
        CommandBoundary._response_bounds("RfcBranchV1", 2)

    default_bounds = CommandBoundary._response_bounds("CommandExecutionResultV1", 1)
    assert (
        default_bounds.max_bytes,
        default_bounds.max_depth,
        default_bounds.max_collection_items,
    ) == (524_288, 8, 512)

    exact_byte_payload = {"x": "a" * (33_554_432 - 8)}
    encoded, _digest, _normalized = CommandBoundary._encode_response(
        exact_byte_payload,
        response_schema="RfcBranchV1",
        response_version=1,
    )
    assert len(encoded.encode("utf-8")) == 33_554_432
    with pytest.raises(ValidationError, match="byte bound"):
        CommandBoundary._encode_response(
            {"x": "a" * (33_554_432 - 7)},
            response_schema="RfcBranchV1",
            response_version=1,
        )

    CommandBoundary._encode_response(
        {"items": [None] * 8_191},
        response_schema="RfcBranchV1",
        response_version=1,
    )
    with pytest.raises(ValidationError, match="collection bound"):
        CommandBoundary._encode_response(
            {"items": [None] * 8_192},
            response_schema="RfcBranchV1",
            response_version=1,
        )

    depth_eight: object = None
    for _ in range(8):
        depth_eight = [depth_eight]
    CommandBoundary._encode_response(
        depth_eight,
        response_schema="RfcBranchV1",
        response_version=1,
    )
    with pytest.raises(ValidationError, match="depth bound"):
        CommandBoundary._encode_response(
            [depth_eight],
            response_schema="RfcBranchV1",
            response_version=1,
        )


def test_stored_unallocated_rfc_branch_version_fails_as_integrity_error() -> None:
    response_json = "{}"
    result = CommittedCommandResult(
        command_id=new_uuid4(),
        response_schema="RfcBranchV1",
        response_version=2,
        response_json=response_json,
        response_sha256=hashlib.sha256(response_json.encode("utf-8")).hexdigest(),
    )
    with pytest.raises(IntegrityFailure, match="response contract is unsupported"):
        CommandBoundary._decode_stored_response(result)



def _max_inventory_bulk_response() -> dict[str, object]:
    revision = 9_223_372_036_854_775_807
    revisions: dict[str, int] = {}
    for ordinal in range(2_000):
        membership_id = f"{ordinal:08x}-0000-4000-8000-{ordinal:012x}"
        fault_tag_id = f"{ordinal + 2_000:08x}-0000-4000-8000-{ordinal + 2_000:012x}"
        revisions[f"fault_tag_membership:{membership_id}"] = revision
        revisions[f"fault_tag:{fault_tag_id}"] = revision
    return {
        "outcome": "APPLIED",
        "target_refs": [
            {
                "type": "inventory_batch",
                "id": "ffffffff-ffff-4fff-bfff-ffffffffffff",
            }
        ],
        "revisions": revisions,
    }


def test_inventory_mutation_reviewed_replay_allocation_covers_2000_target_batch() -> None:
    response = _max_inventory_bulk_response()
    text, _digest, normalized = CommandBoundary._encode_response(
        response,
        response_schema="InventoryMutationResultV1",
        response_version=1,
    )

    assert len(text.encode("utf-8")) < 524_288
    depth, items, _strings = _measure(normalized)
    assert depth <= 8
    assert items == 4_006
    assert items > 512

    bounds = CommandBoundary._response_bounds("InventoryMutationResultV1", 1)
    assert (bounds.max_bytes, bounds.max_depth, bounds.max_collection_items) == (
        524_288,
        8,
        8_192,
    )


def test_inventory_mutation_reviewed_allocation_is_exact_to_version() -> None:
    with pytest.raises(
        ValidationError,
        match="unsupported command response schema/version",
    ):
        CommandBoundary._response_bounds("InventoryMutationResultV1", 2)

    response_json = "{}"
    result = CommittedCommandResult(
        command_id=new_uuid4(),
        response_schema="InventoryMutationResultV1",
        response_version=2,
        response_json=response_json,
        response_sha256=hashlib.sha256(response_json.encode("utf-8")).hexdigest(),
    )
    with pytest.raises(IntegrityFailure, match="response contract is unsupported"):
        CommandBoundary._decode_stored_response(result)
