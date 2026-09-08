from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from .errors import ValidationError

UnknownFieldPolicy = Literal["reject", "preserve-readonly", "quarantine"]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is forbidden: {value}")


def loads_strict_bytes(raw: bytes, *, max_bytes: int | None = None) -> Any:
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValidationError("JSON input exceeds UTF-8 byte bound")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("JSON input is not valid UTF-8") from exc
    return loads_strict(text, max_bytes=max_bytes)


def loads_strict(text: str, *, max_bytes: int | None = None) -> Any:
    encoded = text.encode("utf-8", errors="strict")
    if max_bytes is not None and len(encoded) > max_bytes:
        raise ValidationError("JSON input exceeds UTF-8 byte bound")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except ValidationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValidationError("malformed JSON") from exc


def canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("value cannot be canonicalized as JSON") from exc
    return text.encode("utf-8")


def sha256_canonical_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _measure(value: Any, *, depth: int = 0) -> tuple[int, int, int]:
    max_depth = depth
    collection_items = 0
    string_bytes = 0
    if isinstance(value, str):
        string_bytes += len(value.encode("utf-8"))
    elif isinstance(value, dict):
        collection_items += len(value)
        for key, child in value.items():
            string_bytes += len(key.encode("utf-8"))
            child_depth, child_items, child_strings = _measure(child, depth=depth + 1)
            max_depth = max(max_depth, child_depth)
            collection_items += child_items
            string_bytes += child_strings
    elif isinstance(value, list):
        collection_items += len(value)
        for child in value:
            child_depth, child_items, child_strings = _measure(child, depth=depth + 1)
            max_depth = max(max_depth, child_depth)
            collection_items += child_items
            string_bytes += child_strings
    return max_depth, collection_items, string_bytes


@dataclass(frozen=True, slots=True)
class ObjectContract:
    name: str
    version: int
    required_fields: frozenset[str]
    allowed_fields: frozenset[str]
    unknown_field_policy: UnknownFieldPolicy = "reject"
    max_depth: int = 8
    max_collection_items: int = 512
    max_utf8_bytes: int = 65_536

    def validate(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError(f"{self.name} v{self.version} requires an object")
        missing = self.required_fields - value.keys()
        if missing:
            raise ValidationError(f"missing required fields: {sorted(missing)!r}")
        unknown = value.keys() - self.allowed_fields
        if unknown and self.unknown_field_policy == "reject":
            raise ValidationError(f"unknown fields: {sorted(unknown)!r}")
        encoded = canonical_json_bytes(value)
        if len(encoded) > self.max_utf8_bytes:
            raise ValidationError("JSON contract byte bound exceeded")
        depth, items, _ = _measure(value)
        if depth > self.max_depth:
            raise ValidationError("JSON contract depth bound exceeded")
        if items > self.max_collection_items:
            raise ValidationError("JSON contract collection bound exceeded")
        return value


class ContractRegistry:
    def __init__(self) -> None:
        self._contracts: dict[tuple[str, int], ObjectContract] = {}

    def register(self, contract: ObjectContract) -> None:
        key = (contract.name, contract.version)
        if key in self._contracts:
            raise ValidationError(f"contract already registered: {key!r}")
        self._contracts[key] = contract

    def get(self, name: str, version: int) -> ObjectContract:
        try:
            return self._contracts[(name, version)]
        except KeyError as exc:
            raise ValidationError(f"unsupported JSON contract: {name} v{version}") from exc

    def names(self) -> Iterable[tuple[str, int]]:
        return tuple(sorted(self._contracts))
