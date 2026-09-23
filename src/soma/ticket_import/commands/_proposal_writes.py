from __future__ import annotations

from ..reconciliation.engine import ReconciliationProposalDraft
from ..repositories.proposals import PendingProposalWrite, ProposalChangeRecord


def pending_write_from_draft(draft: ReconciliationProposalDraft) -> PendingProposalWrite:
    """Project one observed-row proposal draft into the repository write contract."""
    return PendingProposalWrite(
        import_run_id=draft.import_run_id,
        evidence_mode=draft.evidence_mode,
        source_observation_id=draft.source_observation_id,
        prior_source_observation_id=None,
        proposal_kind=draft.proposal_kind,
        target_kind=draft.target_kind,
        target_internal_id=draft.target_internal_id,
        target_business_id=draft.target_business_id,
        risk_class=draft.risk_class,
        base_state_token=draft.base_state_token_sha256,
        proposal_fingerprint=draft.proposal_fingerprint_sha256,
        changes=tuple(
            ProposalChangeRecord(
                ordinal=change.ordinal,
                field_key=change.field_key,
                change_kind=change.change_kind,
                value_kind=change.value_kind,
                before_text=change.before_text,
                after_text=change.after_text,
                before_integer=change.before_integer,
                after_integer=change.after_integer,
                source_observation_field_id=change.source_observation_field_id,
            )
            for change in draft.changes
        ),
    )


__all__ = ["pending_write_from_draft"]
