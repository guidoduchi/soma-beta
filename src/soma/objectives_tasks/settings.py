from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from soma.foundation.errors import SomaError, ValidationError
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry


OBJECTIVE_TIMEZONE_KEY = "OBJECTIVE_TIMEZONE_V1"
OBJECTIVE_TIMEZONE_DEFAULT = "America/Guayaquil"


def validate_objective_timezone(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("Objective timezone must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("Objective timezone must be valid Unicode") from exc
    if (
        not encoded
        or len(encoded) > 255
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValidationError("Objective timezone violates its bounded one-line contract")
    try:
        resolved = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SomaError("TIMEZONE_UNKNOWN", "Objective timezone is not an available IANA timezone") from exc
    return resolved.key


def build_objective_timezone_setting_registry() -> SettingDefinitionRegistry:
    registry = SettingDefinitionRegistry()
    registry.register(
        SettingDefinition(
            setting_key=OBJECTIVE_TIMEZONE_KEY,
            semantic_owner="LLD-05",
            contract_name="OBJECTIVE_TIMEZONE_V1",
            current_version=1,
            default_provider=lambda: OBJECTIVE_TIMEZONE_DEFAULT,
            validator=validate_objective_timezone,
            semantic_equals=lambda left, right: left == right,
            unknown_field_policy="reject",
            storage_class="ordinary_nonsecret",
            max_utf8_bytes=255,
            max_depth=1,
            max_collection_items=1,
        )
    )
    return registry


__all__ = [
    "OBJECTIVE_TIMEZONE_DEFAULT",
    "OBJECTIVE_TIMEZONE_KEY",
    "build_objective_timezone_setting_registry",
    "validate_objective_timezone",
]
