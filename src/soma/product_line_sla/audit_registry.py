from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _contract(name: str, fields: frozenset[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=4,
        max_collection_items=32,
        max_utf8_bytes=16_384,
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


_PRODUCT_LINE_FIELDS = frozenset(
    {"product_line_id", "change_kind", "prior_revision", "resulting_revision", "name_fingerprint", "reason_category"}
)
_CONTRACT_FIELDS = frozenset(
    {"contract_id", "customer_org_id", "resulting_revision", "contract_reference_fingerprint", "name_fingerprint"}
)
_CPL_FIELDS = frozenset(
    {"contract_product_line_id", "contract_id", "product_line_id", "customer_org_id", "resulting_revision", "initial_policy_revision_id"}
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
