#!/usr/bin/env python3
"""Pass-2 validation for internal command DTO and replay determinism.

Internal worker/cross-packet commands are not public routes, so route validation
cannot prove their request/response contracts. This checker requires every
traceability edge with an internal caller to resolve named request/response
DTOs and requires concrete command_id authority whenever the edge claims
COMMAND_ENVELOPE_V1 idempotency.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LLD_ROOT = ROOT / "spec/lld"
NULL_TYPES = {"", "none", "null", "unit", "void", "no_body"}


def load(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_json(root: Path):
    for path in sorted(root.rglob("*.json")):
        try:
            yield path, load(path)
        except (OSError, json.JSONDecodeError):
            continue


def normalize_type_name(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(internal|optional|bounded)\s+", "", text, flags=re.I)
    return text.strip()


def collect_types(root: Path) -> set[str]:
    out: set[str] = set()
    for path, doc in iter_json(root / "types") if (root / "types").exists() else []:
        if not isinstance(doc, dict):
            continue
        value = doc.get("types")
        if isinstance(value, dict):
            out.update(str(k) for k in value.keys())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.add(item["name"])
        if isinstance(doc.get("name"), str):
            out.add(doc["name"])
    return out


def collect_commands(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    commands_root = root / "commands"
    if not commands_root.exists():
        return out
    for _, doc in iter_json(commands_root):
        if not isinstance(doc, dict):
            continue
        if isinstance(doc.get("name"), str):
            out.setdefault(doc["name"], doc)
        value = doc.get("commands")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.setdefault(item["name"], item)
    return out


def collect_internal_edges(root: Path) -> list[dict]:
    out: list[dict] = []
    trace_root = root / "tests/traceability"
    if not trace_root.exists():
        return out
    for _, doc in iter_json(trace_root):
        if not isinstance(doc, dict):
            continue
        edges = doc.get("command_edges")
        rows = []
        if isinstance(edges, list):
            rows = [e for e in edges if isinstance(e, dict)]
        elif isinstance(edges, dict):
            rows = [e for e in edges.values() if isinstance(e, dict)]
        for edge in rows:
            if edge.get("internal_caller") or edge.get("internal_callers"):
                out.append(edge)
    return out


def command_has_command_id(command: dict) -> bool:
    inputs = command.get("input", [])
    if isinstance(inputs, list):
        return any("command_id" == str(x).strip() or "command_id" in str(x) for x in inputs)
    return "command_id" in json.dumps(inputs, sort_keys=True)


def main() -> int:
    findings: list[str] = []
    global_index = load(LLD_ROOT / "_index.json")

    for packet in global_index.get("packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("id", ""))
        root = ROOT / str(packet.get("path", ""))
        if not packet_id or not root.exists():
            continue
        types = collect_types(root)
        commands = collect_commands(root)
        for edge in collect_internal_edges(root):
            name = str(edge.get("command", "")).strip()
            if not name:
                findings.append(f"{packet_id} internal command trace edge lacks command name")
                continue
            request_type = normalize_type_name(edge.get("request_type"))
            response_type = normalize_type_name(edge.get("response_type"))
            if request_type.lower() not in NULL_TYPES and request_type not in types:
                findings.append(f"{packet_id}:{name} internal request type is undefined: {request_type}")
            if response_type.lower() not in NULL_TYPES and response_type not in types:
                findings.append(f"{packet_id}:{name} internal response type is undefined: {response_type}")

            idempotency = str(edge.get("idempotency", ""))
            if "COMMAND_ENVELOPE_V1" in idempotency:
                command = commands.get(name)
                if not command:
                    findings.append(f"{packet_id}:{name} trace claims COMMAND_ENVELOPE_V1 but command definition is unresolved")
                elif not command_has_command_id(command):
                    findings.append(f"{packet_id}:{name} claims COMMAND_ENVELOPE_V1 but authoritative command input has no command_id")

    if findings:
        print(f"SOMA internal command determinism: HIGH={len(findings)}")
        for finding in findings:
            print(f"[HIGH] {finding}")
        return 1

    print("SOMA internal command determinism: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
