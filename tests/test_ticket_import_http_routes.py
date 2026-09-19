from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.ticket_import.http.routes import IMPORT_ROUTE_SPECS, resolve_import_route


_EXPECTED_ROUTE_AUTHORITIES = {
    ("POST", "/api/v1/imports/sr/check"): ("StartTicketSourceImportCheck", 202, 4096),
    ("POST", "/api/v1/imports/sr/select"): ("StartTicketSourceImportCheck", 202, 8192),
    ("POST", "/api/v1/imports/rfc/check"): ("StartTicketSourceImportCheck", 202, 4096),
    ("POST", "/api/v1/imports/rfc/select"): ("StartTicketSourceImportCheck", 202, 8192),
    ("POST", "/api/v1/imports/wfm/check"): ("StartTicketSourceImportCheck", 202, 4096),
    ("POST", "/api/v1/imports/wfm/select"): ("StartTicketSourceImportCheck", 202, 8192),
    ("GET", "/api/v1/imports/sources/{source_family}"): ("GetImportSourceStatus", 200, 2048),
    ("GET", "/api/v1/imports/runs"): ("ListImportRuns", 200, 4096),
    ("GET", "/api/v1/imports/runs/{import_run_id}"): ("GetImportRun", 200, 2048),
    ("GET", "/api/v1/imports/runs/{import_run_id}/observations"): (
        "ListPublishedSourceObservations",
        200,
        4096,
    ),
    ("GET", "/api/v1/imports/runs/{import_run_id}/findings"): ("ListImportFindings", 200, 4096),
    ("GET", "/api/v1/imports/runs/{import_run_id}/proposals"): (
        "ListReconciliationProposals",
        200,
        4096,
    ),
    ("GET", "/api/v1/imports/proposals/{proposal_id}"): ("GetProposalReview", 200, 2048),
    ("POST", "/api/v1/imports/proposals/{proposal_id}/accept"): (
        "AcceptReconciliationProposal",
        200,
        8192,
    ),
    ("POST", "/api/v1/imports/proposals/{proposal_id}/wfm-competing-attempt-review"): (
        "ResolveWfmCompetingAttemptReview",
        200,
        8192,
    ),
    ("POST", "/api/v1/imports/proposals/{proposal_id}/reject"): (
        "RejectReconciliationProposal",
        200,
        8192,
    ),
    ("POST", "/api/v1/imports/proposals/{proposal_id}/defer"): (
        "DeferReconciliationProposal",
        200,
        8192,
    ),
    ("POST", "/api/v1/imports/runs/{import_run_id}/finalize"): (
        "FinalizeImportRunReview",
        200,
        4096,
    ),
    ("GET", "/api/v1/imports/runs/{import_run_id}/recovery-preview"): (
        "PreviewImportRecovery",
        200,
        2048,
    ),
    ("POST", "/api/v1/imports/runs/{import_run_id}/recovery"): (
        "ResolveImportRecovery",
        200,
        8192,
    ),
}


def test_route_registry_matches_normative_public_authority_set() -> None:
    actual = {
        (spec.method, spec.path): (spec.handler, spec.success_status, spec.max_request_bytes)
        for spec in IMPORT_ROUTE_SPECS
    }
    assert actual == _EXPECTED_ROUTE_AUTHORITIES
    assert len(IMPORT_ROUTE_SPECS) == 20
    assert "PublishStagedImportRun" not in {spec.handler for spec in IMPORT_ROUTE_SPECS}
    assert "RecordNewerIdenticalSourceCheck" not in {spec.handler for spec in IMPORT_ROUTE_SPECS}


def test_route_registry_keeps_security_policy_at_transport_boundary() -> None:
    for spec in IMPORT_ROUTE_SPECS:
        if spec.handler_kind == "query":
            assert spec.method == "GET"
            assert spec.auth_policy == "LLD12_BROWSER_QUERY_V1"
        else:
            assert spec.method == "POST"
            assert spec.auth_policy == "LLD12_BROWSER_MUTATION_V1"


def test_start_routes_pin_source_family_and_invocation_kind() -> None:
    expected = {
        "/api/v1/imports/sr/check": ("advanced_search_sr", "automatic"),
        "/api/v1/imports/sr/select": ("advanced_search_sr", "manual"),
        "/api/v1/imports/rfc/check": ("rfc_enhanced", "automatic"),
        "/api/v1/imports/rfc/select": ("rfc_enhanced", "manual"),
        "/api/v1/imports/wfm/check": ("wfm_service_provider", "automatic"),
        "/api/v1/imports/wfm/select": ("wfm_service_provider", "manual"),
    }
    actual = {
        spec.path: (spec.constants["source_family"], spec.constants["invocation_kind"])
        for spec in IMPORT_ROUTE_SPECS
        if spec.handler == "StartTicketSourceImportCheck"
    }
    assert actual == expected


def test_route_resolution_extracts_only_declared_path_parameters() -> None:
    run_id = "11111111-1111-4111-8111-111111111111"
    resolved = resolve_import_route("get", f"/api/v1/imports/runs/{run_id}/findings")
    assert resolved is not None
    assert resolved.spec.handler == "ListImportFindings"
    assert dict(resolved.path_parameters) == {"import_run_id": run_id}

    proposal_id = "22222222-2222-4222-8222-222222222222"
    competing = resolve_import_route(
        "POST",
        f"/api/v1/imports/proposals/{proposal_id}/wfm-competing-attempt-review",
    )
    assert competing is not None
    assert competing.spec.handler == "ResolveWfmCompetingAttemptReview"
    assert dict(competing.path_parameters) == {"proposal_id": proposal_id}

    assert resolve_import_route("GET", f"/api/v1/imports/proposals/{proposal_id}/accept") is None
    assert resolve_import_route("GET", "/api/v1/imports/unknown") is None


def test_route_resolver_rejects_non_path_input() -> None:
    with pytest.raises(ValidationError):
        resolve_import_route("", "/api/v1/imports/runs")
    with pytest.raises(ValidationError):
        resolve_import_route("GET", "api/v1/imports/runs")
    with pytest.raises(ValidationError):
        resolve_import_route("GET", "/api/v1/imports/runs?limit=10")
