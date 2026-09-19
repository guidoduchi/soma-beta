from __future__ import annotations

from typing import Mapping

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.commands.finalize_run import ImportRunFinalizationService
from soma.ticket_import.commands.recovery import ResolveImportRecoveryService
from soma.ticket_import.commands.review_competing_attempt import WfmCompetingAttemptReviewService
from soma.ticket_import.commands.start_source_check import StartTicketSourceImportCheckService

from .routes import ResolvedImportRoute, TicketImportHttpResponse, resolve_import_route


def _body_data(
    value: Mapping[str, object] | None,
    *,
    allowed: frozenset[str],
    required: frozenset[str],
) -> dict[str, object]:
    if value is None:
        data: dict[str, object] = {}
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise ValidationError("LLD-04 decoded mutation body must be a mapping")

    if any(not isinstance(key, str) or not key for key in data):
        raise ValidationError("LLD-04 mutation field names must be nonempty strings")
    unexpected = set(data) - allowed
    if unexpected:
        raise ValidationError(f"unexpected LLD-04 mutation field: {sorted(unexpected)[0]}")
    missing = required - set(data)
    if missing:
        raise ValidationError(f"missing LLD-04 mutation field: {sorted(missing)[0]}")
    return data


def _proposal_response(result: object) -> dict[str, object]:
    proposal_id = getattr(result, "proposal_id", None)
    decision = getattr(result, "decision", None)
    revision = getattr(result, "revision", None)
    refs = getattr(result, "owner_result_refs", None)
    if (
        not isinstance(proposal_id, str)
        or not proposal_id
        or decision not in {"accepted", "rejected", "deferred"}
        or type(revision) is not int
        or revision < 1
        or not isinstance(refs, tuple)
    ):
        raise IntegrityFailure("LLD-04 proposal command returned an invalid transport result")
    owner_result_refs: list[dict[str, str]] = []
    for ref in refs:
        if (
            not isinstance(ref, tuple)
            or len(ref) != 2
            or not isinstance(ref[0], str)
            or not ref[0]
            or not isinstance(ref[1], str)
            or not ref[1]
        ):
            raise IntegrityFailure("LLD-04 proposal command returned an invalid owner result reference")
        owner_result_refs.append({"type": ref[0], "id": ref[1]})
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "revision": revision,
        "owner_result_refs": owner_result_refs,
    }


