from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.services.corrections_bulk import InventoryCorrectionsBulkService
from soma.inventory.services.fault_tags import InventoryFaultTagsService


def _factory(initialized_database):
    database_path, builder = initialized_database
    return builder(database_path)


def _proposal(factory) -> tuple[str, str]:
    tag = InventoryFaultTagsService(factory).create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
    )
    proposal_id = new_uuid4()
    fingerprint = "a" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO inventory_proposals("
            "inventory_proposal_id,proposal_kind,evidence_kind,evidence_id,"
            "source_proposal_key,state,input_fingerprint,risk_tier,created_at_utc,"
            "revision,last_command_id"
            ") VALUES (?,?,?,?,?,'pending',?,'normal',1,1,NULL)",
            (
                proposal_id,
                "fault_tag_submission",
                "communication_proposal",
                new_uuid4(),
                "test-reject",
                fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO inventory_proposal_targets("
            "inventory_proposal_target_id,inventory_proposal_id,target_kind,"
            "spare_request_id,rma_id,spare_part_unit_id,fault_tag_id,"
            "fault_tag_membership_id,expected_revision,proposed_action,payload_json"
            ") VALUES (?,?,'fault_tag',NULL,NULL,NULL,?,NULL,1,?,?)",
            (
                new_uuid4(),
                proposal_id,
                str(tag["fault_tag_id"]),
                "submit",
                "{}",
            ),
        )
    return proposal_id, fingerprint


def test_reject_inventory_proposal_is_replay_safe_and_does_not_mutate_target(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    proposal_id, fingerprint = _proposal(factory)
    service = InventoryCorrectionsBulkService(factory)
    command_id = new_uuid4()

    result = service.reject_inventory_proposal(
        command_id=command_id,
        proposal_id=proposal_id,
        expected_revision=1,
        input_fingerprint=fingerprint,
        reason_category="not_authorized",
    )
    assert result.outcome == "APPLIED"
    assert result.target_refs[0].result_type == "inventory_proposal"
    assert result.target_refs[0].result_id == proposal_id
    assert result.revisions == {proposal_id: 2}
    assert result.replayed is False

    replay = service.reject_inventory_proposal(
        command_id=command_id,
        proposal_id=proposal_id,
        expected_revision=1,
        input_fingerprint=fingerprint,
        reason_category="not_authorized",
    )
    assert replay.replayed is True
    assert replay.revisions == {proposal_id: 2}

    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT state,revision,last_command_id FROM inventory_proposals "
            "WHERE inventory_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("rejected", 2, command_id)
        tag = snapshot.connection.execute(
            "SELECT state,revision FROM fault_tag_current_projection"
        ).fetchone()
        assert tuple(tag) == ("draft", 1)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE action_type='inventory.proposal.decided' AND target_id=?",
            (proposal_id,),
        ).fetchone()[0] == 1


def test_reject_inventory_proposal_fails_closed_on_stale_or_collision(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    proposal_id, fingerprint = _proposal(factory)
    service = InventoryCorrectionsBulkService(factory)

    with pytest.raises(SomaError) as stale:
        service.reject_inventory_proposal(
            command_id=new_uuid4(),
            proposal_id=proposal_id,
            expected_revision=2,
            input_fingerprint=fingerprint,
            reason_category="stale",
        )
    assert stale.value.code == "PROPOSAL_STALE"

    command_id = new_uuid4()
    service.reject_inventory_proposal(
        command_id=command_id,
        proposal_id=proposal_id,
        expected_revision=1,
        input_fingerprint=fingerprint,
        reason_category="first",
    )
    with pytest.raises(SomaError) as collision:
        service.reject_inventory_proposal(
            command_id=command_id,
            proposal_id=proposal_id,
            expected_revision=1,
            input_fingerprint=fingerprint,
            reason_category="different",
        )
    assert collision.value.code == "IDEMPOTENCY_CONFLICT"


def test_accept_inventory_proposal_fails_closed_for_unpinned_target_contract(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    proposal_id, fingerprint = _proposal(factory)
    service = InventoryCorrectionsBulkService(factory)

    with pytest.raises(SomaError) as excinfo:
        service.accept_inventory_proposal(
            command_id=new_uuid4(),
            proposal_id=proposal_id,
            expected_revision=1,
            input_fingerprint=fingerprint,
            explicit_confirmation=True,
        )
    assert excinfo.value.code == "DEPENDENCY_INDETERMINATE"

    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT state,revision,last_command_id FROM inventory_proposals "
            "WHERE inventory_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("pending", 1, None)
        tag = snapshot.connection.execute(
            "SELECT state,revision FROM fault_tag_current_projection"
        ).fetchone()
        assert tuple(tag) == ("draft", 1)
