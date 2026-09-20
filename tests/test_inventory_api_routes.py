from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.inventory.api.routes_fault_tags import (
    FAULT_TAG_ROUTE_SPECS,
    build_route_adapter as build_fault_adapter,
    resolve_route as resolve_fault_route,
)
from soma.inventory.api.routes_inventory import (
    INVENTORY_ROUTE_SPECS,
    build_route_adapter as build_inventory_adapter,
    resolve_route as resolve_inventory_route,
)


def test_route_registries_match_normative_surface_and_resolve_parameters() -> None:
    assert len(INVENTORY_ROUTE_SPECS) == 30
    assert len(FAULT_TAG_ROUTE_SPECS) == 21
    request = resolve_inventory_route("GET", "/api/v1/inventory/requests/abc")
    assert request is not None
    assert request.spec.handler == "SpareRequestDetailQuery"
    assert dict(request.path_parameters) == {"request_id": "abc"}
    tag = resolve_fault_route("POST", "/api/v1/inventory/fault-tags/xyz/resend")
    assert tag is not None
    assert tag.spec.handler == "CreateFaultTagResend"
    assert dict(tag.path_parameters) == {"fault_tag_id": "xyz"}
    assert resolve_fault_route("GET", "/api/v1/inventory/fault-tags/xyz/resend") is None


def test_thin_adapter_passes_decoded_transport_and_path_without_business_logic() -> None:
    seen: list[tuple[dict[str, str], dict[str, object]]] = []

    def owner(route, payload):
        seen.append((dict(route.path_parameters), dict(payload)))
        return {"fault_tag_id": route.path_parameters["fault_tag_id"], "state": payload["state"]}

    adapter = build_fault_adapter({"ArchiveOrRestoreFaultTag": owner})
    response = adapter.dispatch(
        "POST",
        "/api/v1/inventory/fault-tags/00000000-0000-4000-8000-000000000001/archive-state",
        {"state": "archived"},
    )
    assert response is not None
    assert response.status == 200
    assert response.response_type == "FaultTagV1"
    assert dict(response.body) == {
        "fault_tag_id": "00000000-0000-4000-8000-000000000001",
        "state": "archived",
    }
    assert seen == [
        (
            {"fault_tag_id": "00000000-0000-4000-8000-000000000001"},
            {"state": "archived"},
        )
    ]


def test_adapter_fails_closed_for_unassembled_owner_and_invalid_transport() -> None:
    adapter = build_inventory_adapter({})
    with pytest.raises(IntegrityFailure, match="not assembled"):
        adapter.dispatch("GET", "/api/v1/inventory/stock", {})
    with pytest.raises(ValidationError, match="mapping"):
        adapter.dispatch("GET", "/api/v1/inventory/stock", [])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="without query"):
        resolve_inventory_route("GET", "/api/v1/inventory/stock?cursor=x")


def test_fault_tag_false_submission_route_is_exactly_lowercase() -> None:
    exact = resolve_fault_route(
        "POST",
        "/api/v1/inventory/fault-tags/00000000-0000-4000-8000-000000000001/submission/correct-false",
    )
    assert exact is not None
    assert exact.spec.handler == "CorrectFalseFaultTagSubmission"
    assert resolve_fault_route(
        "POST",
        "/api/v1/inventory/fault-tags/00000000-0000-4000-8000-000000000001/submission/correct-False",
    ) is None


def test_spare_request_false_submission_route_is_exactly_lowercase() -> None:
    exact = resolve_inventory_route(
        "POST",
        "/api/v1/inventory/requests/00000000-0000-4000-8000-000000000001/submission/correct-false",
    )
    assert exact is not None
    assert exact.spec.handler == "CorrectFalseSpareRequestSubmission"
    assert resolve_inventory_route(
        "POST",
        "/api/v1/inventory/requests/00000000-0000-4000-8000-000000000001/submission/correct-False",
    ) is None
