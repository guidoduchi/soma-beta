from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.rfc_terminal_review import RfcTerminalCascadeParticipantApplyResult


def test_terminal_cascade_participant_summary_preserves_exact_zero_counts() -> None:
    result = RfcTerminalCascadeParticipantApplyResult(
        domain="TASKS_OBJECTIVES",
        result_ref_count=0,
        audit_event_count=0,
        result_fingerprint="a" * 64,
    )

    assert result.to_payload() == {
        "domain": "TASKS_OBJECTIVES",
        "result_ref_count": 0,
        "audit_event_count": 0,
        "result_fingerprint": "a" * 64,
    }


def test_terminal_cascade_audit_cardinality_is_scalar_not_collection_bounded() -> None:
    registry = build_tickets_audit_registry()
    contract = registry.resolve("ticket.rfc.terminal_cascade_executed", 1)
    payload = {
        "proposal_id": new_uuid4(),
        "proposal_revision": 2,
        "terminal_epoch_id": "terminal-epoch-1",
        "scope_fingerprint": "b" * 64,
        "reviewed_preview_fingerprint": "c" * 64,
        "state_transition": "pending_to_executed",
        "task_objective_apply_result": {
            "domain": "TASKS_OBJECTIVES",
            "result_ref_count": 500_000,
            "audit_event_count": 250_000,
            "result_fingerprint": "d" * 64,
        },
        "communication_apply_result": {
            "domain": "COMMUNICATIONS",
            "result_ref_count": 300_000,
            "audit_event_count": 150_000,
            "result_fingerprint": "e" * 64,
        },
        "reason_category": None,
    }

    validated = contract.payload_contract.validate(payload)
    assert validated == payload
    assert contract.sensitivity_validator is not None
    contract.sensitivity_validator(validated)
