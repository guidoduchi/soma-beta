from __future__ import annotations

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import (
    InventoryConsequencesLogisticsService,
)
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from test_inventory_consequence_replay import _reviewed_task
from test_inventory_requests_rma import _device, _factory, _prepare_submitted_request, _sr


def _authorized_received_rma(
    factory,
    *,
    official_sr: str,
    c10: str,
    bom: str,
    condition_token: str,
):
    _sr_row, _need_id, requests, request_id, request_revision = _prepare_submitted_request(
        factory,
        official_sr=official_sr,
        request_quantity=1,
        target_count=1,
        bom=bom,
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=request_revision,
        rows=(RmaAuthorizationIntent(c10, bom),),
        accepted_at_utc=3_000,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])
    with ReadSnapshot(factory) as snapshot:
        target_id = str(
            snapshot.connection.execute(
                "SELECT device_part_unit_id FROM rma_current_assignment WHERE rma_id=?",
                (rma_id,),
            ).fetchone()[0]
        )

    receipt = InventoryConsequencesLogisticsService(factory).record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code=bom,
        manufacturer_serial=f"SER-{c10}",
        condition_token=condition_token,
        effective_at_utc=3_100,
    )
    inbound_id = next(
        ref.result_id
        for ref in receipt.target_refs
        if ref.result_type == "spare_part_unit"
    )
    return rma_id, target_id, inbound_id


def _obligation(factory, rma_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id,revision FROM rma_return_obligation_current "
            "WHERE rma_id=?",
            (rma_id,),
        ).fetchone()


def test_t036_successful_rma_replacement_records_installed_removed_and_return_target(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rma_id, target_id, inbound_id = _authorized_received_rma(
        factory,
        official_sr="97100360",
        c10="C0000000360",
        bom="CONSEQ-036",
        condition_token="new",
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)

    accepted = InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="installed_used",
        target_device_part_unit_id=target_id,
        rma_id=rma_id,
        installed_spare_part_unit_id=inbound_id,
        removed_device_part_unit_id=target_id,
        effective_at_utc=3_200,
    )
    consequence_id = next(
        ref.result_id
        for ref in accepted.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )

    with ReadSnapshot(factory) as snapshot:
        consequence = snapshot.connection.execute(
            "SELECT installed_spare_part_unit_id,removed_device_part_unit_id,"
            "inbound_spare_part_unit_id,parent_dismantled_unit_id "
            "FROM physical_consequence_current WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone()
        inbound = snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone()
        removed = snapshot.connection.execute(
            "SELECT condition_token FROM device_part_current_projection "
            "WHERE device_part_unit_id=?",
            (target_id,),
        ).fetchone()

    assert tuple(consequence) == (inbound_id, target_id, None, None)
    assert str(inbound[0]) == "installed"
    assert str(removed[0]) == "removed"
    obligation = _obligation(factory, rma_id)
    assert tuple(obligation[:3]) == ("open", target_id, None)
    assert str(obligation[3]) == consequence_id


def test_t037_unused_rma_inbound_unit_becomes_open_return_obligation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rma_id, target_id, inbound_id = _authorized_received_rma(
        factory,
        official_sr="97100370",
        c10="C0000000370",
        bom="CONSEQ-037",
        condition_token="new",
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)

    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="unused",
        target_device_part_unit_id=target_id,
        rma_id=rma_id,
        inbound_spare_part_unit_id=inbound_id,
    )

    obligation = _obligation(factory, rma_id)
    assert tuple(obligation[:3]) == ("open", None, inbound_id)
    with ReadSnapshot(factory) as snapshot:
        unit = snapshot.connection.execute(
            "SELECT condition_token,disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone()
    assert tuple(unit) == ("new", "available")


@pytest.mark.parametrize(
    ("disposition", "condition"),
    [("inbound_faulty", "faulty"), ("incompatible", "incompatible")],
)
def test_t038_faulty_or_incompatible_inbound_preserves_state_and_becomes_return_obligation(
    initialized_database,
    disposition,
    condition,
) -> None:
    factory = _factory(initialized_database)
    rma_id, target_id, inbound_id = _authorized_received_rma(
        factory,
        official_sr="97100380",
        c10="C0000000380",
        bom="CONSEQ-038",
        condition_token=condition,
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)

    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition=disposition,
        target_device_part_unit_id=target_id,
        rma_id=rma_id,
        inbound_spare_part_unit_id=inbound_id,
    )

    obligation = _obligation(factory, rma_id)
    assert tuple(obligation[:3]) == ("open", None, inbound_id)
    with ReadSnapshot(factory) as snapshot:
        unit = snapshot.connection.execute(
            "SELECT condition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone()
    assert str(unit[0]) == condition


def test_t039_dismantled_rma_selects_direct_inbound_parent_not_child(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rma_id, target_id, parent_id = _authorized_received_rma(
        factory,
        official_sr="97100390",
        c10="C0000000390",
        bom="CONSEQ-039",
        condition_token="used",
    )
    # A separate child-like unit exists, but dismantled consequence authority must select
    # only the direct inbound parent. T033 separately governs true extracted-child creation.
    child = InventoryNeedsStockService(factory).register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="CONSEQ-039-CHILD",
        condition_token="used",
    )
    child_id = next(
        ref.result_id
        for ref in child.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)

    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="dismantled",
        target_device_part_unit_id=target_id,
        rma_id=rma_id,
        parent_dismantled_unit_id=parent_id,
    )

    obligation = _obligation(factory, rma_id)
    assert tuple(obligation[:3]) == ("open", None, parent_id)
    assert str(obligation[2]) != child_id
    with ReadSnapshot(factory) as snapshot:
        parent = snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (parent_id,),
        ).fetchone()
        child_state = snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (child_id,),
        ).fetchone()
    assert str(parent[0]) == "dismantled"
    assert str(child_state[0]) == "available"


def test_t040_local_stock_replacement_records_physical_facts_without_fabricated_rma(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100400")
    device = _device(factory, sr.service_request_id, "LOCAL-CONSEQ-040")
    removed = InventoryNeedsStockService(factory).register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        bom_code="LOCAL-OLD-040",
        condition_token="faulty",
    )
    removed_id = next(
        ref.result_id
        for ref in removed.target_refs
        if ref.result_type == "device_part_unit"
    )
    installed = InventoryNeedsStockService(factory).register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="LOCAL-NEW-040",
        condition_token="new",
    )
    installed_id = next(
        ref.result_id
        for ref in installed.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)

    accepted = InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="installed_used",
        target_device_part_unit_id=removed_id,
        installed_spare_part_unit_id=installed_id,
        removed_device_part_unit_id=removed_id,
    )
    consequence_id = next(
        ref.result_id
        for ref in accepted.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )

    with ReadSnapshot(factory) as snapshot:
        root = snapshot.connection.execute(
            "SELECT rma_id,target_device_part_unit_id FROM inventory_physical_consequences "
            "WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone()
        obligations = snapshot.connection.execute(
            "SELECT COUNT(*) FROM rma_return_obligation_current "
            "WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone()[0]
        rmas = snapshot.connection.execute("SELECT COUNT(*) FROM rmas").fetchone()[0]
        installed_state = snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (installed_id,),
        ).fetchone()[0]
        removed_state = snapshot.connection.execute(
            "SELECT condition_token FROM device_part_current_projection "
            "WHERE device_part_unit_id=?",
            (removed_id,),
        ).fetchone()[0]

    assert root[0] is None
    assert str(root[1]) == removed_id
    assert obligations == 0
    assert rmas == 0
    assert str(installed_state) == "installed"
    assert str(removed_state) == "removed"
