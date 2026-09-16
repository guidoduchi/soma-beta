from __future__ import annotations

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract


def _contract(name: str, fields: set[str], *, max_collection_items: int = 32) -> ObjectContract:
    frozen = frozenset(fields)
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozen,
        allowed_fields=frozen,
        max_depth=4,
        max_collection_items=max_collection_items,
        max_utf8_bytes=16_384,
    )


def build_ticket_import_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    definitions = (
        (
            "ticket_import.check_started",
            "ImportCheckStartedAuditV1",
            {"source_family", "invocation_kind", "job_id"},
        ),
        (
            "ticket_import.run_published",
            "ImportRunPublishedAuditV1",
            {
                "import_run_id",
                "source_family",
                "run_state",
                "profile_ids",
                "candidate_filename",
                "candidate_chronology_kind",
                "candidate_chronology_value",
                "logical_fingerprint",
                "counts",
                "revision",
            },
        ),
        (
            "ticket_import.run_noop_classified",
            "ImportRunNoopClassifiedAuditV1",
            {
                "import_run_id",
                "source_family",
                "replay_classification",
                "run_state",
                "candidate_chronology_kind",
                "candidate_chronology_value",
                "logical_fingerprint",
                "revision",
            },
        ),
        (
            "ticket_import.proposal_decided",
            "ImportProposalDecisionAuditV1",
            {
                "proposal_id",
                "proposal_kind",
                "decision",
                "proposal_revision",
                "reason_category",
                "owner_result_refs",
            },
        ),
        (
            "ticket_import.checkpoint_advanced",
            "ImportCheckpointAuditV1",
            {
                "source_family",
                "import_run_id",
                "chronology_kind",
                "chronology_value",
                "logical_fingerprint",
                "checkpoint_revision",
            },
        ),
        (
            "ticket_import.run_finalized",
            "ImportRunFinalizedAuditV1",
            {
                "import_run_id",
                "final_state",
                "revision",
                "checkpoint_revision",
                "accepted_count",
                "rejected_count",
                "deferred_count",
            },
        ),
        (
            "ticket_import.recovery_reviewed",
            "ImportRecoveryReviewedAuditV1",
            {
                "import_run_id",
                "review_ordinal",
                "decision",
                "reason_category",
                "review_fingerprint",
                "run_state",
                "run_revision",
            },
        ),
    )
    for action_type, payload_schema, fields in definitions:
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=payload_schema,
                payload_version=1,
                payload_contract=_contract(payload_schema, fields),
            )
        )
    return registry
