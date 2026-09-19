from __future__ import annotations

from types import SimpleNamespace

import pytest

from soma.foundation.errors import ValidationError
from soma.ticket_import.http.mutations import TicketImportMutationRouteAdapter


class _SourceChecks:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            job_id="11111111-1111-4111-8111-111111111111",
            source_family=kwargs["source_family"],
            invocation_kind=kwargs["invocation_kind"],
            replayed=False,
        )


class _ProposalDecisions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _result(self, name: str, kwargs: dict[str, object], decision: str):
        self.calls.append((name, dict(kwargs)))
        return SimpleNamespace(
            proposal_id=kwargs["proposal_id"],
            decision=decision,
            revision=2,
            owner_result_refs=(("owner_event", "22222222-2222-4222-8222-222222222222"),),
            replayed=False,
        )

    def accept(self, **kwargs):
        return self._result("accept", kwargs, "accepted")

    def reject(self, **kwargs):
        return self._result("reject", kwargs, "rejected")

    def defer(self, **kwargs):
        return self._result("defer", kwargs, "deferred")


class _WfmReviews:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            proposal_id=kwargs["proposal_id"],
            decision="accepted",
            revision=4,
            owner_result_refs=(),
            replayed=False,
        )


class _RunFinalization:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def finalize_run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            import_run_id=kwargs["import_run_id"],
            state="accepted",
            revision=5,
            checkpoint={
                "source_family": "advanced_search_sr",
                "chronology_kind": "embedded_filename_timestamp_utc",
                "chronology_value": 10,
                "logical_fingerprint": "a" * 64,
                "import_run_id": kwargs["import_run_id"],
                "revision": 2,
            },
            replayed=False,
        )


class _Recovery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            import_run_id=kwargs["import_run_id"],
            review_ordinal=3,
            decision="authorized",
            run_state="recovery_required",
            run_revision=9,
            replayed=False,
        )


def _adapter():
    source = _SourceChecks()
    proposals = _ProposalDecisions()
    wfm = _WfmReviews()
    finalization = _RunFinalization()
    recovery = _Recovery()
    adapter = TicketImportMutationRouteAdapter(
        object(),
        source_checks=source,
        proposal_decisions=proposals,
        wfm_reviews=wfm,
        run_finalization=finalization,
        recovery=recovery,
    )
    return adapter, source, proposals, wfm, finalization, recovery


def test_automatic_start_binds_route_constants_and_only_accepts_command_id() -> None:
    adapter, source, *_ = _adapter()
    command_id = "33333333-3333-4333-8333-333333333333"

    response = adapter.dispatch(
        "POST",
        "/api/v1/imports/rfc/check",
        {"command_id": command_id},
    )

    assert response is not None
    assert response.status == 202
    assert response.response_type == "ImportJobAcceptedV1"
    assert dict(response.body) == {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "source_family": "rfc_enhanced",
        "invocation_kind": "automatic",
    }
    assert source.calls == [
        {
            "command_id": command_id,
            "source_family": "rfc_enhanced",
            "invocation_kind": "automatic",
        }
    ]

    with pytest.raises(ValidationError):
        adapter.dispatch(
            "POST",
            "/api/v1/imports/rfc/check",
            {"command_id": command_id, "source_family": "advanced_search_sr"},
        )


def test_manual_start_delegates_selected_path_without_accepting_route_overrides() -> None:
    adapter, source, *_ = _adapter()
    command_id = "44444444-4444-4444-8444-444444444444"
    selected_path = r"C:\\imports\\source.xlsx"

    response = adapter.dispatch(
        "POST",
        "/api/v1/imports/wfm/select",
        {"command_id": command_id, "selected_path": selected_path},
    )

    assert response is not None
    assert source.calls == [
        {
            "command_id": command_id,
            "source_family": "wfm_service_provider",
            "invocation_kind": "manual",
            "selected_path": selected_path,
        }
    ]


