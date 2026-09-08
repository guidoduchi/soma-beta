from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

UNICODE_VERSION = "17.0.0"
CASEFOLD_URL = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/CaseFolding.txt"
PROPLIST_URL = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/PropList.txt"
OUTPUT = Path("src/soma/reference/assets/unicode_match_v1.json")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SOMA-Beta-Unicode-Asset-Generator/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty Unicode data response: {url}")
    return data


def _split_ucd_fields(line: str) -> list[str]:
    body = line.split("#", 1)[0].strip()
    if not body:
        return []
    fields = [part.strip() for part in body.split(";")]
    while fields and fields[-1] == "":
        fields.pop()
    return fields


def _parse_casefold(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8-sig", errors="strict")
    if "CaseFolding-17.0.0.txt" not in text[:500]:
        raise RuntimeError("unexpected CaseFolding source version")
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        fields = _split_ucd_fields(line)
        if not fields:
            continue
        if len(fields) != 3:
            raise RuntimeError(f"invalid CaseFolding line: {line!r}")
        source_hex, status, target_hex = fields
        if status not in {"C", "F"}:
            continue
        source = int(source_hex, 16)
        target = "".join(chr(int(item, 16)) for item in target_hex.split())
        key = f"{source:06X}"
        if key in mapping:
            raise RuntimeError(f"duplicate full casefold source code point: {key}")
        mapping[key] = target
    return dict(sorted(mapping.items()))


def _parse_whitespace(raw: bytes) -> list[list[int]]:
    text = raw.decode("utf-8-sig", errors="strict")
    if "PropList-17.0.0.txt" not in text[:500]:
        raise RuntimeError("unexpected PropList source version")
    ranges: list[list[int]] = []
    for line in text.splitlines():
        fields = _split_ucd_fields(line)
        if not fields:
            continue
        if len(fields) != 2 or fields[1] != "White_Space":
            continue
        bounds = fields[0].split("..")
        start = int(bounds[0], 16)
        end = int(bounds[-1], 16)
        ranges.append([start, end])
    if not ranges:
        raise RuntimeError("Unicode White_Space property was not found")
    return ranges


def main() -> None:
    casefold_raw = _download(CASEFOLD_URL)
    proplist_raw = _download(PROPLIST_URL)
    payload = {
        "schema": "SOMA-UNICODE-MATCH-ASSET-V1",
        "profile_id": "UNICODE_MATCH_V1",
        "unicode_version": UNICODE_VERSION,
        "sources": {
            "casefold_url": CASEFOLD_URL,
            "casefold_sha256": hashlib.sha256(casefold_raw).hexdigest(),
            "proplist_url": PROPLIST_URL,
            "proplist_sha256": hashlib.sha256(proplist_raw).hexdigest(),
        },
        "casefold_statuses": ["C", "F"],
        "casefold_map": _parse_casefold(casefold_raw),
        "white_space_ranges": _parse_whitespace(proplist_raw),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {OUTPUT}: mappings={len(payload['casefold_map'])} "
        f"whitespace_ranges={len(payload['white_space_ranges'])} "
        f"asset_sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}"
    )


if __name__ == "__main__":
    main()
