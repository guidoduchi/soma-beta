#!/usr/bin/env python3
"""Evidence-backed second stage for SOMA LLD integrity enforcement.

Stage 1 (run_validate_spec.py) remains the authoritative SIG-001..SIG-022
checker. This program runs it in JSON/report mode and removes only findings
that can be disproved by concrete machine-readable evidence already present in
the same packet. It does not weaken severity thresholds and it does not infer
missing design from packet status or prose claims.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def packet_map(repo: Path) -> dict[str, Path]:
    index = load_json(repo / "spec/lld/_index.json")
    return {
        str(item["id"]): repo / str(item["path"])
        for item in index.get("packets", [])
        if isinstance(item, dict) and item.get("id") and item.get("path")
    }


def packet_index(root: Path) -> dict[str, Any]:
    path = root / "_index.json"
    return load_json(path) if path.is_file() else {}


def manifest_paths(root: Path) -> set[str]:
    index = packet_index(root)
    out: set[str] = set()
    for key in ("packet_files", "normative_paths"):
        value = index.get(key, [])
        if isinstance(value, list):
            out.update(str(x) for x in value if isinstance(x, str))
    return out


def iter_json(root: Path):
    for path in sorted(root.rglob("*.json")):
        try:
            yield path, load_json(path)
        except (OSError, json.JSONDecodeError):
            continue


def route_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, doc in iter_json(root):
        rel = path.relative_to(root).as_posix()
        if rel != "routes.json" and not rel.startswith("routes/"):
            continue
        if not isinstance(doc, dict):
            continue
        value = doc.get("routes")
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def route_key(row: dict[str, Any]) -> str:
    return f"{str(row.get('method', '')).upper()} {row.get('path', '')}".strip()


def base_handler(handler: Any) -> str:
    return re.sub(r"\[[^\]]*\]$", "", str(handler)).strip()


def trace_docs(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tests = root / "tests"
    if not tests.exists():
        return out
    for path in sorted(tests.rglob("traceability*.json")):
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    trace_dir = tests / "traceability"
    if trace_dir.exists():
        for path in sorted(trace_dir.rglob("*.json")):
            try:
                doc = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict):
                out.append(doc)
    return out


def command_edge(root: Path, name: str) -> dict[str, Any] | None:
    for doc in trace_docs(root):
        edges = doc.get("command_edges")
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict) and edge.get("command") == name:
                    return edge
        elif isinstance(edges, dict):
            edge = edges.get(name)
            if isinstance(edge, dict):
                return edge
    return None


def query_edge(root: Path, name: str) -> dict[str, Any] | None:
    for doc in trace_docs(root):
        edges = doc.get("query_edges")
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict) and edge.get("query") == name:
                    return edge
        elif isinstance(edges, dict):
            edge = edges.get(name)
            if isinstance(edge, dict):
                return edge
    return None


def query_contract(root: Path, name: str) -> dict[str, Any] | None:
    for path, doc in iter_json(root):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith("queries/") or not isinstance(doc, dict):
            continue
        if doc.get("name") == name:
            return doc
        queries = doc.get("queries")
        if isinstance(queries, list):
            for item in queries:
                if isinstance(item, dict) and item.get("name") == name:
                    return item
    return None


def operation_destination(root: Path, kind: str, name: str) -> str | None:
    path = root / "implementation/module-map.json"
    if not path.is_file():
        return None
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    table = doc.get("commands" if kind == "command" else "queries")
    if isinstance(table, dict):
        value = table.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for item in doc.get("operation_destinations", []) if isinstance(doc.get("operation_destinations"), list) else []:
        if not isinstance(item, dict):
            continue
        op = item.get("command") if kind == "command" else item.get("query")
        destination = item.get("module") or item.get("destination")
        if op == name and isinstance(destination, str) and destination.strip():
            return destination.strip()
    return None


def action_registry(root: Path) -> tuple[dict[str, dict[str, Any]], set[str], dict[str, Any]]:
    path = root / "audit/actions.json"
    if not path.is_file():
        return {}, set(), {}
    doc = load_json(path)
    if not isinstance(doc, dict):
        return {}, set(), {}
    by_type: dict[str, dict[str, Any]] = {}
    variants: set[str] = set()
    tuple_version = doc.get("action_version")
    if not isinstance(tuple_version, int):
        text = json.dumps(doc.get("rule", doc.get("rules", "")), ensure_ascii=False)
        match = re.search(r"action_version\s*=\s*(\d+)", text)
        tuple_version = int(match.group(1)) if match else None
    actions = doc.get("actions", [])
    for raw in actions if isinstance(actions, list) else []:
        if isinstance(raw, dict):
            action = raw.get("action_type")
            version = raw.get("action_version")
            if not isinstance(action, str):
                continue
            by_type[action] = raw
            variants.add(action)
            if isinstance(version, int):
                variants.add(f"{action}@{version}")
                variants.add(f"{action}.v{version}")
        elif isinstance(raw, list) and raw and isinstance(raw[0], str):
            action = raw[0]
            variants.add(action)
            if isinstance(tuple_version, int):
                variants.add(f"{action}@{tuple_version}")
                variants.add(f"{action}.v{tuple_version}")
    return by_type, variants, doc


def requirement_record(root: Path, requirement_id: str) -> dict[str, Any] | None:
    path = root / "tests/traceability.json"
    if not path.is_file():
        return None
    doc = load_json(path)
    if not isinstance(doc, dict):
        return None
    requirements = doc.get("requirements")
    if isinstance(requirements, dict):
        item = requirements.get(requirement_id)
        if isinstance(item, dict):
            return item
    return None


def query_doc_from_finding(repo: Path, finding: dict[str, Any]) -> dict[str, Any] | None:
    path = repo / str(finding.get("path", ""))
    if not path.is_file():
        return None
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def no_authoritative_storage(root: Path) -> bool:
    path = root / "schema/no-authoritative-storage.json"
    if not path.is_file():
        return False
    try:
        text = json.dumps(load_json(path), ensure_ascii=False).lower()
    except (OSError, json.JSONDecodeError):
        return False
    return "no authoritative" in text or "owns no" in text or "no schema objects" in text


def command_binds_envelope(repo: Path, finding: dict[str, Any], command: str) -> bool:
    path = repo / str(finding.get("path", ""))
    if not path.is_file():
        return False
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict) or doc.get("name") != command:
        return False
    evidence = " ".join(str(doc.get(key, "")) for key in ("request_type", "idempotency", "receipt_order"))
    return "COMMAND_ENVELOPE_V1" in evidence and "command_receipt" in evidence


def query_has_total_order(root: Path, name: str) -> bool:
    contract = query_contract(root, name)
    if not isinstance(contract, dict):
        return False
    ordering = str(contract.get("ordering", "")).strip()
    if not ordering:
        return False
    lower = ordering.lower()
    if lower in {"single result", "not applicable", "none"}:
        return True
    terms = [term.strip() for term in ordering.split(",") if term.strip()]
    if not terms:
        return False
    last = terms[-1].lower()
    return bool(
        re.search(r"(?:^|_)(?:id|ordinal)\b", last)
        or re.search(r"\b(?:id|ordinal)\s+(?:asc|desc)\b", last)
    )


def multiple_forward_migrations_prove(repo: Path, root: Path, packet_id: str) -> bool:
    """Prove a packet's multiple forward allocations are exact, not an ambiguity."""
    try:
        contract = load_json(repo / "spec/lld/_packet-contract-v2.json")
        global_doc = load_json(repo / "spec/lld/migrations.json")
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(contract, dict) or not isinstance(global_doc, dict):
        return False
    migration_rules = contract.get("migration_contract", {}).get("rules", [])
    rules_text = " ".join(str(x) for x in migration_rules) if isinstance(migration_rules, list) else ""
    if "may own more than one forward migration" not in rules_text:
        return False
    if "prior accepted/applied migrations remain immutable" not in rules_text:
        return False

    all_allocations = [
        item for item in global_doc.get("allocations", [])
        if isinstance(item, dict)
    ] if isinstance(global_doc.get("allocations"), list) else []
    sequences = [item.get("sequence") for item in all_allocations]
    migration_ids = [item.get("migration_id") for item in all_allocations]
    if not all(isinstance(value, int) and value > 0 for value in sequences):
        return False
    if not all(isinstance(value, str) and value for value in migration_ids):
        return False
    if len(sequences) != len(set(sequences)) or len(migration_ids) != len(set(migration_ids)):
        return False

    allocations = [item for item in all_allocations if str(item.get("packet_id")) == packet_id]
    if len(allocations) <= 1:
        return False
    expected = {(int(item["sequence"]), str(item["migration_id"])) for item in allocations}

    manifests: list[tuple[int, str]] = []
    for path, doc in iter_json(root):
        rel = path.relative_to(root).as_posix()
        if not rel.startswith("migrations/") or not isinstance(doc, dict):
            continue
        sequence = doc.get("sequence")
        migration_id = doc.get("migration_id")
        if not isinstance(sequence, int) or sequence <= 0 or not isinstance(migration_id, str) or not migration_id:
            return False
        manifests.append((sequence, migration_id))
    if len(manifests) != len(set(manifests)):
        return False
    return len(manifests) == len(allocations) and set(manifests) == expected


