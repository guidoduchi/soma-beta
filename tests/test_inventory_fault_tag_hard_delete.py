from __future__ import annotations

import pytest
import sqlite3

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.fault_tags import FaultTagMembershipIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.queries.previews import InventoryDestructivePreviewQuery
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.hard_delete import InventoryHardDeleteService
from test_inventory_consequence_replay import _reviewed_task
from test_inventory_requests_rma import _prepare_submitted_request
from test_inventory_warehouse_replay import _factory, _current_members, _members, _submitted_tag
from test_inventory_request_creation_replay import _creation
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.inventory.services.needs_stock import InventoryNeedsStockService


def _delete_arguments(preview):
    return dict(command_id=new_uuid4(), target_kind="fault_tag", target_id=preview["target_id"],
                expected_revision=preview["reviewed_revision"],
                preview_fingerprint=preview["input_fingerprint"], deliberate_confirmation=True)


class _CommunicationDependency:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def classify_inventory_hard_delete_dependency(
        self, reader, target_type: str, target_id: str
    ) -> str:
        assert hasattr(reader, "connection")
        self.calls.append((target_type, target_id))
        return self.status


def _populated_draft(factory):
    _, _, requests, request_id, revision = _prepare_submitted_request(
        factory,
        official_sr="97800600",
        request_quantity=1,
        target_count=1,
        bom="DELETE-DRAFT-600",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=revision,
        rows=(RmaAuthorizationIntent("C0000000600", "DELETE-DRAFT-600"),),
        accepted_at_utc=6_000,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])
    logistics = InventoryConsequencesLogisticsService(factory)
    received = logistics.record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code="DELETE-DRAFT-600",
        manufacturer_serial="DELETE-DRAFT-SERIAL-600",
        condition_token="new",
        effective_at_utc=6_001,
    )
    unit_id = next(
        ref.result_id
        for ref in received.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, _, fingerprint = _reviewed_task(factory)
    consequence = logistics.accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="unused",
        rma_id=rma_id,
        inbound_spare_part_unit_id=unit_id,
        effective_at_utc=6_002,
    )
    consequence_id = next(
        ref.result_id
        for ref in consequence.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )
    tags = InventoryFaultTagsService(factory)
    tag = tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "untouched draft return"),),
    )
    return tags, tag, rma_id, unit_id, consequence_id


def test_untouched_fault_tag_delete_retains_allocator_and_replays_t060(initialized_database):
    factory = _factory(initialized_database)
    tags, created, rma_id, unit_id, consequence_id = _populated_draft(factory)
    tag_id = str(created["fault_tag_id"])
    membership_id = str(created["members"][0]["fault_tag_membership_id"])

    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="fault_tag", target_id=tag_id,
    )
    assert preview["classification"] == "CLEAR"
    assert preview["blockers"] == []
    assert preview["retained_related_ids"] == [rma_id]

    with ReadSnapshot(factory) as snapshot:
        logistics_before = snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events"
        ).fetchone()[0]
        obligation_before = tuple(
            snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id=?",
                (rma_id,),
            ).fetchone()
        )

    args = _delete_arguments(preview)
    owner = InventoryHardDeleteService(factory)
    result = owner.hard_delete_untouched_inventory_draft(**args)
    replay = owner.hard_delete_untouched_inventory_draft(**args)
    assert replay.replayed and replay.target_refs == result.target_refs

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tags WHERE fault_tag_id=?", (tag_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_memberships WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rmas WHERE rma_id=?", (rma_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_part_units WHERE spare_part_unit_id=?", (unit_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_physical_consequences "
            "WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone()[0] == 1
        assert tuple(
            snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id=?",
                (rma_id,),
            ).fetchone()
        ) == obligation_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events"
        ).fetchone()[0] == logistics_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE target_id=?", (tag_id,),
        ).fetchone()[0] == 2

    next_tag = tags.create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup"
    )
    assert created["tracking_handle"] == "FT-00000001"
    assert next_tag["tracking_handle"] == "FT-00000002"


def test_submitted_fault_tag_history_blocks_hard_delete_t061(initialized_database):
    factory = _factory(initialized_database)
    _, submitted, _ = _submitted_tag(factory)
    query = InventoryDestructivePreviewQuery(factory)
    preview = query.preview_hard_delete(target_kind="fault_tag", target_id=submitted["fault_tag_id"])
    assert preview["classification"] == "BLOCKED"
    assert "submission_history" in preview["blockers"]
    args = _delete_arguments(preview)
    with pytest.raises(SomaError) as blocked:
        InventoryHardDeleteService(factory).hard_delete_untouched_inventory_draft(**args)
    assert blocked.value.code == "HARD_DELETE_BLOCKED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (args["command_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
            (submitted["fault_tag_id"],),
        ).fetchone()[0] == 1


