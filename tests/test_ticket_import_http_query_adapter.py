from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.ticket_import.http.routes import TicketImportQueryRouteAdapter


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def test_query_adapter_dispatches_real_run_query_service(initialized_database) -> None:
    adapter = TicketImportQueryRouteAdapter(_factory(initialized_database))

    response = adapter.dispatch("GET", "/api/v1/imports/runs", {"limit": 25})

    assert response is not None
    assert response.status == 200
    assert response.response_type == "ImportRunPageV1"
    assert dict(response.body) == {"items": [], "next_cursor": None}


def test_query_adapter_dispatches_route_bound_source_family(initialized_database) -> None:
    adapter = TicketImportQueryRouteAdapter(_factory(initialized_database))

    response = adapter.dispatch("GET", "/api/v1/imports/sources/advanced_search_sr")

    assert response is not None
    assert response.status == 200
    assert response.response_type == "ImportSourceStatusV1"
    assert response.body["source_family"] == "advanced_search_sr"
    assert response.body["configured"] is False


def test_query_adapter_rejects_undeclared_query_fields(initialized_database) -> None:
    adapter = TicketImportQueryRouteAdapter(_factory(initialized_database))

    with pytest.raises(ValidationError):
        adapter.dispatch("GET", "/api/v1/imports/runs", {"source_family": None, "surprise": "nope"})


def test_query_adapter_does_not_dispatch_mutation_routes(initialized_database) -> None:
    adapter = TicketImportQueryRouteAdapter(_factory(initialized_database))

    with pytest.raises(ValidationError):
        adapter.dispatch("POST", "/api/v1/imports/sr/check", {})


def test_query_adapter_leaves_unowned_paths_unresolved(initialized_database) -> None:
    adapter = TicketImportQueryRouteAdapter(_factory(initialized_database))

    assert adapter.dispatch("GET", "/api/v1/not-imports") is None
