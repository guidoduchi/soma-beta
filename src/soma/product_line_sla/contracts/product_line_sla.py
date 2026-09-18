from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure


@dataclass(frozen=True, slots=True)
class CatalogMutationResult:
    target_type: str
    target_id: str
    revision: int
    policy_revision_id: str | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class PolicyRevisionResult:
    contract_product_line_id: str
    policy_revision_id: str
    policy_revision_ordinal: int
    cpl_revision: int
    tier_count: int
    content_fingerprint: str
    replayed: bool


def catalog_result_from_execution(result: CommandExecutionResult) -> CatalogMutationResult:
    if result.response_schema != "SlaCatalogMutationResultV1" or result.response_version != 1:
        raise IntegrityFailure("Product Line SLA catalog response contract is invalid")
    value = result.response
    if not isinstance(value, dict) or set(value) != {
        "target_type",
        "target_id",
        "revision",
        "policy_revision_id",
    }:
        raise IntegrityFailure("Product Line SLA catalog response shape is invalid")
    if not isinstance(value["target_type"], str) or not isinstance(value["target_id"], str):
        raise IntegrityFailure("Product Line SLA catalog response identity is invalid")
    revision = value["revision"]
    policy_revision_id = value["policy_revision_id"]
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure("Product Line SLA catalog response revision is invalid")
    if policy_revision_id is not None and not isinstance(policy_revision_id, str):
        raise IntegrityFailure("Product Line SLA catalog policy identity is invalid")
    return CatalogMutationResult(
        target_type=value["target_type"],
        target_id=value["target_id"],
        revision=revision,
        policy_revision_id=policy_revision_id,
        replayed=result.replayed,
    )




@dataclass(frozen=True, slots=True)
class ClassificationPreview:
    service_request_id: str
    state: str
    customer_org_id: str | None
    target_contract_product_line_id: str | None
    mapping_id: str | None
    current_contract_product_line_id: str | None
    current_revision: int
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class ClassificationMutationResult:
    service_request_id: str
    contract_product_line_id: str | None
    classification_event_id: str | None
    revision: int
    outcome: str
    replayed: bool


def classification_result_from_execution(result: CommandExecutionResult) -> ClassificationMutationResult:
    if result.response_schema != "SlaClassificationMutationResultV1" or result.response_version != 1:
        raise IntegrityFailure("SLA classification response contract is invalid")
    value = result.response
    if not isinstance(value, dict) or set(value) != {
        "service_request_id",
        "contract_product_line_id",
        "classification_event_id",
        "revision",
        "outcome",
    }:
        raise IntegrityFailure("SLA classification response shape is invalid")
    if not isinstance(value["service_request_id"], str) or not value["service_request_id"]:
        raise IntegrityFailure("SLA classification Service Request identity is invalid")
    for key in ("contract_product_line_id", "classification_event_id"):
        if value[key] is not None and not isinstance(value[key], str):
            raise IntegrityFailure("SLA classification optional identity is invalid")
    if type(value["revision"]) is not int or value["revision"] < 0:
        raise IntegrityFailure("SLA classification revision is invalid")
    if value["outcome"] not in {"APPLIED", "NO_CHANGE", "CLEARED", "INVALIDATED"}:
        raise IntegrityFailure("SLA classification outcome is invalid")
    return ClassificationMutationResult(
        service_request_id=value["service_request_id"],
        contract_product_line_id=value["contract_product_line_id"],
        classification_event_id=value["classification_event_id"],
        revision=value["revision"],
        outcome=value["outcome"],
        replayed=result.replayed,
    )

def policy_result_from_execution(result: CommandExecutionResult) -> PolicyRevisionResult:
    if result.response_schema != "SlaPolicyRevisionResultV1" or result.response_version != 1:
        raise IntegrityFailure("SLA policy response contract is invalid")
    value = result.response
    if not isinstance(value, dict) or set(value) != {
        "contract_product_line_id",
        "policy_revision_id",
        "policy_revision_ordinal",
        "cpl_revision",
        "tier_count",
        "content_fingerprint",
    }:
        raise IntegrityFailure("SLA policy response shape is invalid")
    for key in ("contract_product_line_id", "policy_revision_id", "content_fingerprint"):
        if not isinstance(value[key], str) or not value[key]:
            raise IntegrityFailure("SLA policy response identity/fingerprint is invalid")
    for key in ("policy_revision_ordinal", "cpl_revision", "tier_count"):
        if type(value[key]) is not int or value[key] <= 0:
            raise IntegrityFailure("SLA policy response count/revision is invalid")
    return PolicyRevisionResult(
        contract_product_line_id=value["contract_product_line_id"],
        policy_revision_id=value["policy_revision_id"],
        policy_revision_ordinal=value["policy_revision_ordinal"],
        cpl_revision=value["cpl_revision"],
        tier_count=value["tier_count"],
        content_fingerprint=value["content_fingerprint"],
        replayed=result.replayed,
    )


__all__ = [
    "CatalogMutationResult",
    "ClassificationMutationResult",
    "ClassificationPreview",
    "PolicyRevisionResult",
    "catalog_result_from_execution",
    "classification_result_from_execution",
    "policy_result_from_execution",
]