class TicketImportMutationRouteAdapter:
    """Thin authenticated-mutation adapter for the public LLD-04 browser command surface.

    LLD-12 owns session, Host, Origin, CSRF and raw request-byte enforcement before this
    adapter is called. Route-owned path/source constants are never accepted from the body.
    Service injection is supported so application assembly can supply exact LLD-05/06
    participants without moving owning-domain logic into HTTP.
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        source_checks: StartTicketSourceImportCheckService | None = None,
        proposal_decisions: ProposalDecisionService | None = None,
        wfm_reviews: WfmCompetingAttemptReviewService | None = None,
        run_finalization: ImportRunFinalizationService | None = None,
        recovery: ResolveImportRecoveryService | None = None,
    ) -> None:
        self._source_checks = (
            StartTicketSourceImportCheckService(connection_factory)
            if source_checks is None
            else source_checks
        )
        self._proposal_decisions = (
            ProposalDecisionService(connection_factory)
            if proposal_decisions is None
            else proposal_decisions
        )
        self._wfm_reviews = (
            WfmCompetingAttemptReviewService(connection_factory)
            if wfm_reviews is None
            else wfm_reviews
        )
        self._run_finalization = (
            ImportRunFinalizationService(connection_factory)
            if run_finalization is None
            else run_finalization
        )
        self._recovery = (
            ResolveImportRecoveryService(connection_factory)
            if recovery is None
            else recovery
        )

    @staticmethod
    def _response(resolved: ResolvedImportRoute, body: Mapping[str, object]) -> TicketImportHttpResponse:
        return TicketImportHttpResponse(
            status=resolved.spec.success_status,
            response_type=resolved.spec.response_type,
            body=body,
        )

    def dispatch(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
    ) -> TicketImportHttpResponse | None:
        """Dispatch one already-authenticated POST route using a decoded JSON object body."""

        resolved = resolve_import_route(method, path)
        if resolved is None:
            return None
        if resolved.spec.handler_kind != "command":
            raise ValidationError("query route cannot be dispatched through the LLD-04 mutation adapter")

        handler = resolved.spec.handler
        path_parameters = resolved.path_parameters

        if handler == "StartTicketSourceImportCheck":
            invocation_kind = resolved.spec.constants["invocation_kind"]
            source_family = resolved.spec.constants["source_family"]
            if invocation_kind == "automatic":
                data = _body_data(
                    body,
                    allowed=frozenset({"command_id"}),
                    required=frozenset({"command_id"}),
                )
                result = self._source_checks.start(
                    command_id=data["command_id"],
                    source_family=source_family,
                    invocation_kind=invocation_kind,
                )
            elif invocation_kind == "manual":
                data = _body_data(
                    body,
                    allowed=frozenset({"command_id", "selected_path"}),
                    required=frozenset({"command_id", "selected_path"}),
                )
                result = self._source_checks.start(
                    command_id=data["command_id"],
                    source_family=source_family,
                    invocation_kind=invocation_kind,
                    selected_path=data["selected_path"],
                )
            else:
                raise IntegrityFailure("LLD-04 start route invocation constant is invalid")
            result_body = {
                "job_id": result.job_id,
                "source_family": result.source_family,
                "invocation_kind": result.invocation_kind,
            }

        elif handler == "AcceptReconciliationProposal":
            data = _body_data(
                body,
                allowed=frozenset(
                    {
                        "command_id",
                        "proposal_revision",
                        "proposal_fingerprint",
                        "base_state_token",
                        "reason_category",
                    }
                ),
                required=frozenset(
                    {"command_id", "proposal_revision", "proposal_fingerprint", "base_state_token"}
                ),
            )
            result = self._proposal_decisions.accept(
                command_id=data["command_id"],
                proposal_id=path_parameters["proposal_id"],
                proposal_revision=data["proposal_revision"],
                proposal_fingerprint=data["proposal_fingerprint"],
                base_state_token=data["base_state_token"],
                reason_category=data.get("reason_category"),
            )
            result_body = _proposal_response(result)

        elif handler in {"RejectReconciliationProposal", "DeferReconciliationProposal"}:
            data = _body_data(
                body,
                allowed=frozenset(
                    {"command_id", "proposal_revision", "proposal_fingerprint", "reason_category"}
                ),
                required=frozenset(
                    {"command_id", "proposal_revision", "proposal_fingerprint", "reason_category"}
                ),
            )
            method_name = "reject" if handler == "RejectReconciliationProposal" else "defer"
            decision_method = getattr(self._proposal_decisions, method_name)
            result = decision_method(
                command_id=data["command_id"],
                proposal_id=path_parameters["proposal_id"],
                proposal_revision=data["proposal_revision"],
                proposal_fingerprint=data["proposal_fingerprint"],
                reason_category=data["reason_category"],
            )
            result_body = _proposal_response(result)

        elif handler == "ResolveWfmCompetingAttemptReview":
            data = _body_data(
                body,
                allowed=frozenset(
                    {
                        "command_id",
                        "proposal_revision",
                        "proposal_fingerprint",
                        "base_state_token",
                        "decision",
                        "activity_review_fingerprint",
                        "reason_category",
                    }
                ),
                required=frozenset(
                    {
                        "command_id",
                        "proposal_revision",
                        "proposal_fingerprint",
                        "base_state_token",
                        "decision",
                        "activity_review_fingerprint",
                        "reason_category",
                    }
                ),
            )
            result = self._wfm_reviews.resolve(
                command_id=data["command_id"],
                proposal_id=path_parameters["proposal_id"],
                proposal_revision=data["proposal_revision"],
                proposal_fingerprint=data["proposal_fingerprint"],
                base_state_token=data["base_state_token"],
                decision=data["decision"],
                activity_review_fingerprint=data["activity_review_fingerprint"],
                reason_category=data["reason_category"],
            )
            result_body = _proposal_response(result)

        elif handler == "FinalizeImportRunReview":
            data = _body_data(
                body,
                allowed=frozenset({"command_id", "run_revision"}),
                required=frozenset({"command_id", "run_revision"}),
            )
            result = self._run_finalization.finalize_run(
                command_id=data["command_id"],
                import_run_id=path_parameters["import_run_id"],
                expected_run_revision=data["run_revision"],
            )
            result_body = {
                "import_run_id": result.import_run_id,
                "state": result.state,
                "revision": result.revision,
                "checkpoint": dict(result.checkpoint),
            }

        elif handler == "ResolveImportRecovery":
            data = _body_data(
                body,
                allowed=frozenset(
                    {"command_id", "review_fingerprint", "decision", "reason_category"}
                ),
                required=frozenset(
                    {"command_id", "review_fingerprint", "decision", "reason_category"}
                ),
            )
            result = self._recovery.resolve(
                command_id=data["command_id"],
                import_run_id=path_parameters["import_run_id"],
                review_fingerprint=data["review_fingerprint"],
                decision=data["decision"],
                reason_category=data["reason_category"],
            )
            result_body = {
                "import_run_id": result.import_run_id,
                "decision": result.decision,
                "review_ordinal": result.review_ordinal,
                "run_state": result.run_state,
            }

        else:
            raise IntegrityFailure("LLD-04 public command route has no command-service dispatch authority")

        return self._response(resolved, result_body)


__all__ = ["TicketImportMutationRouteAdapter"]
