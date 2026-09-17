from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.tickets.rfc_import_reader import RfcImportReader

from ..providers.wfm_competing_attempt_evidence import TicketImportWfmCompetingAttemptEvidenceProvider
from .engine import (
    ProposalChangeDraft,
    ReconciliationProposalDraft,
    _proposal_source_authority,
    build_wfm_competing_attempt_review_proposal,
)

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"


def build_wfm_plan_reconciliation_proposal(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
    wfm_reader: type[WfmImportReader] = WfmImportReader,
    evidence_provider: TicketImportWfmCompetingAttemptEvidenceProvider | None = None,
) -> ReconciliationProposalDraft | None:
    evidence_authority = (
        TicketImportWfmCompetingAttemptEvidenceProvider()
        if evidence_provider is None
        else evidence_provider
    )
    evidence = evidence_authority.load_exact(
        reader,
        expected_import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    rfc_authority = RfcImportReader() if rfc_reader is None else rfc_reader
    rfc = rfc_authority.get_by_number(reader, evidence.parent_rfc_no)
    if rfc is None:
        return None
    rfc_id = rfc.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid WFM plan-review identity")
    canonical_rfc_id = require_uuid4(rfc_id)

    if wfm_reader.task_no_status(reader, evidence.task_no) != "ACTIVE":
        return None
    identity = wfm_reader.get_by_task_no(reader, evidence.task_no)
    if identity is None:
        raise IntegrityFailure("ACTIVE WFM plan-review target lacks identity authority")
    task_id = identity.get("task_id")
    current_rfc_id = identity.get("current_rfc_id")
    if not isinstance(task_id, str):
        raise IntegrityFailure("WFM import reader returned invalid plan-review Task identity")
    canonical_task_id = require_uuid4(task_id)
    if current_rfc_id != canonical_rfc_id:
        return None

    source = wfm_reader.source_projection(reader, canonical_task_id)
    if source is None:
        return None
    if (
        source.get("accepted_source_observation_id") != evidence.source_observation_id
        or source.get("source_plan_start_utc") != evidence.planned_start_utc
        or source.get("source_plan_end_utc") != evidence.planned_end_utc
    ):
        return None
    source_revision = source.get("source_projection_revision")
    if type(source_revision) is not int or source_revision <= 0:
        raise IntegrityFailure("accepted WFM source-plan revision is invalid")

    operational = wfm_reader.operational_plan_context(reader, canonical_task_id)
    before_start: int | None = None
    before_end: int | None = None
    if operational is not None:
        start = operational.get("start_utc")
        end = operational.get("end_utc")
        revision = operational.get("revision")
        if (
            type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
            or type(revision) is not int
            or revision <= 0
        ):
            raise IntegrityFailure("current WFM operational-plan authority is invalid")
        before_start = start
        before_end = end
    if before_start == evidence.planned_start_utc and before_end == evidence.planned_end_utc:
        return None

    base_token = wfm_reader.source_acceptance_base_token(
        reader,
        WfmImportBaseTarget("wfm_plan_reconciliation", evidence.task_no, canonical_task_id),
    )
    changes = (
        ProposalChangeDraft(
            ordinal=0,
            field_key="planned_start",
            change_kind="set",
            value_kind="instant",
            before_text=None,
            after_text=None,
            before_integer=before_start,
            after_integer=evidence.planned_start_utc,
            source_observation_field_id=evidence.planned_start_field_id,
        ),
        ProposalChangeDraft(
            ordinal=1,
            field_key="planned_end",
            change_kind="set",
            value_kind="instant",
            before_text=None,
            after_text=None,
            before_integer=before_end,
            after_integer=evidence.planned_end_utc,
            source_observation_field_id=evidence.planned_end_field_id,
        ),
    )
    proposal_identity = {
        "proposal_kind": "wfm_plan_reconciliation",
        "evidence_mode": "observed_row",
        "risk_class": "high",
        "target_kind": "task_plan",
        "target_internal_id": canonical_task_id,
        "target_business_id": evidence.task_no,
    }
    source_authority = _proposal_source_authority(
        reader,
        import_run_id=require_uuid4(import_run_id),
        source_observation_id=require_uuid4(source_observation_id),
        task_no=evidence.task_no,
        parent_rfc_no=evidence.parent_rfc_no,
    )
    proposal_fingerprint = sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": source_authority,
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object() for change in changes],
        }
    )
    return ReconciliationProposalDraft(
        import_run_id=require_uuid4(import_run_id),
        evidence_mode="observed_row",
        source_observation_id=require_uuid4(source_observation_id),
        proposal_kind="wfm_plan_reconciliation",
        target_kind="task_plan",
        target_internal_id=canonical_task_id,
        target_business_id=evidence.task_no,
        risk_class="high",
        base_state_token_sha256=base_token,
        proposal_fingerprint_sha256=proposal_fingerprint,
        changes=changes,
    )


def build_wfm_follow_on_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
) -> tuple[ReconciliationProposalDraft, ...]:
    plan = build_wfm_plan_reconciliation_proposal(
        reader,
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    competing = build_wfm_competing_attempt_review_proposal(
        reader,
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    return tuple(proposal for proposal in (plan, competing) if proposal is not None)


__all__ = [
    "build_wfm_follow_on_proposals",
    "build_wfm_plan_reconciliation_proposal",
]