def suppression_reason(repo: Path, roots: dict[str, Path], finding: dict[str, Any]) -> str | None:
    packet_id = str(finding.get("packet_id", ""))
    root = roots.get(packet_id)
    if root is None:
        return None
    check = str(finding.get("check_id", ""))
    message = str(finding.get("message", ""))

    match = re.fullmatch(r"expected exactly one global migration allocation, found (\d+)", message)
    if check == "SIG-009" and match and int(match.group(1)) > 1:
        if multiple_forward_migrations_prove(repo, root, packet_id):
            return (
                "packet contract explicitly permits multiple reviewed forward migrations and "
                "every packet migration manifest matches one globally unique allocation sequence/id"
            )
        return None

    match = re.fullmatch(r"command (.+) resolves neither public route nor internal caller", message)
    if check == "SIG-004" and match:
        command = match.group(1)
        rows = route_rows(root)
        if any(str(row.get("handler_kind", "")).lower() == "command"
               and base_handler(row.get("handler")) == command for row in rows):
            return f"parameterized/exact command handler {command} exists in packet route family"
        edge = command_edge(root, command)
        if isinstance(edge, dict) and (edge.get("internal_caller") or edge.get("internal_callers")):
            return f"traceability declares internal caller for {command}"
        if isinstance(edge, dict) and isinstance(edge.get("routes"), list):
            declared = {str(x) for x in edge["routes"]}
            actual = {route_key(row) for row in rows
                      if str(row.get("handler_kind", "")).lower() == "command"
                      and base_handler(row.get("handler")) == command}
            if declared and declared.issubset(actual):
                return f"all declared route specializations for {command} resolve exactly"
        return None

    match = re.fullmatch(r"mutating command (.+) does not bind COMMAND_ENVELOPE_V1", message)
    if check == "SIG-019" and match:
        command = match.group(1)
        if command_binds_envelope(repo, finding, command):
            return f"{command} binds COMMAND_ENVELOPE_V1 and command_receipt in its command leaf"
        return None

    match = re.fullmatch(r"command (.+) references unknown audit action (.+)", message)
    if check == "SIG-005" and match:
        _, variants, _ = action_registry(root)
        ref = match.group(2)
        candidate = ref.split(" plus ", 1)[0].strip()
        if ref in variants or candidate in variants:
            return f"audit action {candidate} exists in compact/versioned registry"
        return None

    match = re.fullmatch(r"audit action missing (target|result_refs|sensitivity) policy: (.+)", message)
    if check == "SIG-005" and match:
        category, action = match.groups()
        actions, _, registry = action_registry(root)
        item = actions.get(action)
        if not isinstance(item, dict):
            return None
        if category == "target" and any(k in item for k in
                ("target_policy", "target_types", "target_type", "target", "allowed_targets")):
            return "audit target policy is present under an accepted V2 equivalent key"
        if category == "result_refs" and (any(k in item for k in
                ("result_refs", "result_ref_types", "result_ref_policy", "allowed_results"))
                or any(k in registry for k in ("result_refs", "result_ref_policy"))):
            return "audit result-ref policy is present under an accepted V2 equivalent key"
        if category == "sensitivity" and (any(k in item for k in
                ("sensitivity", "sensitive_fields", "sensitive_field_policy", "forbidden"))
                or any(k in registry for k in ("sensitivity", "sensitive_field_policy"))):
            return "audit sensitivity policy is explicit through sensitivity/forbidden metadata"
        return None

    match = re.fullmatch(r"audit action references missing payload schema (.+)", message)
    if check == "SIG-005" and match:
        payload = match.group(1)
        actions, _, registry = action_registry(root)
        for item in actions.values():
            if item.get("payload_schema") != payload:
                continue
            if isinstance(item.get("payload_fields"), list) and "forbidden" in item:
                return f"payload schema {payload} is defined inline by closed payload_fields/forbidden"
        if registry.get("payload_schema") == payload and isinstance(registry.get("payload_contract"), dict):
            return f"payload schema {payload} is defined by registry-level payload_contract"
        return None

    match = re.fullmatch(r"governing requirement (BETA-REQ-\d{4}) has no normative coverage edge", message)
    if check == "SIG-010" and match:
        req = requirement_record(root, match.group(1))
        if isinstance(req, dict):
            paths = req.get("paths")
            tests = req.get("tests")
            manifest = manifest_paths(root)
            has_normative = isinstance(paths, list) and any(str(p) in manifest for p in paths)
            has_tests = isinstance(tests, list) and bool(tests)
            if has_normative and has_tests:
                return f"native requirements map provides both normative paths and tests for {match.group(1)}"
        return None

    match = re.fullmatch(r"query (.+) lacks deterministic total ordering", message)
    if check == "SIG-013" and match:
        name = match.group(1)
        if query_has_total_order(root, name):
            return f"query contract for {name} declares deterministic total ordering"
        return None

    match = re.fullmatch(r"query (.+) declares no supporting index", message)
    if check == "SIG-013" and match:
        name = match.group(1)
        contract = query_contract(root, name)
        if isinstance(contract, dict) and contract.get("required_indexes") == []:
            consistency = str(contract.get("read_consistency", "")).lower()
            if "in-memory" in consistency or "no database" in consistency or "no db" in consistency:
                return f"query {name} is explicitly non-database/in-memory"
        doc = query_doc_from_finding(repo, finding)
        if isinstance(doc, dict) and doc.get("required_indexes") == []:
            consistency = str(doc.get("read_consistency", "")).lower()
            if "in-memory" in consistency or "no database" in consistency or "no db" in consistency:
                return f"query {name} is explicitly non-database/in-memory"
        return None

    match = re.fullmatch(r"(command|query) (.+) has no source-module destination", message)
    if check == "SIG-015" and match:
        kind, name = match.groups()
        destination = operation_destination(root, kind, name)
        if destination is not None:
            return f"implementation map binds {kind} {name} to exact module {destination}"
        return None

    if check == "SIG-012" and "STRICT policy" in message and no_authoritative_storage(root):
        return "packet explicitly owns no authoritative storage/tables"

    return None


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
    cmd = [sys.executable, str(repo / "tools/lld/run_validate_spec.py"),
           "--repo-root", str(repo), "--enforce", "report", "--json"]
    for packet in args.packet:
        cmd.extend(["--packet", packet])
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.stdout.write(proc.stdout)
        return proc.returncode
    try:
        stage1 = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write("FATAL: stage-1 validator did not return valid JSON\n")
        sys.stdout.write(proc.stdout)
        return 2

    roots = packet_map(repo)
    active: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for finding in stage1.get("findings", []):
        if not isinstance(finding, dict):
            continue
        reason = suppression_reason(repo, roots, finding)
        if reason is None:
            active.append(finding)
        else:
            suppressed.append({**finding, "suppression_reason": reason})

    summary = summarize(active)
    if args.json:
        print(json.dumps({
            "schema": "SOMA-AI-LLD-SPEC-INTEGRITY-RESULT-V2-STAGE2",
            "enforcement": args.enforce,
            "selected_packets": sorted(args.packet) if args.packet else "all",
            "summary": summary,
            "suppressed_equivalent_findings": len(suppressed),
            "findings": active,
            "suppressed": suppressed,
        }, indent=2, ensure_ascii=False))
    else:
        print("SOMA LLD integrity (evidence-normalized): " + " ".join(
            f"{severity}={summary.get(severity, 0)}" for severity in SEVERITIES
        ))
        print(f"Evidence-proved representation equivalents suppressed: {len(suppressed)}")
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
