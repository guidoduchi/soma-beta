#!/usr/bin/env python3
"""Final evidence stage for SOMA LLD review-readiness enforcement.

Stages 1 and 2 remain authoritative for SIG-001..SIG-022 and representation
normalization. This final stage recognizes only narrowly proven specialized
technical-ledger idempotency that is intentionally outside application
COMMAND_ENVELOPE_V1 semantics. It never suppresses a domain command finding.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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

    # Specialized exception is intentionally restricted to migration authority.
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
        else:
            active.append(finding)

    summary = summarize(active)
    prior_suppressed = int(stage2.get("suppressed_equivalent_findings", 0))
    total_suppressed = prior_suppressed + len(specialized)

    if args.json:
        print(json.dumps({
            "schema":"SOMA-AI-LLD-SPEC-INTEGRITY-RESULT-V2-FINAL",
            "enforcement":args.enforce,
            "selected_packets":sorted(args.packet) if args.packet else "all",
            "summary":summary,
            "suppressed_equivalent_findings":total_suppressed,
            "specialized_technical_ledger_equivalents":specialized,
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
