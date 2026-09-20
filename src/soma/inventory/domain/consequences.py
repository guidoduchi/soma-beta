from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4

from .needs import validate_effective_at_utc

_PHYSICAL_DISPOSITIONS = frozenset(
    {
        "installed_used",
        "unused",
        "inbound_faulty",
        "incompatible",
        "dismantled",
        "removed_only",
        "no_physical_change",
        "other_reviewed",
    }
)


@dataclass(frozen=True, slots=True)
class PhysicalConsequenceIntent:
    physical_disposition: str
    installed_spare_part_unit_id: str | None = None
    removed_device_part_unit_id: str | None = None
    inbound_spare_part_unit_id: str | None = None
    parent_dismantled_unit_id: str | None = None
    explicit_return_device_part_unit_id: str | None = None
    explicit_return_spare_part_unit_id: str | None = None
    effective_at_utc: int | None = None

    def validate(self) -> "PhysicalConsequenceIntent":
        disposition = validate_physical_disposition(self.physical_disposition)
        installed = _uuid_or_none(self.installed_spare_part_unit_id)
        removed = _uuid_or_none(self.removed_device_part_unit_id)
        inbound = _uuid_or_none(self.inbound_spare_part_unit_id)
        parent = _uuid_or_none(self.parent_dismantled_unit_id)
        explicit_device = _uuid_or_none(self.explicit_return_device_part_unit_id)
        explicit_spare = _uuid_or_none(self.explicit_return_spare_part_unit_id)
        effective = validate_effective_at_utc(self.effective_at_utc)

        if explicit_device is not None and explicit_spare is not None:
            raise ValidationError("physical consequence explicit return unit must be exactly one typed identity")

        if disposition == "installed_used":
            if installed is None or removed is None:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "installed_used requires installed Spare Part Unit and removed Device Part Unit",
                )
        elif disposition in {"unused", "inbound_faulty", "incompatible"}:
            if inbound is None:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    f"{disposition} requires inbound Spare Part Unit",
                )
        elif disposition == "dismantled":
            if parent is None:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "dismantled requires parent assembly Spare Part Unit",
                )
        elif disposition == "removed_only":
            if removed is None:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "removed_only requires removed Device Part Unit",
                )
        elif disposition == "no_physical_change":
            if any(
                value is not None
                for value in (
                    installed,
                    removed,
                    inbound,
                    parent,
                    explicit_device,
                    explicit_spare,
                )
            ):
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "no_physical_change cannot carry physical-unit relationships",
                )
        elif disposition == "other_reviewed":
            if (explicit_device is None) == (explicit_spare is None):
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "other_reviewed requires exactly one explicit typed return unit",
                )

        return PhysicalConsequenceIntent(
            physical_disposition=disposition,
            installed_spare_part_unit_id=installed,
            removed_device_part_unit_id=removed,
            inbound_spare_part_unit_id=inbound,
            parent_dismantled_unit_id=parent,
            explicit_return_device_part_unit_id=explicit_device,
            explicit_return_spare_part_unit_id=explicit_spare,
            effective_at_utc=effective,
        )

    def return_candidate(self) -> tuple[str, str] | None:
        if self.physical_disposition == "installed_used":
            assert self.removed_device_part_unit_id is not None
            return "device_part_unit", self.removed_device_part_unit_id
        if self.physical_disposition in {"unused", "inbound_faulty", "incompatible"}:
            assert self.inbound_spare_part_unit_id is not None
            return "spare_part_unit", self.inbound_spare_part_unit_id
        if self.physical_disposition == "dismantled":
            assert self.parent_dismantled_unit_id is not None
            return "spare_part_unit", self.parent_dismantled_unit_id
        if self.physical_disposition == "removed_only":
            assert self.removed_device_part_unit_id is not None
            return "device_part_unit", self.removed_device_part_unit_id
        if self.physical_disposition == "other_reviewed":
            if self.explicit_return_device_part_unit_id is not None:
                return "device_part_unit", self.explicit_return_device_part_unit_id
            assert self.explicit_return_spare_part_unit_id is not None
            return "spare_part_unit", self.explicit_return_spare_part_unit_id
        return None


@dataclass(frozen=True, slots=True)
class ExtractedSparePartIntent:
    bom_code: str
    manufacturer_serial: str | None = None
    condition_token: str | None = None


def validate_physical_disposition(value: str) -> str:
    if value not in _PHYSICAL_DISPOSITIONS:
        raise ValidationError("physical_disposition is invalid")
    return value


def _uuid_or_none(value: str | None) -> str | None:
    return None if value is None else require_uuid4(value)


__all__ = [
    "ExtractedSparePartIntent",
    "PhysicalConsequenceIntent",
    "validate_physical_disposition",
]
