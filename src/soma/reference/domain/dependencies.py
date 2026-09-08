from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from soma.foundation.errors import ValidationError
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

ReferenceType = Literal["customer_organization", "contact", "dispatch_location"]
GuardState = Literal["CLEAR", "BLOCKED", "INDETERMINATE"]


@dataclass(frozen=True, slots=True)
class ReferenceTarget:
    target_type: ReferenceType
    target_id: str


@dataclass(frozen=True, slots=True)
class DependencyGuard:
    state: GuardState
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyBlocker:
    blocker_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class DependencyPage:
    blockers: tuple[DependencyBlocker, ...]
    continuation: str | None


class ReferenceDependencyValidator(Protocol):
    validator_id: str

    def guard_archive(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard: ...

    def guard_reactivate(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard: ...

    def count_archive_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int: ...

    def list_archive_blockers(
        self, snapshot: ReadSnapshot, target: ReferenceTarget, cursor: str | None, limit: int
    ) -> DependencyPage: ...

    def count_reactivation_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int: ...

    def list_reactivation_blockers(
        self, snapshot: ReadSnapshot, target: ReferenceTarget, cursor: str | None, limit: int
    ) -> DependencyPage: ...


class ReferenceDependencyRegistry:
    """Closed-at-runtime registry of owner-provided dependency validators.

    LLD-02 never inspects another packet's private tables. A composition root registers
    providers before requests are served; duplicate/invalid IDs are rejected.
    """

    def __init__(self) -> None:
        self._validators: dict[str, ReferenceDependencyValidator] = {}

    def register(self, validator: ReferenceDependencyValidator) -> None:
        validator_id = getattr(validator, "validator_id", None)
        if not isinstance(validator_id, str) or not validator_id or len(validator_id.encode("utf-8")) > 128:
            raise ValidationError("dependency validator_id is invalid")
        if validator_id in self._validators:
            raise ValidationError(f"dependency validator already registered: {validator_id}")
        self._validators[validator_id] = validator

    def ordered(self) -> tuple[ReferenceDependencyValidator, ...]:
        return tuple(self._validators[key] for key in sorted(self._validators))
