"""Canonical LLD-06 catalog values; no persistence ownership."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductLineRecord:
    product_line_id: str
    name: str
    lifecycle_state: str
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


@dataclass(frozen=True, slots=True)
class ContractRecord:
    contract_id: str
    customer_org_id: str
    name: str
    contract_reference: str
    lifecycle_state: str
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


@dataclass(frozen=True, slots=True)
class ContractProductLineRecord:
    contract_product_line_id: str
    contract_id: str
    product_line_id: str
    lifecycle_state: str
    current_policy_revision_id: str | None
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


__all__ = ["ProductLineRecord","ContractRecord","ContractProductLineRecord"]
