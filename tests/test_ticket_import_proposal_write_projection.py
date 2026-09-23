from __future__ import annotations

from soma.ticket_import.commands._proposal_writes import pending_write_from_draft
from soma.ticket_import.reconciliation.engine import (
    ProposalChangeDraft,
    ReconciliationProposalDraft,
)


def test_pending_write_projection_preserves_exact_draft_fields() -> None:
    draft = ReconciliationProposalDraft(
        import_run_id="11111111-1111-4111-8111-111111111111",
        evidence_mode="observed_row",
        source_observation_id="22222222-2222-4222-8222-222222222222",
        proposal_kind="rfc_create_or_adopt",
        target_kind="rfc",
        target_internal_id="33333333-3333-4333-8333-333333333333",
        target_business_id="NC20260922000001",
        risk_class="medium",
        base_state_token_sha256="a" * 64,
        proposal_fingerprint_sha256="b" * 64,
        changes=(
            ProposalChangeDraft(
                ordinal=0,
                field_key="rfc_no",
                change_kind="create",
                value_kind="identity",
                before_text=None,
                after_text="NC20260922000001",
                before_integer=None,
                after_integer=None,
                source_observation_field_id=None,
            ),
        ),
    )

    write = pending_write_from_draft(draft)
    assert write.import_run_id == draft.import_run_id
    assert write.evidence_mode == "observed_row"
    assert write.source_observation_id == draft.source_observation_id
    assert write.prior_source_observation_id is None
    assert write.proposal_kind == draft.proposal_kind
    assert write.target_kind == draft.target_kind
    assert write.target_internal_id == draft.target_internal_id
    assert write.target_business_id == draft.target_business_id
    assert write.risk_class == draft.risk_class
    assert write.base_state_token == draft.base_state_token_sha256
    assert write.proposal_fingerprint == draft.proposal_fingerprint_sha256
    assert len(write.changes) == 1
    assert write.changes[0].field_key == "rfc_no"
    assert write.changes[0].after_text == "NC20260922000001"
