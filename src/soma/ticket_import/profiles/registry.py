from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError


@dataclass(frozen=True, slots=True)
class ImportFieldSpec:
    field_key: str
    field_class: str
    value_kind: str
    vocabulary_id: str | None = None
    max_utf8_bytes: int = 65_536
    max_lines: int = 512


_ADVANCED_SEARCH_FIELDS = {
    "problem_summary": ImportFieldSpec("problem_summary", "active", "text"),
    "report_date": ImportFieldSpec("report_date", "active", "instant"),
    "customer_contact_label": ImportFieldSpec("customer_contact_label", "active", "text"),
    "customer_severity": ImportFieldSpec(
        "customer_severity", "active", "controlled", "ADVANCED_SEARCH_SEVERITY_V1"
    ),
    "current_handler_label": ImportFieldSpec("current_handler_label", "active", "text"),
    "status": ImportFieldSpec("status", "active", "controlled", "ADVANCED_SEARCH_STATUS_V1"),
    "customer_org_label": ImportFieldSpec("customer_org_label", "active", "text"),
    "customer_account_code": ImportFieldSpec("customer_account_code", "active", "text"),
    "suspend_planned_end": ImportFieldSpec("suspend_planned_end", "active", "instant"),
    "suspension_duration": ImportFieldSpec("suspension_duration", "active", "duration_seconds"),
    "last_update": ImportFieldSpec("last_update", "active", "instant"),
    "resolve_by": ImportFieldSpec("resolve_by", "deferred", "instant"),
    "resolve_by_suspend": ImportFieldSpec("resolve_by_suspend", "deferred", "instant"),
    "owner": ImportFieldSpec("owner", "deferred", "text"),
    "l2_assignee": ImportFieldSpec("l2_assignee", "deferred", "text"),
    "l3_assignee": ImportFieldSpec("l3_assignee", "deferred", "text"),
    "related_sr": ImportFieldSpec("related_sr", "deferred", "text"),
    "authorization_no": ImportFieldSpec("authorization_no", "deferred", "text"),
    "escalation_no": ImportFieldSpec("escalation_no", "deferred", "text"),
    "pr_number": ImportFieldSpec("pr_number", "deferred", "text"),
}

_RFC_FIELDS = {
    "external_created_at": ImportFieldSpec("external_created_at", "active", "instant"),
    "creator": ImportFieldSpec("creator", "active", "text", max_utf8_bytes=2_048, max_lines=1),
    "customer_account_number": ImportFieldSpec(
        "customer_account_number", "active", "text", max_utf8_bytes=1_024, max_lines=1
    ),
    "customer_account_name": ImportFieldSpec(
        "customer_account_name", "active", "text", max_utf8_bytes=4_096, max_lines=4
    ),
    "severity": ImportFieldSpec("severity", "active", "text", max_utf8_bytes=256, max_lines=1),
    "summary": ImportFieldSpec("summary", "active", "text", max_utf8_bytes=16_384, max_lines=64),
    "status": ImportFieldSpec("status", "active", "controlled", "RFC_STATUS_V1", 256, 1),
    "owner_external_id": ImportFieldSpec(
        "owner_external_id", "active", "text", max_utf8_bytes=2_048, max_lines=1
    ),
    "owner_name": ImportFieldSpec("owner_name", "active", "text", max_utf8_bytes=4_096, max_lines=4),
    "l1_handler_name": ImportFieldSpec(
        "l1_handler_name", "active", "text", max_utf8_bytes=4_096, max_lines=4
    ),
    "l2_handler_name": ImportFieldSpec(
        "l2_handler_name", "active", "text", max_utf8_bytes=4_096, max_lines=4
    ),
    "last_update": ImportFieldSpec("last_update", "active", "instant"),
    **{
        key: ImportFieldSpec(key, "deferred", "text", max_utf8_bytes=8_192, max_lines=32)
        for key in (
            "service_type",
            "scenario",
            "product_line_code",
            "product_line",
            "product_code",
            "product_name",
        )
    },
}

_WFM_FIELDS = {
    "rfc_status": ImportFieldSpec("rfc_status", "active", "controlled", "RFC_STATUS_V1", 256, 1),
    "task_status": ImportFieldSpec(
        "task_status", "active", "controlled", "WFM_TASK_STATUS_V1", 256, 1
    ),
    "dispatch_progress": ImportFieldSpec(
        "dispatch_progress", "active", "text", max_utf8_bytes=2_048, max_lines=4
    ),
    "planned_start": ImportFieldSpec("planned_start", "active", "instant"),
    "planned_end": ImportFieldSpec("planned_end", "active", "instant"),
    "rep_office": ImportFieldSpec("rep_office", "active", "text", max_utf8_bytes=2_048, max_lines=4),
    "risk_level": ImportFieldSpec("risk_level", "active", "text", max_utf8_bytes=256, max_lines=1),
    "task_name": ImportFieldSpec("task_name", "active", "text", max_utf8_bytes=16_384, max_lines=64),
    "description": ImportFieldSpec("description", "active", "text"),
    "customer_organization": ImportFieldSpec(
        "customer_organization", "active", "text", max_utf8_bytes=4_096, max_lines=4
    ),
}

_FIELDS_BY_FAMILY = {
    "advanced_search_sr": _ADVANCED_SEARCH_FIELDS,
    "rfc_enhanced": _RFC_FIELDS,
    "wfm_service_provider": _WFM_FIELDS,
}

_PROFILE_IDS = {
    "advanced_search_sr": ("ADVANCED_SEARCH_SR_V1", "ADVANCED_SEARCH_HEADERS_V1"),
    "rfc_enhanced": ("RFC_ENHANCED_V1", "RFC_HEADERS_V1"),
    "wfm_service_provider": ("WFM_SERVICE_PROVIDER_V1", "WFM_HEADERS_V1"),
}


def require_field_spec(source_family: str, field_key: str) -> ImportFieldSpec:
    family = _FIELDS_BY_FAMILY.get(source_family)
    if family is None:
        raise SomaError("IMPORT_SOURCE_FAMILY_INVALID", "source family is outside the closed LLD-04 registry")
    spec = family.get(field_key)
    if spec is None:
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "field is outside the source profile registry")
    return spec


def require_profile_ids(source_family: str) -> tuple[str, str]:
    ids = _PROFILE_IDS.get(source_family)
    if ids is None:
        raise SomaError("IMPORT_SOURCE_FAMILY_INVALID", "source family is outside the closed LLD-04 registry")
    return ids
