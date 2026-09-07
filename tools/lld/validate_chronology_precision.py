#!/usr/bin/env python3
"""Fail closed when LLD-09 reintroduces millisecond application chronology.

HLD-14 requires known application instants to persist as canonical UTC whole
seconds. Source/provider precision may remain in opaque/raw provenance, but the
LLD-09 normative corpus must not name authoritative application timestamp
fields with the historical ``*_utc_ms`` convention.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "spec/lld/communications"
TOKEN = "_utc_ms"


def main() -> int:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(PACKET.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if TOKEN in line:
                hits.append((path.relative_to(ROOT).as_posix(), line_no, line.strip()))
    if hits:
        print(f"SOMA HLD-14 chronology precision: HIGH={len(hits)}")
        for path, line_no, line in hits:
            print(f"[HIGH] {path}:{line_no}: forbidden application chronology token {TOKEN}: {line[:500]}")
        return 1
    print("SOMA HLD-14 chronology precision: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
