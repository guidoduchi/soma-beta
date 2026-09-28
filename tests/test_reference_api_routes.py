from __future__ import annotations

from collections.abc import Mapping

import pytest

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.reference.api.routes_reference import (
    REFERENCE_ROUTE_SPECS,
    ReferenceRouteAdapter,
    resolve_reference_route,
)


def test_reference_route_registry_matches_closed_public_surface() -> None:
    assert len(REFERENCE_ROUTE_SPECS) == 32
    assert len({(spec.method, spec.path) for spec in REFERENCE_ROUTE_SPECS}) == 32
    assert all(spec.method != "DELETE" for spec in REFERENCE_ROUTE_SPECS)
    assert all(
        spec.auth_policy
        == (
            "LLD12_BROWSER_QUERY_V1"
            if spec.handler_kind == "query"
            else "LLD12_BROWSER_MUTATION_V1"
        )
        for spec in REFERENCE_ROUTE_SPECS
    )
    assert not any(
        spec.handler == "CreateDedicatedDispatchLocationForSite"
        for spec in REFERENCE_ROUTE_SPECS
    )
    assert not any(
        spec.handler == "CreateLocalUserProfileIdentity"
        for spec in REFERENCE_ROUTE_SPECS
    )


@pytest.mark.parametrize(
    "reference_type",
    ["customer_organization", "contact", "dispatch_location"],
)
def test_generic_reference_type_resolves_only_closed_enum(reference_type: str) -> None:
    resolved = resolve_reference_route(
        "POST",
        f"/api/v1/reference/{reference_type}/"
        "00000000-0000-4000-8000-000000000001/archive",
    )
    assert resolved is not None
    assert resolved.spec.handler == "ArchiveReference"
    assert resolved.path_parameters["reference_type"] == reference_type


@pytest.mark.parametrize(
    "reference_type",
    ["customer-organizations", "contacts", "dispatch-locations", "settings", "sqlite_schema"],
)
def test_generic_reference_type_rejects_non_enum_values(reference_type: str) -> None:
    assert resolve_reference_route(
        "POST",
        f"/api/v1/reference/{reference_type}/"
        "00000000-0000-4000-8000-000000000001/archive",
    ) is None


def test_literal_reference_routes_do_not_fall_through_to_generic_authority() -> None:
    resolved = resolve_reference_route(
        "POST",
        "/api/v1/reference/match/contact",
    )
    assert resolved is not None
    assert resolved.spec.handler == "MatchContact"
    assert dict(resolved.path_parameters) == {}


def test_route_resolver_rejects_query_fragment_and_nonabsolute_input() -> None:
    with pytest.raises(ValidationError):
        resolve_reference_route(
            "GET",
            "/api/v1/reference/contacts?limit=5",
        )
    with pytest.raises(ValidationError):
        resolve_reference_route("GET", "api/v1/reference/contacts")
    with pytest.raises(ValidationError):
        resolve_reference_route(
            "GET",
            "/api/v1/reference/contacts#fragment",
        )


def test_reference_route_adapter_is_thin_bounded_and_owner_injected() -> None:
    seen: list[tuple[str, Mapping[str, object], dict[str, str]]] = []

    def handler(resolved, payload):
        seen.append(
            (
                resolved.spec.handler,
                payload,
                dict(resolved.path_parameters),
            )
        )
        return {"ok": True}

    adapter = ReferenceRouteAdapter({"CreateContact": handler})
    response = adapter.dispatch(
        "POST",
        "/api/v1/reference/contacts",
        {"name": "Ada"},
    )
    assert response is not None
    assert response.status == 201
    assert response.response_type == "ReferenceMutationResultV1"
    assert dict(response.body) == {"ok": True}
    assert seen == [("CreateContact", {"name": "Ada"}, {})]

    with pytest.raises(ValidationError):
        adapter.dispatch(
            "POST",
            "/api/v1/reference/contacts",
            {"name": "x" * 9_000},
        )


def test_reference_route_adapter_fails_closed_when_owner_not_assembled() -> None:
    adapter = ReferenceRouteAdapter({})
    with pytest.raises(IntegrityFailure, match="not assembled"):
        adapter.dispatch("GET", "/api/v1/reference/contacts", {})


def test_reference_transport_contains_no_persistence_or_sql_authority() -> None:
    import inspect
    import soma.reference.api.routes_reference as routes

    source = inspect.getsource(routes).upper()
    assert ".EXECUTE(" not in source
    assert "DELETE FROM" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
