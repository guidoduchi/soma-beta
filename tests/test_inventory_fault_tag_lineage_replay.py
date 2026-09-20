from __future__ import annotations

import pytest

from soma.foundation.errors import IdempotencyConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.fault_tags import FaultTagMembershipIntent
from test_inventory_warehouse_replay import _current_members, _factory, _members, _submitted_tag


def test_replacement_failure_rolls_back_predecessor_successor_and_allocator(
    initialized_database, monkeypatch,
):
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    args = dict(command_id=new_uuid4(), predecessor_fault_tag_id=submitted["fault_tag_id"],
                return_method="non_pickup", reason_code="correction",
                memberships=tuple(FaultTagMembershipIntent(x, "return") for x in rmas))
    original = tags._repository.create_lineage_successor

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after lineage write")

    with monkeypatch.context() as patch:
        patch.setattr(tags._repository, "create_lineage_successor", fail_after_write)
        with pytest.raises(RuntimeError, match="after lineage write"):
            tags.create_fault_tag_replacement(**args)
    with ReadSnapshot(factory) as snapshot:
        assert tags._response(snapshot.connection, submitted["fault_tag_id"]) == submitted
        for table in ("command_receipts", "audit_events", "fault_tag_lineage"):
            assert snapshot.connection.execute(f"SELECT COUNT(*) FROM {table} WHERE command_id=?", (args["command_id"],)).fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM fault_tags").fetchone()[0] == 1
    result = tags.create_fault_tag_replacement(**args)
    assert result["tracking_handle"] == "FT-00000002"


@pytest.mark.parametrize("relation", ["replacement", "resend"])
def test_fault_tag_lineage_is_immutable_and_replays_after_successor_changes(
    initialized_database, monkeypatch, relation,
):
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    predecessor = submitted["fault_tag_id"]
    if relation == "resend":
        tags.record_warehouse_receipt(command_id=new_uuid4(), memberships=_members(submitted))
        tags.record_warehouse_final_decision(
            command_id=new_uuid4(), memberships=_current_members(factory, predecessor),
            decision="rejected", explicit_confirmation=True, reason_code="packaging",
        )
    with ReadSnapshot(factory) as snapshot:
        prior_members = tuple(tuple(row) for row in snapshot.connection.execute(
            "SELECT * FROM fault_tag_membership_current WHERE fault_tag_id=? ORDER BY fault_tag_membership_id", (predecessor,),
        ))
        frozen = tuple(tuple(row) for row in snapshot.connection.execute(
            "SELECT * FROM fault_tag_submission_snapshots WHERE fault_tag_id=?", (predecessor,),
        ))
    call = getattr(tags, f"create_fault_tag_{relation}")
    arguments = dict(
        command_id=new_uuid4(), predecessor_fault_tag_id=predecessor,
        return_method="non_pickup", reason_code="corrected_return",
        memberships=tuple(FaultTagMembershipIntent(identity, "return") for identity in rmas),
    )
    result = call(**arguments)
    assert result["fault_tag_id"] != predecessor
    assert result["state"] == "draft"
    assert {x["fault_tag_membership_id"] for x in result["members"]}.isdisjoint(
        x["fault_tag_membership_id"] for x in submitted["members"]
    )
    assert call(**arguments) == result
    tags.archive_or_restore_fault_tag(
        command_id=new_uuid4(), fault_tag_id=result["fault_tag_id"],
        base_revision=result["revision"], action="archive", reason_code="operator_archive",
    )
    with pytest.raises(SomaError):
        call(**{**arguments, "command_id": new_uuid4()})

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not read current Fault Tag state")

    monkeypatch.setattr(tags._repository, "current_tag", forbidden)
    assert call(**arguments) == result
    with pytest.raises(IdempotencyConflict):
        call(**{**arguments, "reason_code": "different_intent"})
    with ReadSnapshot(factory) as snapshot:
        if relation == "resend":
            assert tuple(tuple(row) for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current WHERE fault_tag_id=? ORDER BY fault_tag_membership_id", (predecessor,),
            )) == prior_members
        else:
            assert snapshot.connection.execute(
                "SELECT state FROM fault_tag_current_projection WHERE fault_tag_id=?", (predecessor,),
            ).fetchone()[0] == "superseded"
        assert tuple(tuple(row) for row in snapshot.connection.execute(
            "SELECT * FROM fault_tag_submission_snapshots WHERE fault_tag_id=?", (predecessor,),
        )) == frozen
        lineage = snapshot.connection.execute(
            "SELECT relation_type,successor_fault_tag_id FROM fault_tag_lineage "
            "WHERE predecessor_fault_tag_id=?", (predecessor,),
        ).fetchall()
        assert [tuple(row) for row in lineage] == [
            ("corrects_replaces" if relation == "replacement" else "resend_of", result["fault_tag_id"])
        ]
        for identity in rmas:
            assert snapshot.connection.execute(
                "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?", (identity,),
            ).fetchone()[0] == "open"
