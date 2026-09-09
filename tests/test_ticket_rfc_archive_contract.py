from __future__ import annotations

from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.rfc_archive import _COMMAND_OPERATION_PAGE_LIMIT


_ARCHIVE_FIELDS = frozenset(
    {
        "rfc_archive_operation_id",
        "scope_kind",
        "scope_fingerprint",
        "changed_rfc_count",
        "excluded_prearchived_count",
        "resulting_operation_state",
        "reason_category",
    }
)


def test_restore_command_replay_page_bound_matches_certified_design() -> None:
    assert _COMMAND_OPERATION_PAGE_LIMIT == 32


def test_archive_audit_runtime_contract_is_scalar_for_both_actions() -> None:
    registry = build_tickets_audit_registry()
    for action in ("ticket.rfc.archived", "ticket.rfc.archive_restored"):
        contract = registry.resolve(action, 1)
        assert contract.payload_schema == "RfcArchiveAuditV1"
        assert contract.payload_contract.required_fields == _ARCHIVE_FIELDS
        assert contract.payload_contract.allowed_fields == _ARCHIVE_FIELDS
        assert "changed_rfc_ids" not in contract.payload_contract.allowed_fields
