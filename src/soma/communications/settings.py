from __future__ import annotations

import json
from importlib.resources import files

from soma.foundation.errors import ValidationError
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry

from soma.communications.contracts.common import integer

PREFIX = "communications."
SCHEDULE_KEYS = (PREFIX + "processing_enabled", PREFIX + "processing_interval_minutes", PREFIX + "overlap_messages")
GRACE_KEY = PREFIX + "orphan_grace_minutes"


def build_communications_setting_registry() -> SettingDefinitionRegistry:
    registry = SettingDefinitionRegistry()
    definitions = json.loads(files("soma.communications.contracts").joinpath("registry.json").read_text(encoding="utf-8"))["leaves"]["settings/communications.json"]["definitions"]
    for item in definitions:
        if item["type"] == "boolean":
            def validate(value):
                if type(value) is not bool:
                    raise ValidationError("Communication setting requires an exact boolean")
                return value
        else:
            bounds = item["bounds"]
            def validate(value, minimum=bounds["min"], maximum=bounds["max"]):
                return integer(value, minimum=minimum, maximum=maximum)
        registry.register(SettingDefinition(item["key"], "LLD-09", item["contract"], 1,
                                             lambda default=item["default"]: default, validate,
                                             lambda left, right: type(left) is type(right) and left == right))
    return registry
