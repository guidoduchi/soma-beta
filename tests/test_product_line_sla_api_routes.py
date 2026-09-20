from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from soma.foundation.strict_json import sha256_canonical_json

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.product_line_sla.api.routes_product_line_sla import (
    PRODUCT_LINE_SLA_ROUTE_SPECS,
    ProductLineSlaRouteAdapter,
    build_route_adapter,
    resolve_route,
)


def test_lld06_route_registry_matches_normative_routes_and_fragments() -> None:
    # Exact route metadata from accepted design dbcf681f, including its fragment.
    assert sha256_canonical_json([asdict(spec) for spec in PRODUCT_LINE_SLA_ROUTE_SPECS]) == (
        "f3bbcb4807c83dae489a84a9e3600efe9d56e9ae675f1bdb9305e49c8d25b16d"
    )
    assert len(PRODUCT_LINE_SLA_ROUTE_SPECS) == 29
    assert len({(item.method, item.path) for item in PRODUCT_LINE_SLA_ROUTE_SPECS}) == 29
    policy = resolve_route("POST", "/api/v1/contract-product-lines/abc/policy")
    assert policy is not None
    assert policy.spec.handler == "ReviseSlaPolicy"
    assert dict(policy.path_parameters) == {"id": "abc"}
    report = resolve_route("POST", "/api/v1/reports/xyz/cancel")
    assert report is not None
    assert report.spec.handler == "CancelSlaReportAttempt"
    assert dict(report.path_parameters) == {"report_attempt_id": "xyz"}


def test_lld06_adapter_delegates_without_calculating_domain_authority() -> None:
    seen = []

    def owner(route, payload):
        seen.append((dict(route.path_parameters), dict(payload)))
        return {"report_attempt_id": route.path_parameters["report_attempt_id"], "state": "cancelled"}

    response = build_route_adapter({"CancelSlaReportAttempt": owner}).dispatch(
        "POST", "/api/v1/reports/abc/cancel", {"reason": "operator"}
    )
    assert response is not None
    assert response.status == 200
    assert dict(response.body) == {"report_attempt_id": "abc", "state": "cancelled"}
    assert seen == [({"report_attempt_id": "abc"}, {"reason": "operator"})]


def test_lld06_adapter_fails_closed_for_unassembled_and_invalid_transport() -> None:
    adapter = build_route_adapter({})
    with pytest.raises(IntegrityFailure, match="not assembled"):
        adapter.dispatch("GET", "/api/v1/product-lines")
    with pytest.raises(ValidationError, match="mapping"):
        adapter.dispatch("GET", "/api/v1/product-lines", [])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="without query"):
        resolve_route("GET", "/api/v1/product-lines?cursor=x")

@pytest.mark.parametrize("path", [
    "/api/v1/reports/{id}/{oops", "/api/v1/reports/id}",
    "/api/v1/reports/{id}/{id}", "/api/v1/reports/{id}/",
])
def test_malformed_route_specs_fail_closed(path):
    with pytest.raises(IntegrityFailure):
        replace(PRODUCT_LINE_SLA_ROUTE_SPECS[0], path=path)


def test_adapter_honors_supplied_registry_and_literal_route_precedence():
    prototype = PRODUCT_LINE_SLA_ROUTE_SPECS[0]
    dynamic = replace(prototype, path="/api/v1/custom/{id}", handler="Dynamic")
    literal = replace(prototype, path="/api/v1/custom/history", handler="History")
    adapter = ProductLineSlaRouteAdapter(
        {"History": lambda route, payload: {"owner": route.spec.handler}},
        (dynamic, literal),
    )
    response = adapter.dispatch("get", "/api/v1/custom/history")
    assert response.body["owner"] == "History"
    assert adapter.dispatch("GET", "/api/v1/product-lines") is None
    with pytest.raises(IntegrityFailure, match="ambiguous"):
        ProductLineSlaRouteAdapter({}, (dynamic, replace(dynamic, path="/api/v1/custom/{other}")))
    with pytest.raises(IntegrityFailure, match="duplicate"):
        ProductLineSlaRouteAdapter({}, (literal, literal))


@pytest.mark.parametrize("payload", [{1: "wrong"}, {"nested": {1: "wrong"}}, {"value": "x" * 4096}])
def test_invalid_payload_never_reaches_owner(payload):
    calls = []
    adapter = build_route_adapter({"ListProductLines": lambda *args: calls.append(args)})
    with pytest.raises(ValidationError):
        adapter.dispatch("GET", "/api/v1/product-lines", payload)
    assert calls == []


def test_internal_report_worker_operations_have_no_public_route():
    handlers = {spec.handler for spec in PRODUCT_LINE_SLA_ROUTE_SPECS}
    assert handlers.isdisjoint({
        "StageReportSnapshotBatch", "SealReportSnapshot", "MarkReportGenerating",
        "MarkReportVerifying", "CompleteSlaReport", "FailSlaReportAttempt",
    })


def test_adapter_preserves_owner_failure_and_rejects_non_object_response():
    failure = ValidationError("owner rejection")

    def reject(*args):
        raise failure

    with pytest.raises(ValidationError) as caught:
        build_route_adapter({"ListProductLines": reject}).dispatch("GET", "/api/v1/product-lines")
    assert caught.value is failure
    with pytest.raises(IntegrityFailure, match="non-object"):
        build_route_adapter({"ListProductLines": lambda *args: []}).dispatch("GET", "/api/v1/product-lines")
