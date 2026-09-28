from __future__ import annotations

from collections.abc import Iterable
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
    providers, declares its required owner set, and finalizes the registry before
    lifecycle services can be constructed.
    """

    def __init__(self) -> None:
        self._validators: dict[str, ReferenceDependencyValidator] = {}
        self._required_validator_ids: frozenset[str] = frozenset()
        self._finalized = False

    @staticmethod
    def _validated_id(value: object) -> str:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128:
            raise ValidationError("dependency validator_id is invalid")
        return value

    def register(self, validator: ReferenceDependencyValidator) -> None:
        if self._finalized:
            raise ValidationError("dependency registry is already finalized")
        validator_id = self._validated_id(getattr(validator, "validator_id", None))
        if validator_id in self._validators:
            raise ValidationError(f"dependency validator already registered: {validator_id}")
        self._validators[validator_id] = validator

    def finalize(self, *, required_validator_ids: Iterable[str]) -> None:
        if self._finalized:
            raise ValidationError("dependency registry is already finalized")
        required = frozenset(self._validated_id(value) for value in required_validator_ids)
        missing = required - self._validators.keys()
        if missing:
            raise ValidationError("required dependency validators are missing")
        self._required_validator_ids = required
        self._finalized = True

    @classmethod
    def isolated_for_tests(cls) -> "ReferenceDependencyRegistry":
        registry = cls()
        registry.finalize(required_validator_ids=())
        return registry

    def require_finalized(self) -> None:
        if not self._finalized:
            raise ValidationError("reference dependency registry is not finalized")
        missing = self._required_validator_ids - self._validators.keys()
        if missing:
            raise ValidationError("required dependency validators are missing")

    def ordered(self) -> tuple[ReferenceDependencyValidator, ...]:
        self.require_finalized()
        return tuple(self._validators[key] for key in sorted(self._validators))
