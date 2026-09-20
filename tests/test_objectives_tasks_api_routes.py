from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.api.routes_objectives_tasks import (
    ROUTES,
    ObjectiveTaskRouteAdapter,
    resolve_objectives_tasks_route,
)


def test_lld05_route_registry_matches_normative_core_routes() -> None:
    assert len({(route.method, route.path) for route in ROUTES}) == len(ROUTES)
    assert resolve_objectives_tasks_route("GET", "/api/v1/objectives") is not None
    resolved = resolve_objectives_tasks_route(
        "POST",
        "/api/v1/tasks/00000000-0000-4000-8000-000000000001/review-preview",
    )
    assert resolved is not None
    assert resolved.spec.handler == "TaskOutcomeReviewPreview"
    assert resolved.path_parameters["task_id"] == "00000000-0000-4000-8000-000000000001"


def test_complete_route_metadata_matches_accepted_packet_and_both_fragments():
    # Accepted design dbcf681f: core Tasks, Objective/grouping, review previews.
    assert len(ROUTES) == 48
    assert sha256_canonical_json([asdict(route) for route in ROUTES]) == (
        "609011db2f96840d923f728eff3520d1d7f3693f76aa315d3caeed4ef93c603e"
    )


@pytest.mark.parametrize("spec", ROUTES, ids=lambda spec: spec.handler)
def test_every_declared_route_resolves_to_its_own_owner(spec):
    concrete = "/".join("00000000-0000-4000-8000-000000000001" if part.startswith("{") else part
                        for part in spec.path.split("/"))
    resolved = resolve_objectives_tasks_route(spec.method, concrete)
    assert resolved is not None
    assert resolved.spec == spec


def test_historical_proposals_are_not_an_objective_id():
    resolved = resolve_objectives_tasks_route("GET", "/api/v1/objectives/historical-proposals")
    assert resolved.spec.handler == "HistoricalObjectiveProposalList"
    assert dict(resolved.path_parameters) == {}
    calls = []
    adapter = ObjectiveTaskRouteAdapter({
        "HistoricalObjectiveProposalList": lambda route, payload: calls.append(route.spec.handler) or {"items": []},
        "ObjectiveWorkbench": lambda *_args: pytest.fail("static path was captured as an Objective ID"),
    })
    response = adapter.dispatch("GET", "/api/v1/objectives/historical-proposals")
    assert response.status == 200
    assert response.response_type == "HistoricalObjectiveProposalPageV1"
    assert response.body == {"items": []}
    assert calls == ["HistoricalObjectiveProposalList"]


@pytest.mark.parametrize("payload", [[], {1: "invalid"}, {"nested": {1: "invalid"}}, {"value": "x" * 4096}])
def test_invalid_decoded_transport_never_calls_task_owner(payload):
    adapter = ObjectiveTaskRouteAdapter({"TaskList": lambda *_args: pytest.fail("invalid request reached owner")})
    with pytest.raises(ValidationError):
        adapter.dispatch("GET", "/api/v1/tasks", payload)


@pytest.mark.parametrize("path", ["/api/v1/tasks/a{id}b", "/api/v1/tasks/{id", "/api/v1/tasks/id}", "/api/v1/tasks/"])
def test_invalid_route_template_fails_closed(path):
    with pytest.raises(IntegrityFailure):
        replace(ROUTES[0], path=path)


def test_missing_task_owner_is_not_silently_accepted():
    with pytest.raises(IntegrityFailure, match="CreateLocalTask"):
        ObjectiveTaskRouteAdapter({}).dispatch("POST", "/api/v1/tasks/local", {})
