from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.regularization import regularization_fingerprint
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.infrastructure_participants import DeviceReferenceOperationalReader


class _ReceiptOrderingProofProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.consumed: set[str] = set()

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
        if proof in self.consumed:
            return False
        assert action == "RegularizeDeviceReference"
        assert target == {
            "target_type": "device_reference",
            "target_id": target["target_id"],
        }
        assert type(base_revision) is int and base_revision > 0
        assert isinstance(scope_fingerprint, str) and len(scope_fingerprint) == 64
        # The accepted LLD-08 leaf requires proof consumption before the
        # command receipt while remaining inside the same outer UnitOfWork.
        assert uow.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (proof,),
        ).fetchone() == (0,)
        self.consumed.add(proof)
        return {
            "action_code": action,
            "target": dict(target),
            "base_revision": base_revision,
            "preview_fingerprint": scope_fingerprint,
        }


def _assembled(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
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
    assert command_id in provider.consumed


def test_regularization_consumed_proof_remains_single_use_after_later_audit_failure(
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
    assert command_id in provider.consumed
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (0,)

    monkeypatch.undo()
    with pytest.raises(SomaError) as reused:
        service.execute(
            "RegularizeDeviceReference",
            command_id=command_id,
            payload=payload,
        )
    assert reused.value.code == "DEVICE_RESOLUTION_PROOF_REQUIRED"
    assert provider.calls == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (0,)


def test_regularization_rejects_malformed_validated_proof_binding(initialized_database):
    factory, service, _provider, device, network_element_id = _assembled(
        initialized_database
    )

    class WrongBindingProvider(_ReceiptOrderingProofProvider):
        def validate_and_consume(self, *args, **kwargs):
            value = super().validate_and_consume(*args, **kwargs)
            if not isinstance(value, dict):
                return value
            return {**value, "target": {"target_type": "device_reference", "target_id": new_uuid4()}}

    provider = WrongBindingProvider()
    service.proof_provider = provider
    command_id = new_uuid4()
    payload = _link_payload(service, factory, device, network_element_id, command_id)

    with pytest.raises(SomaError) as malformed:
        service.execute(
            "RegularizeDeviceReference",
            command_id=command_id,
            payload=payload,
        )
    assert malformed.value.code == "DEVICE_RESOLUTION_PROOF_REQUIRED"
    assert command_id in provider.consumed
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (0,)



def test_regularization_no_change_still_requires_and_consumes_deliberate_proof(
    initialized_database,
):
    factory, service, provider, device, network_element_id = _assembled(
        initialized_database
    )
    first_command = new_uuid4()
    first_payload = _link_payload(
        service, factory, device, network_element_id, first_command
    )
    service.execute(
        "RegularizeDeviceReference",
        command_id=first_command,
        payload=first_payload,
    )

    request = {
        "device_reference_id": device.device_reference_id,
        "device_reference_revision": device.revision,
        "action": "correct_link",
        "target_network_element_id": network_element_id,
        "resolution_revision": 1,
    }
    with ReadSnapshot(factory) as snapshot:
        preview = regularization_fingerprint(service, snapshot, request)

    no_proof_command = new_uuid4()
    with pytest.raises(SomaError) as missing:
        service.execute(
            "RegularizeDeviceReference",
            command_id=no_proof_command,
            payload={
                **request,
                "preview_fingerprint": preview,
            },
        )
    assert missing.value.code == "DEVICE_RESOLUTION_PROOF_REQUIRED"

    no_change_command = new_uuid4()
    result = service.execute(
        "RegularizeDeviceReference",
        command_id=no_change_command,
        payload={
            **request,
            "preview_fingerprint": preview,
            "deliberate_action_proof": no_change_command,
        },
    )
    assert result.no_change
    assert result.response["no_change"] is True
    assert no_change_command in provider.consumed
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM device_reference_resolution_current "
            "WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?",
            (no_change_command,),
        ).fetchone() == ("NO_CHANGE",)
