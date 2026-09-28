from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _contract(name: str, fields: frozenset[str]) -> ObjectContract:
    batch = name == "BatchClassificationAuditV1"
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=4,
        max_collection_items=512 if batch else 32,
        max_utf8_bytes=32_768 if batch else 16_384,
    )


def _uuid(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    try:
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be UUID text")
        require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid") from exc


def _sha(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} must be lowercase SHA-256")


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


def _validate_product_line(payload: dict[str, object]) -> None:
    _uuid(payload.get("product_line_id"), "product_line_id")
    if payload.get("change_kind") not in {"CREATE", "UPDATE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Product Line change kind is invalid")
    prior = payload.get("prior_revision")
    if prior is not None:
        _positive_int(prior, "prior_revision")
    _positive_int(payload.get("resulting_revision"), "resulting_revision")
    _sha(payload.get("name_fingerprint"), "name_fingerprint")
    reason = payload.get("reason_category")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Product Line reason category is invalid")


def _validate_contract(payload: dict[str, object]) -> None:
    _uuid(payload.get("contract_id"), "contract_id")
    _uuid(payload.get("customer_org_id"), "customer_org_id")
    _positive_int(payload.get("resulting_revision"), "resulting_revision")
    _sha(payload.get("contract_reference_fingerprint"), "contract_reference_fingerprint")
    _sha(payload.get("name_fingerprint"), "name_fingerprint")


def _validate_cpl(payload: dict[str, object]) -> None:
    for field in ("contract_product_line_id", "contract_id", "product_line_id", "customer_org_id"):
        _uuid(payload.get(field), field)
    _positive_int(payload.get("resulting_revision"), "resulting_revision")
    _uuid(payload.get("initial_policy_revision_id"), "initial_policy_revision_id", nullable=True)




def _validate_catalog_lifecycle(payload: dict[str, object]) -> None:
    if payload.get("target_type") not in {"product_line", "contract", "contract_product_line"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "catalog lifecycle target type is invalid")
    _uuid(payload.get("target_id"), "target_id")
    if payload.get("prior_state") not in {"active", "archived"} or payload.get("new_state") not in {
        "active",
        "archived",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "catalog lifecycle state is invalid")
    if payload.get("prior_state") == payload.get("new_state"):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "catalog lifecycle audit requires a state change")
    prior = payload.get("prior_revision")
    resulting = payload.get("resulting_revision")
    _positive_int(prior, "prior_revision")
    _positive_int(resulting, "resulting_revision")
    if resulting != prior + 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "catalog lifecycle revision must advance exactly once")
    _sha(payload.get("dependency_fingerprint"), "dependency_fingerprint")
    reason = payload.get("reason_category")
    if not isinstance(reason, str) or not reason:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "catalog lifecycle reason category is required")

def _validate_mapping(payload: dict[str, object]) -> None:
    _uuid(payload.get("mapping_id"), "mapping_id")
    _uuid(payload.get("customer_org_id"), "customer_org_id")
    _uuid(payload.get("contract_product_line_id"), "contract_product_line_id")
    if payload.get("mapping_key_type") != "customer_account_code":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification mapping key type is invalid")
    _sha(payload.get("normalized_key_fingerprint"), "normalized_key_fingerprint")
    if payload.get("action") not in {"CREATE", "SUPERSEDE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification mapping action is invalid")
    _positive_int(payload.get("resulting_revision"), "resulting_revision")
    reason = payload.get("reason_category")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification mapping reason category is invalid")


