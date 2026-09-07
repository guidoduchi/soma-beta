#!/usr/bin/env python3
"""Require every canonical SIG-008 interface registry to be packet-manifest normative."""
from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_paths(index: dict) -> set[str]:
    out: set[str] = set()
    for key in ("packet_files", "normative_paths"):
        value = index.get(key)
        if isinstance(value, list):
            out.update(str(x) for x in value if isinstance(x, str))
    return out


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    global_index = load_json(repo / "spec/lld/_index.json")
    findings: list[str] = []
    for packet in global_index.get("packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("id", "GLOBAL"))
        root = repo / str(packet.get("path", ""))
        index_path = root / "_index.json"
        if not index_path.is_file():
            continue
        manifest = manifest_paths(load_json(index_path))
        candidates = [root / "interfaces.json"]
        subdir = root / "interfaces"
        if subdir.is_dir():
            candidates.extend(sorted(subdir.rglob("*.json")))
        for path in candidates:
            if not path.is_file():
                continue
            try:
                doc = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(doc, dict) or doc.get("schema") != "SOMA-LLD-INTERFACE-REGISTRY-V2":
                continue
            rel = path.relative_to(root).as_posix()
            # Root interfaces.json is already a mandatory packet-core path.
            if rel == "interfaces.json":
                continue
            if rel not in manifest:
                findings.append(
                    f"[BLOCKER] SIG-001 {packet_id} {path.relative_to(repo).as_posix()}: "
                    "canonical cross-packet interface registry is not indexed in packet_files/normative_paths"
                )
    print(f"SOMA canonical interface manifest closure: BLOCKER={len(findings)}")
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
