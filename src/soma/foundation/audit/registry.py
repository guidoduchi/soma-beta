from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from soma.foundation.errors import SomaError
from soma.foundation.strict_json import ObjectContract

SensitivityValidator = Callable[[dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class AuditActionContract:
    action_type: str
    action_version: int
    payload_schema: str
    payload_version: int
    payload_contract: ObjectContract
    allowed_reason_categories: frozenset[str] | None = None
    sensitivity_validator: SensitivityValidator | None = None


class AuditRegistry:
    def __init__(self) -> None:
        self._actions: dict[tuple[str, int], AuditActionContract] = {}

    def register(self, contract: AuditActionContract) -> None:
        key = (contract.action_type, contract.action_version)
        if key in self._actions:
            raise SomaError("AUDIT_ACTION_DUPLICATE", f"audit action already registered: {key!r}")
        if (
            contract.payload_contract.name != contract.payload_schema
            or contract.payload_contract.version != contract.payload_version
        ):
            raise SomaError("AUDIT_ACTION_INVALID", "audit payload contract name/version mismatch")
        self._actions[key] = contract

    def resolve(self, action_type: str, action_version: int) -> AuditActionContract:
        try:
            return self._actions[(action_type, action_version)]
        except KeyError as exc:
            raise SomaError("AUDIT_ACTION_UNKNOWN", f"unknown audit action: {action_type} v{action_version}") from exc
