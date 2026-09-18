from __future__ import annotations

from dataclasses import replace
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.objectives_tasks.services.wfm_import_reassignment import WfmImportParentReassignmentParticipant
from soma.tickets.rfc_wfm_provisional import RfcWfmProvisionalEligibilityService

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .wfm_sr_link import build_wfm_task_name_sr_link_proposals
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


def _deferred_wfm_create_proposal(reader: Any, *, source) -> ReconciliationProposalDraft:
    _status_token, lifecycle, _status_field = _lifecycle_from_source(source)
    changes = (
        ProposalChangeDraft(
            ordinal=0,
            field_key="task_no",
            change_kind="create",
            value_kind="identity",
            before_text=None,
            after_text=source.canonical_task_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
        ProposalChangeDraft(
            ordinal=1,
            field_key="rfc_no",
            change_kind="link",
            value_kind="identity",
            before_text=None,
            after_text=source.canonical_parent_rfc_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
    )
    base_token = WfmImportReader.source_acceptance_base_token(
        reader,
        WfmImportBaseTarget("wfm_create_or_adopt", source.canonical_task_no, None),
    )
    identity = {
        "proposal_kind": "wfm_create_or_adopt",
        "evidence_mode": "observed_row",
        "risk_class": "medium",
        "target_kind": "wfm",
        "target_internal_id": None,
        "target_business_id": source.canonical_task_no,
        "parent_rfc_no": source.canonical_parent_rfc_no,
        "source_lifecycle_class": lifecycle,
        "parent_identity_deferred": True,
    }
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="wfm_create_or_adopt",
        target_kind="wfm",
        target_internal_id=None,  # type: ignore[arg-type]
        target_business_id=source.canonical_task_no,
        risk_class="medium",
        base_state_token_sha256=base_token,
        proposal_fingerprint_sha256=_proposal_fingerprint(
            source=source,
            proposal_identity=identity,
            changes=changes,
        ),
        changes=changes,
    )


def _parent_reassignment_proposal(
    reader: Any,
    *,
    source,
    task_id: str,
    new_rfc_id: str,
) -> ReconciliationProposalDraft:
    identity = WfmImportReader.get_by_task_no(reader, source.canonical_task_no)
    if identity is None or identity.get("task_id") != task_id:
        raise IntegrityFailure("WFM parent reassignment target identity changed during proposal composition")
    prior_rfc_id = identity.get("current_rfc_id")
    if not isinstance(prior_rfc_id, str) or prior_rfc_id == new_rfc_id:
        raise IntegrityFailure("WFM parent reassignment proposal lacks a distinct current parent")
    prior = reader.execute("SELECT rfc_no FROM rfcs WHERE rfc_id=?", (prior_rfc_id,)).fetchone()
    target = reader.execute("SELECT rfc_no FROM rfcs WHERE rfc_id=?", (new_rfc_id,)).fetchone()
    if prior is None or target is None:
        raise IntegrityFailure("WFM parent reassignment RFC identity authority disappeared")
    prior_rfc_no = str(prior[0])
    new_rfc_no = str(target[0])
    if new_rfc_no != source.canonical_parent_rfc_no:
        raise IntegrityFailure("WFM parent reassignment target RFC does not match source evidence")

    changes = (
        ProposalChangeDraft(
            ordinal=0,
            field_key="task_no",
            change_kind="adopt",
            value_kind="identity",
            before_text=source.canonical_task_no,
            after_text=source.canonical_task_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
        ProposalChangeDraft(
            ordinal=1,
            field_key="rfc_no",
            change_kind="set",
            value_kind="identity",
            before_text=prior_rfc_no,
            after_text=new_rfc_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
    )
    base_token = WfmImportParentReassignmentParticipant.base_state_token(
        reader,
        task_no=source.canonical_task_no,
        task_id=task_id,
        new_rfc_id=new_rfc_id,
    )
    proposal_identity = {
        "proposal_kind": "wfm_create_or_adopt",
        "evidence_mode": "observed_row",
        "risk_class": "high",
        "target_kind": "wfm",
        "target_internal_id": task_id,
        "target_business_id": source.canonical_task_no,
        "prior_rfc_no": prior_rfc_no,
        "new_rfc_no": new_rfc_no,
    }
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="wfm_create_or_adopt",
        target_kind="wfm",
        target_internal_id=task_id,
        target_business_id=source.canonical_task_no,
        risk_class="high",
        base_state_token_sha256=base_token,
        proposal_fingerprint_sha256=_proposal_fingerprint(
            source=source,
            proposal_identity=proposal_identity,
            changes=changes,
        ),
        changes=changes,
    )


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

    if base.scope_status in {"conflict", "equivalent_duplicate_suppressed"} or base.task_no_status == "RETIRED":
        return base

    source = _load_source_observation(
        reader,
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    if source.canonical_task_no != base.canonical_task_no or source.canonical_parent_rfc_no != base.canonical_parent_rfc_no:
        raise IntegrityFailure("WFM reconciliation source identity changed during proposal composition")

    proposals = list(base.proposals)
    state = base.resolution_state
    if base.resolution_state == "parent_rfc_review":
        if base.task_no_status != "ABSENT":
            raise IntegrityFailure("missing-parent WFM create review requires absent Task No authority")
        proposals.append(_deferred_wfm_create_proposal(reader, source=source))
        state = "parent_rfc_and_wfm_create_review"
    elif base.resolution_state == "parent_rfc_review_required":
        if base.task_id is None or base.rfc_id is None:
            raise IntegrityFailure("WFM parent reassignment review is missing exact Task/RFC targets")
        proposals.append(
            _parent_reassignment_proposal(
                reader,
                source=source,
                task_id=base.task_id,
                new_rfc_id=base.rfc_id,
            )
        )
        state = "parent_rfc_adoption_review"

    sr_links = build_wfm_task_name_sr_link_proposals(reader, source=source)
    proposals.extend(sr_links)
    if sr_links:
        if state == "no_source_change":
            state = "sr_link_review"
        else:
            state = f"{state}_and_sr_link_review"

    eligibility = _provisional_eligibility_proposal(
        reader,
        source=source,
        rfc_id=base.rfc_id,
    )
    if eligibility is not None:
        proposals.append(eligibility)
        if state == "parent_rfc_and_wfm_create_review":
            state = "parent_rfc_wfm_create_and_eligibility_review"
        elif state == "parent_rfc_adoption_review":
            state = "parent_rfc_adoption_and_eligibility_review"
        elif state == "create_review":
            state = "create_and_eligibility_review"
        elif state == "source_review":
            state = "source_and_eligibility_review"
        elif state == "no_source_change":
            state = "eligibility_review"

    if tuple(proposals) == base.proposals and state == base.resolution_state:
        return base
    return replace(base, resolution_state=state, proposals=tuple(proposals))
