from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from .errors import ValidationError

UnknownFieldPolicy = Literal["reject", "preserve-readonly", "quarantine"]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is forbidden: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValidationError("JSON number exceeds the finite numeric range")
    return parsed


def _validate_unicode(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            item.encode("utf-8", errors="strict")
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def loads_strict_bytes(raw: bytes, *, max_bytes: int | None = None) -> Any:
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValidationError("JSON input exceeds UTF-8 byte bound")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("JSON input is not valid UTF-8") from exc
    return loads_strict(text, max_bytes=max_bytes)


def loads_strict(text: str, *, max_bytes: int | None = None) -> Any:
    try:
        encoded = text.encode("utf-8", errors="strict")
        if max_bytes is not None and len(encoded) > max_bytes:
            raise ValidationError("JSON input exceeds UTF-8 byte bound")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
        _validate_unicode(value)
        return value
    except ValidationError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
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
        return text.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValidationError("value cannot be canonicalized as JSON") from exc


def sha256_canonical_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _measure(value: Any, *, depth: int = 0) -> tuple[int, int, int]:
    max_depth = depth
    collection_items = 0
    string_bytes = 0
    pending = [(value, depth)]
    while pending:
        item, item_depth = pending.pop()
        max_depth = max(max_depth, item_depth)
        if isinstance(item, str):
            string_bytes += len(item.encode("utf-8"))
        elif isinstance(item, dict):
            collection_items += len(item)
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValidationError("JSON object keys must be strings")
                string_bytes += len(key.encode("utf-8"))
                pending.append((child, item_depth + 1))
        elif isinstance(item, list):
            collection_items += len(item)
            pending.extend((child, item_depth + 1) for child in item)
    return max_depth, collection_items, string_bytes


def canonical_json_bytes_bounded(
    value: Any,
    *,
    max_bytes: int,
    max_depth: int,
    max_collection_items: int,
) -> bytes:
    encoded = canonical_json_bytes(value)
    if len(encoded) > max_bytes:
        raise ValidationError("JSON contract byte bound exceeded")
    depth, items, _ = _measure(value)
    if depth > max_depth:
        raise ValidationError("JSON contract depth bound exceeded")
    if items > max_collection_items:
        raise ValidationError("JSON contract collection bound exceeded")
    return encoded


def loads_canonical_json(
    text: str,
    *,
    max_bytes: int,
    max_depth: int,
    max_collection_items: int,
) -> Any:
    value = loads_strict(text, max_bytes=max_bytes)
    canonical = canonical_json_bytes_bounded(
        value,
        max_bytes=max_bytes,
        max_depth=max_depth,
        max_collection_items=max_collection_items,
    )
    try:
        original = text.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValidationError("JSON input is not valid UTF-8") from exc
    if canonical != original:
        raise ValidationError("JSON text is not canonical")
    return value


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
            raise ValidationError("missing required JSON fields")
        unknown = value.keys() - self.allowed_fields
        if unknown and self.unknown_field_policy == "reject":
            raise ValidationError("unknown JSON fields")
        canonical_json_bytes_bounded(
            value,
            max_bytes=self.max_utf8_bytes,
            max_depth=self.max_depth,
            max_collection_items=self.max_collection_items,
        )
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