def _validate_classification(payload: dict[str, object]) -> None:
    _uuid(payload.get("service_request_id"), "service_request_id")
    _uuid(payload.get("classification_event_id"), "classification_event_id")
    _uuid(payload.get("prior_contract_product_line_id"), "prior_contract_product_line_id", nullable=True)
    _uuid(payload.get("new_contract_product_line_id"), "new_contract_product_line_id", nullable=True)
    _uuid(payload.get("policy_revision_id"), "policy_revision_id", nullable=True)
    _uuid(payload.get("customer_org_id"), "customer_org_id", nullable=True)
    if payload.get("event_kind") not in {"ASSIGN", "RECLASSIFY", "CLEAR", "INVALIDATE_CUSTOMER"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification event kind is invalid")
    if payload.get("origin") not in {"manual_review", "automatic_mapping", "customer_change", "clear"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification audit origin is invalid")
    _sha(payload.get("input_fingerprint"), "input_fingerprint")
    reason = payload.get("reason_category")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "classification reason category is invalid")

def _validate_batch_classification(payload: dict[str, object]) -> None:
    correlation = payload.get("batch_correlation_id")
    if (
        not isinstance(correlation, str)
        or not correlation
        or correlation != correlation.strip()
        or len(correlation.encode("utf-8", errors="strict")) > 256
        or "\x00" in correlation
        or "\r" in correlation
        or "\n" in correlation
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "batch correlation identity is invalid")

    requested = payload.get("requested_count")
    eligible = payload.get("eligible_count")
    applied = payload.get("applied_count")
    unchanged = payload.get("unchanged_count")
    rejected = payload.get("rejected_count")
    for value, field, allow_zero in (
        (requested, "requested_count", False),
        (eligible, "eligible_count", True),
        (applied, "applied_count", True),
        (unchanged, "unchanged_count", True),
        (rejected, "rejected_count", True),
    ):
        _positive_int(value, field, allow_zero=allow_zero)
    assert isinstance(requested, int)
    assert isinstance(eligible, int)
    assert isinstance(applied, int)
    assert isinstance(unchanged, int)
    assert isinstance(rejected, int)
    if requested > 500 or eligible > requested:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "batch classification count bound is invalid")
    if applied + unchanged > eligible:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "batch classification eligible totals are invalid")
    if applied + unchanged + rejected != requested:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "batch classification final totals are not exact")

    _sha(payload.get("preview_fingerprint"), "preview_fingerprint")
    refs = payload.get("result_refs")
    if not isinstance(refs, list) or len(refs) != applied or len(refs) > 500:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "batch classification result refs are invalid")
    seen: set[str] = set()
    for value in refs:
        _uuid(value, "batch classification result ref")
        assert isinstance(value, str)
        if value in seen:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "batch classification result refs duplicate")
        seen.add(value)


def _validate_policy(payload: dict[str, object]) -> None:
    _uuid(payload.get("contract_product_line_id"), "contract_product_line_id")
    _uuid(payload.get("prior_policy_revision_id"), "prior_policy_revision_id", nullable=True)
    _uuid(payload.get("new_policy_revision_id"), "new_policy_revision_id")
    _positive_int(payload.get("policy_revision_ordinal"), "policy_revision_ordinal")
    _positive_int(payload.get("resulting_cpl_revision"), "resulting_cpl_revision")
    _positive_int(payload.get("tier_count"), "tier_count")
    _sha(payload.get("policy_fingerprint"), "policy_fingerprint")
    reason = payload.get("reason_category")
    if not isinstance(reason, str) or not reason:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "SLA policy reason category is required")



_REPORT_STATES = {
    "staging",
    "ready_to_generate",
    "generating",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}


def _validate_report_attempt(payload: dict[str, object]) -> None:
    _uuid(payload.get("report_attempt_id"), "report_attempt_id")
    if payload.get("event") not in {
        "START",
        "SEAL",
        "GENERATING",
        "VERIFYING",
        "FAILED",
        "CANCELLED",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "report event is invalid")
    before = payload.get("state_before")
    if before is not None and before not in _REPORT_STATES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "report prior state is invalid")
    if payload.get("state_after") not in _REPORT_STATES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "report resulting state is invalid")
    _positive_int(payload.get("attempt_revision"), "attempt_revision")
    _sha(payload.get("scope_fingerprint"), "scope_fingerprint")
    snapshot_hash = payload.get("snapshot_hash")
    if snapshot_hash is not None:
        _sha(snapshot_hash, "snapshot_hash")
    failure_code = payload.get("failure_code")
    if failure_code is not None and (
        not isinstance(failure_code, str)
        or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", failure_code) is None
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "report failure code is invalid")


def _validate_completed_report(payload: dict[str, object]) -> None:
    _uuid(payload.get("report_attempt_id"), "report_attempt_id")
    _sha(payload.get("snapshot_hash"), "snapshot_hash")
    filename = payload.get("artifact_filename")
    if (
        not isinstance(filename, str)
        or not filename
        or len(filename.encode("utf-8")) > 4096
        or any(ch in filename for ch in ("/", "\\", "\x00"))
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "report artifact filename is invalid")
    _sha(payload.get("artifact_sha256"), "artifact_sha256")
    _positive_int(payload.get("artifact_size_bytes"), "artifact_size_bytes")
    _positive_int(payload.get("verified_at_utc"), "verified_at_utc", allow_zero=True)
    _positive_int(payload.get("completed_at_utc"), "completed_at_utc", allow_zero=True)
    for field in ("member_count", "cohort_count", "section_count"):
        _positive_int(payload.get(field), field, allow_zero=True)


