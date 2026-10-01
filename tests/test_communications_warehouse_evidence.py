from io import BytesIO

import pytest

from soma.communications.contracts.message import TransientAttachment
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.warehouse_evidence import warehouse_reception_context
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from test_communications_identity import message


def test_rt_is_exact_reception_context_without_new_identity_direction_or_chronology():
    transient = message(subject="Warehouse RT25020301", body="Items received under RT25020301")
    before = (transient.chronology, transient.direction, transient.provider_identity)
    context = warehouse_reception_context(transient)
    assert context.state == "EXACT" and context.reference == "RT25020301"
    assert context.reference not in repr(context)
    assert (transient.chronology, transient.direction, transient.provider_identity) == before


def test_thread_history_can_supply_same_reference_but_different_batches_are_ambiguous():
    assert warehouse_reception_context(message(subject=None, body="Subject: RT25020301\nItems in warehouse")).state == "EXACT"
    assert warehouse_reception_context(message(subject="RT25020301", body="Older thread RT25020302")).state == "AMBIGUOUS"


@pytest.mark.parametrize("value", ["rt25020301", "XRT25020301", "RT25020301X", "_RT25020301", "RT25020301_", "éRT25020301", "RT25020301\u0301", "RT250203010", "RT２５０２０３０１"])
def test_context_does_not_match_inside_longer_identifiers_or_fold_identity(value):
    assert warehouse_reception_context(message(subject=value, body=None)).state == "ABSENT"


@pytest.mark.parametrize("value", ["RT25022901", "RT25130101", "RT25020001", "RT25023101"])
def test_invalid_calendar_context_does_not_become_receipt_evidence(value):
    assert warehouse_reception_context(message(subject=value, body=None)).state == "INVALID"


def test_valid_leap_day_and_missing_or_filename_only_reference():
    assert warehouse_reception_context(message(subject="RT24022901", body=None)).state == "EXACT"
    assert warehouse_reception_context(message(subject="SR7654321 C1234567890", body="Receipt confirmed")).state == "ABSENT"
    attachment = TransientAttachment(0, "RT25020301.eml", None, 0, BytesIO(b""))
    assert warehouse_reception_context(message(subject=None, body=None, attachments=(attachment,))).state == "ABSENT"


def test_large_repeated_thread_keeps_one_reference_and_invalid_context_fails_closed():
    context = warehouse_reception_context(message(subject=None, body=("RT25020301 " * 10000)))
    assert context.state == "EXACT" and context.reference == "RT25020301"
    assert warehouse_reception_context(message(subject="RT25020301", body="RT25023101")).state == "INVALID"


def test_exact_warehouse_pair_resolves_only_current_selected_physical_membership(communication_database):
    from soma.foundation.persistence.uow import ReadSnapshot
    from soma.inventory.services.participants import InventoryCommunicationIdentityProvider
    from test_inventory_warehouse_replay import _submitted_tag, _members
    from test_communications_identity_providers import providers
    _, factory = communication_database
    service, tag, rmas = _submitted_tag(factory)
    with ReadSnapshot(factory) as reader:
        sr7, c10 = reader.connection.execute("SELECT s.sr7,a.c10 FROM rmas r "
            "JOIN spare_request_identifier_aliases s ON s.spare_request_id=r.spare_request_id "
            "JOIN rma_identifier_aliases a ON a.rma_id=r.rma_id WHERE r.rma_id=?", (rmas[0],)).fetchone()
        result = providers().warehouse_receipt_target(reader, sr7, c10)
        exported = tuple(providers().snapshot(reader))
        assert {item.target_type for item in exported}.issuperset({'RMA', 'FAULT_TAG'})
        for item in exported:
            assert providers().validate(reader, item) == 'VALID'
        member = next(item for item in tag['members'] if item['rma_id'] == rmas[0])
        assert result == {'fault_tag_id': tag['fault_tag_id'], 'fault_tag_revision': tag['revision'],
            'membership_id': member['fault_tag_membership_id'], 'membership_revision': member['revision']}
        assert InventoryCommunicationIdentityProvider.resolve_warehouse_receipt_target(reader, 'SR9999999', c10) is None
    selected = next(item for item in _members(tag) if item.fault_tag_membership_id == result['membership_id'])
    service.record_warehouse_receipt(command_id=new_uuid4(), memberships=(selected,))
    with ReadSnapshot(factory) as reader:
        assert providers().warehouse_receipt_target(reader, sr7, c10) is None


