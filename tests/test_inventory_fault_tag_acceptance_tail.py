from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.fault_tags import FaultTagMembershipIntent, WarehouseMembershipIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from test_inventory_consequence_replay import _factory, _reviewed_task
from test_inventory_requests_rma import _prepare_submitted_request
from test_inventory_warehouse_replay import _current_members, _members, _submitted_tag


def _draft_fingerprint(factory, fault_tag_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return str(
            snapshot.connection.execute(
                "SELECT input_fingerprint FROM fault_tag_current_projection "
                "WHERE fault_tag_id=?",
                (fault_tag_id,),
            ).fetchone()[0]
        )


def _eligible_rma(
    factory,
    *,
    official_sr: str,
    c10: str,
    bom: str,
) -> tuple[str, str, str]:
    sr, _need_id, requests, request_id, revision = _prepare_submitted_request(
        factory,
        official_sr=official_sr,
        request_quantity=1,
        target_count=1,
        bom=bom,
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=revision,
        rows=(RmaAuthorizationIntent(c10, bom),),
        accepted_at_utc=2_200,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])
    logistics = InventoryConsequencesLogisticsService(factory)
    received = logistics.record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code=bom,
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in received.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)
    logistics.accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="unused",
        rma_id=rma_id,
        inbound_spare_part_unit_id=unit_id,
    )
    return rma_id, request_id, sr.service_request_id


def test_t044_fault_tag_may_span_independent_sr_and_request_contexts(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    first = _eligible_rma(
        factory,
        official_sr="97800044",
        c10="C0000000441",
        bom="FT44-A",
    )
    second = _eligible_rma(
        factory,
        official_sr="97800045",
        c10="C0000000442",
        bom="FT44-B",
    )
    assert first[1] != second[1]
    assert first[2] != second[2]

    tags = InventoryFaultTagsService(factory)
    draft = tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(
            FaultTagMembershipIntent(first[0], "return first"),
            FaultTagMembershipIntent(second[0], "return second"),
        ),
    )
    tag_id = str(draft["fault_tag_id"])
    assert len(draft["members"]) == 2

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT m.fault_tag_membership_id,m.rma_id,r.spare_request_id,"
            "q.service_request_id,m.physical_consequence_id,"
            "m.device_part_unit_id,m.spare_part_unit_id "
            "FROM fault_tag_memberships m "
            "JOIN rmas r ON r.rma_id=m.rma_id "
            "JOIN spare_requests q ON q.spare_request_id=r.spare_request_id "
            "WHERE m.fault_tag_id=? ORDER BY m.rma_id",
            (tag_id,),
        ).fetchall()

    assert len(rows) == 2
    assert len({str(row[0]) for row in rows}) == 2
    assert {str(row[1]) for row in rows} == {first[0], second[0]}
    assert {str(row[2]) for row in rows} == {first[1], second[1]}
    assert {str(row[3]) for row in rows} == {first[2], second[2]}
    assert len({str(row[4]) for row in rows}) == 2
    for row in rows:
        assert (row[5] is None) != (row[6] is None)


def test_t045_second_submission_rejects_active_rma_membership_conflict(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rma_id, _request_id, _sr_id = _eligible_rma(
        factory,
        official_sr="97800046",
        c10="C0000000451",
        bom="FT45",
    )
    tags = InventoryFaultTagsService(factory)

    first = tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "first attempt"),),
    )
    second = tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "second attempt"),),
    )
    tags.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(first["fault_tag_id"]),
        expected_fingerprint=_draft_fingerprint(factory, str(first["fault_tag_id"])),
    )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as conflict:
        tags.accept_fault_tag_submission(
            command_id=command_id,
            fault_tag_id=str(second["fault_tag_id"]),
            expected_fingerprint=_draft_fingerprint(factory, str(second["fault_tag_id"])),
        )
    assert conflict.value.code == "FAULT_TAG_MEMBERSHIP_CONFLICT"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        state = snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_id=?",
            (str(second["fault_tag_id"]),),
        ).fetchone()
        assert tuple(state) == ("draft", 0)


