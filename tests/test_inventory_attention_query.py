from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.queries.attention_history import InventoryAttentionHistoryQuery
from soma.inventory.queries.requests_rma import InventoryRequestsRmaQueryService
from soma.inventory.services.consequences_logistics import (
    InventoryConsequencesLogisticsService,
)
from test_inventory_consequence_replay import _correct_review, _reviewed_task
from test_inventory_requests_rma import _prepare_submitted_request


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _submitted(factory, *, official_sr: str):
    _sr, _need, _service, request_id, _revision = _prepare_submitted_request(
        factory,
        official_sr=official_sr,
        request_quantity=1,
        target_count=1,
        bom=f"ATTN-{official_sr}",
    )
    return request_id


def test_t019_response_overdue_attention_uses_exact_24_hour_boundary(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    request_id = _submitted(factory, official_sr="97100101")
    query = InventoryAttentionHistoryQuery(factory)

    before = query.attention(
        attention_kind="spare_request_response_overdue",
        as_of_utc=2_000 + 86_399,
    )
    assert before["items"] == []
    assert before["exact_total"] == 0

    boundary = query.attention(
        attention_kind="spare_request_response_overdue",
        as_of_utc=2_000 + 86_400,
    )
    assert boundary["exact_total"] == 1
    assert len(boundary["items"]) == 1
    item = boundary["items"][0]
    assert item["target_kind"] == "spare_request"
    assert item["target_id"] == request_id
    assert item["attention_kind"] == "spare_request_response_overdue"
    assert item["severity"] == "action_required"
    assert item["derived_context"]["age_seconds"] == 86_400

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_attention_projection"
        ).fetchone()[0] == 0


def test_spare_request_response_warning_filter_uses_same_exact_boundary(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    request_id = _submitted(factory, official_sr="97100102")
    query = InventoryRequestsRmaQueryService(factory)

    before = query.list_requests(
        response_warning_only=True,
        as_of_utc=2_000 + 86_399,
    )
    assert before["exact_total"] == 0
    assert before["items"] == []

    boundary = query.list_requests(
        response_warning_only=True,
        as_of_utc=2_000 + 86_400,
    )
    assert boundary["exact_total"] == 1
    assert [item["spare_request_id"] for item in boundary["items"]] == [request_id]
    assert boundary["items"][0]["response_warning_age_seconds"] == 86_400


def test_attention_cursor_binds_exact_as_of_and_preserves_equal_kind_members(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    first_id = _submitted(factory, official_sr="97100103")
    second_id = _submitted(factory, official_sr="97100104")
    expected = sorted((first_id, second_id))
    as_of = 2_000 + 86_400
    query = InventoryAttentionHistoryQuery(factory)

    first = query.attention(
        attention_kind="spare_request_response_overdue",
        as_of_utc=as_of,
        limit=1,
    )
    assert first["exact_total"] == 2
    assert [item["target_id"] for item in first["items"]] == [expected[0]]
    assert first["continuation"] is not None

    second = query.attention(
        attention_kind="spare_request_response_overdue",
        as_of_utc=as_of,
        cursor=first["continuation"],
        limit=1,
    )
    assert second["exact_total"] == 2
    assert [item["target_id"] for item in second["items"]] == [expected[1]]
    assert second["continuation"] is None

    with pytest.raises(ValidationError, match="as_of_utc"):
        query.attention(
            attention_kind="spare_request_response_overdue",
            cursor=first["continuation"],
            limit=1,
        )
    with pytest.raises(ValidationError, match="cursor contract"):
        query.attention(
            attention_kind="spare_request_response_overdue",
            as_of_utc=as_of + 1,
            cursor=first["continuation"],
            limit=1,
        )


def test_t041_task_review_change_is_read_only_attention_overlay(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task_id, reviewed, fingerprint = _reviewed_task(factory)
    accepted = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="no_physical_change",
    )
    consequence_id = accepted.target_refs[0].result_id
    query = InventoryAttentionHistoryQuery(factory)

    before = query.attention(
        attention_kind="task_outcome_consequence_pending",
        as_of_utc=1,
    )
    assert before["items"] == []

    _correct_review(factory, task_id, reviewed)
    with ReadSnapshot(factory) as snapshot:
        receipt_count = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        )
        audit_count = int(
            snapshot.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
        projection_count = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM inventory_attention_projection"
            ).fetchone()[0]
        )

    after = query.attention(
        attention_kind="task_outcome_consequence_pending",
        as_of_utc=1,
    )
    assert after["exact_total"] == 1
    assert len(after["items"]) == 1
    item = after["items"][0]
    assert item["target_kind"] == "physical_consequence"
    assert item["target_id"] == consequence_id
    assert item["attention_kind"] == "task_outcome_consequence_pending"
    assert item["derived_context"]["task_id"] == task_id
    assert item["derived_context"]["accepted_task_review_fingerprint"] == fingerprint
    assert item["derived_context"]["current_task_review_fingerprint"] != fingerprint

    with ReadSnapshot(factory) as snapshot:
        assert int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        ) == receipt_count
        assert int(
            snapshot.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        ) == audit_count
        assert int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM inventory_attention_projection"
            ).fetchone()[0]
        ) == projection_count == 0