def test_missing_batch_reference_warns_without_inventing_item_receipt_or_decision():
    transient = message(subject="Warehouse update", body="Items have status CLOSED")
    context = warehouse_reception_context(transient)
    assert context.state == "ABSENT" and context.reference is None
    assert context.warning_code == "WAREHOUSE_RETURN_BATCH_REFERENCE_MISSING"
    assert transient.body == "Items have status CLOSED"
    assert warehouse_reception_context(message(subject="RT25020301", body="Items have status CLOSED")).warning_code is None


@pytest.mark.parametrize("decision", ["CLOSED", "closed"])
def test_closed_wording_is_never_an_actionable_final_decision(decision):
    payload = {"schema": "COMM_INVENTORY_WAREHOUSE_DECISION_V1", "membership_id": new_uuid4(), "membership_revision": 1,
               "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1", "decision": decision,
                         "reason_code": None, "effective_at_utc": None}}
    with pytest.raises(ValidationError):
        CommunicationProposalContractRegistry().validate("COMM_INVENTORY_WAREHOUSE_DECISION_V1", 1, "FAULT_TAG", payload)


@pytest.mark.parametrize("batch_reference", [None, "RT25020301"])
@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_operator_records_one_exact_item_with_optional_batch_and_explicit_decision(
    communication_database, batch_reference, decision,
):
    from soma.foundation.errors import SomaError
    from soma.foundation.persistence.uow import ReadSnapshot
    from soma.inventory.services.fault_tags import InventoryFaultTagsService
    from test_inventory_warehouse_replay import _submitted_tag, _members

    _, factory = communication_database
    service, tag, _ = _submitted_tag(factory)
    selected, sibling = _members(tag)
    context = warehouse_reception_context(message(subject=batch_reference, body="Items have status CLOSED"))
    assert (context.warning_code is not None) == (batch_reference is None)

    # RT is advisory Communications context; the existing owner command selects
    # an exact membership and does not depend on the batch token or mail prose.
    request = {"command_id": new_uuid4(), "memberships": (selected,)}
    service.record_warehouse_receipt(**request)
    assert service.record_warehouse_receipt(**request).replayed
    with ReadSnapshot(factory) as reader:
        current = InventoryFaultTagsService._response(reader.connection, tag["fault_tag_id"])
    selected = next(item for item in _members(current) if item.fault_tag_membership_id == selected.fault_tag_membership_id)
    final = {"command_id": new_uuid4(), "memberships": (selected,), "decision": decision,
             "reason_code": "DAMAGED" if decision == "rejected" else None, "explicit_confirmation": False}
    with pytest.raises(SomaError) as raised:
        service.record_warehouse_final_decision(**final)
    assert raised.value.code == "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED"
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (final["command_id"],)).fetchone()[0] == 0
        assert reader.connection.execute("SELECT state FROM fault_tag_membership_current WHERE fault_tag_membership_id=?", (selected.fault_tag_membership_id,)).fetchone()[0] == "warehouse_received"
    final["explicit_confirmation"] = True
    service.record_warehouse_final_decision(**final)
    assert service.record_warehouse_final_decision(**final).replayed
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT state FROM fault_tag_membership_current WHERE fault_tag_membership_id=?", (sibling.fault_tag_membership_id,)).fetchone()[0] == "submitted_awaiting_receipt"
        assert reader.connection.execute("SELECT state FROM fault_tag_membership_current WHERE fault_tag_membership_id=?", (selected.fault_tag_membership_id,)).fetchone()[0] == decision
