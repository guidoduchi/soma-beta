from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.services.wfm_import import WfmImportReader
from soma.objectives_tasks.services.wfm_import_reassignment import (
    WfmImportParentReassignmentParticipant,
    WfmParentReassignmentFromSourceMutation,
)
from soma.ticket_import.providers.wfm_review_evidence import _load_published_source
from soma.ticket_import.reconciliation.wfm_service_provider import _lifecycle_from_source
from soma.tickets.rfc_import_reader import RfcImportReader

from ._wfm_proposal_acceptance import prepare_wfm_create_accept
from ..repositories.proposals import ProposalRecord


def _require_current_parent_business_id(reader: Any, rfc_id: str) -> str:
    row = reader.execute("SELECT rfc_no FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone()
    if row is None:
        raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM current parent RFC disappeared")
    return str(row[0])


def prepare_wfm_create_or_adopt_accept(
    service: Any,
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
) -> PreparedMutation:
    if proposal.target_internal_id is None:
        if proposal.source_observation_id is None or proposal.target_business_id is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM creation proposal binding is invalid")
        source = _load_published_source(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            expected_source_observation_id=proposal.source_observation_id,
        )
        if source.canonical_task_no != proposal.target_business_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM creation identity changed")
        target = RfcImportReader().get_by_number(uow.connection, source.canonical_parent_rfc_no)
        if target is None or not isinstance(target.get("rfc_id"), str):
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM parent RFC has not been accepted")
        _status_token, lifecycle, _status_field = _lifecycle_from_source(source)
        WfmImportParentReassignmentParticipant.require_import_eligible_rfc(
            uow.connection,
            rfc_id=str(target["rfc_id"]),
            source_lifecycle_class=lifecycle,
        )
        return prepare_wfm_create_accept(
            service,
            uow,
            proposal=proposal,
            run=run,
            base_token=base_token,
            proposal_revision=proposal_revision,
            command_id=command_id,
            reason=reason,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    if (
        proposal.evidence_mode != "observed_row"
        or proposal.source_observation_id is None
        or proposal.target_kind != "wfm"
        or proposal.target_business_id is None
        or proposal.risk_class != "high"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM adoption proposal binding is invalid")
    source = _load_published_source(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
    )
    if source.canonical_task_no != proposal.target_business_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM adoption Task No changed")
    identity = WfmImportReader.get_by_task_no(uow.connection, proposal.target_business_id)
    if identity is None or identity.get("task_id") != proposal.target_internal_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM adoption target identity changed")
    current_rfc_id = identity.get("current_rfc_id")
    if not isinstance(current_rfc_id, str):
        raise IntegrityFailure("WFM import reader returned invalid current parent identity")
    target = RfcImportReader().get_by_number(uow.connection, source.canonical_parent_rfc_no)
    if target is None or not isinstance(target.get("rfc_id"), str):
        raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM adoption parent RFC disappeared")
    new_rfc_id = str(target["rfc_id"])
    if current_rfc_id == new_rfc_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM adoption no longer changes parent RFC")

    current_rfc_no = _require_current_parent_business_id(uow.connection, current_rfc_id)
    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != 2:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM adoption requires exact Task and RFC identity changes")
    task_change, rfc_change = changes
    if (
        task_change.ordinal != 0
        or task_change.field_key != "task_no"
        or task_change.change_kind != "adopt"
        or task_change.value_kind != "identity"
        or task_change.before_text != proposal.target_business_id
        or task_change.after_text != proposal.target_business_id
        or task_change.before_integer is not None
        or task_change.after_integer is not None
        or task_change.source_observation_field_id is not None
        or rfc_change.ordinal != 1
        or rfc_change.field_key != "rfc_no"
        or rfc_change.change_kind != "set"
        or rfc_change.value_kind != "identity"
        or rfc_change.before_text != current_rfc_no
        or rfc_change.after_text != source.canonical_parent_rfc_no
        or rfc_change.before_integer is not None
        or rfc_change.after_integer is not None
        or rfc_change.source_observation_field_id is not None
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM adoption proposal encoding changed")

    _status_token, lifecycle, _status_field = _lifecycle_from_source(source)
    current_base = WfmImportParentReassignmentParticipant.base_state_token(
        uow.connection,
        task_no=proposal.target_business_id,
        task_id=proposal.target_internal_id,
        new_rfc_id=new_rfc_id,
    )
    if not hmac.compare_digest(current_base, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM adoption base state changed")
    WfmImportParentReassignmentParticipant.require_import_eligible_rfc(
        uow.connection,
        rfc_id=new_rfc_id,
        source_lifecycle_class=lifecycle,
    )

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    mutation = WfmParentReassignmentFromSourceMutation(
        task_id=proposal.target_internal_id,
        task_no=proposal.target_business_id,
        new_rfc_id=new_rfc_id,
        source_lifecycle_class=lifecycle,
        base_state_token=base_token,
        accepted_command_id=command_id,
        reason_category=reason or "wfm_source_parent_correction",
        actor_kind=actor_kind,
        actor_id=actor_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = WfmImportParentReassignmentParticipant.reassign_parent_from_source(inner, mutation)
        service._repository.transition_accept(
            inner,
            proposal=proposal,
            run=run,
            decided_at_utc=decided_at,
            disposition_id=disposition_id,
            reason_category=reason,
            command_id=command_id,
        )
        orchestration = service._orchestration_audit(
            audit_event_id=orchestration_audit_id,
            command_id=command_id,
            proposal=proposal,
            proposal_revision=proposal_revision,
            reason=reason,
            actor_kind=actor_kind,
            actor_id=actor_id,
            disposition_id=disposition_id,
            owner_result_refs=owner_result.result_refs,
        )
        return (*owner_result.audit_events, orchestration)

    return PreparedMutation(
        False,
        "reconciliation_proposal",
        proposal.proposal_id,
        apply,
        response_schema="ProposalDecisionResultV1",
        response_factory=lambda inner: service._decision_response(
            inner,
            proposal_id=proposal.proposal_id,
            command_id=command_id,
        ),
    )