def test_proposal_routes_keep_proposal_id_as_path_authority_and_project_owner_refs() -> None:
    adapter, _, proposals, *_ = _adapter()
    proposal_id = "55555555-5555-4555-8555-555555555555"
    command_id = "66666666-6666-4666-8666-666666666666"

    response = adapter.dispatch(
        "POST",
        f"/api/v1/imports/proposals/{proposal_id}/accept",
        {
            "command_id": command_id,
            "proposal_revision": 1,
            "proposal_fingerprint": "a" * 64,
            "base_state_token": "b" * 64,
            "reason_category": None,
        },
    )

    assert response is not None
    assert dict(response.body) == {
        "proposal_id": proposal_id,
        "decision": "accepted",
        "revision": 2,
        "owner_result_refs": [
            {"type": "owner_event", "id": "22222222-2222-4222-8222-222222222222"}
        ],
    }
    assert proposals.calls[0] == (
        "accept",
        {
            "command_id": command_id,
            "proposal_id": proposal_id,
            "proposal_revision": 1,
            "proposal_fingerprint": "a" * 64,
            "base_state_token": "b" * 64,
            "reason_category": None,
        },
    )

    with pytest.raises(ValidationError):
        adapter.dispatch(
            "POST",
            f"/api/v1/imports/proposals/{proposal_id}/accept",
            {
                "command_id": command_id,
                "proposal_id": proposal_id,
                "proposal_revision": 1,
                "proposal_fingerprint": "a" * 64,
                "base_state_token": "b" * 64,
            },
        )


def test_wfm_review_and_finalize_dispatch_exact_transport_fields() -> None:
    adapter, _, _, wfm, finalization, _ = _adapter()
    proposal_id = "77777777-7777-4777-8777-777777777777"
    run_id = "88888888-8888-4888-8888-888888888888"

    wfm_response = adapter.dispatch(
        "POST",
        f"/api/v1/imports/proposals/{proposal_id}/wfm-competing-attempt-review",
        {
            "command_id": "99999999-9999-4999-8999-999999999999",
            "proposal_revision": 3,
            "proposal_fingerprint": "c" * 64,
            "base_state_token": "d" * 64,
            "decision": "same_activity",
            "activity_review_fingerprint": "e" * 64,
            "reason_category": "operator_review",
        },
    )
    assert wfm_response is not None
    assert wfm.calls[0]["proposal_id"] == proposal_id
    assert set(wfm.calls[0]) == {
        "command_id",
        "proposal_id",
        "proposal_revision",
        "proposal_fingerprint",
        "base_state_token",
        "decision",
        "activity_review_fingerprint",
        "reason_category",
    }

    finalize_response = adapter.dispatch(
        "POST",
        f"/api/v1/imports/runs/{run_id}/finalize",
        {"command_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "run_revision": 4},
    )
    assert finalize_response is not None
    assert finalization.calls == [
        {
            "command_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "import_run_id": run_id,
            "expected_run_revision": 4,
        }
    ]
    assert dict(finalize_response.body)["revision"] == 5


def test_recovery_transport_has_no_hidden_revision_inputs_and_hides_internal_run_revision() -> None:
    adapter, *_, recovery = _adapter()
    run_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    command_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

    response = adapter.dispatch(
        "POST",
        f"/api/v1/imports/runs/{run_id}/recovery",
        {
            "command_id": command_id,
            "review_fingerprint": "f" * 64,
            "decision": "authorize_correction",
            "reason_category": "reviewed_correction",
        },
    )

    assert response is not None
    assert response.response_type == "RecoveryDecisionResultV1"
    assert dict(response.body) == {
        "import_run_id": run_id,
        "decision": "authorized",
        "review_ordinal": 3,
        "run_state": "recovery_required",
    }
    assert recovery.calls == [
        {
            "command_id": command_id,
            "import_run_id": run_id,
            "review_fingerprint": "f" * 64,
            "decision": "authorize_correction",
            "reason_category": "reviewed_correction",
        }
    ]

    with pytest.raises(ValidationError):
        adapter.dispatch(
            "POST",
            f"/api/v1/imports/runs/{run_id}/recovery",
            {
                "command_id": command_id,
                "review_fingerprint": "f" * 64,
                "decision": "authorize_correction",
                "reason_category": "reviewed_correction",
                "run_revision": 7,
            },
        )


def test_mutation_adapter_rejects_query_routes_missing_fields_and_non_mapping_bodies() -> None:
    adapter, *_ = _adapter()

    with pytest.raises(ValidationError):
        adapter.dispatch("GET", "/api/v1/imports/runs", {})
    with pytest.raises(ValidationError):
        adapter.dispatch("POST", "/api/v1/imports/sr/check", {})
    with pytest.raises(ValidationError):
        adapter.dispatch("POST", "/api/v1/imports/sr/check", ["not", "an", "object"])

    assert adapter.dispatch("POST", "/api/v1/imports/not-a-route", {}) is None