def test_t047_submitted_fault_tag_cannot_be_directly_edited_or_remove_member(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    tags, submitted, _rmas = _submitted_tag(factory)
    tag_id = str(submitted["fault_tag_id"])

    with ReadSnapshot(factory) as snapshot:
        before = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current "
                "WHERE fault_tag_id=? ORDER BY fault_tag_membership_id",
                (tag_id,),
            ).fetchall()
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as rejected:
        tags.update_fault_tag_draft(
            command_id=command_id,
            fault_tag_id=tag_id,
            base_revision=int(submitted["revision"]),
            return_method="non_pickup",
            memberships=(),
        )
    assert rejected.value.code == "FAULT_TAG_NOT_DRAFT"

    with ReadSnapshot(factory) as snapshot:
        after = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current "
                "WHERE fault_tag_id=? ORDER BY fault_tag_membership_id",
                (tag_id,),
            ).fetchall()
        )
        assert after == before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_t048_false_submission_returns_same_fault_tag_to_draft_and_preserves_history(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    tags, submitted, _rmas = _submitted_tag(factory)
    tag_id = str(submitted["fault_tag_id"])

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT current_submission_snapshot_id FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchone()
        snapshot_id = str(projection[0])
        frozen_snapshot = tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        )
        frozen_members = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=? "
                "ORDER BY membership_snapshot_id",
                (snapshot_id,),
            ).fetchall()
        )
        submission_event_id = str(frozen_snapshot[2])
        submitted_event_ids = {
            str(row[0]): str(row[1])
            for row in snapshot.connection.execute(
                "SELECT fault_tag_membership_id,last_event_id "
                "FROM fault_tag_membership_current WHERE fault_tag_id=?",
                (tag_id,),
            ).fetchall()
        }

    corrected = tags.correct_false_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=tag_id,
        submission_event_id=submission_event_id,
        reason_code="operator confirmed no send occurred",
    )
    assert corrected["fault_tag_id"] == tag_id
    assert corrected["state"] == "corrected_false_submission"

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT state,current_submission_snapshot_id FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchone()
        assert tuple(current) == ("draft", None)
        assert tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        ) == frozen_snapshot
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=? "
                "ORDER BY membership_snapshot_id",
                (snapshot_id,),
            ).fetchall()
        ) == frozen_members

        lifecycle = snapshot.connection.execute(
            "SELECT event_kind,target_event_id FROM fault_tag_lifecycle_events "
            "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_event_id",
            (tag_id,),
        ).fetchall()
        assert any(str(row[0]) == "submission_accepted" for row in lifecycle)
        assert any(
            str(row[0]) == "submission_corrected_false"
            and str(row[1]) == submission_event_id
            for row in lifecycle
        )
        members = snapshot.connection.execute(
            "SELECT fault_tag_membership_id,state,active_submitted,last_event_id "
            "FROM fault_tag_membership_current WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchall()
        assert {str(row[1]) for row in members} == {"draft"}
        assert {int(row[2]) for row in members} == {0}
        for row in members:
            correction = snapshot.connection.execute(
                "SELECT event_kind,target_event_id FROM fault_tag_membership_events "
                "WHERE membership_event_id=?",
                (str(row[3]),),
            ).fetchone()
            assert tuple(correction) == (
                "correct",
                submitted_event_ids[str(row[0])],
            )
            original = snapshot.connection.execute(
                "SELECT event_kind FROM fault_tag_membership_events "
                "WHERE membership_event_id=?",
                (submitted_event_ids[str(row[0])],),
            ).fetchone()
            assert str(original[0]) == "submitted"


def test_t049_material_membership_correction_creates_linear_replacement(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    predecessor = str(submitted["fault_tag_id"])

    with ReadSnapshot(factory) as snapshot:
        frozen_snapshot = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id",
                (predecessor,),
            ).fetchall()
        )

    replacement = tags.create_fault_tag_replacement(
        command_id=new_uuid4(),
        predecessor_fault_tag_id=predecessor,
        return_method="non_pickup",
        memberships=tuple(
            FaultTagMembershipIntent(rma_id, "corrected return scope")
            for rma_id in rmas
        ),
        reason_code="submitted memberships were materially wrong",
    )
    successor = str(replacement["fault_tag_id"])
    assert successor != predecessor
    assert replacement["state"] == "draft"
    assert {
        str(member["fault_tag_membership_id"]) for member in replacement["members"]
    }.isdisjoint(
        str(member["fault_tag_membership_id"]) for member in submitted["members"]
    )

    with ReadSnapshot(factory) as snapshot:
        predecessor_state = snapshot.connection.execute(
            "SELECT state FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (predecessor,),
        ).fetchone()
        assert str(predecessor_state[0]) == "superseded"
        predecessor_members = snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_id=?",
            (predecessor,),
        ).fetchall()
        assert {tuple(row) for row in predecessor_members} == {("superseded", 0)}
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id",
                (predecessor,),
            ).fetchall()
        ) == frozen_snapshot
        lineage = snapshot.connection.execute(
            "SELECT relation_type,predecessor_fault_tag_id,successor_fault_tag_id "
            "FROM fault_tag_lineage WHERE predecessor_fault_tag_id=?",
            (predecessor,),
        ).fetchall()
        assert [tuple(row) for row in lineage] == [
            ("corrects_replaces", predecessor, successor)
        ]

    with pytest.raises(SomaError) as second:
        tags.create_fault_tag_replacement(
            command_id=new_uuid4(),
            predecessor_fault_tag_id=predecessor,
            return_method="non_pickup",
            memberships=tuple(
                FaultTagMembershipIntent(rma_id, "another correction")
                for rma_id in rmas
            ),
            reason_code="second replacement is forbidden",
        )
    assert second.value.code == "REPLACEMENT_LINEAGE_CONFLICT"


