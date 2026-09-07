#!/usr/bin/env python3
"""Fail closed when more than one LLD owns the same public route.

Packet-local route validation is insufficient for composition-root determinism: one
HTTP method/path pair must resolve to exactly one packet/handler contract globally.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LLD_ROOT = ROOT / "spec/lld"


def load(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    findings: list[str] = []
    global_index = load(LLD_ROOT / "_index.json")
    owners: dict[tuple[str, str], list[tuple[str, str, dict]]] = defaultdict(list)

    for packet in global_index.get("packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("id", ""))
        packet_path = ROOT / str(packet.get("path", ""))
        index_path = packet_path / "_index.json"
        if not packet_id or not index_path.is_file():
            continue
        packet_index = load(index_path)
        manifest: list[str] = []
        for key in ("packet_files", "normative_paths"):
            value = packet_index.get(key, [])
            if isinstance(value, list):
                manifest.extend(str(x) for x in value if isinstance(x, str))

        route_paths = sorted({p for p in manifest if p == "routes.json" or p.startswith("routes/")})
        for rel in route_paths:
            path = packet_path / rel
            if not path.is_file():
                continue
            doc = load(path)
            routes = doc.get("routes", []) if isinstance(doc, dict) else []
            if not isinstance(routes, list):
                continue
            for route in routes:
                if not isinstance(route, dict):
                    continue
                method = str(route.get("method", "")).upper().strip()
                url = str(route.get("path", "")).strip()
                if not method or not url:
                    continue
                owners[(method, url)].append((packet_id, rel, route))

    for (method, url), rows in sorted(owners.items()):
        if len(rows) <= 1:
            continue
        rendered = []
        for packet_id, rel, route in rows:
            rendered.append(
                f"{packet_id}:{rel}:handler={route.get('handler')}:kind={route.get('handler_kind')}:"
                f"request={route.get('request_type')}:response={route.get('response_type')}:"
                f"status={route.get('success_status')}:auth={route.get('auth_policy')}"
            )
        findings.append(f"duplicate global route {method} {url} -> " + " | ".join(rendered))

    if findings:
        print(f"SOMA global route ownership: BLOCKER={len(findings)}")
        for finding in findings:
            print(f"[BLOCKER] {finding}")
        return 1

    print("SOMA global route ownership: BLOCKER=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
