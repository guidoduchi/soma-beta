#!/usr/bin/env python3
"""Final evidence stage for SOMA LLD review-readiness enforcement.

Stages 1 and 2 remain authoritative for SIG-001..SIG-022 and representation
normalization. This final stage recognizes only narrowly proven representation
equivalents that preserve or strengthen the same closure requirements:

* specialized technical migration-ledger idempotency outside application
  COMMAND_ENVELOPE_V1 semantics;
* bounded traceability fragments validated as one logical graph; and
* bounded route fragments that are actively revalidated here and may add new
  BLOCKER/HIGH findings when malformed.

A split representation is never trusted because it exists. The final stage
independently proves the engineering facts that would otherwise live in a
monolithic normative leaf.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW")
NULL_TYPES = {"", "none", "null", "no_body", "empty", "unit", "void"}
GENERIC_ERRORS = {
    "VALIDATION_FAILED", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND",
    "STALE_REVISION", "IDEMPOTENCY_CONFLICT", "PERSISTENCE_BUSY",
    "PERSISTENCE_FAILURE", "INTERNAL_ERROR", "AUDIT_VALIDATION_FAILED",
    "AUDIT_INTEGRITY_FAILURE", "SECURITY_NOT_READY",
}
ROUTE_REQUIRED = {
    "method", "path", "handler_kind", "handler", "request_type",
    "response_type", "success_status", "max_request_bytes", "auth_policy",
    "error_codes",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def packet_roots(repo: Path) -> dict[str, Path]:
    index = load_json(repo / "spec/lld/_index.json")
    return {
        str(item["id"]): repo / str(item["path"])
        for item in index.get("packets", [])
        if isinstance(item, dict) and item.get("id") and item.get("path")
    }


def packet_index(root: Path) -> dict[str, Any]:
    path = root / "_index.json"
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def manifest_paths(root: Path) -> set[str]:
    index = packet_index(root)
    out: set[str] = set()
    for key in ("packet_files", "normative_paths"):
        value = index.get(key, [])
        if isinstance(value, list):
            out.update(str(x) for x in value if isinstance(x, str))
    return out


def iter_json(root: Path) -> Iterable[tuple[Path, Any]]:
    for path in sorted(root.rglob("*.json")):
        try:
            yield path, load_json(path)
        except (OSError, json.JSONDecodeError):
            continue


def trace_fragments(root: Path) -> list[dict[str, Any]]:
    directory = root / "tests/traceability"
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*.json")):
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def fragment_command_edge(root: Path, name: str) -> dict[str, Any] | None:
    found: list[dict[str, Any]] = []
    for doc in trace_fragments(root):
        edges = doc.get("command_edges")
        if isinstance(edges, list):
            found.extend(
                edge for edge in edges
                if isinstance(edge, dict) and edge.get("command") == name
            )
        elif isinstance(edges, dict) and isinstance(edges.get(name), dict):
            found.append(edges[name])
    return found[0] if len(found) == 1 else None


def fragment_query_edge(root: Path, name: str) -> dict[str, Any] | None:
    found: list[dict[str, Any]] = []
    for doc in trace_fragments(root):
        edges = doc.get("query_edges")
        if isinstance(edges, list):
            found.extend(
                edge for edge in edges
                if isinstance(edge, dict) and edge.get("query") == name
            )
        elif isinstance(edges, dict) and isinstance(edges.get(name), dict):
            found.append(edges[name])
    return found[0] if len(found) == 1 else None


def base_handler(value: Any) -> str:
    return re.sub(r"\[[^\]]*\]$", "", str(value)).split("(", 1)[0].strip()


def route_fragment_names(root: Path) -> list[str]:
    path = root / "routes.json"
    if not path.is_file():
        return []
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(doc, dict):
        return []
    value = doc.get("route_fragments", [])
    return [str(x) for x in value if isinstance(x, str)] if isinstance(value, list) else []


def route_rows(root: Path) -> list[dict[str, Any]]:
    paths = [root / "routes.json"] + [root / rel for rel in route_fragment_names(root)]
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("routes"), list):
            rows.extend(row for row in doc["routes"] if isinstance(row, dict))
    return rows


def test_ids(root: Path) -> set[str]:
    out: set[str] = set()
    tests_root = root / "tests"
    if not tests_root.exists():
        return out
    for path, doc in iter_json(tests_root):
        if "traceability" in path.parts or not isinstance(doc, dict):
            continue
        for value in doc.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    out.add(item["id"])
    return out


def audit_variants(root: Path) -> set[str]:
    path = root / "audit/actions.json"
    if not path.is_file():
        return set()
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(doc, dict):
        return set()
    out: set[str] = set()
    for item in doc.get("actions", []) if isinstance(doc.get("actions"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("action_type"), str):
            continue
        action = item["action_type"]
        out.add(action)
        version = item.get("action_version")
        if isinstance(version, int):
            out.add(f"{action}.v{version}")
            out.add(f"{action}@{version}")
    return out


def command_fragment_proves(root: Path, name: str) -> bool:
    edge = fragment_command_edge(root, name)
    if not isinstance(edge, dict):
        return False
    required = {
        "request_type", "response_type", "transaction_boundary",
        "revision_effects", "audit", "errors", "tests", "idempotency",
    }
    if any(key not in edge for key in required):
        return False
    if not all(isinstance(edge.get(key), str) and edge.get(key).strip()
               for key in ("request_type", "response_type", "transaction_boundary",
                           "revision_effects", "idempotency")):
        return False
    if "COMMAND_ENVELOPE_V1" not in str(edge.get("idempotency", "")):
        return False
    errors = edge.get("errors")
    if not isinstance(errors, list) or not errors or not all(isinstance(x, str) and x for x in errors):
        return False
    tests = edge.get("tests")
    known_tests = test_ids(root)
    if not isinstance(tests, list) or not tests or any(str(t) not in known_tests for t in tests):
        return False
    audit = edge.get("audit")
    refs = audit if isinstance(audit, list) else [audit]
    variants = audit_variants(root)
    for ref in refs:
        if str(ref).lower() in {"none", "n/a"}:
            continue
        if str(ref) not in variants:
            return False
    public = any(
        str(row.get("handler_kind", "")).lower() == "command"
        and base_handler(row.get("handler")) == name
        for row in route_rows(root)
    )
    internal = bool(edge.get("internal_caller") or edge.get("internal_callers"))
    return public or internal


def query_fragment_proves(root: Path, name: str) -> bool:
    edge = fragment_query_edge(root, name)
    if not isinstance(edge, dict):
        return False
    ordering = edge.get("ordering")
    pagination = edge.get("pagination")
    indexes = edge.get("required_indexes")
    tests = edge.get("tests")
    if not isinstance(ordering, str) or not ordering.strip():
        return False
    if not isinstance(indexes, list) or not indexes or not all(str(x).strip() for x in indexes):
        return False
    known_tests = test_ids(root)
    if not isinstance(tests, list) or not tests or any(str(t) not in known_tests for t in tests):
        return False
    if isinstance(pagination, dict) and "cursor" in json.dumps(pagination, ensure_ascii=False).lower():
        last = pagination.get("last_key_tuple")
        null_order = pagination.get("null_order")
        if not isinstance(last, list) or not last or not isinstance(null_order, str) or not null_order.strip():
            return False
    elif pagination is None:
        return False
    return True


def split_traceability_proves(repo: Path, roots: dict[str, Path], finding: dict[str, Any]) -> bool:
    packet_id = str(finding.get("packet_id", ""))
    root = roots.get(packet_id)
    if root is None:
        return False
    check = str(finding.get("check_id", ""))
    message = str(finding.get("message", ""))

    match = re.fullmatch(r"retrofit command (.+) has no exact traceability closure edge", message)
    if check == "SIG-004" and match:
        return command_fragment_proves(root, match.group(1))

    match = re.fullmatch(r"command (.+) has no command->tests traceability edge", message)
    if check == "SIG-011" and match:
        return command_fragment_proves(root, match.group(1))

    match = re.fullmatch(r"retrofit query (.+) has no exact traceability edge", message)
    if check == "SIG-013" and match:
        return query_fragment_proves(root, match.group(1))

    return False


def specialized_migration_ledger_proves(repo: Path, finding: dict[str, Any]) -> bool:
    if finding.get("check_id") != "SIG-019" or finding.get("severity") != "HIGH":
        return False
    message = str(finding.get("message", ""))
    prefix = "mutating command "
    suffix = " does not bind COMMAND_ENVELOPE_V1"
    if not (message.startswith(prefix) and message.endswith(suffix)):
        return False
    command = message[len(prefix):-len(suffix)]
    path = repo / str(finding.get("path", ""))
    if not path.is_file():
        return False
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict) or doc.get("name") != command:
        return False

    evidence = " ".join(str(doc.get(key, "")) for key in (
        "name", "visibility", "request_type", "transaction_boundary",
        "idempotency", "receipt_order", "mutations", "revision_effects",
        "audit_action", "post_commit_work"
    )).lower()
    idempotency = str(doc.get("idempotency", "")).lower()
    receipt = str(doc.get("receipt_order", "")).lower()
    revisions = str(doc.get("revision_effects", "")).lower()
    mutations = " ".join(str(x) for x in doc.get("mutations", [])).lower() \
        if isinstance(doc.get("mutations"), list) else str(doc.get("mutations", "")).lower()

    return all((
        "migration" in evidence,
        "ledger" in idempotency,
        "sequence" in idempotency,
        "hash" in idempotency,
        "schema_migrations" in receipt,
        "ledger" in receipt,
        "schema_migrations" in mutations,
        "no domain" in revisions,
        str(doc.get("audit_action", "")).lower().startswith("none"),
    ))


def collect_operation_names(root: Path, family: str) -> set[str]:
    out: set[str] = set()
    prefix = f"{family}/"
    plural = "commands" if family == "commands" else "queries"
    for path, doc in iter_json(root):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith(prefix) or not isinstance(doc, dict):
            continue
        if isinstance(doc.get("name"), str):
            out.add(doc["name"])
        value = doc.get(plural)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.add(item["name"])
    return out


def collect_types(root: Path) -> set[str]:
    out: set[str] = set()
    for path, doc in iter_json(root):
        rel = path.relative_to(root).as_posix()
        if not (rel.startswith("types/") or rel == "interfaces.json") or not isinstance(doc, dict):
            continue
        value = doc.get("types")
        if isinstance(value, dict):
            out.update(str(k) for k in value)
        for key in ("value_types", "payload_types", "result_types"):
            value = doc.get(key)
            if isinstance(value, dict):
                out.update(str(k) for k in value)
        if isinstance(doc.get("name"), str) and "TYPE" in str(doc.get("schema", "")):
            out.add(doc["name"])
    return out


def collect_errors(root: Path) -> set[str]:
    out = set(GENERIC_ERRORS)
    path = root / "errors.json"
    if not path.is_file():
        return out
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return out
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


def synthetic(check_id: str, severity: str, packet_id: str, path: str, message: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "severity": severity,
        "packet_id": packet_id,
        "path": path,
        "message": message,
    }


def validate_route_fragments(repo: Path, roots: dict[str, Path], selected: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for packet_id, root in roots.items():
        if selected and packet_id not in selected:
            continue
        root_path = root / "routes.json"
        if not root_path.is_file():
            continue
        try:
            root_doc = load_json(root_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(root_doc, dict):
            continue
        declared = route_fragment_names(root)
        if not declared:
            continue

        manifest = manifest_paths(root)
        discovered = {
            path.relative_to(root).as_posix()
            for path in sorted((root / "routes").rglob("*.json"))
        } if (root / "routes").is_dir() else set()
        declared_set = set(declared)
        for rel in sorted(discovered - declared_set):
            findings.append(synthetic(
                "SIG-001", "BLOCKER", packet_id,
                (root / rel).relative_to(repo).as_posix(),
                "route fragment exists but is not declared by routes.json",
            ))
        for rel in declared:
            rendered = (root / rel).relative_to(repo).as_posix()
            if not rel.startswith("routes/") or not rel.endswith(".json"):
                findings.append(synthetic(
                    "SIG-003", "BLOCKER", packet_id, rendered,
                    "route_fragments entry must be a packet-relative routes/*.json path",
                ))
                continue
            if rel not in manifest:
                findings.append(synthetic(
                    "SIG-001", "BLOCKER", packet_id, rendered,
                    "declared route fragment is not indexed in packet_files/normative_paths",
                ))
            path = root / rel
            if not path.is_file():
                findings.append(synthetic(
                    "SIG-001", "BLOCKER", packet_id, rendered,
                    "declared route fragment file is missing",
                ))
                continue
            if path.stat().st_size > 12000:
                findings.append(synthetic(
                    "SIG-018", "HIGH", packet_id, rendered,
                    f"normative route fragment is {path.stat().st_size} bytes > 12000 byte AI granularity budget",
                ))
            try:
                doc = load_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(synthetic(
                    "SIG-001", "BLOCKER", packet_id, rendered,
                    f"invalid route fragment JSON: {exc}",
                ))
                continue
            if not isinstance(doc, dict) or doc.get("lld_id") != packet_id:
                findings.append(synthetic(
                    "SIG-003", "BLOCKER", packet_id, rendered,
                    "route fragment must be an object with matching lld_id",
                ))
            if not isinstance(doc, dict) or not isinstance(doc.get("routes"), list):
                findings.append(synthetic(
                    "SIG-003", "BLOCKER", packet_id, rendered,
                    "route fragment routes must be an array",
                ))

        prefix = str(root_doc.get("canonical_api_prefix", "/api/v1"))
        commands = collect_operation_names(root, "commands")
        queries = collect_operation_names(root, "queries")
        types = collect_types(root)
        errors = collect_errors(root)
        seen: dict[str, str] = {}
        sources: list[tuple[str, dict[str, Any]]] = [("routes.json", root_doc)]
        for rel in declared:
            path = root / rel
            if not path.is_file():
                continue
            try:
                doc = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict):
                sources.append((rel, doc))

        for rel, doc in sources:
            value = doc.get("routes")
            if not isinstance(value, list):
                continue
            for ordinal, row in enumerate(value, 1):
                rendered = (root / rel).relative_to(repo).as_posix()
                if not isinstance(row, dict):
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route #{ordinal} is not an object",
                    ))
                    continue
                key = f"{str(row.get('method','')).upper()} {row.get('path','')}".strip()
                if key in seen:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"duplicate route across root/fragments: {key}; first declared in {seen[key]}",
                    ))
                else:
                    seen[key] = rel
                if rel == "routes.json":
                    continue  # stage 1 already validates every root route field.
                missing = sorted(ROUTE_REQUIRED - set(row))
                if missing:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key!r} missing fields: {', '.join(missing)}",
                    ))
                    continue
                path_value = str(row.get("path", ""))
                if not path_value.startswith(prefix):
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key!r} does not use canonical {prefix} prefix",
                    ))
                kind = str(row.get("handler_kind", "")).lower()
                handler = base_handler(row.get("handler"))
                if kind == "command" and handler not in commands:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key} references unknown command handler {row.get('handler')}",
                    ))
                elif kind == "query" and handler not in queries:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key} references unknown query handler {row.get('handler')}",
                    ))
                elif kind not in {"command", "query", "internal", "technical", "stream"}:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key} has unsupported handler_kind {kind!r}",
                    ))
                for field in ("request_type", "response_type"):
                    type_name = row.get(field)
                    if isinstance(type_name, str) and type_name.lower() not in NULL_TYPES and type_name not in types:
                        findings.append(synthetic(
                            "SIG-003", "BLOCKER", packet_id, rendered,
                            f"route {key} references unknown {field} {type_name}",
                        ))
                max_bytes = row.get("max_request_bytes")
                if not isinstance(max_bytes, int) or max_bytes <= 0:
                    findings.append(synthetic(
                        "SIG-022", "MEDIUM", packet_id, rendered,
                        f"route {key} max_request_bytes must be positive integer",
                    ))
                if not isinstance(row.get("success_status"), int) or not 100 <= row["success_status"] <= 599:
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key} success_status must be an HTTP status integer",
                    ))
                auth = row.get("auth_policy")
                if not isinstance(auth, str) or not auth.strip():
                    findings.append(synthetic(
                        "SIG-003", "BLOCKER", packet_id, rendered,
                        f"route {key} auth_policy is empty",
                    ))
                route_errors = row.get("error_codes")
                if not isinstance(route_errors, list):
                    findings.append(synthetic(
                        "SIG-020", "MEDIUM", packet_id, rendered,
                        f"route {key} error_codes must be an array",
                    ))
                else:
                    for code in route_errors:
                        if str(code) not in errors:
                            findings.append(synthetic(
                                "SIG-020", "MEDIUM", packet_id, rendered,
                                f"route {key} references unknown stable error code {code}",
                            ))
    return findings


def summarize(findings: list[dict[str, Any]]) -> dict[str, int]:
    out = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        severity = str(finding.get("severity", ""))
        out[severity] = out.get(severity, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--packet", action="append", default=[])
    parser.add_argument("--enforce", choices=("report", "ai-ready", "review-ready"), default="report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    roots = packet_roots(repo)
    selected = set(args.packet)
    cmd = [sys.executable, str(repo / "tools/lld/enforce_validate_spec.py"),
           "--repo-root", str(repo), "--enforce", "report", "--json"]
    for packet in args.packet:
        cmd.extend(["--packet", packet])
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.stdout.write(proc.stdout)
        return proc.returncode
    try:
        stage2 = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write("FATAL: stage-2 validator did not return valid JSON\n")
        sys.stdout.write(proc.stdout)
        return 2

    active: list[dict[str, Any]] = []
    specialized: list[dict[str, Any]] = []
    split_trace: list[dict[str, Any]] = []
    for finding in stage2.get("findings", []):
        if not isinstance(finding, dict):
            continue
        if specialized_migration_ledger_proves(repo, finding):
            specialized.append({
                **finding,
                "suppression_reason": (
                    "technical migration command proves immutable schema_migrations "
                    "sequence/id/hash ledger idempotency and no domain revision authority"
                ),
            })
        elif split_traceability_proves(repo, roots, finding):
            split_trace.append({
                **finding,
                "suppression_reason": (
                    "bounded traceability fragment independently proves the same command/query "
                    "closure required from the monolithic root graph"
                ),
            })
        else:
            active.append(finding)

    route_fragment_findings = validate_route_fragments(repo, roots, selected)
    active.extend(route_fragment_findings)
    active.sort(key=lambda f: (
        SEVERITIES.index(str(f.get("severity"))) if str(f.get("severity")) in SEVERITIES else 99,
        str(f.get("packet_id", "")), str(f.get("path", "")),
        str(f.get("check_id", "")), str(f.get("message", "")),
    ))
    summary = summarize(active)
    prior_suppressed = int(stage2.get("suppressed_equivalent_findings", 0))
    total_suppressed = prior_suppressed + len(specialized) + len(split_trace)

    if args.json:
        print(json.dumps({
            "schema":"SOMA-AI-LLD-SPEC-INTEGRITY-RESULT-V2-FINAL",
            "enforcement":args.enforce,
            "selected_packets":sorted(args.packet) if args.packet else "all",
            "summary":summary,
            "suppressed_equivalent_findings":total_suppressed,
            "specialized_technical_ledger_equivalents":specialized,
            "bounded_traceability_equivalents":split_trace,
            "route_fragment_findings":route_fragment_findings,
            "findings":active,
        }, indent=2, ensure_ascii=False))
    else:
        print("SOMA LLD integrity (final evidence-normalized): " + " ".join(
            f"{severity}={summary.get(severity, 0)}" for severity in SEVERITIES
        ))
        print(f"Evidence-proved representation equivalents suppressed: {total_suppressed}")
        for finding in active:
            print(f"[{finding.get('severity')}] {finding.get('check_id')} "
                  f"{finding.get('packet_id')} {finding.get('path')}: {finding.get('message')}")

    index = load_json(repo / "spec/lld/_index.json")
    packets = [item for item in index.get("packets", []) if isinstance(item, dict)]
    if selected:
        packets = [item for item in packets if item.get("id") in selected]
    if args.enforce == "review-ready":
        fail_packets = {str(item["id"]) for item in packets if item.get("status") == "review_ready"}
    elif args.enforce == "ai-ready":
        fail_packets = {str(item["id"]) for item in packets if item.get("ai_implementation_ready") is True}
    else:
        fail_packets = set()
    blocking = [finding for finding in active
                if finding.get("severity") in {"BLOCKER", "HIGH"}
                and (finding.get("packet_id") == "GLOBAL"
                     or finding.get("packet_id") in fail_packets)]
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
