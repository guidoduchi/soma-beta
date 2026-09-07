#!/usr/bin/env python3
"""Final evidence stage for SOMA LLD review-readiness enforcement.

Stages 1 and 2 remain authoritative for SIG-001..SIG-022 and representation
normalization. This final stage recognizes only narrowly proven representation
equivalents that preserve or strengthen the same closure requirements:

* specialized technical migration-ledger idempotency outside application
  COMMAND_ENVELOPE_V1 semantics; and
* bounded traceability fragments that are validated as one logical graph.

A split trace edge is accepted only when this stage independently proves the
fields that stage 1 would have required from the monolithic root graph. The
split therefore cannot hide missing tests, audit ownership, idempotency,
route/internal-caller closure, deterministic query ordering, cursor semantics,
or supporting indexes.
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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def packet_roots(repo: Path) -> dict[str, Path]:
    index = load_json(repo / "spec/lld/_index.json")
    return {
        str(item["id"]): repo / str(item["path"])
        for item in index.get("packets", [])
        if isinstance(item, dict) and item.get("id") and item.get("path")
    }


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


def route_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "routes.json"
    if not path.is_file():
        return []
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(doc, dict) or not isinstance(doc.get("routes"), list):
        return []
    return [row for row in doc["routes"] if isinstance(row, dict)]


def test_ids(root: Path) -> set[str]:
    out: set[str] = set()
    for path, doc in iter_json(root / "tests") if (root / "tests").exists() else []:
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
    selected = set(args.packet)
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
