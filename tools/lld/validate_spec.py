#!/usr/bin/env python3
"""SOMA Beta LLD machine-addressable integrity checker.

The checker enforces the accepted packet contract and SIG-001..SIG-022
cross-reference gate.  It is deliberately fail-closed for review-ready
packets: a missing machine-readable registry is a finding, not an invitation
for an implementation agent to infer the missing design.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

SEVERITY_RANK = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
NORMATIVE_DIRS = {
    "schema", "commands", "queries", "algorithms", "ui", "tests", "types",
    "settings", "audit", "jobs", "transitions", "migrations",
    "implementation", "artifacts", "profiles",
}
ROOT_NORMATIVE = {
    "bounds.json", "errors.json", "interfaces.json", "routes.json",
    "technology.json",
}
NULL_TYPES = {"", "none", "null", "no_body", "empty", "unit", "void"}
GENERIC_ERRORS = {
    "VALIDATION_FAILED", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND",
    "STALE_REVISION", "IDEMPOTENCY_CONFLICT", "PERSISTENCE_BUSY",
    "PERSISTENCE_FAILURE", "INTERNAL_ERROR", "AUDIT_VALIDATION_FAILED",
    "AUDIT_INTEGRITY_FAILURE", "SECURITY_NOT_READY",
}

@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str
    packet_id: str
    path: str
    message: str
    def sort_key(self) -> tuple[int, str, str, str, str]:
        return (
            SEVERITY_RANK.get(self.severity, 99),
            self.packet_id, self.path, self.check_id, self.message
        )

class SpecError(RuntimeError):
    pass

def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpecError(f"required file missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise SpecError(f"not valid UTF-8: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(
            f"invalid JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc

def rel(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()

def add(findings: list[Finding], check_id: str, severity: str,
        packet_id: str, path: Path | str, message: str, repo: Path) -> None:
    rendered = rel(repo, path) if isinstance(path, Path) else path
    findings.append(Finding(check_id, severity, packet_id, rendered, message))

def flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_strings(child)

def iter_json_files(root: Path) -> Iterable[Path]:
    if root.exists():
        yield from (p for p in sorted(root.rglob("*.json")) if p.is_file())

def relative_packet_json(packet_root: Path) -> Iterable[tuple[str, Path]]:
    for path in iter_json_files(packet_root):
        yield path.relative_to(packet_root).as_posix(), path

def packet_manifest_paths(index: dict[str, Any]) -> list[str]:
    packet_files = index.get("packet_files")
    if packet_files is None:
        return []
    return [s for s in flatten_strings(packet_files) if s.endswith(".json")]

def resolve_manifest_path(repo: Path, packet_root: Path, raw: str) -> Path:
    if raw.startswith(("spec/", "tools/", ".github/")):
        return repo / raw
    return packet_root / raw

def accepted_exception_keys(doc: dict[str, Any]) -> set[tuple[str, str, str]]:
    accepted: set[tuple[str, str, str]] = set()
    for item in doc.get("exceptions", []):
        if item.get("accepted_by_owner") is True:
            accepted.add((
                str(item.get("check_id", "")),
                str(item.get("packet_id", "")),
                str(item.get("scope", "")),
            ))
    return accepted

def is_exception(f: Finding, accepted: set[tuple[str, str, str]]) -> bool:
    if f.severity == "BLOCKER":
        return False
    for check_id, packet_id, scope in accepted:
        if check_id != f.check_id or packet_id not in ("*", f.packet_id):
            continue
        if scope in ("*", f.path) or f.path.startswith(scope.rstrip("/") + "/"):
            return True
    return False

def safe_load(path: Path) -> Any | None:
    try:
        return load_json(path)
    except SpecError:
        return None

def packet_docs(packet_root: Path) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    for relative, path in relative_packet_json(packet_root):
        doc = safe_load(path)
        if doc is not None:
            docs[relative] = doc
    return docs

def values_from_named_list(doc: Any, key: str, name_keys: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    if not isinstance(doc, dict):
        return out
    value = doc.get(key)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict):
                for name_key in name_keys:
                    name = item.get(name_key)
                    if isinstance(name, str) and name:
                        out.add(name)
                        break
    return out

def collect_commands(docs: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for path, doc in docs.items():
        if not path.startswith("commands/") or not isinstance(doc, dict):
            continue
        if doc.get("schema") == "SOMA-LLD-COMMAND-V2" and isinstance(doc.get("name"), str):
            out[doc["name"]] = (path, doc)
        for item in doc.get("commands", []) if isinstance(doc.get("commands"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                out[item["name"]] = (path, item)
    return out

def collect_queries(docs: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for path, doc in docs.items():
        if not path.startswith("queries/") or not isinstance(doc, dict):
            continue
        if doc.get("schema") == "SOMA-LLD-QUERY-V2" and isinstance(doc.get("name"), str):
            out[doc["name"]] = (path, doc)
        for item in doc.get("queries", []) if isinstance(doc.get("queries"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                out[item["name"]] = (path, item)
    return out

def collect_types(docs: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for path, doc in docs.items():
        if not (path.startswith("types/") or path == "interfaces.json"):
            continue
        if not isinstance(doc, dict):
            continue
        types = doc.get("types")
        if isinstance(types, dict):
            out.update(str(k) for k in types)
        for key in ("value_types", "payload_types", "result_types"):
            value = doc.get(key)
            if isinstance(value, dict):
                out.update(str(k) for k in value)
        if isinstance(doc.get("name"), str) and "TYPE" in str(doc.get("schema", "")):
            out.add(doc["name"])
    return out

def collect_error_codes(doc: Any) -> set[str]:
    out = set(GENERIC_ERRORS)
    if not isinstance(doc, dict):
        return out
    for key in ("categories", "domain_errors", "errors"):
        value = doc.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                out.add(item["code"])
            elif isinstance(item, list) and item and isinstance(item[0], str):
                out.add(item[0])
    mapping = doc.get("internal_failure_mapping")
    if isinstance(mapping, dict):
        out.update(str(v) for v in mapping.values())
    return out

def audit_registry(doc: Any) -> tuple[set[str], set[str]]:
    actions: set[str] = set()
    payloads: set[str] = set()
    if not isinstance(doc, dict):
        return actions, payloads
    types = doc.get("payload_types")
    if isinstance(types, dict):
        payloads.update(str(k) for k in types)
    for item in doc.get("actions", []) if isinstance(doc.get("actions"), list) else []:
        if not isinstance(item, dict):
            continue
        action_type = item.get("action_type")
        version = item.get("action_version")
        if isinstance(action_type, str):
            actions.add(f"{action_type}.v{version}" if isinstance(version, int) else action_type)
            actions.add(action_type)
        payload = item.get("payload_schema")
        if isinstance(payload, str):
            payloads.add(payload)
    return actions, payloads

def route_key(route: dict[str, Any]) -> str:
    return f"{str(route.get('method', '')).upper()} {route.get('path', '')}".strip()

def traceability_doc(docs: dict[str, Any]) -> dict[str, Any] | None:
    doc = docs.get("tests/traceability.json")
    return doc if isinstance(doc, dict) else None

def trace_command_edges(trace: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not trace:
        return out
    for edge in trace.get("command_edges", []) if isinstance(trace.get("command_edges"), list) else []:
        if isinstance(edge, dict) and isinstance(edge.get("command"), str):
            out[edge["command"]] = edge
    return out

def trace_query_edges(trace: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not trace:
        return out
    for edge in trace.get("query_edges", []) if isinstance(trace.get("query_edges"), list) else []:
        if isinstance(edge, dict) and isinstance(edge.get("query"), str):
            out[edge["query"]] = edge
    return out

def check_json_and_manifest(repo: Path, packet: dict[str, Any],
                            packet_root: Path, index: dict[str, Any],
                            findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    for relative, path in relative_packet_json(packet_root):
        try:
            load_json(path)
        except SpecError as exc:
            add(findings, "SIG-001", "BLOCKER", packet_id, path, str(exc), repo)

    manifest = packet_manifest_paths(index)
    seen: set[str] = set()
    for raw in manifest:
        if raw in seen:
            add(findings, "SIG-001", "BLOCKER", packet_id,
                packet_root / "_index.json", f"duplicate packet_files entry: {raw}", repo)
        seen.add(raw)
        if not resolve_manifest_path(repo, packet_root, raw).is_file():
            add(findings, "SIG-001", "BLOCKER", packet_id,
                packet_root / "_index.json", f"packet_files references missing path: {raw}", repo)

    nonnorm = {
        str(v) for v in flatten_strings(index.get("nonnormative_files", []))
        if str(v).endswith(".json")
    }
    indexed = set(manifest)
    for relative, path in relative_packet_json(packet_root):
        parts = Path(relative).parts
        if not parts:
            continue
        if parts[0] in NORMATIVE_DIRS and relative not in indexed and relative not in nonnorm:
            add(findings, "SIG-001", "BLOCKER", packet_id, path,
                "normative JSON leaf is not indexed in packet_files or explicit nonnormative_files", repo)

def check_required_paths(repo: Path, packet: dict[str, Any],
                         packet_root: Path, index: dict[str, Any],
                         contract: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    if packet.get("status") != "review_ready":
        return
    for raw in contract.get("required_core_paths", []):
        target = packet_root / str(raw).rstrip("/")
        is_dir = str(raw).endswith("/")
        if not (target.is_dir() if is_dir else target.is_file()):
            add(findings, "SIG-001", "BLOCKER", packet_id, target,
                f"required core {'directory' if is_dir else 'file'} missing", repo)
    for prop in contract.get("mandatory_packet_index_properties", []):
        if prop not in index:
            add(findings, "SIG-002", "BLOCKER", packet_id,
                packet_root / "_index.json", f"mandatory packet property missing: {prop}", repo)
    for prop in ("ai_implementation_ready", "owner_accepted"):
        if not isinstance(index.get(prop), bool):
            add(findings, "SIG-002", "BLOCKER", packet_id,
                packet_root / "_index.json", f"{prop} must be boolean", repo)
    if index.get("status") == "review_ready" and index.get("ai_implementation_ready") is True:
        impl = index.get("implementation_gate", {})
        if not (isinstance(impl, dict) and impl.get("review_pass_1") == "PASS"
                and impl.get("review_pass_2") == "PASS"):
            add(findings, "SIG-002", "BLOCKER", packet_id,
                packet_root / "_index.json",
                "ai_implementation_ready=true without explicit PASS for both technical review passes", repo)

def check_route_resolution(repo: Path, packet: dict[str, Any],
                           packet_root: Path, docs: dict[str, Any],
                           contract: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    routes_doc = docs.get("routes.json")
    if not isinstance(routes_doc, dict):
        return
    commands = collect_commands(docs)
    queries = collect_queries(docs)
    types = collect_types(docs)
    errors = collect_error_codes(docs.get("errors.json"))
    required = contract.get("transport_contract", {}).get("required_per_route", [])
    prefix = contract.get("transport_contract", {}).get("canonical_api_prefix", "/api/v1")
    routes = routes_doc.get("routes", [])
    if not isinstance(routes, list):
        add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
            "routes must be an array", repo)
        return
    seen_keys: set[str] = set()
    for ordinal, route in enumerate(routes, 1):
        if not isinstance(route, dict):
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route #{ordinal} is not an object", repo)
            continue
        key = route_key(route)
        if key in seen_keys:
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"duplicate route: {key}", repo)
        seen_keys.add(key)
        path = str(route.get("path", ""))
        if not path.startswith(prefix):
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key!r} does not use canonical {prefix} prefix", repo)
        missing = [field for field in required if field not in route]
        if missing:
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key!r} missing fields: {', '.join(missing)}", repo)
            continue

        kind = str(route.get("handler_kind", "")).lower()
        handler = str(route.get("handler", ""))
        if kind == "command" and handler not in commands:
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key} references unknown command handler {handler}", repo)
        elif kind == "query" and handler not in queries:
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key} references unknown query handler {handler}", repo)
        elif kind not in {"command", "query", "internal", "technical", "stream"}:
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key} has unsupported handler_kind {kind!r}", repo)

        for field in ("request_type", "response_type"):
            value = route.get(field)
            if isinstance(value, str) and value.lower() not in NULL_TYPES and value not in types:
                add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                    f"route {key} references unknown {field} {value}", repo)
        max_bytes = route.get("max_request_bytes")
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            add(findings, "SIG-022", "MEDIUM", packet_id, packet_root / "routes.json",
                f"route {key} max_request_bytes must be positive integer", repo)
        auth = route.get("auth_policy")
        if not isinstance(auth, str) or not auth.strip():
            add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                f"route {key} auth_policy is empty", repo)
        route_errors = route.get("error_codes")
        if not isinstance(route_errors, list):
            add(findings, "SIG-020", "MEDIUM", packet_id, packet_root / "routes.json",
                f"route {key} error_codes must be an array", repo)
        else:
            for code in route_errors:
                if str(code) not in errors:
                    add(findings, "SIG-020", "MEDIUM", packet_id, packet_root / "routes.json",
                        f"route {key} references unknown stable error code {code}", repo)

def flatten_test_ids(docs: dict[str, Any]) -> Iterable[str]:
    for path, doc in docs.items():
        if not path.startswith("tests/") or path.endswith("traceability.json"):
            continue
        if not isinstance(doc, dict):
            continue
        for key in ("cases", "scenarios", "tests", "failure_cases"):
            value = doc.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        yield item["id"]
        for value in doc.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        yield item["id"]

def check_command_closure(repo: Path, packet: dict[str, Any],
                          packet_root: Path, docs: dict[str, Any],
                          contract: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    commands = collect_commands(docs)
    routes_doc = docs.get("routes.json")
    routes = routes_doc.get("routes", []) if isinstance(routes_doc, dict) else []
    route_commands: dict[str, list[dict[str, Any]]] = {}
    for r in routes if isinstance(routes, list) else []:
        if isinstance(r, dict) and str(r.get("handler_kind", "")).lower() == "command":
            route_commands.setdefault(str(r.get("handler", "")), []).append(r)
    trace = traceability_doc(docs)
    edges = trace_command_edges(trace)
    required = set(contract.get("command_leaf_contract", {}).get("required", []))
    tests = set(flatten_test_ids(docs))

    if commands and trace is None:
        add(findings, "SIG-010", "HIGH", packet_id, packet_root / "tests/traceability.json",
            "authoritative commands exist but tests/traceability.json is missing", repo)

    for name, (path, command) in commands.items():
        edge = edges.get(name)
        is_v2 = str(command.get("schema", "")).startswith("SOMA-LLD-COMMAND-V2")
        if is_v2:
            missing = sorted(k for k in required if k not in command)
            if missing:
                add(findings, "SIG-004", "BLOCKER", packet_id, packet_root / path,
                    f"command {name} missing V2 fields: {', '.join(missing)}", repo)
        else:
            closure_required = {
                "request_type", "response_type", "transaction_boundary",
                "revision_effects", "audit", "errors", "tests"
            }
            if edge is None:
                add(findings, "SIG-004", "BLOCKER", packet_id, packet_root / path,
                    f"retrofit command {name} has no exact traceability closure edge", repo)
            else:
                missing = sorted(k for k in closure_required if k not in edge)
                if missing:
                    add(findings, "SIG-004", "BLOCKER", packet_id,
                        packet_root / "tests/traceability.json",
                        f"command edge {name} missing closure fields: {', '.join(missing)}", repo)

        if edge is None:
            add(findings, "SIG-011", "HIGH", packet_id,
                packet_root / "tests/traceability.json",
                f"command {name} has no command->tests traceability edge", repo)
            continue
        edge_tests = edge.get("tests")
        if not isinstance(edge_tests, list) or not edge_tests:
            add(findings, "SIG-011", "HIGH", packet_id,
                packet_root / "tests/traceability.json",
                f"command {name} has no success/precondition test IDs", repo)
        else:
            for test_id in edge_tests:
                if str(test_id) not in tests:
                    add(findings, "SIG-011", "HIGH", packet_id,
                        packet_root / "tests/traceability.json",
                        f"command {name} references unknown test id {test_id}", repo)

        public_routes = route_commands.get(name, [])
        if not public_routes and "internal_caller" not in edge and "internal_callers" not in edge:
            add(findings, "SIG-004", "BLOCKER", packet_id,
                packet_root / "tests/traceability.json",
                f"command {name} resolves neither public route nor internal caller", repo)

        idempotency = command.get("idempotency") if is_v2 else edge.get("idempotency")
        if name not in {"StartHost", "ShutdownHost"}:
            if not isinstance(idempotency, str) or "COMMAND_ENVELOPE_V1" not in idempotency:
                add(findings, "SIG-019", "HIGH", packet_id,
                    packet_root / (path if is_v2 else "tests/traceability.json"),
                    f"mutating command {name} does not bind COMMAND_ENVELOPE_V1", repo)

def check_audit_closure(repo: Path, packet: dict[str, Any],
                        packet_root: Path, docs: dict[str, Any],
                        findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    commands = collect_commands(docs)
    if not commands:
        return
    action_doc = docs.get("audit/actions.json")
    if not isinstance(action_doc, dict):
        add(findings, "SIG-005", "BLOCKER", packet_id,
            packet_root / "audit/actions.json",
            "packet owns authoritative commands but audit/actions.json is missing", repo)
        return
    actions, payloads = audit_registry(action_doc)
    for item in action_doc.get("actions", []) if isinstance(action_doc.get("actions"), list) else []:
        if not isinstance(item, dict):
            continue
        for field in ("action_type", "action_version", "payload_schema", "payload_version",
                      "target_policy", "result_refs", "sensitivity"):
            if field not in item:
                add(findings, "SIG-005", "BLOCKER", packet_id,
                    packet_root / "audit/actions.json",
                    f"audit action missing {field}: {item.get('action_type','?')}", repo)
        payload = item.get("payload_schema")
        if isinstance(payload, str) and payload not in payloads:
            add(findings, "SIG-005", "BLOCKER", packet_id,
                packet_root / "audit/actions.json",
                f"audit action references missing payload schema {payload}", repo)
    trace = traceability_doc(docs)
    for name, edge in trace_command_edges(trace).items():
        audit = edge.get("audit")
        if audit in (None, "none", "NONE"):
            continue
        refs = audit if isinstance(audit, list) else [audit]
        for ref in refs:
            if str(ref) not in actions:
                add(findings, "SIG-005", "BLOCKER", packet_id,
                    packet_root / "tests/traceability.json",
                    f"command {name} references unknown audit action {ref}", repo)

def check_setting_registry(repo: Path, packet: dict[str, Any],
                           packet_root: Path, docs: dict[str, Any],
                           findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    refs: set[str] = set()
    for path, doc in docs.items():
        if path.startswith("settings/"):
            continue
        for text in flatten_strings(doc):
            refs.update(re.findall(r"\b[A-Z][A-Z0-9_]{3,}_V\d+\b", text))
    semantic_refs: set[str] = set()
    for path, doc in docs.items():
        if path.startswith("settings/"):
            continue
        serialized = json.dumps(doc, ensure_ascii=False)
        for ref in refs:
            near = re.search(rf"(?i)(setting|config)[^\"']{{0,80}}\b{re.escape(ref)}\b|\b{re.escape(ref)}\b[^\"']{{0,80}}(?i:setting|config)", serialized)
            if near:
                semantic_refs.add(ref)
    if not semantic_refs:
        return
    settings_docs = [doc for path, doc in docs.items() if path.startswith("settings/") and isinstance(doc, dict)]
    if not settings_docs:
        add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
            f"semantic setting references exist ({', '.join(sorted(semantic_refs))}) but settings registry is missing", repo)
        return
    definitions: dict[str, dict[str, Any]] = {}
    for doc in settings_docs:
        for key in ("settings", "definitions"):
            for item in doc.get(key, []) if isinstance(doc.get(key), list) else []:
                if isinstance(item, dict):
                    name = item.get("key") or item.get("setting_key") or item.get("id")
                    if isinstance(name, str):
                        definitions[name] = item
    required_fields = {"key", "owner", "version", "default", "validator", "equality", "storage", "bounds", "value_contract"}
    for ref in sorted(semantic_refs):
        item = definitions.get(ref)
        if item is None:
            add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
                f"referenced semantic setting {ref} is not registered", repo)
            continue
        category_ok = {
            "key": any(k in item for k in ("key", "setting_key", "id")),
            "owner": any(k in item for k in ("owner", "semantic_owner")),
            "version": any(k in item for k in ("version", "contract_version")),
            "default": any(k in item for k in ("default", "default_provider")),
            "validator": any(k in item for k in ("validator", "validation")),
            "equality": any(k in item for k in ("equality", "semantic_equality")),
            "storage": any(k in item for k in ("storage", "storage_class")),
            "bounds": "bounds" in item,
            "value_contract": any(k in item for k in ("value_contract", "type", "type_contract")),
        }
        missing = [k for k in required_fields if not category_ok[k]]
        if missing:
            add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
                f"setting {ref} missing semantic categories: {', '.join(missing)}", repo)

def check_jobs(repo: Path, packet: dict[str, Any], packet_root: Path,
               docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    trace = traceability_doc(docs)
    job_edges = trace.get("job_edges", []) if isinstance(trace, dict) else []
    serialized = " ".join(flatten_strings(docs))
    looks_durable = bool(re.search(r"\bdurable job\b|\benqueue\b|\bcheckpoint\b", serialized, re.I))
    if not job_edges and not looks_durable:
        return
    job_docs = [doc for path, doc in docs.items() if path.startswith("jobs/") and isinstance(doc, dict)]
    if not job_docs:
        add(findings, "SIG-007", "BLOCKER", packet_id, packet_root / "jobs",
            "durable-job behavior exists but jobs registry is missing", repo)
        return
    registry: dict[str, dict[str, Any]] = {}
    for doc in job_docs:
        if isinstance(doc.get("job_type"), str):
            registry[doc["job_type"]] = doc
        for item in doc.get("jobs", []) if isinstance(doc.get("jobs"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("job_type"), str):
                registry[item["job_type"]] = item
    required = {
        "job_type", "contract_version", "payload_schema", "checkpoint_schema",
        "retry_policy", "crash_recovery_policy", "cancellation_policy",
        "sensitive_field_policy", "coalescing"
    }
    for edge in job_edges if isinstance(job_edges, list) else []:
        if not isinstance(edge, dict):
            continue
        job_type = str(edge.get("job_type", ""))
        item = registry.get(job_type)
        if item is None:
            add(findings, "SIG-007", "BLOCKER", packet_id, packet_root / "jobs",
                f"traceability references unregistered job_type {job_type}", repo)
            continue
        missing = [f for f in required if f not in item and not (f == "coalescing" and "dedup_policy" in item)]
        if missing:
            add(findings, "SIG-007", "BLOCKER", packet_id, packet_root / "jobs",
                f"job {job_type} missing fields: {', '.join(missing)}", repo)
        if not item.get("unknown_version_fail_closed", True):
            add(findings, "SIG-007", "BLOCKER", packet_id, packet_root / "jobs",
                f"job {job_type} does not fail closed on unknown versions", repo)

def check_traceability(repo: Path, packet: dict[str, Any], packet_root: Path,
                       index: dict[str, Any], docs: dict[str, Any],
                       findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    trace = traceability_doc(docs)
    if packet.get("status") != "review_ready":
        return
    if trace is None:
        add(findings, "SIG-010", "HIGH", packet_id, packet_root / "tests/traceability.json",
            "review-ready packet lacks machine-readable traceability graph", repo)
        return
    requirement_edges = trace.get("requirement_edges")
    if not isinstance(requirement_edges, dict):
        add(findings, "SIG-010", "HIGH", packet_id, packet_root / "tests/traceability.json",
            "requirement_edges is missing", repo)
        return
    governing = index.get("requirement_ids", [])
    supporting = set(str(x) for x in index.get("supporting_requirement_ids", []))
    manifest = set(packet_manifest_paths(index))
    for req in governing if isinstance(governing, list) else []:
        req = str(req)
        edges = requirement_edges.get(req)
        if not isinstance(edges, list) or not edges:
            add(findings, "SIG-010", "HIGH", packet_id, packet_root / "tests/traceability.json",
                f"governing requirement {req} has no normative coverage edge", repo)
            continue
        has_test = False
        has_normative = False
        for target in edges:
            target = str(target)
            if target.startswith("tests/"):
                has_test = True
            if target in manifest and not target.startswith("tests/"):
                has_normative = True
            if target.endswith(".json") and target not in manifest:
                add(findings, "SIG-010", "HIGH", packet_id,
                    packet_root / "tests/traceability.json",
                    f"requirement {req} references non-manifest path {target}", repo)
        if not has_test or not has_normative:
            add(findings, "SIG-010", "HIGH", packet_id,
                packet_root / "tests/traceability.json",
                f"requirement {req} must map to both normative leaf and test", repo)
    for req in requirement_edges:
        if req in supporting and req not in set(str(x) for x in governing):
            meta = trace.get("supporting_requirement_edges", {})
            if not isinstance(meta, dict) or req not in meta:
                add(findings, "SIG-010", "HIGH", packet_id,
                    packet_root / "tests/traceability.json",
                    f"supporting requirement {req} appears in governing requirement_edges without explicit supporting classification", repo)

def check_queries(repo: Path, packet: dict[str, Any], packet_root: Path,
                  docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    queries = collect_queries(docs)
    trace = traceability_doc(docs)
    edges = trace_query_edges(trace)
    test_ids = set(flatten_test_ids(docs))
    required_v2 = {
        "name", "input_type", "response_type", "read_consistency",
        "ordering", "pagination", "required_indexes", "errors",
        "acceptance_test_ids",
    }
    for name, (path, query) in queries.items():
        is_v2 = str(query.get("schema", "")).startswith("SOMA-LLD-QUERY-V2")
        if is_v2:
            missing = sorted(f for f in required_v2 if f not in query)
            if missing:
                add(findings, "SIG-013", "HIGH", packet_id, packet_root / path,
                    f"query {name} missing V2 fields: {', '.join(missing)}", repo)
            ordering = query.get("ordering")
            pagination = query.get("pagination")
            indexes = query.get("required_indexes")
            tests = query.get("acceptance_test_ids")
        else:
            edge = edges.get(name)
            if edge is None:
                add(findings, "SIG-013", "HIGH", packet_id,
                    packet_root / "tests/traceability.json",
                    f"retrofit query {name} has no exact traceability edge", repo)
                continue
            ordering = edge.get("ordering")
            pagination = edge.get("pagination")
            indexes = edge.get("required_indexes")
            tests = edge.get("tests")
        if not ordering:
            add(findings, "SIG-013", "HIGH", packet_id,
                packet_root / (path if is_v2 else "tests/traceability.json"),
                f"query {name} lacks deterministic total ordering", repo)
        if pagination and "cursor" in str(pagination).lower():
            text = json.dumps(pagination, ensure_ascii=False)
            if "null" not in text.lower() or "last" not in text.lower():
                add(findings, "SIG-013", "HIGH", packet_id,
                    packet_root / (path if is_v2 else "tests/traceability.json"),
                    f"paged query {name} does not pin cursor key/null ordering", repo)
        if not isinstance(indexes, list) or not indexes:
            add(findings, "SIG-013", "HIGH", packet_id,
                packet_root / (path if is_v2 else "tests/traceability.json"),
                f"query {name} declares no supporting index", repo)
        if not isinstance(tests, list) or not tests:
            add(findings, "SIG-011", "HIGH", packet_id,
                packet_root / (path if is_v2 else "tests/traceability.json"),
                f"query {name} has no acceptance test IDs", repo)
        else:
            for test in tests:
                if str(test) not in test_ids:
                    add(findings, "SIG-011", "HIGH", packet_id,
                        packet_root / (path if is_v2 else "tests/traceability.json"),
                        f"query {name} references unknown test {test}", repo)

def check_migrations(repo: Path, packet: dict[str, Any], packet_root: Path,
                     docs: dict[str, Any], global_migrations: dict[str, Any],
                     findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    schema_docs = [doc for path, doc in docs.items() if path.startswith("schema/") and isinstance(doc, dict)]
    owns_schema = any(
        isinstance(doc.get("tables"), list) and doc.get("tables")
        for doc in schema_docs
    )
    if not owns_schema:
        return
    allocations = [
        a for a in global_migrations.get("allocations", [])
        if isinstance(a, dict) and str(a.get("packet_id")) == packet_id
    ] if isinstance(global_migrations, dict) else []
    if len(allocations) != 1:
        add(findings, "SIG-009", "BLOCKER", packet_id,
            "spec/lld/migrations.json",
            f"expected exactly one global migration allocation, found {len(allocations)}", repo)
        return
    migration_docs = [
        (path, doc) for path, doc in docs.items()
        if path.startswith("migrations/") and isinstance(doc, dict)
    ]
    if not migration_docs:
        add(findings, "SIG-009", "BLOCKER", packet_id, packet_root / "migrations",
            "schema-owning packet lacks packet migration object allocation manifest", repo)
        return
    declared_objects: list[str] = []
    for _, doc in migration_docs:
        for key in ("objects", "schema_objects", "allocated_objects"):
            value = doc.get(key)
            if isinstance(value, list):
                declared_objects.extend(str(v) for v in value)
    if not declared_objects:
        add(findings, "SIG-009", "BLOCKER", packet_id, packet_root / "migrations",
            "packet migration manifest does not enumerate owned schema objects", repo)

def check_implementation_map(repo: Path, packet: dict[str, Any],
                             packet_root: Path, docs: dict[str, Any],
                             findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    if packet.get("status") != "review_ready":
        return
    maps = [
        doc for path, doc in docs.items()
        if path.startswith("implementation/") and isinstance(doc, dict)
    ]
    if not maps:
        add(findings, "SIG-015", "HIGH", packet_id, packet_root / "implementation",
            "review-ready packet lacks implementation module map", repo)
        return
    mapped: set[str] = set()
    for doc in maps:
        for key in ("commands", "queries", "repositories", "services", "routes", "jobs", "modules"):
            value = doc.get(key)
            if isinstance(value, dict):
                mapped.update(str(k) for k in value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for name_key in ("name", "command", "query", "route", "job_type", "interface"):
                            if isinstance(item.get(name_key), str):
                                mapped.add(item[name_key]); break
                    elif isinstance(item, str):
                        mapped.add(item)
    for name in collect_commands(docs):
        if name not in mapped:
            add(findings, "SIG-015", "HIGH", packet_id, packet_root / "implementation",
                f"command {name} has no source-module destination", repo)
    for name in collect_queries(docs):
        if name not in mapped:
            add(findings, "SIG-015", "HIGH", packet_id, packet_root / "implementation",
                f"query {name} has no source-module destination", repo)

def check_transitions(repo: Path, packet: dict[str, Any], packet_root: Path,
                      docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    schema_text = " ".join(
        json.dumps(doc, ensure_ascii=False)
        for path, doc in docs.items() if path.startswith("schema/")
    )
    state_enum_count = len(re.findall(r"(?:state|status|lifecycle)[^)]*IN\s*\(", schema_text, re.I))
    correction = bool(re.search(r"correction|restore|reactivate|reversal", schema_text, re.I))
    if state_enum_count == 0 and not correction:
        return
    transition_docs = [
        doc for path, doc in docs.items()
        if path.startswith("transitions/") and isinstance(doc, dict)
    ]
    if not transition_docs:
        add(findings, "SIG-014", "HIGH", packet_id, packet_root / "transitions",
            "governed multi-state/correction semantics exist but transitions registry is missing", repo)
        return
    matrices = []
    for doc in transition_docs:
        if isinstance(doc.get("transitions"), list):
            matrices.extend(doc["transitions"])
        if isinstance(doc.get("state_machines"), list):
            matrices.extend(doc["state_machines"])
    if not matrices:
        add(findings, "SIG-014", "HIGH", packet_id, packet_root / "transitions",
            "transitions registry contains no machine-readable transition entries", repo)

def check_schema_policy(repo: Path, packet: dict[str, Any], packet_root: Path,
                        docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    schema_docs = [
        (path, doc) for path, doc in docs.items()
        if path.startswith("schema/") and isinstance(doc, dict)
    ]
    if not schema_docs:
        return
    combined = json.dumps([doc for _, doc in schema_docs], ensure_ascii=False)
    if "STRICT" not in combined:
        add(findings, "SIG-012", "HIGH", packet_id, packet_root / "schema",
            "schema family does not declare authoritative SQLite STRICT policy", repo)
    fk_evidence = any(
        "fk-index" in path or "foreign" in path.lower()
        or "required_indexes" in doc or "indexes" in doc
        for path, doc in schema_docs
    )
    if not fk_evidence:
        add(findings, "SIG-012", "HIGH", packet_id, packet_root / "schema",
            "schema family lacks machine-readable FK/supporting-index closure evidence", repo)

def check_artifacts(repo: Path, packet: dict[str, Any], packet_root: Path,
                    docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    serialized = " ".join(flatten_strings(docs))
    generates = bool(re.search(r"\b(generate|write|export|artifact|xlsx|msg)\b", serialized, re.I))
    index = docs.get("_index.json")
    not_owned = " ".join(index.get("not_owned_here", [])) if isinstance(index, dict) else ""
    owns = generates and not ("artifact" in not_owned.lower() and "->" in not_owned)
    artifact_docs = [
        doc for path, doc in docs.items()
        if path.startswith("artifacts/") and isinstance(doc, dict)
    ]
    if owns and not artifact_docs:
        command_text = " ".join(
            flatten_strings(doc) for path, doc in docs.items()
            if path.startswith(("commands/", "jobs/"))
        )
        if re.search(r"\b(generate|write|export).*(artifact|xlsx|msg)|\b(artifact|xlsx|msg).*(generate|write|export)", command_text, re.I):
            add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                "packet generates/verifies artifacts but has no versioned artifacts registry", repo)
            return
    for doc in artifact_docs:
        required = {"format_contract", "writer", "verifier", "temporary_policy", "finalization_policy", "collision_policy"}
        missing = sorted(f for f in required if f not in doc)
        if missing:
            add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                f"artifact contract missing fields: {', '.join(missing)}", repo)

def check_leaf_granularity(repo: Path, packet: dict[str, Any],
                           packet_root: Path, index: dict[str, Any],
                           findings: list[Finding]) -> None:
    limit = 12000
    allowed = {
        str(item.get("path"))
        for item in index.get("granularity_exceptions", [])
        if isinstance(item, dict) and item.get("accepted") is True
    }
    for relative, path in relative_packet_json(packet_root):
        parts = Path(relative).parts
        is_normative = (
            (parts and parts[0] in NORMATIVE_DIRS)
            or relative in ROOT_NORMATIVE
        )
        if is_normative and relative != "_index.json" and path.stat().st_size > limit and relative not in allowed:
            add(findings, "SIG-018", "HIGH", str(packet["id"]), path,
                f"normative leaf is {path.stat().st_size} bytes > {limit} byte AI granularity budget", repo)

def compile_placeholder_patterns(gate: dict[str, Any]) -> list[re.Pattern[str]]:
    for check in gate.get("checks", []):
        if isinstance(check, dict) and check.get("id") == "SIG-017":
            return [re.compile(str(raw), re.I) for raw in check.get("patterns", [])]
    return []

def check_placeholders(repo: Path, packet: dict[str, Any], packet_root: Path,
                       patterns: list[re.Pattern[str]], findings: list[Finding]) -> None:
    if packet.get("status") != "review_ready":
        return
    for relative, path in relative_packet_json(packet_root):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                snippet = re.sub(r"\s+", " ", text[max(0, match.start()-70):match.end()+100])
                add(findings, "SIG-017", "HIGH", str(packet["id"]), path,
                    f"potential unresolved design placeholder matched /{pattern.pattern}/: {snippet[:240]}", repo)
                break

def check_bounds(repo: Path, packet: dict[str, Any], packet_root: Path,
                 docs: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = str(packet["id"])
    if not isinstance(docs.get("bounds.json"), dict):
        add(findings, "SIG-022", "MEDIUM", packet_id, packet_root / "bounds.json",
            "bounds registry missing", repo)
        return
    serialized = " ".join(flatten_strings(docs))
    if re.search(r"\bunbounded\b", serialized, re.I) and not re.search(r"no unbounded|never unbounded|bounded", serialized, re.I):
        add(findings, "SIG-022", "MEDIUM", packet_id, packet_root,
            "operator-controlled unbounded materialization language detected", repo)

def check_interfaces_global(repo: Path, packet_data: list[tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]],
                            findings: list[Finding]) -> None:
    providers: dict[str, set[str]] = {}
    consumers: dict[str, set[str]] = {}
    for packet, root, index, docs in packet_data:
        packet_id = str(packet["id"])
        trace = traceability_doc(docs)
        if not trace:
            continue
        for edge in trace.get("cross_packet", []) if isinstance(trace.get("cross_packet"), list) else []:
            if not isinstance(edge, dict):
                continue
            iface = str(edge.get("interface", "")).strip()
            provider = str(edge.get("provider", "")).strip()
            consumer = str(edge.get("consumer", packet_id)).strip()
            if not iface:
                continue
            if provider:
                providers.setdefault(iface, set()).add(provider)
            if consumer:
                consumers.setdefault(iface, set()).add(consumer)
    for iface, consumer_set in consumers.items():
        provider_set = providers.get(iface, set())
        if len(provider_set) != 1:
            add(findings, "SIG-008", "BLOCKER", "GLOBAL",
                "spec/lld/_index.json",
                f"cross-packet interface {iface!r} consumed by {sorted(consumer_set)} has {len(provider_set)} providers: {sorted(provider_set)}", repo)

def check_global_index(repo: Path, lld_index: dict[str, Any],
                       findings: list[Finding]) -> None:
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    expected = [f"LLD-{n:02d}" for n in range(1, 13)]
    actual: list[str] = []
    for packet in lld_index.get("packets", []):
        packet_id = str(packet.get("id", "GLOBAL"))
        actual.append(packet_id)
        packet_path = str(packet.get("path", ""))
        if packet_id in seen_ids:
            add(findings, "SIG-001", "BLOCKER", "GLOBAL", "spec/lld/_index.json",
                f"duplicate packet id: {packet_id}", repo)
        if packet_path in seen_paths:
            add(findings, "SIG-001", "BLOCKER", "GLOBAL", "spec/lld/_index.json",
                f"duplicate packet path: {packet_path}", repo)
        seen_ids.add(packet_id); seen_paths.add(packet_path)
        if packet.get("ai_implementation_ready") is not False and packet.get("status") != "review_ready":
            add(findings, "SIG-002", "BLOCKER", packet_id, "spec/lld/_index.json",
                "only a review_ready packet may claim ai_implementation_ready", repo)
    if actual != expected:
        add(findings, "SIG-001", "BLOCKER", "GLOBAL", "spec/lld/_index.json",
            f"packet registry must contain exactly ordered {expected}; got {actual}", repo)

def summarize(findings: list[Finding]) -> dict[str, int]:
    summary = {level: 0 for level in SEVERITY_RANK}
    for finding in findings:
        summary[finding.severity] = summary.get(finding.severity, 0) + 1
    return summary

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--packet", action="append", default=[])
    parser.add_argument("--enforce", choices=("report", "ai-ready", "review-ready"), default="report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    try:
        lld_index = load_json(repo / "spec/lld/_index.json")
        contract = load_json(repo / "spec/lld/_packet-contract-v2.json")
        gate = load_json(repo / "spec/lld/_integrity-gate.json")
        global_migrations = load_json(repo / "spec/lld/migrations.json")
        exceptions_path = repo / "spec/lld/exceptions.json"
        exceptions_doc = load_json(exceptions_path) if exceptions_path.exists() else {"exceptions": []}
    except SpecError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    if lld_index.get("schema") != "SOMA-LLD-INDEX-V2":
        print("FATAL: spec/lld/_index.json is not SOMA-LLD-INDEX-V2", file=sys.stderr)
        return 2

    selected = set(args.packet)
    known = {p.get("id") for p in lld_index.get("packets", [])}
    if selected - known:
        print(f"FATAL: unknown packet id(s): {', '.join(sorted(selected-known))}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    check_global_index(repo, lld_index, findings)
    patterns = compile_placeholder_patterns(gate)
    packets = [
        p for p in lld_index.get("packets", [])
        if not selected or p.get("id") in selected
    ]
    packet_data: list[tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]] = []

    for packet in packets:
        packet_id = str(packet["id"])
        packet_root = repo / str(packet["path"])
        if not packet_root.exists():
            if packet.get("status") != "planned":
                add(findings, "SIG-001", "BLOCKER", packet_id, packet_root,
                    f"{packet.get('status')} packet directory does not exist", repo)
            continue
        index_path = packet_root / "_index.json"
        index = safe_load(index_path)
        if not isinstance(index, dict):
            add(findings, "SIG-001", "BLOCKER", packet_id, index_path,
                "packet index missing or invalid", repo)
            index = {}
        docs = packet_docs(packet_root)
        packet_data.append((packet, packet_root, index, docs))

        check_json_and_manifest(repo, packet, packet_root, index, findings)
        check_required_paths(repo, packet, packet_root, index, contract, findings)
        check_route_resolution(repo, packet, packet_root, docs, contract, findings)
        check_command_closure(repo, packet, packet_root, docs, contract, findings)
        check_audit_closure(repo, packet, packet_root, docs, findings)
        check_setting_registry(repo, packet, packet_root, docs, findings)
        check_jobs(repo, packet, packet_root, docs, findings)
        check_traceability(repo, packet, packet_root, index, docs, findings)
        check_queries(repo, packet, packet_root, docs, findings)
        check_migrations(repo, packet, packet_root, docs, global_migrations, findings)
        check_schema_policy(repo, packet, packet_root, docs, findings)
        check_transitions(repo, packet, packet_root, docs, findings)
        check_implementation_map(repo, packet, packet_root, docs, findings)
        check_artifacts(repo, packet, packet_root, docs, findings)
        check_placeholders(repo, packet, packet_root, patterns, findings)
        check_leaf_granularity(repo, packet, packet_root, index, findings)
        check_bounds(repo, packet, packet_root, docs, findings)

    check_interfaces_global(repo, packet_data, findings)

    accepted = accepted_exception_keys(exceptions_doc)
    active = sorted((f for f in findings if not is_exception(f, accepted)), key=Finding.sort_key)
    summary = summarize(active)

    if args.json:
        print(json.dumps({
            "schema": "SOMA-AI-LLD-SPEC-INTEGRITY-RESULT-V2",
            "enforcement": args.enforce,
            "selected_packets": sorted(selected) if selected else "all",
            "summary": summary,
            "findings": [asdict(f) for f in active],
        }, indent=2, ensure_ascii=False))
    else:
        print("SOMA LLD integrity: " + " ".join(
            f"{k}={summary.get(k,0)}" for k in SEVERITY_RANK
        ))
        for finding in active:
            print(f"[{finding.severity}] {finding.check_id} {finding.packet_id} {finding.path}: {finding.message}")

    if args.enforce == "ai-ready":
        fail_packets = {
            str(p["id"]) for p in packets
            if p.get("ai_implementation_ready") is True
        }
    elif args.enforce == "review-ready":
        fail_packets = {
            str(p["id"]) for p in packets
            if p.get("status") == "review_ready"
        }
    else:
        fail_packets = set()

    blocking = [
        f for f in active
        if f.severity in {"BLOCKER", "HIGH"}
        and (f.packet_id == "GLOBAL" or f.packet_id in fail_packets)
    ]
    return 1 if blocking else 0

if __name__ == "__main__":
    raise SystemExit(main())
