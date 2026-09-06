#!/usr/bin/env python3
"""SOMA AI-first LLD specification integrity checker.

This tool validates the machine-addressable design surface under spec/lld.
It intentionally supports a retrofit mode: existing review-ready packets may
report V2 findings while ai_implementation_ready is false, but any packet that
claims ai_implementation_ready must pass with zero BLOCKER/HIGH findings.

Standard library only; safe for offline design/release checks.
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
NORMATIVE_DIRS = {"schema", "commands", "queries", "algorithms", "ui", "tests", "types", "settings", "audit", "jobs", "transitions", "migrations", "implementation", "artifacts"}


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str
    packet_id: str
    path: str
    message: str

    def sort_key(self) -> tuple[int, str, str, str]:
        return (SEVERITY_RANK.get(self.severity, 99), self.packet_id, self.path, self.check_id)


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
        raise SpecError(f"invalid JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def rel(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_strings(child)


def iter_json_files(packet_root: Path) -> Iterable[Path]:
    if packet_root.exists():
        yield from (path for path in sorted(packet_root.rglob("*.json")) if path.is_file())


def packet_manifest_paths(index: dict[str, Any]) -> list[str]:
    packet_files = index.get("packet_files")
    if packet_files is None:
        return []
    return [value for value in flatten_strings(packet_files) if value.endswith(".json")]


def resolve_manifest_path(repo: Path, packet_root: Path, raw: str) -> Path:
    if raw.startswith(("spec/", "tools/", ".github/")):
        return repo / raw
    return packet_root / raw


def exception_keys(exceptions_doc: dict[str, Any]) -> set[tuple[str, str, str]]:
    accepted: set[tuple[str, str, str]] = set()
    for item in exceptions_doc.get("exceptions", []):
        if item.get("accepted_by_owner"):
            accepted.add((str(item.get("check_id", "")), str(item.get("packet_id", "")), str(item.get("scope", ""))))
    return accepted


def is_exception(finding: Finding, accepted: set[tuple[str, str, str]]) -> bool:
    if finding.severity == "BLOCKER":
        return False
    for check_id, packet_id, scope in accepted:
        if check_id == finding.check_id and packet_id in ("*", finding.packet_id):
            if scope in ("*", finding.path) or finding.path.startswith(scope.rstrip("/") + "/"):
                return True
    return False


def add(findings: list[Finding], check_id: str, severity: str, packet_id: str, path: Path | str, message: str, repo: Path) -> None:
    rendered = rel(repo, path) if isinstance(path, Path) else path
    findings.append(Finding(check_id, severity, packet_id, rendered, message))


def scan_json_validity(repo: Path, packet_id: str, packet_root: Path, findings: list[Finding]) -> None:
    for path in iter_json_files(packet_root):
        try:
            load_json(path)
        except SpecError as exc:
            add(findings, "SIG-001", "BLOCKER", packet_id, path, str(exc), repo)


def check_required_core_paths(repo: Path, packet: dict[str, Any], packet_root: Path, contract: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = packet["id"]
    status = packet.get("status")
    if status not in {"review_ready", "drafting"}:
        return
    for raw in contract.get("required_core_paths", []):
        is_dir = raw.endswith("/")
        target = packet_root / raw.rstrip("/")
        exists = target.is_dir() if is_dir else target.is_file()
        if not exists:
            severity = "BLOCKER" if status == "review_ready" else "MEDIUM"
            add(findings, "SIG-001", severity, packet_id, target, f"required core {'directory' if is_dir else 'file'} missing for {status} packet", repo)


def check_manifest(repo: Path, packet: dict[str, Any], packet_root: Path, packet_index: dict[str, Any], findings: list[Finding]) -> None:
    packet_id = packet["id"]
    seen: set[str] = set()
    for raw in packet_manifest_paths(packet_index):
        if raw in seen:
            add(findings, "SIG-001", "BLOCKER", packet_id, packet_root / "_index.json", f"duplicate packet_files entry: {raw}", repo)
            continue
        seen.add(raw)
        if not resolve_manifest_path(repo, packet_root, raw).is_file():
            add(findings, "SIG-001", "BLOCKER", packet_id, packet_root / "_index.json", f"packet_files references missing path: {raw}", repo)


def check_packet_index_properties(repo: Path, packet: dict[str, Any], packet_root: Path, packet_index: dict[str, Any], contract: dict[str, Any], findings: list[Finding]) -> None:
    if packet.get("status") != "review_ready":
        return
    packet_id = packet["id"]
    for prop in contract.get("mandatory_packet_index_properties", []):
        if prop not in packet_index:
            add(findings, "SIG-002", "BLOCKER", packet_id, packet_root / "_index.json", f"V2 mandatory packet property missing: {prop}", repo)
    for prop in ("ai_implementation_ready", "owner_accepted"):
        if prop in packet_index and not isinstance(packet_index[prop], bool):
            add(findings, "SIG-002", "BLOCKER", packet_id, packet_root / "_index.json", f"{prop} must be boolean", repo)


def check_routes(repo: Path, packet: dict[str, Any], packet_root: Path, contract: dict[str, Any], findings: list[Finding]) -> None:
    routes_path = packet_root / "routes.json"
    if not routes_path.is_file():
        return
    try:
        doc = load_json(routes_path)
    except SpecError:
        return
    routes = [item for item in doc.get("routes", []) if isinstance(item, dict)] if isinstance(doc, dict) else []
    required = contract.get("transport_contract", {}).get("required_per_route", [])
    prefix = contract.get("transport_contract", {}).get("canonical_api_prefix", "/api/v1")
    for ordinal, route in enumerate(routes, 1):
        path = str(route.get("path", ""))
        if path.startswith("/api") and not path.startswith(prefix):
            add(findings, "SIG-003", "BLOCKER", packet["id"], routes_path, f"route #{ordinal} uses noncanonical API path {path!r}; expected {prefix} prefix", repo)
        missing = [field for field in required if field not in route]
        if missing:
            add(findings, "SIG-003", "BLOCKER", packet["id"], routes_path, f"route #{ordinal} {route.get('method','?')} {path or '?'} missing V2 fields: {', '.join(missing)}", repo)


def check_audit_registry(repo: Path, packet: dict[str, Any], packet_root: Path, findings: list[Finding]) -> None:
    commands_dir = packet_root / "commands"
    if packet.get("status") == "review_ready" and commands_dir.is_dir() and any(commands_dir.rglob("*.json")) and not (packet_root / "audit").is_dir():
        add(findings, "SIG-005", "BLOCKER", packet["id"], packet_root, "packet owns authoritative command files but has no audit/ registry directory", repo)


def check_leaf_granularity(repo: Path, packet: dict[str, Any], packet_root: Path, findings: list[Finding]) -> None:
    limit = 12000
    allowed = {item.get("path") for item in packet.get("granularity_exceptions", []) if isinstance(item, dict) and item.get("accepted")}
    for path in iter_json_files(packet_root):
        try:
            top = path.relative_to(packet_root).parts[0]
        except ValueError:
            continue
        relative = path.relative_to(packet_root).as_posix()
        if top in NORMATIVE_DIRS and path.stat().st_size > limit and relative not in allowed:
            add(findings, "SIG-018", "HIGH", packet["id"], path, f"normative leaf is {path.stat().st_size} bytes > {limit} byte AI granularity budget without accepted exception", repo)


def compile_placeholder_patterns(gate: dict[str, Any]) -> list[re.Pattern[str]]:
    for check in gate.get("checks", []):
        if check.get("id") == "SIG-017":
            return [re.compile(str(raw), re.IGNORECASE) for raw in check.get("patterns", [])]
    return []


def check_placeholders(repo: Path, packet: dict[str, Any], packet_root: Path, patterns: list[re.Pattern[str]], findings: list[Finding]) -> None:
    if packet.get("status") != "review_ready":
        return
    for path in iter_json_files(packet_root):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                snippet = re.sub(r"\s+", " ", text[max(0, match.start()-70):match.end()+100])
                add(findings, "SIG-017", "HIGH", packet["id"], path, f"potential unresolved design placeholder matched /{pattern.pattern}/: {snippet[:240]}", repo)
                break


def check_global_index(repo: Path, lld_index: dict[str, Any], findings: list[Finding]) -> None:
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for packet in lld_index.get("packets", []):
        packet_id = str(packet.get("id", "GLOBAL"))
        packet_path = str(packet.get("path", ""))
        if packet_id in seen_ids:
            add(findings, "SIG-001", "BLOCKER", "GLOBAL", "spec/lld/_index.json", f"duplicate packet id: {packet_id}", repo)
        if packet_path in seen_paths:
            add(findings, "SIG-001", "BLOCKER", "GLOBAL", "spec/lld/_index.json", f"duplicate packet path: {packet_path}", repo)
        seen_ids.add(packet_id)
        seen_paths.add(packet_path)
        if packet.get("ai_implementation_ready") is not False and packet.get("status") != "review_ready":
            add(findings, "SIG-002", "BLOCKER", packet_id, "spec/lld/_index.json", "only a review_ready packet may claim ai_implementation_ready", repo)


def summarize(findings: list[Finding]) -> dict[str, int]:
    summary = {level: 0 for level in SEVERITY_RANK}
    for finding in findings:
        summary[finding.severity] = summary.get(finding.severity, 0) + 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--packet", action="append", default=[], help="limit scan to packet id; may be repeated")
    parser.add_argument("--enforce", choices=("report", "ai-ready", "review-ready"), default="report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    try:
        lld_index = load_json(repo / "spec/lld/_index.json")
        contract = load_json(repo / "spec/lld/_packet-contract-v2.json")
        gate = load_json(repo / "spec/lld/_integrity-gate.json")
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
    packets = [p for p in lld_index.get("packets", []) if not selected or p.get("id") in selected]

    for packet in packets:
        packet_root = repo / str(packet["path"])
        status = packet.get("status")
        if not packet_root.exists():
            if status != "planned":
                add(findings, "SIG-001", "BLOCKER", packet["id"], packet_root, f"{status} packet directory does not exist", repo)
            continue
        scan_json_validity(repo, packet["id"], packet_root, findings)
        check_required_core_paths(repo, packet, packet_root, contract, findings)
        index_path = packet_root / "_index.json"
        if index_path.is_file():
            try:
                packet_index = load_json(index_path)
            except SpecError:
                packet_index = {}
            check_manifest(repo, packet, packet_root, packet_index, findings)
            check_packet_index_properties(repo, packet, packet_root, packet_index, contract, findings)
        check_routes(repo, packet, packet_root, contract, findings)
        check_audit_registry(repo, packet, packet_root, findings)
        check_leaf_granularity(repo, packet, packet_root, findings)
        check_placeholders(repo, packet, packet_root, patterns, findings)

    accepted = exception_keys(exceptions_doc)
    active = sorted((f for f in findings if not is_exception(f, accepted)), key=Finding.sort_key)
    summary = summarize(active)

    if args.json:
        print(json.dumps({"schema":"SOMA-AI-LLD-SPEC-INTEGRITY-RESULT-V1","enforcement":args.enforce,"selected_packets":sorted(selected) if selected else "all","summary":summary,"findings":[asdict(f) for f in active]}, indent=2, ensure_ascii=False))
    else:
        print("SOMA LLD integrity: " + " ".join(f"{k}={summary.get(k,0)}" for k in SEVERITY_RANK))
        for finding in active:
            print(f"[{finding.severity}] {finding.check_id} {finding.packet_id} {finding.path}: {finding.message}")

    if args.enforce == "ai-ready":
        fail_packets = {str(p["id"]) for p in packets if p.get("ai_implementation_ready") is True}
    elif args.enforce == "review-ready":
        fail_packets = {str(p["id"]) for p in packets if p.get("status") == "review_ready"}
    else:
        fail_packets = set()
    blocking = [f for f in active if f.severity in {"BLOCKER", "HIGH"} and (f.packet_id == "GLOBAL" or f.packet_id in fail_packets)]
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
