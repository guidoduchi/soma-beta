from __future__ import annotations

from typing import Any

from .engine import ReconciliationProposalDraft
from .rfc_enhanced import build_rfc_enhanced_source_projection_proposals
from .rfc_enhanced_customer import build_rfc_enhanced_customer_reconciliation_proposals
from .rfc_enhanced_sr_link import build_rfc_enhanced_sr_link_candidate_proposals

_PUBLISHED_REVIEW_STATES = frozenset({"waiting_review", "recovery_required"})


def build_rfc_identity_follow_on_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
) -> tuple[ReconciliationProposalDraft, ...]:
    """Build RFC reviews that become possible only after exact RFC identity acceptance."""
    kwargs = {
        "import_run_id": import_run_id,
        "source_observation_id": source_observation_id,
        "allowed_run_states": _PUBLISHED_REVIEW_STATES,
    }
    projection = build_rfc_enhanced_source_projection_proposals(reader, **kwargs)
    customer = build_rfc_enhanced_customer_reconciliation_proposals(reader, **kwargs)
    sr_links = build_rfc_enhanced_sr_link_candidate_proposals(reader, **kwargs)

    drafts = (
        *projection.proposals,
        *customer.proposals,
        *sr_links.proposals,
    )
    return tuple(drafts)


__all__ = ["build_rfc_identity_follow_on_proposals"]
