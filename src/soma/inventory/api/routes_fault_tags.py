from __future__ import annotations

from collections.abc import Mapping

from ._common import (
    InventoryRouteAdapter,
    InventoryRouteSpec,
    OwnerHandler,
    ResolvedInventoryRoute,
    resolve_inventory_route,
    route_spec,
)

FAULT_TAG_ROUTE_SPECS: tuple[InventoryRouteSpec, ...] = (
    route_spec("GET", "/api/v1/inventory/fault-tags", "query", "FaultTagListQuery", "FaultTagListQueryV1", "FaultTagPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/fault-tags/{fault_tag_id}", "query", "FaultTagDetailQuery", "FaultTagDetailQueryV1", "FaultTagV1", 200, 2048, "LLD12_BROWSER_QUERY_V1", ["NOT_FOUND"]),
    route_spec("GET", "/api/v1/inventory/fault-tag-memberships/eligible", "query", "EligibleFaultTagMembershipQuery", "EligibleFaultTagMembershipQueryV1", "FaultTagEligibilityPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED","DEPENDENCY_INDETERMINATE"]),
    route_spec("GET", "/api/v1/inventory/warehouse/queue", "query", "WarehouseQueueQuery", "WarehouseQueueQueryV1", "WarehouseQueuePageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/fault-tags/{fault_tag_id}/lineage", "query", "FaultTagLineageQuery", "FaultTagLineageQueryV1", "FaultTagLineageV1", 200, 2048, "LLD12_BROWSER_QUERY_V1", ["NOT_FOUND"]),
    route_spec("POST", "/api/v1/inventory/fault-tags", "command", "CreateFaultTagDraft", "CreateFaultTagDraftRequestV1", "FaultTagV1", 201, 16384, "LLD12_BROWSER_MUTATION_V1", ["RETURN_SELECTION_INVALID","FAULT_TAG_MEMBERSHIP_CONFLICT","FAULT_TAG_PICKUP_ORIGIN_REQUIRED","IDEMPOTENCY_CONFLICT"]),
    route_spec("PATCH", "/api/v1/inventory/fault-tags/{fault_tag_id}/draft", "command", "UpdateFaultTagDraft", "UpdateFaultTagDraftRequestV1", "FaultTagV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","FAULT_TAG_NOT_DRAFT","FAULT_TAG_MEMBERSHIP_CONFLICT","FAULT_TAG_PICKUP_ORIGIN_REQUIRED","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tags/{fault_tag_id}/submission", "command", "AcceptFaultTagSubmission", "AcceptFaultTagSubmissionRequestV1", "FaultTagV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","FAULT_TAG_NOT_DRAFT","FAULT_TAG_MEMBERSHIP_CONFLICT","FAULT_TAG_PICKUP_ORIGIN_REQUIRED","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tags/{fault_tag_id}/submission/correct-false", "command", "CorrectFalseFaultTagSubmission", "CorrectFalseFaultTagSubmissionRequestV1", "FaultTagV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tag-memberships/warehouse-receipt", "command", "RecordWarehouseReceipt", "RecordWarehouseReceiptRequestV1", "InventoryMutationResultV1", 200, 32768, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","BULK_INCOMPATIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tag-memberships/final-decision", "command", "RecordWarehouseFinalDecision", "RecordWarehouseFinalDecisionRequestV1", "InventoryMutationResultV1", 200, 32768, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","WAREHOUSE_RECEIPT_REQUIRED","WAREHOUSE_FINAL_CONFIRMATION_REQUIRED","BULK_INCOMPATIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tags/{fault_tag_id}/replacement", "command", "CreateFaultTagReplacement", "CreateFaultTagReplacementRequestV1", "FaultTagV1", 201, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","REPLACEMENT_LINEAGE_CONFLICT","FAULT_TAG_MEMBERSHIP_CONFLICT","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tags/{fault_tag_id}/resend", "command", "CreateFaultTagResend", "CreateFaultTagResendRequestV1", "FaultTagV1", 201, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","RESEND_NOT_ELIGIBLE","FAULT_TAG_MEMBERSHIP_CONFLICT","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/fault-tags/{fault_tag_id}/archive-state", "command", "ArchiveOrRestoreFaultTag", "ArchiveOrRestoreFaultTagRequestV1", "FaultTagV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/proposals/{proposal_id}/accept", "command", "AcceptInventoryProposal", "AcceptInventoryProposalRequestV1", "InventoryMutationResultV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["PROPOSAL_STALE","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/proposals/{proposal_id}/reject", "command", "RejectInventoryProposal", "RejectInventoryProposalRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["PROPOSAL_STALE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/bulk/preview", "query", "PreviewInventoryBulkAction", "InventoryBulkPreviewQueryV1", "InventoryBulkPreviewV1", 200, 32768, "LLD12_BROWSER_QUERY_V1", ["BULK_INCOMPATIBLE","DEPENDENCY_INDETERMINATE"]),
    route_spec("POST", "/api/v1/inventory/bulk/accept", "command", "AcceptInventoryBulkAction", "AcceptInventoryBulkActionRequestV1", "InventoryMutationResultV1", 200, 32768, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","BULK_INCOMPATIBLE","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/corrections", "command", "CorrectInventoryEvidence", "CorrectInventoryEvidenceRequestV1", "InventoryMutationResultV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","REPLACEMENT_LINEAGE_CONFLICT","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/destructive/preview", "query", "PreviewInventoryHardDelete", "InventoryHardDeletePreviewQueryV1", "InventoryBulkPreviewV1", 200, 8192, "LLD12_BROWSER_QUERY_V1", ["HARD_DELETE_BLOCKED","DEPENDENCY_INDETERMINATE"]),
    route_spec("POST", "/api/v1/inventory/destructive/confirm", "command", "HardDeleteUntouchedInventoryDraft", "HardDeleteUntouchedInventoryDraftRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","HARD_DELETE_BLOCKED","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
)

_KEYS = tuple((spec.method, spec.path) for spec in FAULT_TAG_ROUTE_SPECS)
if len(_KEYS) != len(set(_KEYS)):
    raise RuntimeError("duplicate LLD-07 route authority")


def resolve_route(method: str, path: str) -> ResolvedInventoryRoute | None:
    return resolve_inventory_route(FAULT_TAG_ROUTE_SPECS, method, path)


def build_route_adapter(handlers: Mapping[str, OwnerHandler]) -> InventoryRouteAdapter:
    """Build the Fault Tag/warehouse/correction adapter from explicit owner bindings."""
    return InventoryRouteAdapter(FAULT_TAG_ROUTE_SPECS, handlers)


__all__ = ["FAULT_TAG_ROUTE_SPECS", "build_route_adapter", "resolve_route"]
