from __future__ import annotations

import pytest
from types import SimpleNamespace

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.infrastructure.api.routes_infrastructure import (
    INFRASTRUCTURE_ROUTE_SPECS, build_route_adapter, resolve_route,
    build_owner_route_adapter,
)


def test_route_inventory_matches_pinned_packet_and_resolves_literal_first():
    assert len(INFRASTRUCTURE_ROUTE_SPECS) == 49
    assert len({(spec.method, spec.path) for spec in INFRASTRUCTURE_ROUTE_SPECS}) == 49
    route = resolve_route("GET", "/api/v1/infrastructure/workbooks/history")
    assert route is not None and route.spec.handler == "InfrastructureWorkbookHistoryQuery"
    assert resolve_route("GET", "/api/v1/infrastructure/unknown") is None
    for spec in INFRASTRUCTURE_ROUTE_SPECS:
        path = spec.path
        for field in spec.path_fields:
            path = path.replace(
                "{" + field + "}", "a" * 64 if field == "logical_fingerprint" else new_uuid4(),
            )
        resolved = resolve_route(spec.method, path)
        assert resolved is not None and resolved.spec == spec


def test_route_injects_path_owned_query_identity_and_rejects_conflict():
    identity = new_uuid4()
    captured = []

    def handler(route, payload):
        captured.append((route, dict(payload)))
        return {"site_id": payload["site_id"]}

    adapter = build_route_adapter({"SiteDetailQuery": handler})
    path = f"/api/v1/infrastructure/sites/{identity}"
    response = adapter.dispatch("GET", path)
    assert response.status == 200 and response.body["site_id"] == identity
    assert captured[0][1] == {"site_id": identity}
    with pytest.raises(ValidationError):
        adapter.dispatch("GET", path, {"site_id": new_uuid4()})
    with pytest.raises(ValidationError):
        adapter.dispatch("GET", path, {"unknown": True})
    with pytest.raises(ValidationError):
        adapter.dispatch("GET", "/api/v1/infrastructure/sites/not-a-uuid")


def test_command_route_validates_envelope_identity_and_dto():
    identity = new_uuid4()
    seen = []

    def handler(_route, payload):
        seen.append(dict(payload))
        return {"ok": True}

    adapter = build_route_adapter({"UpdateSiteDescriptive": handler})
    path = f"/api/v1/infrastructure/sites/{identity}"
    request = dict(command_id=new_uuid4(), base_revision=1,
                   name="Site", address_text="1 Main Street", reason_code="correction")
    response = adapter.dispatch("PATCH", path, request)
    assert response.status == 200
    assert seen[0]["site_id"] == identity and seen[0]["command_id"] == request["command_id"]
    with pytest.raises(ValidationError):
        adapter.dispatch("PATCH", path, {**request, "site_id": new_uuid4()})
    with pytest.raises(ValidationError):
        adapter.dispatch("PATCH", path, {**request, "command_id": "invalid"})
    with pytest.raises(ValidationError):
        adapter.dispatch("PATCH", path, {**request, "unexpected": "value"})


def test_unassembled_route_fails_closed():
    with pytest.raises(IntegrityFailure):
        build_route_adapter({}).dispatch("GET", "/api/v1/infrastructure/tree")


def test_installed_owner_binding_uses_authenticated_actor_and_fails_closed_for_missing_owner(monkeypatch):
    calls = []

    class Service:
        def execute(self, command, **kwargs):
            calls.append((command, kwargs))
            response_schema = {
                "GenerateInfrastructureWorkbook": "INFRA_JOB_ACCEPTED_V1",
                "StageInfrastructureWorkbookCheck": "INFRA_JOB_ACCEPTED_V1",
                "AcceptInfrastructureWorkbookRun": "INFRA_WORKBOOK_ACCEPT_RESULT_V1",
                "RejectInfrastructureWorkbookRun": "INFRA_WORKBOOK_RUN_RESULT_V1",
            }.get(command, "INFRA_MUTATION_RESULT_V1")
            return SimpleNamespace(response_schema=response_schema, response={"ok": True})

    from soma.infrastructure.queries.core import InfrastructureQueries

    def query(_self, name, request):
        calls.append((name, request))
        return {"site_id": request["site_id"]}

    monkeypatch.setattr(InfrastructureQueries, "execute", query)
    adapter = build_owner_route_adapter(Service(), actor_kind="local_user", actor_id="admin")
    customer = new_uuid4()
    command_id = new_uuid4()
    response = adapter.dispatch("POST", "/api/v1/infrastructure/sites", {
        "command_id": command_id, "customer_org_id": customer,
        "name": "Site", "address_text": "1 Main Street",
    })
    assert response.body == {"ok": True}
    assert calls[0][0] == "CreateSite"
    assert calls[0][1]["actor_id"] == "admin"
    assert calls[0][1]["command_id"] == command_id
    site_id = new_uuid4()
    detail = adapter.dispatch("GET", f"/api/v1/infrastructure/sites/{site_id}")
    assert detail.body["site_id"] == site_id
    export = adapter.dispatch("POST", "/api/v1/infrastructure/workbooks/export", {
        "command_id": new_uuid4(), "mode": "registration_template",
        "scope": {"scope_kind": "all"}, "destination_directory": r"D:\Exports",
    })
    assert export.body == {"ok": True}
    accepted = adapter.dispatch(
        "POST",
        f"/api/v1/infrastructure/workbooks/runs/{new_uuid4()}/accept",
        {
            "command_id": new_uuid4(),
            "run_revision": 1,
            "run_input_fingerprint": "a" * 64,
            "dispositions": [],
        },
    )
    assert accepted.body == {"ok": True}
    assert calls[-1][0] == "AcceptInfrastructureWorkbookRun"
    with pytest.raises(ValidationError):
        build_owner_route_adapter(Service(), actor_kind="", actor_id=None)
