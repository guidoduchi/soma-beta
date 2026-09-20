from __future__ import annotations

from soma.objectives_tasks.api.routes_objectives_tasks import (
    ROUTES,
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
