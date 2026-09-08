from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.strict_json import canonical_json_bytes

UnknownFieldPolicy = Literal["reject", "preserve-readonly", "quarantine"]


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    setting_key: str
    semantic_owner: str
    contract_name: str
    current_version: int
    default_provider: Callable[[], Any]
    validator: Callable[[Any], Any]
    semantic_equals: Callable[[Any, Any], bool]
    unknown_field_policy: UnknownFieldPolicy = "reject"
    storage_class: str = "ordinary_nonsecret"
    max_utf8_bytes: int = 65_536
    max_depth: int = 8
    max_collection_items: int = 512
    state_validator: Callable[[Any, Any], None] | None = None

    def validate_definition(self) -> None:
        for label, value in (
            ("setting_key", self.setting_key),
            ("semantic_owner", self.semantic_owner),
            ("contract_name", self.contract_name),
        ):
            if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
                raise ValidationError(f"{label} is invalid")
        if type(self.current_version) is not int or self.current_version < 1:
            raise ValidationError("setting current_version must be positive")
        if self.storage_class != "ordinary_nonsecret":
            raise SomaError("SETTING_SECRET_FORBIDDEN", "secret-bearing setting definitions belong to LLD-12")
        if self.unknown_field_policy not in ("reject", "preserve-readonly", "quarantine"):
            raise ValidationError("setting unknown_field_policy is invalid")
        for value in (self.max_utf8_bytes, self.max_depth, self.max_collection_items):
            if type(value) is not int or value < 1:
                raise ValidationError("setting bounds must be positive integers")

    def validate_value(self, value: Any) -> Any:
        validated = self.validator(value)
        encoded = canonical_json_bytes(validated)
        if len(encoded) > self.max_utf8_bytes:
            raise SomaError("FIELD_BOUND_EXCEEDED", "setting value exceeds its UTF-8 byte bound")
        depth, items = _measure(validated)
        if depth > self.max_depth or items > self.max_collection_items:
            raise SomaError("FIELD_BOUND_EXCEEDED", "setting value exceeds depth/collection bounds")
        return validated


def _measure(value: Any, depth: int = 0) -> tuple[int, int]:
    maximum = depth
    items = 0
    if isinstance(value, dict):
        items += len(value)
        for child in value.values():
            child_depth, child_items = _measure(child, depth + 1)
            maximum = max(maximum, child_depth)
            items += child_items
    elif isinstance(value, list):
        items += len(value)
        for child in value:
            child_depth, child_items = _measure(child, depth + 1)
            maximum = max(maximum, child_depth)
            items += child_items
    return maximum, items


class SettingDefinitionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, SettingDefinition] = {}

    def register(self, definition: SettingDefinition) -> None:
        definition.validate_definition()
        if definition.setting_key in self._definitions:
            raise ValidationError(f"setting definition already registered: {definition.setting_key}")
        self._definitions[definition.setting_key] = definition

    def get(self, key: str) -> SettingDefinition | None:
        return self._definitions.get(key)

    def require(self, key: str) -> SettingDefinition:
        definition = self.get(key)
        if definition is None:
            raise SomaError("SETTING_UNKNOWN", "setting key is not registered")
        return definition

    def all_for_owner(self, owner: str) -> tuple[SettingDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions)
            if self._definitions[key].semantic_owner == owner
        )