def test_t061_proposal_history_blocks_fault_tag_hard_delete(initialized_database):
    factory = _factory(initialized_database)
    tag = InventoryFaultTagsService(factory).create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup"
    )
    tag_id = str(tag["fault_tag_id"])
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO inventory_proposals("
            "inventory_proposal_id,proposal_kind,evidence_kind,evidence_id,"
            "source_proposal_key,state,input_fingerprint,risk_tier,created_at_utc,"
            "revision,last_command_id"
            ") VALUES (?,'fault_tag_submission','indexed_sent','proposal-evidence-61',"
            "'proposal-key-61','pending',?,'high',6100,1,NULL)",
            (proposal_id, "0" * 64),
        )
        uow.connection.execute(
            "INSERT INTO inventory_proposal_targets("
            "inventory_proposal_target_id,inventory_proposal_id,target_kind,"
            "spare_request_id,rma_id,spare_part_unit_id,fault_tag_id,"
            "fault_tag_membership_id,expected_revision,proposed_action,payload_json"
            ") VALUES (?,?,'fault_tag',NULL,NULL,NULL,?,NULL,1,"
            "'fault_tag_submission','{}')",
            (new_uuid4(), proposal_id, tag_id),
        )

    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="fault_tag", target_id=tag_id
    )
    assert preview["classification"] == "BLOCKED"
    assert "proposal_history" in preview["blockers"]


def test_t061_warehouse_and_lineage_history_block_fault_tag_hard_delete(initialized_database):
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    predecessor = str(submitted["fault_tag_id"])
    members = _members(submitted)
    tags.record_warehouse_receipt(
        command_id=new_uuid4(), memberships=(members[0],)
    )
    warehouse_preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="fault_tag", target_id=predecessor
    )
    assert warehouse_preview["classification"] == "BLOCKED"
    assert "membership_history" in warehouse_preview["blockers"]

    replacement = tags.create_fault_tag_replacement(
        command_id=new_uuid4(),
        predecessor_fault_tag_id=predecessor,
        return_method="non_pickup",
        memberships=tuple(
            FaultTagMembershipIntent(rma_id, "replacement return scope")
            for rma_id in rmas
        ),
        reason_code="reviewed material correction",
    )
    successor = str(replacement["fault_tag_id"])
    lineage_preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="fault_tag", target_id=successor
    )
    assert lineage_preview["classification"] == "BLOCKED"
    assert "lineage_history" in lineage_preview["blockers"]


@pytest.mark.parametrize(
    ("provider_status", "expected_classification", "expected_blocker"),
    [
        ("BLOCKED", "BLOCKED", "communications_protected_history"),
        ("INDETERMINATE", "INDETERMINATE", "communications_dependency_indeterminate"),
    ],
)
def test_t061_communication_generation_dependency_blocks_or_fails_closed(
    initialized_database,
    provider_status,
    expected_classification,
    expected_blocker,
):
    factory = _factory(initialized_database)
    tag = InventoryFaultTagsService(factory).create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup"
    )
    tag_id = str(tag["fault_tag_id"])
    provider = _CommunicationDependency(provider_status)
    query = InventoryDestructivePreviewQuery(factory, provider)
    preview = query.preview_hard_delete(target_kind="fault_tag", target_id=tag_id)
    assert preview["classification"] == expected_classification
    assert expected_blocker in preview["blockers"]
    assert provider.calls == [("fault_tag", tag_id)]

    args = _delete_arguments(preview)
    owner = InventoryHardDeleteService(factory, provider)
    with pytest.raises(SomaError) as blocked:
        owner.hard_delete_untouched_inventory_draft(**args)
    assert blocked.value.code == "HARD_DELETE_BLOCKED"
    assert provider.calls == [("fault_tag", tag_id), ("fault_tag", tag_id)]
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (args["command_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tags WHERE fault_tag_id=?", (tag_id,),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["spare_request", "spare_part_unit"])
def test_other_untouched_draft_creation_facts_are_deletable(initialized_database, kind):
    factory = _factory(initialized_database)
    if kind == "spare_request":
        created = InventoryRequestsRmaService(factory).create_spare_request_draft(**_creation(factory))
        identity = created["spare_request_id"]
    else:
        created = InventoryNeedsStockService(factory).register_spare_part_unit(
            command_id=new_uuid4(), origin="manual_local", bom_code="UNTOUCHED", condition_token="new",
        )
        identity = next(ref.result_id for ref in created.target_refs if ref.result_type == kind)
    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(target_kind=kind, target_id=identity)
    assert preview["classification"] == "CLEAR"
    args = {**_delete_arguments(preview), "target_kind": kind}
    owner = InventoryHardDeleteService(factory)
    owner.hard_delete_untouched_inventory_draft(**args)
    assert owner.hard_delete_untouched_inventory_draft(**args).replayed


def test_initial_fact_cannot_be_deleted_without_matching_pending_command(initialized_database):
    factory = _factory(initialized_database)
    tag = InventoryFaultTagsService(factory).create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup",
    )
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute("DELETE FROM fault_tag_current_projection WHERE fault_tag_id=?", (tag["fault_tag_id"],))
            uow.connection.execute("DELETE FROM fault_tag_lifecycle_events WHERE fault_tag_id=?", (tag["fault_tag_id"],))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM fault_tag_current_projection WHERE fault_tag_id=?", (tag["fault_tag_id"],)).fetchone()[0] == 1
