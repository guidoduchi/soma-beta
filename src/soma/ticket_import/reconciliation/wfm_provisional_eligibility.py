from __future__ import annotations

from dataclasses import replace
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.tickets.rfc_wfm_provisional import RfcWfmProvisionalEligibilityService

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .wfm_service_provider import (
    WfmServiceProviderProposalBuildResult,
    _field,
    _lifecycle_from_source,
    _load_source_observation,
    _proposal_fingerprint,
    build_wfm_service_provider_proposals as _build_base_wfm_proposals,
)

_RFC_STATUS_VOCABULARY = "RFC_STATUS_V1"
_TERMINAL_RFC_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})


def _provisional_eligibility_proposal(
    reader: Any,
    *,
    source,
    rfc_id: str | None,
) -> ReconciliationProposalDraft | None:
    _task_status_token, task_lifecycle, _task_status_field = _lifecycle_from_source(source)
    if task_lifecycle != "active":
        return None

    rfc_status = _field(source, "rfc_status")
    if rfc_status is None:
        return None
    if (
        rfc_status.field_class != "active"
        or rfc_status.value_state != "usable"
        or rfc_status.value_kind != "controlled"
        or rfc_status.vocabulary_id != _RFC_STATUS_VOCABULARY
        or rfc_status.normalized_text != "Implement"
    ):
        return None

    before_status: str | None = None
    if rfc_id is not None:
        current = reader.execute(
            "SELECT status_text,status_class,status_authority FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if current is not None:
            status_text = None if current[0] is None else str(current[0])
            status_class = str(current[1])
            status_authority = None if current[2] is None else str(current[2])
            if status_authority == "enhanced_rfc":
                return None
            if status_class in _TERMINAL_RFC_STATUS_CLASSES:
                return None
            if status_class == "implement_eligible" and status_authority == "wfm_provisional":
                return None
            before_status = status_text

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="status",
        change_kind="set",
        value_kind="controlled",
        before_text=before_status,
        after_text="Implement",
        before_integer=None,
        after_integer=None,
        source_observation_field_id=rfc_status.source_observation_field_id,
    )
    base_token = RfcWfmProvisionalEligibilityService.base_state_token(
        reader,
        source.canonical_parent_rfc_no,
    )
    identity = {
        "proposal_kind": "wfm_provisional_eligibility",
        "evidence_mode": "observed_row",
        "risk_class": "high",
        "target_kind": "rfc",
        "target_internal_id": rfc_id,
        "target_business_id": source.canonical_parent_rfc_no,
        "wfm_task_no": source.canonical_task_no,
        "status_authority": "wfm_provisional",
    }
    changes = (change,)
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="wfm_provisional_eligibility",
        target_kind="rfc",
        target_internal_id=rfc_id,  # type: ignore[arg-type]
        target_business_id=source.canonical_parent_rfc_no,
        risk_class="high",
        base_state_token_sha256=base_token,
        proposal_fingerprint_sha256=_proposal_fingerprint(
            source=source,
            proposal_identity=identity,
            changes=changes,
        ),
        changes=changes,
    )


def build_wfm_service_provider_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    wfm_reader=None,
    rfc_reader=None,
) -> WfmServiceProviderProposalBuildResult:
    kwargs: dict[str, object] = {
        "import_run_id": import_run_id,
        "source_observation_id": source_observation_id,
    }
    if wfm_reader is not None:
        kwargs["wfm_reader"] = wfm_reader
    if rfc_reader is not None:
        kwargs["rfc_reader"] = rfc_reader
    base = _build_base_wfm_proposals(reader, **kwargs)

    if base.scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return base
    if base.task_no_status == "RETIRED" or base.resolution_state == "parent_rfc_review_required":
        return base

    source = _load_source_observation(
        reader,
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    if source.canonical_task_no != base.canonical_task_no or source.canonical_parent_rfc_no != base.canonical_parent_rfc_no:
        raise IntegrityFailure("WFM provisional eligibility source identity changed during proposal composition")

    eligibility = _provisional_eligibility_proposal(
        reader,
        source=source,
        rfc_id=base.rfc_id,
    )
    if eligibility is None:
        return base

    proposals = (*base.proposals, eligibility)
    if base.resolution_state == "parent_rfc_review":
        state = "parent_rfc_and_eligibility_review"
    elif base.resolution_state == "create_review":
        state = "create_and_eligibility_review"
    elif base.resolution_state == "source_review":
        state = "source_and_eligibility_review"
    elif base.resolution_state == "no_source_change":
        state = "eligibility_review"
    else:
        state = base.resolution_state
    return replace(base, resolution_state=state, proposals=proposals)
