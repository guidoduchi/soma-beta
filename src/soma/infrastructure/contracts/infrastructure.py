from __future__ import annotations

import json
import re
from importlib.resources import files

import regex

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.matching import trim_match_whitespace

REGISTRY = json.loads(files(__package__).joinpath("registry.json").read_text(encoding="utf-8"))
TYPES = {item["id"]: item for item in REGISTRY["types"]}
COMMANDS = {item["name"]: item for item in REGISTRY["commands"]}


def validate_value(kind: str, value):
    if kind.endswith("|null"):
        return None if value is None else validate_value(kind[:-5], value)
    if kind == "CURSOR_V1":
        if not isinstance(value, dict):
            raise ValidationError("Cursor must be an object")
        return dict(value)
    if kind in TYPES:
        contract = TYPES[kind]
        if not isinstance(value, dict):
            raise ValidationError(f"{kind} requires an object")
        required, optional = contract.get("required", {}), contract.get("optional", {})
        if set(required) - value.keys() or value.keys() - (required.keys() | optional.keys()):
            raise ValidationError(f"{kind} has missing or unknown fields")
        return {key: (None if item is None and key in optional else validate_value(
            required.get(key, optional.get(key)), item)) for key, item in value.items()}
    if kind == "uuid":
        return require_uuid4(value)
    if kind == "sha256":
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValidationError("Expected a lowercase SHA-256 fingerprint")
        return value
    if kind == "boolean":
        if type(value) is not bool:
            raise ValidationError("Expected a boolean")
        return value
    if kind.startswith("enum:"):
        if not isinstance(value, str) or value not in kind[5:].split("|"):
            raise ValidationError("Unsupported enum value")
        return value
    array = re.fullmatch(r"array<(.+)>,max(\d+)", kind)
    if array:
        if not isinstance(value, list) or len(value) > int(array[2]):
            raise ValidationError("Collection exceeds its contract")
        return [validate_value(array[1], item) for item in value]
    if kind in ("rev", "rev_or_zero") or kind.startswith(("int:", "integer")):
        low, high = (0 if kind == "rev_or_zero" else 1), None
        bounds = re.search(r":(\d+)\.\.(\d+)", kind)
        minimum = re.search(r">=(\d+)", kind)
        if bounds:
            low, high = int(bounds[1]), int(bounds[2])
        elif minimum:
            low = int(minimum[1])
        elif kind == "integer":
            low = None
        if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
            raise ValidationError("Integer is outside the contract bounds")
        return value
    if kind == "reason":
        kind = "reason_code"
    bound = REGISTRY["bounds"]["text_bounds"].get(kind)
    byte_bound = re.search(r"<=(\d+)bytes", kind)
    if bound or byte_bound or kind == "string":
        if not isinstance(value, str):
            raise ValidationError("Expected text")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError as exc:
            raise ValidationError("Text must be valid UTF-8") from exc
        if "\x00" in value:
            raise ValidationError("Text contains NUL")
        maximum = bound["max_utf8_bytes"] if bound else int(byte_bound[1]) if byte_bound else 4096
        if size > maximum:
            raise ValidationError("Text exceeds its byte bound")
        if bound:
            value = trim_match_whitespace(value)
            if len(regex.findall(r"\X", value)) > bound["max_graphemes"]:
                raise ValidationError("Text exceeds its grapheme bound")
            if not value:
                if bound["blank"] == "normalize_to_null":
                    return None
                raise ValidationError("Blank text is forbidden")
        return value
    raise IntegrityFailure(f"Unsupported Infrastructure type: {kind}")


def validate_request(command: str, payload: dict) -> dict:
    if command not in COMMANDS:
        raise ValidationError("Unknown Infrastructure command")
    return validate_value(COMMANDS[command]["request_type"], payload)
