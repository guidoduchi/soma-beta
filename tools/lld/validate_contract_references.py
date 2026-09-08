#!/usr/bin/env python3
"""Validate implementation-facing JSON contract file/fragment references.

Pass-2 found a stale DTO payload_contract after a command family was split into
new leaves. Existing route/type validators proved that names existed, but did
not prove that an explicit `*.json#fragment` pointer actually resolved.

This checker walks every registered LLD packet and validates string-valued
fields whose key names describe a contract and whose value names a JSON file.
Relative paths resolve from the owning packet root; `spec/...` paths resolve
from repository root. Dotted fragments such as `CommandName.input` resolve
against either direct document keys or a named object in a common registry
collection. JSON Pointer fragments are also supported.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
LLD_ROOT = ROOT / "spec/lld"
REGISTRY_COLLECTIONS = (
    "commands",
    "queries",
    "types",
    "jobs",
    "routes",
    "provided",
    "consumed",
    "state_machines",
)
NAME_KEYS = ("name", "command", "query", "job_type", "contract_id", "id")


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_contract_refs(value: Any, key_path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = key_path + (str(key),)
            if isinstance(child, str) and "contract" in str(key).lower() and ".json" in child:
                yield child_path, child
            yield from iter_contract_refs(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_contract_refs(child, key_path + (str(index),))


def resolve_file(packet_root: Path, raw: str) -> tuple[Path, str]:
    file_part, sep, fragment = raw.partition("#")
    file_part = file_part.strip()
    if file_part.startswith("spec/") or file_part.startswith("tools/") or file_part.startswith("docs/"):
        path = ROOT / file_part
    else:
        path = packet_root / file_part
    return path, fragment.strip() if sep else ""


def decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resolve_json_pointer(doc: Any, fragment: str) -> bool:
    current = doc
    for raw_token in fragment.lstrip("/").split("/") if fragment else []:
        token = decode_pointer_token(raw_token)
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return False
    return True


def descend(current: Any, tokens: list[str]) -> bool:
    for token in tokens:
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return False
    return True


def find_named_object(doc: Any, token: str) -> Any | None:
    if isinstance(doc, dict):
        for collection_name in REGISTRY_COLLECTIONS:
            collection = doc.get(collection_name)
            if isinstance(collection, dict):
                if token in collection:
                    return collection[token]
                values = collection.values()
            elif isinstance(collection, list):
                values = collection
            else:
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                if any(str(item.get(name_key, "")) == token for name_key in NAME_KEYS):
                    return item
        if any(str(doc.get(name_key, "")) == token for name_key in NAME_KEYS):
            return doc
    return None


def resolve_fragment(doc: Any, fragment: str) -> bool:
    if not fragment:
        return True
    if fragment.startswith("/"):
        return resolve_json_pointer(doc, fragment)

    tokens = [token for token in fragment.split(".") if token]
    if not tokens:
        return True
    if descend(doc, tokens):
        return True

    named = find_named_object(doc, tokens[0])
    if named is None:
        return False
    return descend(named, tokens[1:])


def main() -> int:
    findings: list[str] = []
    global_index = load(LLD_ROOT / "_index.json")

    for packet in global_index.get("packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("id", ""))
        packet_root = ROOT / str(packet.get("path", ""))
        if not packet_id or not packet_root.exists():
            continue

        for source_path in sorted(packet_root.rglob("*.json")):
            try:
                source_doc = load(source_path)
            except (OSError, json.JSONDecodeError):
                continue
            for key_path, raw_ref in iter_contract_refs(source_doc):
                target_path, fragment = resolve_file(packet_root, raw_ref)
                rel_source = source_path.relative_to(ROOT)
                field = ".".join(key_path)
                if not target_path.is_file():
                    findings.append(
                        f"{packet_id}:{rel_source}:{field} references missing contract file {raw_ref}"
                    )
                    continue
                if not fragment:
                    continue
                try:
                    target_doc = load(target_path)
                except (OSError, json.JSONDecodeError):
                    findings.append(
                        f"{packet_id}:{rel_source}:{field} references unreadable contract {raw_ref}"
                    )
                    continue
                if not resolve_fragment(target_doc, fragment):
                    findings.append(
                        f"{packet_id}:{rel_source}:{field} references unresolved contract fragment {raw_ref}"
                    )

    if findings:
        print(f"SOMA contract reference closure: HIGH={len(findings)}")
        for finding in findings:
            print(f"[HIGH] {finding}")
        return 1

    print("SOMA contract reference closure: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
