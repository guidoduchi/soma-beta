from __future__ import annotations

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.regularization import regularization_fingerprint
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.infrastructure_participants import DeviceReferenceOperationalReader


class _ReceiptOrderingProofProvider:
    def __init__(self) -> None:
        self.calls = 0

    def validate_and_consume(
        self,
        uow,
        proof,
        action,
        target,
        base_revision,
        scope_fingerprint,
    ):
        self.calls += 1
        assert action == "RegularizeDeviceReference"
        assert target["kind"] == "device_reference"
        assert type(base_revision) is int and base_revision > 0
        assert isinstance(scope_fingerprint, str) and len(scope_fingerprint) == 64
        # The accepted LLD-08 leaf requires proof consumption before the
        # command receipt while remaining inside the same outer UnitOfWork.
        assert uow.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (proof,),
        ).fetchone() == (0,)
        uow.connection.execute(
            "INSERT INTO test_deliberate_proof_consumptions(proof) VALUES (?)",
            (proof,),
        )
        return True


def _assembled(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TABLE test_deliberate_proof_consumptions("
            "proof TEXT PRIMARY KEY)"
        )
    provider = _ReceiptOrderingProofProvider()
    service = InfrastructureService(
        factory,
        device_reader=DeviceReferenceOperationalReader(),
        proof_provider=provider,
    )
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Regularization customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Regularization Site",
            "address_text": "1 Proof Street",
        },
    ).response["target"]["id"]
    network_element_id = service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": "NE-PROOF-01",
            }
        },
    ).response["target"]["id"]
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name="Device proof target",
    )
    return factory, service, provider, device, network_element_id


def _link_payload(service, factory, device, network_element_id, command_id):
    request = {
        "device_reference_id": device.device_reference_id,
        "device_reference_revision": device.revision,
        "action": "link_existing",
        "target_network_element_id": network_element_id,
    }
    with ReadSnapshot(factory) as snapshot:
        preview = regularization_fingerprint(service, snapshot, request)
    return {
        **request,
        "preview_fingerprint": preview,
        "deliberate_action_proof": command_id,
    }


def test_regularization_consumes_proof_before_receipt_and_replay_does_not_reconsume(
    initialized_database,
):
    factory, service, provider, device, network_element_id = _assembled(
        initialized_database
    )
    command_id = new_uuid4()
    payload = _link_payload(
        service, factory, device, network_element_id, command_id
    )

    first = service.execute(
        "RegularizeDeviceReference",
        command_id=command_id,
        payload=payload,
    )
    replay = service.execute(
        "RegularizeDeviceReference",
        command_id=command_id,
        payload=payload,
    )

    assert first.response["target"] == {
        "kind": "device_reference",
        "id": device.device_reference_id,
    }
    assert first.response["revision"] == 1
    assert replay.replayed and replay.response == first.response
    assert provider.calls == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT network_element_id,revision "
            "FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (network_element_id, 1)
        assert snapshot.connection.execute(
            "SELECT revision FROM device_references WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (device.revision,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM test_deliberate_proof_consumptions WHERE proof=?",
            (command_id,),
        ).fetchone() == (1,)


def test_regularization_proof_consumption_rolls_back_with_later_audit_failure(
    initialized_database,
    monkeypatch,
):
    factory, service, provider, device, network_element_id = _assembled(
        initialized_database
    )
    command_id = new_uuid4()
    payload = _link_payload(
        service, factory, device, network_element_id, command_id
    )

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected regularization audit failure")

    monkeypatch.setattr(service.boundary._audit_writer, "write", fail_audit)
    with pytest.raises(RuntimeError, match="injected regularization audit failure"):
        service.execute(
            "RegularizeDeviceReference",
            command_id=command_id,
            payload=payload,
        )

    assert provider.calls == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM test_deliberate_proof_consumptions WHERE proof=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (0,)
