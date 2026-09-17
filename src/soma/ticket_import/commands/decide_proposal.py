from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.audit_registry import build_objectives_tasks_audit_registry

from ._proposal_decision_rfc_sr import *  # noqa: F401,F403
from ._proposal_decision_rfc_sr import ProposalDecisionService as _RfcSrProposalDecisionService
from ._proposal_decision_core import (
    _REVIEWED_SR_SOURCE_CORRECTION_KINDS,
    _SR_CONTACT_PROPOSAL_ROLES,
    _build_acceptance_audit_registry,
    _validate_fingerprint,
    _validate_optional_reason,
)
from ._wfm_create_or_adopt_acceptance import prepare_wfm_create_or_adopt_accept
from ._wfm_proposal_acceptance import (
    prepare_wfm_provisional_rfc_accept,
    prepare_wfm_source_projection_accept,
)
from ._wfm_provisional_eligibility_acceptance import prepare_wfm_provisional_eligibility_accept


class ProposalDecisionService(_RfcSrProposalDecisionService):
    """Single LLD-04 proposal-decision authority extended with reviewed WFM owners."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        registry = _build_acceptance_audit_registry()
        registry.extend(build_objectives_tasks_audit_registry())
        self._boundary = CommandBoundary(self._factory, AuditWriter(registry))

    def accept(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        base_state_token: str,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ProposalDecisionResult:
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be a positive integer")
        fingerprint = _validate_fingerprint(proposal_fingerprint)
        base_token = _validate_fingerprint(base_state_token, field_name="base_state_token")
        reason = _validate_optional_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            target_type="reconciliation_proposal",
            target_id=proposal_id,
            semantic_payload={
                "decision": "accepted",
                "proposal_revision": proposal_revision,
                "proposal_fingerprint": fingerprint,
                "base_state_token": base_token,
                "reason_category": reason,
            },
            base_revisions={"proposal": proposal_revision},
            authorizing_fingerprints={"proposal": fingerprint, "base_state": base_token},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._repository.require_pending(uow.connection, proposal_id)
            if (
                proposal.revision != proposal_revision
                or not hmac.compare_digest(proposal.proposal_fingerprint, fingerprint)
                or not hmac.compare_digest(proposal.base_state_token, base_token)
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal revision/fingerprint/base state changed")
            if proposal.risk_class == "blocked":
                raise SomaError("IMPORT_PROPOSAL_BLOCKED", "blocked reconciliation proposal cannot be accepted")
            run = self._repository.get_run(uow.connection, proposal.import_run_id)
            if run.run_state not in {"staged", "waiting_review", "recovery_required"}:
                raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run no longer permits proposal acceptance")
            self._repository.require_current_recovery_authorization(uow.connection, run)

            if proposal.proposal_kind == "rfc_create_or_adopt":
                return self._prepare_rfc_create_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "rfc_source_projection":
                return self._prepare_rfc_source_projection_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "rfc_customer_reconciliation":
                return self._prepare_rfc_customer_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "sr_rfc_link_candidate":
                return self._prepare_rfc_sr_link_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "wfm_provisional_rfc":
                return prepare_wfm_provisional_rfc_accept(
                    self, uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "wfm_provisional_eligibility":
                return prepare_wfm_provisional_eligibility_accept(
                    self, uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "wfm_create_or_adopt":
                return prepare_wfm_create_or_adopt_accept(
                    self, uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "wfm_source_projection":
                return prepare_wfm_source_projection_accept(
                    self, uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "sr_create_or_adopt":
                return self._prepare_sr_create_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "sr_source_projection":
                return self._prepare_sr_source_projection_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind in _REVIEWED_SR_SOURCE_CORRECTION_KINDS:
                return self._prepare_sr_source_projection_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id, precedence_basis="reviewed_correction",
                )
            if proposal.proposal_kind == "sr_customer_reconciliation":
                return self._prepare_sr_customer_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind in _SR_CONTACT_PROPOSAL_ROLES:
                return self._prepare_sr_contact_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            if proposal.proposal_kind == "sr_source_disappearance_review":
                return self._prepare_sr_disappearance_accept(
                    uow, proposal=proposal, run=run, base_token=base_token,
                    proposal_revision=proposal_revision, command_id=command_id, reason=reason,
                    actor_kind=actor_kind, actor_id=actor_id,
                )
            raise SomaError(
                "IMPORT_PROPOSAL_BLOCKED",
                "proposal kind has no implemented owning-domain acceptance participant",
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))