def test_t053_rejected_open_obligation_resend_preserves_predecessor(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    tags, submitted, _rmas = _submitted_tag(factory)
    predecessor = str(submitted["fault_tag_id"])
    first = _members(submitted)[0]

    tags.record_warehouse_receipt(
        command_id=new_uuid4(),
        memberships=(first,),
    )
    current = _current_members(factory, predecessor)
    rejected_member = next(
        item
        for item in current
        if item.fault_tag_membership_id == first.fault_tag_membership_id
    )
    tags.record_warehouse_final_decision(
        command_id=new_uuid4(),
        memberships=(rejected_member,),
        decision="rejected",
        explicit_confirmation=True,
        reason_code="warehouse rejected return",
    )

    with ReadSnapshot(factory) as snapshot:
        rejected_rma = str(
            snapshot.connection.execute(
                "SELECT rma_id FROM fault_tag_memberships "
                "WHERE fault_tag_membership_id=?",
                (first.fault_tag_membership_id,),
            ).fetchone()[0]
        )
        predecessor_projection = tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_current_projection WHERE fault_tag_id=?",
                (predecessor,),
            ).fetchone()
        )
        predecessor_members = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current "
                "WHERE fault_tag_id=? ORDER BY fault_tag_membership_id",
                (predecessor,),
            ).fetchall()
        )
        predecessor_events = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_events "
                "WHERE fault_tag_membership_id IN ("
                "SELECT fault_tag_membership_id FROM fault_tag_memberships "
                "WHERE fault_tag_id=?) "
                "ORDER BY fault_tag_membership_id,recorded_at_utc,membership_event_id",
                (predecessor,),
            ).fetchall()
        )
        obligation_before = tuple(
            snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id=?",
                (rejected_rma,),
            ).fetchone()
        )
        assert obligation_before[1] == "open"

    resend = tags.create_fault_tag_resend(
        command_id=new_uuid4(),
        predecessor_fault_tag_id=predecessor,
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rejected_rma, "resend rejected return"),),
        reason_code="retry warehouse return",
    )
    successor = str(resend["fault_tag_id"])
    assert successor != predecessor
    assert resend["state"] == "draft"
    assert len(resend["members"]) == 1
    assert str(resend["members"][0]["rma_id"]) == rejected_rma
    assert str(resend["members"][0]["fault_tag_membership_id"]) != first.fault_tag_membership_id

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_current_projection WHERE fault_tag_id=?",
                (predecessor,),
            ).fetchone()
        ) == predecessor_projection
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current "
                "WHERE fault_tag_id=? ORDER BY fault_tag_membership_id",
                (predecessor,),
            ).fetchall()
        ) == predecessor_members
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_events "
                "WHERE fault_tag_membership_id IN ("
                "SELECT fault_tag_membership_id FROM fault_tag_memberships "
                "WHERE fault_tag_id=?) "
                "ORDER BY fault_tag_membership_id,recorded_at_utc,membership_event_id",
                (predecessor,),
            ).fetchall()
        ) == predecessor_events
        assert tuple(
            snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id=?",
                (rejected_rma,),
            ).fetchone()
        ) == obligation_before
        lineage = snapshot.connection.execute(
            "SELECT relation_type,predecessor_fault_tag_id,successor_fault_tag_id "
            "FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? "
            "AND successor_fault_tag_id=?",
            (predecessor, successor),
        ).fetchall()
        assert [tuple(row) for row in lineage] == [
            ("resend_of", predecessor, successor)
        ]
