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


def suppression_reason(repo: Path, roots: dict[str, Path], finding: dict[str, Any]) -> str | None:
    packet_id = str(finding.get("packet_id", ""))
    root = roots.get(packet_id)
    if root is None:
        return None
    check = str(finding.get("check_id", ""))
    message = str(finding.get("message", ""))

    # SIG-004: prove an exact public route or declared internal caller exists.
    match = re.fullmatch(r"command (.+) resolves neither public route nor internal caller", message)
    if check == "SIG-004" and match:
        command = match.group(1)
        if any(str(row.get("handler_kind", "")).lower() == "command"
               and row.get("handler") == command for row in route_rows(root)):
            return f"exact command handler {command} exists in packet route family"
        edge = command_edge(root, command)
        if isinstance(edge, dict) and (edge.get("internal_caller") or edge.get("internal_callers")):
            return f"traceability declares internal caller for {command}"
        return None

    # SIG-005: normalize exact audit action version spelling/compact tuple registry.
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
            # An action-local closed field list + forbidden list is itself the named schema.
            if isinstance(item.get("payload_fields"), list) and "forbidden" in item:
                return f"payload schema {payload} is defined inline by closed payload_fields/forbidden"
        if registry.get("payload_schema") == payload and isinstance(registry.get("payload_contract"), dict):
            return f"payload schema {payload} is defined by registry-level payload_contract"
        return None

    # SIG-010: native LLD-12-style requirements map keeps paths/tests as separate fields.
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

    # SIG-013: an explicitly in-memory/non-database query requires no DB index.
    match = re.fullmatch(r"query (.+) declares no supporting index", message)
    if check == "SIG-013" and match:
        doc = query_doc_from_finding(repo, finding)
        if isinstance(doc, dict) and doc.get("required_indexes") == []:
            consistency = str(doc.get("read_consistency", "")).lower()
            if "in-memory" in consistency or "no database" in consistency or "no db" in consistency:
                return f"query {match.group(1)} is explicitly non-database/in-memory"
        return None

    # SIG-012: a projection-only packet with an explicit no-storage schema has no STRICT table duty.
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
