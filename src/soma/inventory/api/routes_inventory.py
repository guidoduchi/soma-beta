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

INVENTORY_ROUTE_SPECS: tuple[InventoryRouteSpec, ...] = (
    route_spec("GET", "/api/v1/inventory/stock", "query", "StockEligibilityQuery", "StockEligibilityQueryV1", "StockEligibilityPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/needs", "query", "InventoryNeedsQuery", "InventoryNeedsQueryV1", "InventoryNeedPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/tasks/{task_id}", "query", "TaskInventoryContextQuery", "TaskInventoryContextQueryV1", "TaskInventoryContextV1", 200, 2048, "LLD12_BROWSER_QUERY_V1", ["NOT_FOUND"]),
    route_spec("GET", "/api/v1/inventory/attention", "query", "InventoryAttentionQuery", "InventoryAttentionQueryV1", "InventoryAttentionPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/history/{target_kind}/{target_id}", "query", "InventoryHistoryQuery", "InventoryHistoryQueryV1", "InventoryHistoryPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("POST", "/api/v1/inventory/device-parts", "command", "RegisterDevicePartUnit", "RegisterDevicePartUnitRequestV1", "InventoryMutationResultV1", 201, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","INV_INVALID_ID","NEED_CROSS_SR","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/needs/{need_id}/plan", "command", "SetSpareNeedPlannedQuantity", "SetSpareNeedPlannedQuantityRequestV1", "InventoryMutationResultV1", 200, 4096, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","NEED_CROSS_SR","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/needs/{need_id}/lifecycle", "command", "ChangeSpareNeedLifecycle", "ChangeSpareNeedLifecycleRequestV1", "InventoryMutationResultV1", 200, 4096, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","NEED_DELETE_BLOCKED","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/units", "command", "RegisterSparePartUnit", "RegisterSparePartUnitRequestV1", "InventoryMutationResultV1", 201, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_INVALID_ID","STOCK_NOT_ELIGIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/allocations/task", "command", "ReserveSparePartUnitForTask", "ReserveSparePartUnitForTaskRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","STOCK_NOT_ELIGIBLE","UNIT_ALREADY_RESERVED","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/allocations/{allocation_id}/release", "command", "ReleaseSparePartUnitReservation", "ReleaseSparePartUnitReservationRequestV1", "InventoryMutationResultV1", 200, 4096, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/needs/{need_id}/local-selection", "command", "RecordLocalNeedFulfillmentSelection", "RecordLocalNeedFulfillmentSelectionRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","STOCK_NOT_ELIGIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/tasks/{task_id}/physical-consequences", "command", "AcceptInventoryPhysicalConsequence", "AcceptInventoryPhysicalConsequenceRequestV1", "InventoryMutationResultV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["TASK_REVIEW_STALE","RETURN_SELECTION_INVALID","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/physical-consequences/{physical_consequence_id}/correct", "command", "CorrectInventoryPhysicalConsequence", "CorrectInventoryPhysicalConsequenceRequestV1", "InventoryMutationResultV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","TASK_REVIEW_STALE","RETURN_SELECTION_INVALID","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/logistics", "command", "RecordActualLogisticsEvent", "RecordActualLogisticsEventRequestV1", "InventoryMutationResultV1", 201, 32768, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/logistics/participants/{participant_id}/correct", "command", "CorrectLogisticsParticipant", "CorrectLogisticsParticipantRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("GET", "/api/v1/inventory/requests", "query", "SpareRequestListQuery", "SpareRequestListQueryV1", "SpareRequestPageV1", 200, 4096, "LLD12_BROWSER_QUERY_V1", ["VALIDATION_FAILED"]),
    route_spec("GET", "/api/v1/inventory/requests/{request_id}", "query", "SpareRequestDetailQuery", "SpareRequestDetailQueryV1", "SpareRequestV1", 200, 2048, "LLD12_BROWSER_QUERY_V1", ["NOT_FOUND"]),
    route_spec("POST", "/api/v1/inventory/requests", "command", "CreateSpareRequestDraft", "CreateSpareRequestDraftRequestV1", "SpareRequestV1", 201, 16384, "LLD12_BROWSER_MUTATION_V1", ["NEED_CROSS_SR","REQUEST_SUBMISSION_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("PATCH", "/api/v1/inventory/requests/{request_id}/draft", "command", "UpdateSpareRequestDraft", "UpdateSpareRequestDraftRequestV1", "SpareRequestV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","REQUEST_NOT_DRAFT","NEED_CROSS_SR","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/requests/{request_id}/submission", "command", "AcceptSpareRequestSubmission", "AcceptSpareRequestSubmissionRequestV1", "SpareRequestV1", 200, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","REQUEST_NOT_DRAFT","REQUEST_SUBMISSION_INVALID","NEED_CROSS_SR","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/requests/{request_id}/submission/correct-False", "command", "CorrectFalseSpareRequestSubmission", "CorrectFalseSpareRequestSubmissionRequestV1", "SpareRequestV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","CORRECTION_TARGET_INVALID","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/requests/{request_id}/official-id", "command", "AssignOrCorrectSpareRequestOfficialId", "AssignOrCorrectSpareRequestOfficialIdRequestV1", "SpareRequestV1", 200, 4096, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","INV_INVALID_ID","SR7_CONFLICT","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/requests/{request_id}/lifecycle", "command", "CancelOrRejectSpareRequest", "CancelOrRejectSpareRequestRequestV1", "SpareRequestV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","REQUEST_SUBMISSION_INVALID","DEPENDENCY_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/requests/{request_id}/rmas", "command", "AcceptRmaAuthorizationBatch", "AcceptRmaAuthorizationBatchRequestV1", "RmaBatchResultV1", 200, 32768, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","RMA_REQUIRES_SR7","C10_CONFLICT","RMA_TARGET_INCOMPATIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("GET", "/api/v1/inventory/rmas/{rma_id}", "query", "RmaDetailQuery", "RmaDetailQueryV1", "RmaDetailV1", 200, 2048, "LLD12_BROWSER_QUERY_V1", ["NOT_FOUND"]),
    route_spec("POST", "/api/v1/inventory/rmas/{rma_id}/official-id", "command", "CorrectRmaOfficialId", "CorrectRmaOfficialIdRequestV1", "InventoryMutationResultV1", 200, 4096, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","C10_CONFLICT","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/rmas/{rma_id}/assignment", "command", "SetRmaTargetAssignment", "SetRmaTargetAssignmentRequestV1", "InventoryMutationResultV1", 200, 8192, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","RMA_TARGET_INCOMPATIBLE","IDEMPOTENCY_CONFLICT"]),
    route_spec("POST", "/api/v1/inventory/rmas/{rma_id}/receipt", "command", "RecordRmaInboundReceipt", "RecordRmaInboundReceiptRequestV1", "InventoryMutationResultV1", 201, 16384, "LLD12_BROWSER_MUTATION_V1", ["INV_STALE","RMA_INBOUND_EXISTS","INV_INVALID_ID","IDEMPOTENCY_CONFLICT"]),
)

_KEYS = tuple((spec.method, spec.path) for spec in INVENTORY_ROUTE_SPECS)
if len(_KEYS) != len(set(_KEYS)):
    raise RuntimeError("duplicate LLD-07 route authority")


def resolve_route(method: str, path: str) -> ResolvedInventoryRoute | None:
    return resolve_inventory_route(INVENTORY_ROUTE_SPECS, method, path)


def build_route_adapter(handlers: Mapping[str, OwnerHandler]) -> InventoryRouteAdapter:
    """Build the general Inventory/request/RMA adapter from explicit owner bindings."""
    return InventoryRouteAdapter(INVENTORY_ROUTE_SPECS, handlers)


__all__ = ["INVENTORY_ROUTE_SPECS", "build_route_adapter", "resolve_route"]
