"""Canonical LLD-06 classification values; no persistence ownership."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassificationMappingRecord:
    mapping_id: str
    mapping_key_type: str
    normalized_key: str
    customer_org_id: str
    contract_product_line_id: str
    active: bool
    revision: int
    created_at_utc: int
    opened_command_id: str
    closed_command_id: str | None


@dataclass(frozen=True, slots=True)
class SrClassificationCurrentRecord:
    service_request_id: str
    contract_product_line_id: str
    classification_event_id: str
    revision: int
    last_command_id: str


__all__ = ["ClassificationMappingRecord","SrClassificationCurrentRecord"]
