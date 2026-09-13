from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.import_mutations import ServiceRequestSourceProjectionMutation
from soma.tickets.sr_source_projection import AcceptedSrFieldDeltaSet

from ._proposal_decision_core import *  # noqa: F401,F403
from ._proposal_decision_core import (
    _TERMINAL_SR_STATUSES,
    ProposalDecisionService as _CoreProposalDecisionService,
)


class ProposalDecisionService(_CoreProposalDecisionService):
    """Public proposal-decision service with the certified SR field-set freshness repair."""

    def _prepare_sr_source_projection_accept(
        self,
        uow: UnitOfWork,
        *,
        proposal: ProposalRecord,
        run: Any,
        base_token: str,
        proposal_revision: int,
        command_id: str,
        reason: str | None,
        actor_kind: str,
        actor_id: str | None,
        precedence_basis: str = "source_chronology",
    ) -> PreparedMutation:
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "service_request"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection proposal binding is incomplete")
        target_identity = uow.connection.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (proposal.target_internal_id,),
        ).fetchone()
        if (
            target_identity is None
            or target_identity[0] is None
            or str(target_identity[0]) != proposal.target_business_id
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal target identity no longer matches the Service Request")

        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if not changes or len(changes) > 11:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection change set is empty or exceeds field registry")
        if len({change.field_key for change in changes}) != len(changes):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection proposal repeats a field")
        field_keys = tuple(change.field_key for change in changes)
        try:
            current_base = self._sr_import_mutations.source_field_set_base_token(
                uow.connection,
                proposal.target_internal_id,
                field_keys,
            )
        except ValidationError as exc:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection field-set scope is invalid") from exc
        except SomaError as exc:
            if exc.code == "NOT_FOUND":
                raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request target no longer exists") from exc
            raise
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request source field-set base state changed")

        if precedence_basis == "reviewed_correction":
            self._require_reviewed_source_correction_shape(
                uow.connection,
                proposal=proposal,
                changes=changes,
            )
        elif precedence_basis == "source_chronology":
            terminal_entries = [
                change
                for change in changes
                if change.field_key == "status" and change.after_text in _TERMINAL_SR_STATUSES
            ]
            if terminal_entries and (proposal.risk_class != "high" or len(changes) != 1):
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "terminal SR source entry must remain one high-risk Status proposal",
                )
        else:
            raise IntegrityFailure("unsupported SR source projection precedence basis")

        deltas = []
        for change in changes:
            if change.source_observation_field_id is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection change lacks source field evidence")
            deltas.append(
                self._sr_source_provider.build_source_projection_delta(
                    uow.connection,
                    service_request_id=proposal.target_internal_id,
                    expected_import_run_id=proposal.import_run_id,
                    expected_source_observation_id=proposal.source_observation_id,
                    source_observation_field_id=change.source_observation_field_id,
                    field_key=change.field_key,
                    change_kind=change.change_kind,
                    change_value_kind=change.value_kind,
                    after_text=change.after_text,
                    after_integer=change.after_integer,
                    precedence_basis=precedence_basis,
                )
            )

        disposition_id = new_uuid4()
        audit_event_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = ServiceRequestSourceProjectionMutation(
            service_request_id=proposal.target_internal_id,
            base_state_token=base_token,
            accepted_delta_set=AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=tuple(deltas),
            ),
        )

        def apply(inner: UnitOfWork):
            owner_result = self._sr_import_mutations.apply_accepted_source_projection(inner, mutation)
            self._repository.transition_accept(
                inner,
                proposal=proposal,
                run=run,
                decided_at_utc=decided_at,
                disposition_id=disposition_id,
                reason_category=reason,
                command_id=command_id,
            )
            return self._orchestration_audit(
                audit_event_id=audit_event_id,
                command_id=command_id,
                proposal=proposal,
                proposal_revision=proposal_revision,
                reason=reason,
                actor_kind=actor_kind,
                actor_id=actor_id,
                disposition_id=disposition_id,
                owner_result_refs=owner_result.result_refs,
            )

        return PreparedMutation(
            False,
            "reconciliation_proposal",
            proposal.proposal_id,
            apply,
            response_schema="ProposalDecisionResultV1",
            response_factory=lambda inner: self._decision_response(
                inner,
                proposal_id=proposal.proposal_id,
                command_id=command_id,
            ),
        )
