from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import resources
from typing import Any

import unicodedata2

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import loads_strict_bytes

PROFILE_ID = "UNICODE_MATCH_V1"
UNICODE_VERSION = "17.0.0"
EXPECTED_ASSET_SHA256 = "ec78bcbdf7afa6621dfe342790227e052a55f5913395bc69d92b1bf910a76aca"
DEFAULT_KEY_MAX_UTF8_BYTES = 2048


class _UnicodeMatchAsset:
    __slots__ = ("casefold", "whitespace_ranges", "source_metadata")

    def __init__(
        self,
        *,
        casefold: dict[int, str],
        whitespace_ranges: tuple[tuple[int, int], ...],
        source_metadata: dict[str, str],
    ) -> None:
        self.casefold = casefold
        self.whitespace_ranges = whitespace_ranges
        self.source_metadata = source_metadata

    def is_whitespace(self, character: str) -> bool:
        codepoint = ord(character)
        for start, end in self.whitespace_ranges:
            if codepoint < start:
                return False
            if start <= codepoint <= end:
                return True
        return False


@lru_cache(maxsize=1)
def _asset() -> _UnicodeMatchAsset:
    resource = resources.files("soma.reference.assets").joinpath("unicode_match_v1.json")
    raw = resource.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_ASSET_SHA256:
        raise RuntimeError(
            f"UNICODE_MATCH_V1 asset integrity mismatch: expected {EXPECTED_ASSET_SHA256}, got {digest}"
        )
    parsed = loads_strict_bytes(raw, max_bytes=512_000)
    if not isinstance(parsed, dict):
        raise RuntimeError("UNICODE_MATCH_V1 asset must be a JSON object")
    if parsed.get("schema") != "SOMA-UNICODE-MATCH-ASSET-V1":
        raise RuntimeError("UNICODE_MATCH_V1 asset schema mismatch")
    if parsed.get("profile_id") != PROFILE_ID or parsed.get("unicode_version") != UNICODE_VERSION:
        raise RuntimeError("UNICODE_MATCH_V1 asset profile/version mismatch")
    if parsed.get("casefold_statuses") != ["C", "F"]:
        raise RuntimeError("UNICODE_MATCH_V1 must contain full default C+F case folding")
    if getattr(unicodedata2, "unidata_version", None) != UNICODE_VERSION:
        raise RuntimeError(
            f"unicodedata2 Unicode version mismatch: expected {UNICODE_VERSION}, "
            f"got {getattr(unicodedata2, 'unidata_version', None)!r}"
        )

    raw_casefold = parsed.get("casefold_map")
    raw_whitespace = parsed.get("white_space_ranges")
    raw_sources = parsed.get("sources")
    if not isinstance(raw_casefold, dict) or not isinstance(raw_whitespace, list) or not isinstance(raw_sources, dict):
        raise RuntimeError("UNICODE_MATCH_V1 asset shape is invalid")

    casefold: dict[int, str] = {}
    for key, value in raw_casefold.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError("UNICODE_MATCH_V1 casefold entry is invalid")
        codepoint = int(key, 16)
        if codepoint in casefold:
            raise RuntimeError("UNICODE_MATCH_V1 casefold source is duplicated")
        casefold[codepoint] = value

    ranges: list[tuple[int, int]] = []
    previous_end = -1
    for item in raw_whitespace:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or type(item[0]) is not int
            or type(item[1]) is not int
            or item[0] < 0
            or item[1] < item[0]
            or item[0] <= previous_end
        ):
            raise RuntimeError("UNICODE_MATCH_V1 whitespace ranges are invalid")
        ranges.append((item[0], item[1]))
        previous_end = item[1]

    source_metadata: dict[str, str] = {}
    for key in ("casefold_url", "casefold_sha256", "proplist_url", "proplist_sha256"):
        value = raw_sources.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"UNICODE_MATCH_V1 source metadata missing {key}")
        source_metadata[key] = value

    return _UnicodeMatchAsset(
        casefold=casefold,
        whitespace_ranges=tuple(ranges),
        source_metadata=source_metadata,
    )


def is_match_whitespace(character: str) -> bool:
    if not isinstance(character, str) or len(character) != 1:
        raise ValidationError("whitespace classification expects exactly one Unicode code point")
    return _asset().is_whitespace(character)


def trim_match_whitespace(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("text value must be a string")
    asset = _asset()
    start = 0
    end = len(value)
    while start < end and asset.is_whitespace(value[start]):
        start += 1
    while end > start and asset.is_whitespace(value[end - 1]):
        end -= 1
    return value[start:end]


def _validate_raw_text(raw: str, *, max_utf8_bytes: int) -> None:
    if not isinstance(raw, str):
        raise ValidationError("matching input must be a string")
    encoded = raw.encode("utf-8", errors="strict")
    if not encoded:
        raise ValidationError("matching input cannot be empty")
    if len(encoded) > max_utf8_bytes:
        raise ValidationError("matching input exceeds its UTF-8 byte bound")
    if "\x00" in raw or "\r" in raw or "\n" in raw:
        raise ValidationError("matching input contains a forbidden control character")


def _collapse_unicode_whitespace(value: str, asset: _UnicodeMatchAsset) -> str:
    output: list[str] = []
    in_whitespace = False
    for character in value:
        if asset.is_whitespace(character):
            if output:
                in_whitespace = True
            continue
        if in_whitespace:
            output.append(" ")
            in_whitespace = False
        output.append(character)
    return "".join(output)


def normalize_match_key(
    raw: str,
    *,
    raw_max_utf8_bytes: int,
    key_max_utf8_bytes: int = DEFAULT_KEY_MAX_UTF8_BYTES,
) -> str:
    """Normalize one descriptive/reference matching value under UNICODE_MATCH_V1.

    This deliberately does not call Python's str.casefold() or str.isspace().
    Both case-fold and whitespace authority come from the checked-in Unicode 17 asset.
    """

    _validate_raw_text(raw, max_utf8_bytes=raw_max_utf8_bytes)
    asset = _asset()
    normalized = unicodedata2.normalize("NFKC", raw)
    collapsed = _collapse_unicode_whitespace(normalized, asset)
    folded = "".join(asset.casefold.get(ord(character), character) for character in collapsed)
    encoded = folded.encode("utf-8", errors="strict")
    if not encoded:
        raise ValidationError("matching input normalizes to an empty key")
    if len(encoded) > key_max_utf8_bytes:
        raise ValidationError("normalized matching key exceeds its UTF-8 byte bound")
    if "\x00" in folded or "\r" in folded or "\n" in folded:
        raise ValidationError("normalized matching key contains a forbidden control character")
    return folded


def unicode_match_asset_metadata() -> dict[str, Any]:
    asset = _asset()
    return {
        "profile_id": PROFILE_ID,
        "unicode_version": UNICODE_VERSION,
        "asset_sha256": EXPECTED_ASSET_SHA256,
        **asset.source_metadata,
    }
