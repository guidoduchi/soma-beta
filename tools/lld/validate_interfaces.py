#!/usr/bin/env python3
"""Fail-closed SOMA SIG-008 cross-packet interface closure validator.

Unlike the legacy SIG-008 implementation, this checker does not treat a
traceability edge's claimed provider as proof that the provider exists. It
builds the provider registry from normative interface declarations, builds
consumer expectations independently, and then reconciles provider identity,
method signatures, versioned type contracts, and shared-UoW/read-only
transaction semantics.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Decl:
    name: str
    packet_id: str
    role: str
    provider: str | None
    methods: tuple[str, ...]
    types: tuple[str, ...]
    tx_kind: str | None
    path: str


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str
    packet_id: str
    path: str
    message: str


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_sig(value: Any) -> str:
    text = str(value).strip()
    text = text.replace("→", "->")
    return re.sub(r"\s+", "", text)


def norm_types(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted(norm_sig(x) for x in value if isinstance(x, str) and x.strip()))


def methods_of(item: dict[str, Any]) -> tuple[str, ...]:
    raw = item.get("methods")
    if isinstance(raw, list):
        return tuple(sorted(norm_sig(x) for x in raw if isinstance(x, str) and x.strip()))
    method = item.get("method")
    if isinstance(method, str) and method.strip():
        return (norm_sig(method),)
    return ()


def first_owner_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\bLLD-(\d{2})\b", value)
    return f"LLD-{match.group(1)}" if match else None


def tx_kind(item: dict[str, Any]) -> str | None:
    text = " ".join(
        str(item.get(key, ""))
        for key in ("transaction", "rule", "contract")
    ).lower().replace("-", " ")
    if not text.strip():
        return None
    if "caller" in text and ("unitofwork" in text.replace(" ", "") or "uow" in text):
        return "caller_uow"
    if "same" in text and ("unitofwork" in text.replace(" ", "") or "uow" in text):
        return "caller_uow"
    if "no nested" in text and ("commit" in text or "receipt" in text):
        return "caller_uow"
    if "read only" in text or "read-only" in text:
        return "read_only"
    if "pure allocator" in text or "pure query" in text or "pure read" in text:
        return "read_only"
    return None


def interface_docs(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
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
        if isinstance(doc, dict):
            yield path, doc


def add_decl(out: list[Decl], packet_id: str, role: str,
             provider: str | None, item: dict[str, Any], path: Path, repo: Path) -> None:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return
    out.append(Decl(
        name=name.strip(), packet_id=packet_id, role=role, provider=provider,
        methods=methods_of(item), types=norm_types(item.get("types")),
        tx_kind=tx_kind(item), path=path.relative_to(repo).as_posix(),
    ))


def declarations(repo: Path, packet_id: str, root: Path) -> list[Decl]:
    out: list[Decl] = []
    for path, doc in interface_docs(root):
        # Explicit V2 registry form.
        for item in doc.get("provided", []) if isinstance(doc.get("provided"), list) else []:
            if isinstance(item, dict):
                add_decl(out, packet_id, "provider", packet_id, item, path, repo)
        for item in doc.get("consumed", []) if isinstance(doc.get("consumed"), list) else []:
            if isinstance(item, dict):
                provider = first_owner_id(item.get("provider"))
                add_decl(out, packet_id, "consumer", provider, item, path, repo)

        # V2/V1 packet interface documents use several historical keys. Role is
        # derived from the owner, never from the key name alone.
        for key in ("providers", "foundation", "composition_interfaces",
                    "consumed_interfaces", "python_interfaces"):
            value = doc.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                owner = first_owner_id(item.get("owner"))
                if key == "consumed_interfaces" and owner is None:
                    role, provider = "consumer", None
                elif owner is None or owner == packet_id:
                    role, provider = "provider", packet_id
                else:
                    role, provider = "consumer", owner
                add_decl(out, packet_id, role, provider, item, path, repo)
    return out


def trace_consumers(repo: Path, packet_id: str, root: Path) -> list[Decl]:
    path = root / "tests/traceability.json"
    if not path.is_file():
        return []
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(doc, dict):
        return []
    out: list[Decl] = []
    edges = doc.get("cross_packet")
    if not isinstance(edges, list):
        return out
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        name = edge.get("interface")
        if not isinstance(name, str) or not name.strip():
            continue
        consumer = first_owner_id(edge.get("consumer")) or packet_id
        if consumer != packet_id:
            continue
        provider = first_owner_id(edge.get("provider"))
        out.append(Decl(
            name=name.strip(), packet_id=packet_id, role="trace_consumer",
            provider=provider, methods=(), types=(), tx_kind=None,
            path=path.relative_to(repo).as_posix(),
        ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    index = load_json(repo / "spec/lld/_index.json")
    packets = [p for p in index.get("packets", []) if isinstance(p, dict)]

    all_decls: list[Decl] = []
    traces: list[Decl] = []
    for packet in packets:
        packet_id = str(packet.get("id", ""))
        root = repo / str(packet.get("path", ""))
        all_decls.extend(declarations(repo, packet_id, root))
        traces.extend(trace_consumers(repo, packet_id, root))

    providers: dict[str, list[Decl]] = {}
    consumers: dict[tuple[str, str], list[Decl]] = {}
    for decl in all_decls:
        if decl.role == "provider":
            providers.setdefault(decl.name, []).append(decl)
        elif decl.role == "consumer":
            consumers.setdefault((decl.name, decl.packet_id), []).append(decl)
    for decl in traces:
        consumers.setdefault((decl.name, decl.packet_id), []).append(decl)

    findings: list[Finding] = []
    for (name, consumer_id), rows in sorted(consumers.items()):
        actual = providers.get(name, [])
        actual_packets = sorted({d.packet_id for d in actual})
        expected_packets = sorted({d.provider for d in rows if d.provider})
        if len(actual_packets) != 1:
            findings.append(Finding(
                "SIG-008", "BLOCKER", "GLOBAL", "spec/lld/_index.json",
                f"cross-packet interface {name!r} consumed by {consumer_id} has "
                f"{len(actual_packets)} actual provider packets {actual_packets}; "
                f"consumer claims are not provider proof",
            ))
            continue
        provider_id = actual_packets[0]
        if expected_packets and expected_packets != [provider_id]:
            findings.append(Finding(
                "SIG-008", "BLOCKER", consumer_id, rows[0].path,
                f"interface {name!r} expects provider {expected_packets} but actual owner-side "
                f"declaration is {provider_id}",
            ))

        # Require one canonical owner-side shape. Multiple identical declarations
        # in the same provider packet are tolerated; divergent duplicates are not.
        provider_shapes = {(d.methods, d.types, d.tx_kind) for d in actual}
        if len(provider_shapes) != 1:
            findings.append(Finding(
                "SIG-008", "BLOCKER", provider_id, actual[0].path,
                f"interface {name!r} has divergent duplicate provider declarations in {provider_id}",
            ))
            continue
        provider = actual[0]
        concrete_consumers = [d for d in rows if d.role == "consumer"]
        if not concrete_consumers:
            findings.append(Finding(
                "SIG-008", "BLOCKER", consumer_id, rows[0].path,
                f"interface {name!r} exists only as a traceability claim for {consumer_id}; "
                "no normative consumer-side interface declaration exists",
            ))
            continue
        for consumer in concrete_consumers:
            if not provider.methods:
                findings.append(Finding(
                    "SIG-008", "BLOCKER", provider_id, provider.path,
                    f"provider declaration for {name!r} has no machine-readable method signatures",
                ))
            elif not consumer.methods:
                findings.append(Finding(
                    "SIG-008", "BLOCKER", consumer_id, consumer.path,
                    f"consumer declaration for {name!r} has no machine-readable method signatures",
                ))
            elif consumer.methods != provider.methods:
                findings.append(Finding(
                    "SIG-008", "BLOCKER", consumer_id, consumer.path,
                    f"interface {name!r} method mismatch: consumer={list(consumer.methods)} "
                    f"provider={list(provider.methods)}",
                ))
            if consumer.types:
                if not provider.types:
                    findings.append(Finding(
                        "SIG-008", "BLOCKER", provider_id, provider.path,
                        f"interface {name!r} consumer declares versioned/types contract but provider does not",
                    ))
                elif consumer.types != provider.types:
                    findings.append(Finding(
                        "SIG-008", "BLOCKER", consumer_id, consumer.path,
                        f"interface {name!r} type mismatch: consumer={list(consumer.types)} "
                        f"provider={list(provider.types)}",
                    ))
            if consumer.tx_kind and provider.tx_kind and consumer.tx_kind != provider.tx_kind:
                findings.append(Finding(
                    "SIG-008", "BLOCKER", consumer_id, consumer.path,
                    f"interface {name!r} transaction mismatch: consumer={consumer.tx_kind} "
                    f"provider={provider.tx_kind}",
                ))

    findings.sort(key=lambda f: (f.packet_id, f.path, f.message))
    if args.json:
        print(json.dumps({
            "schema":"SOMA-SIG-008-INTERFACE-CLOSURE-V1",
            "summary":{"BLOCKER":len(findings)},
            "findings":[asdict(f) for f in findings],
        }, indent=2, ensure_ascii=False))
    else:
        print(f"SOMA SIG-008 interface closure: BLOCKER={len(findings)}")
        for finding in findings:
            print(f"[BLOCKER] SIG-008 {finding.packet_id} {finding.path}: {finding.message}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