_REPORT_ATTEMPT_FIELDS = frozenset(
    {
        "report_attempt_id",
        "event",
        "state_before",
        "state_after",
        "attempt_revision",
        "scope_fingerprint",
        "snapshot_hash",
        "failure_code",
    }
)
_COMPLETED_REPORT_FIELDS = frozenset(
    {
        "report_attempt_id",
        "snapshot_hash",
        "artifact_filename",
        "artifact_sha256",
        "artifact_size_bytes",
        "verified_at_utc",
        "completed_at_utc",
        "member_count",
        "cohort_count",
        "section_count",
    }
)


_PRODUCT_LINE_FIELDS = frozenset(
    {"product_line_id", "change_kind", "prior_revision", "resulting_revision", "name_fingerprint", "reason_category"}
)
_CONTRACT_FIELDS = frozenset(
    {"contract_id", "customer_org_id", "resulting_revision", "contract_reference_fingerprint", "name_fingerprint"}
)
_CPL_FIELDS = frozenset(
    {"contract_product_line_id", "contract_id", "product_line_id", "customer_org_id", "resulting_revision", "initial_policy_revision_id"}
)


_CATALOG_LIFECYCLE_FIELDS = frozenset(
    {
        "target_type",
        "target_id",
        "prior_state",
        "new_state",
        "prior_revision",
        "resulting_revision",
        "dependency_fingerprint",
        "reason_category",
    }
)

_MAPPING_FIELDS = frozenset(
    {
        "mapping_id",
        "customer_org_id",
        "mapping_key_type",
        "normalized_key_fingerprint",
        "contract_product_line_id",
        "action",
        "resulting_revision",
        "reason_category",
    }
)
_CLASSIFICATION_FIELDS = frozenset(
    {
        "service_request_id",
        "classification_event_id",
        "event_kind",
        "prior_contract_product_line_id",
        "new_contract_product_line_id",
        "policy_revision_id",
        "customer_org_id",
        "input_fingerprint",
        "origin",
        "reason_category",
    }
)

_BATCH_CLASSIFICATION_FIELDS = frozenset(
    {
        "batch_correlation_id",
        "requested_count",
        "eligible_count",
        "applied_count",
        "unchanged_count",
        "rejected_count",
        "preview_fingerprint",
        "result_refs",
    }
)


_POLICY_FIELDS = frozenset(
    {
        "contract_product_line_id",
        "prior_policy_revision_id",
        "new_policy_revision_id",
        "policy_revision_ordinal",
        "resulting_cpl_revision",
        "tier_count",
        "policy_fingerprint",
        "reason_category",
    }
)


def build_product_line_sla_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    for action_type, schema, fields, validator in (
        ("sla.product_line.created_or_updated", "ProductLineAuditV1", _PRODUCT_LINE_FIELDS, _validate_product_line),
        ("sla.contract.created", "ContractAuditV1", _CONTRACT_FIELDS, _validate_contract),
        ("sla.contract_product_line.created", "ContractProductLineAuditV1", _CPL_FIELDS, _validate_cpl),
        ("sla.policy.revised", "SlaPolicyAuditV1", _POLICY_FIELDS, _validate_policy),
        (
            "sla.catalog_lifecycle.changed",
            "CatalogLifecycleAuditV1",
            _CATALOG_LIFECYCLE_FIELDS,
            _validate_catalog_lifecycle,
        ),
        (
            "sla.classification_mapping.created_or_superseded",
            "ClassificationMappingAuditV1",
            _MAPPING_FIELDS,
            _validate_mapping,
        ),
        (
            "sla.service_request.classification_changed",
            "ServiceRequestClassificationAuditV1",
            _CLASSIFICATION_FIELDS,
            _validate_classification,
        ),
        (
            "sla.service_request.batch_classification_applied",
            "BatchClassificationAuditV1",
            _BATCH_CLASSIFICATION_FIELDS,
            _validate_batch_classification,
        ),
        (
            "sla.report.started",
            "ReportAttemptAuditV1",
            _REPORT_ATTEMPT_FIELDS,
            _validate_report_attempt,
        ),
        (
            "sla.report.progressed",
            "ReportAttemptAuditV1",
            _REPORT_ATTEMPT_FIELDS,
            _validate_report_attempt,
        ),
        (
            "sla.report.completed",
            "CompletedReportAuditV1",
            _COMPLETED_REPORT_FIELDS,
            _validate_completed_report,
        ),
        (
            "sla.report.cancelled_or_failed",
            "ReportAttemptAuditV1",
            _REPORT_ATTEMPT_FIELDS,
            _validate_report_attempt,
        ),
    ):
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=schema,
                payload_version=1,
                payload_contract=_contract(schema, fields),
                sensitivity_validator=validator,
            )
        )
    return registry


__all__ = ["build_product_line_sla_audit_registry"]
