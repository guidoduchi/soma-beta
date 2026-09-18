from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.ticket_import.parsing.sr_candidates import extract_sr_candidates
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .wfm_service_provider import _SourceObservation, _field, _proposal_fingerprint


def _accepted_rfc_summary_has_existing_sr_candidate(
    reader: Any,
    *,
    rfc_id: str,
) -> bool:
    projection = RfcImportReader().current_source_projection(reader, rfc_id)
    if projection is None:
        return False
    summary = projection.get("summary_text")
    if summary is None:
        return False
    if not isinstance(summary, str):
        raise IntegrityFailure("accepted RFC Summary authority is not text")
    sr_reader = ServiceRequestImportReader()
    return any(
        sr_reader.get_by_official(reader, candidate.official_sr_no) is not None
        for candidate in extract_sr_candidates(summary)
    )


def build_wfm_task_name_sr_link_proposals(
    reader: Any,
    *,
    source: _SourceObservation,
) -> tuple[ReconciliationProposalDraft, ...]:
    target = RfcImportReader().get_by_number(reader, source.canonical_parent_rfc_no)
    if target is None:
        return ()
    rfc_id = target.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("WFM SR-link fallback resolved invalid RFC identity")
    if _accepted_rfc_summary_has_existing_sr_candidate(reader, rfc_id=rfc_id):
        return ()

    task_name = _field(source, "task_name")
    if task_name is None or task_name.value_state != "usable":
        return ()
    if (
        task_name.field_class != "active"
        or task_name.value_kind != "text"
        or task_name.normalized_text is None
        or task_name.integer_value is not None
    ):
        raise IntegrityFailure("usable WFM Task Name has invalid text authority")

    sr_reader = ServiceRequestImportReader()
    proposals: list[ReconciliationProposalDraft] = []
    for candidate in extract_sr_candidates(task_name.normalized_text):
        sr = sr_reader.get_by_official(reader, candidate.official_sr_no)
        if sr is None:
            continue
        service_request_id = sr.get("service_request_id")
        if not isinstance(service_request_id, str):
            raise IntegrityFailure("WFM Task Name candidate resolved invalid Service Request identity")
        context = RfcImportMutationService.sr_link_candidate_context(
            reader,
            service_request_id,
            rfc_id,
        )
        if context.duplicate_active:
            continue

        change = ProposalChangeDraft(
            ordinal=0,
            field_key="service_request_id",
            change_kind="candidate",
            value_kind="identity",
            before_text=None,
            after_text=service_request_id,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=task_name.source_observation_field_id,
        )
        proposal_identity = {
            "proposal_kind": "sr_rfc_link_candidate",
            "evidence_mode": "observed_row",
            "risk_class": context.risk_class,
            "target_kind": "sr_rfc_relationship",
            "target_internal_id": rfc_id,
            "target_business_id": source.canonical_parent_rfc_no,
            "candidate_service_request_id": service_request_id,
            "candidate_official_sr_no": candidate.official_sr_no,
            "candidate_source": "wfm_task_name_fallback",
        }
        proposals.append(
            ReconciliationProposalDraft(
                import_run_id=source.import_run_id,
                evidence_mode="observed_row",
                source_observation_id=source.source_observation_id,
                proposal_kind="sr_rfc_link_candidate",
                target_kind="sr_rfc_relationship",
                target_internal_id=rfc_id,
                target_business_id=source.canonical_parent_rfc_no,
                risk_class=context.risk_class,
                base_state_token_sha256=context.base_state_token,
                proposal_fingerprint_sha256=_proposal_fingerprint(
                    source=source,
                    proposal_identity=proposal_identity,
                    changes=(change,),
                ),
                changes=(change,),
            )
        )
    return tuple(proposals)


__all__ = [
    "build_wfm_task_name_sr_link_proposals",
    "_accepted_rfc_summary_has_existing_sr_candidate",
]
