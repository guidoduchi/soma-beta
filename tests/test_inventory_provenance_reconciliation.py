from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.corrections_bulk import InventoryCorrectionsBulkService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from test_inventory_requests_rma import _factory, _prepare_submitted_request


def test_t013_local_unit_later_adopts_rma_provenance_without_identity_or_history_replacement(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need_id, requests, request_id, request_revision = _prepare_submitted_request(
        factory,
        official_sr="97100113",
        request_quantity=1,
        target_count=1,
        bom="PROVENANCE-BOM",
    )
    authorized = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=request_revision,
        rows=(RmaAuthorizationIntent("C0000000113", "PROVENANCE-BOM"),),
        accepted_at_utc=2_113,
    )
    rma_id = str(authorized["created_rmas"][0]["rma_id"])

    registered = InventoryNeedsStockService(factory).register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="PROVENANCE-BOM",
        manufacturer_serial="LOCAL-0113",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in registered.target_refs
        if ref.result_type == "spare_part_unit"
    )
    assert registered.revisions[f"spare_part_unit:{unit_id}"] == 1

    with ReadSnapshot(factory) as snapshot:
        before_root = tuple(
            snapshot.connection.execute(
                "SELECT spare_part_unit_id,local_tracking_sequence,local_tracking_id,"
                "bom_code,bom_key,manufacturer_serial,serial_key,creation_origin,"
                "origin_rma_id,parent_spare_part_unit_id,created_at_utc,created_command_id "
                "FROM spare_part_units WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone()
        )
        before_events = [
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT unit_event_id,event_kind,condition_token,disposition_token,"
                "location_kind,location_ref_id,custody_text,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id "
                "FROM spare_part_lifecycle_events WHERE spare_part_unit_id=? "
                "ORDER BY recorded_at_utc,unit_event_id",
                (unit_id,),
            ).fetchall()
        ]
    assert before_root[7] == "manual_local"
    assert before_root[8] is None
    assert len(before_events) == 1
    assert before_events[0][1] == "registered"

    command_id = new_uuid4()
    service = InventoryCorrectionsBulkService(factory)
    applied = service.correct_inventory_evidence(
        command_id=command_id,
        correction_kind="spare_part_rma_provenance",
        target_id=unit_id,
        expected_revision=1,
        origin_rma_id=rma_id,
        reason_code="reviewed provider provenance",
    )
    assert applied.outcome == "APPLIED"
    assert applied.replayed is False
    assert applied.revisions == {f"spare_part_unit:{unit_id}": 2}

    replay = service.correct_inventory_evidence(
        command_id=command_id,
        correction_kind="spare_part_rma_provenance",
        target_id=unit_id,
        expected_revision=1,
        origin_rma_id=rma_id,
        reason_code="reviewed provider provenance",
    )
    assert replay == type(replay)(
        outcome=applied.outcome,
        target_refs=applied.target_refs,
        revisions=applied.revisions,
        replayed=True,
    )

    with ReadSnapshot(factory) as snapshot:
        after_root = tuple(
            snapshot.connection.execute(
                "SELECT spare_part_unit_id,local_tracking_sequence,local_tracking_id,"
                "bom_code,bom_key,manufacturer_serial,serial_key,creation_origin,"
                "origin_rma_id,parent_spare_part_unit_id,created_at_utc,created_command_id "
                "FROM spare_part_units WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone()
        )
        after_events = [
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT unit_event_id,event_kind,condition_token,disposition_token,"
                "location_kind,location_ref_id,custody_text,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id "
                "FROM spare_part_lifecycle_events WHERE spare_part_unit_id=? "
                "ORDER BY recorded_at_utc,unit_event_id",
                (unit_id,),
            ).fetchall()
        ]
        projection = snapshot.connection.execute(
            "SELECT revision,last_command_id FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()
        direct = snapshot.connection.execute(
            "SELECT 1 FROM rma_direct_inbound_units WHERE rma_id=? OR spare_part_unit_id=?",
            (rma_id, unit_id),
        ).fetchone()
        audits = snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=? ORDER BY action_type",
            (command_id,),
        ).fetchall()

    assert after_root[:8] == before_root[:8]
    assert after_root[8] == rma_id
    assert after_root[9:] == before_root[9:]
    assert after_events[0] == before_events[0]
    assert [row[1] for row in after_events] == ["registered", "correction"]
    assert after_events[1][10:12] == ("rma_provenance", rma_id)
    assert tuple(projection) == (2, command_id)
    assert direct is None
    assert [str(row[0]) for row in audits] == [
        "inventory.evidence.corrected",
        "inventory.spare_unit.registered_or_reserved",
    ]

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        service.correct_inventory_evidence(
            command_id=rejected_command,
            correction_kind="spare_part_rma_provenance",
            target_id=unit_id,
            expected_revision=2,
            origin_rma_id=rma_id,
            reason_code="duplicate provenance adoption",
        )
    assert excinfo.value.code == "CORRECTION_TARGET_INVALID"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (rejected_command,),
        ).fetchone() is None
