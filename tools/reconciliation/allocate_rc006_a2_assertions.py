#!/usr/bin/env python3
"""Deterministic RC-006-A2 assertion allocator and allocation-state checker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

TOOL_VERSION = "1.0.0"
BASELINE_ID = "A2-BASELINE-002"
EXTRACTION_SCHEMA = "A2-EXTRACTION-SCHEMA-V1"
SOURCE_ROLES_PATH = "docs/reconciliation/RC006_A2_SOURCE_ROLES.tsv"
SOURCE_ROLES_BLOB_SHA = "d6ad8f0f40fe860315ea4b8952545987ee29ca9d"
SOURCE_ROLES_PAYLOAD_SHA256 = "cb04974e04e1c7428dc20145bd2781dc0d184b559cee419039e20c72e25c4810"
STATE_SCHEMA = "RC006-A2-ASSERTION-ALLOCATION-STATE-V1"
CANDIDATE_SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"
RECORD_SCHEMA = "RC006-A2-ASSERTION-RECORD-V1"
STATE_PATH = "docs/reconciliation/RC006_A2_ASSERTION_ALLOCATION_STATE.json"
LEDGER_PATH = "docs/reconciliation/RC006_A2_ASSERTION_AUTHORITY.jsonl"

ROLE_DEST = "DESTINATION_ASSERTION_SOURCE"
ROLE_CANON = "CANONICAL_AUTHORITY_SOURCE"
ROLE_ASSURANCE = "ASSURANCE_CONTEXT_SOURCE"
VALID_ROLES = {ROLE_DEST, ROLE_CANON, ROLE_ASSURANCE}
EXPECTED_ROLE_COUNTS = {ROLE_DEST: 16, ROLE_CANON: 33, ROLE_ASSURANCE: 25}

INITIAL_SOURCE_ORDER = [
    "docs/PRODUCT_CONTRACT.md",
    "docs/IMPORT_CONTRACT.md",
    "docs/RFC_WFM_CONTRACT.md",
    "docs/WORKBENCH_CONTRACT.md",
    "docs/PRODUCT_LINE_SLA.md",
    "docs/INVENTORY_LIFECYCLE.md",
    "docs/INFRASTRUCTURE_CONTRACT.md",
    "docs/COMMUNICATIONS_CONTRACT.md",
    "docs/UI_UX_CONTRACT.md",
    "docs/FOUNDATION_RUNTIME_CONTRACT.md",
    "docs/ARCHITECTURE.md",
    "docs/GLOSSARY.md",
    "docs/DECISIONS.md",
    "docs/BRANDING.md",
    "docs/ROADMAP.md",
    "docs/FOUNDATION_GAPS.md",
]

NORMATIVE_KINDS = {"OBLIGATION", "PROHIBITION", "PERMISSION", "DESIGN_BOUNDARY"}
ASSERT_RE = re.compile(r"^A2-ASSERT-(\d{6})$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CANDIDATE_KEYS = {
    "schema", "source_path", "source_blob_sha", "section_heading", "section_anchor",
    "section_ordinal", "assertion_ordinal", "source_start_line", "source_end_line",
    "exact_text", "fingerprint_sha256", "normative_kind", "classification_review",
    "review_note",
}

RECORD_KEYS = {
    "schema", "assertion_id", "allocation_batch_id", "source_path", "source_blob_sha",
    "section_heading", "section_anchor", "section_ordinal", "assertion_ordinal",
    "source_start_line", "source_end_line", "exact_text", "fingerprint_sha256",
    "normative_kind", "canonical_clause_ids", "requirement_owners", "destination_edges",
    "semantic_review", "contradiction_status", "supersedes", "superseded_by", "status",
    "review_note",
}


class ToolError(RuntimeError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def tool_identity() -> tuple[str, str]:
    data = Path(__file__).resolve().read_bytes()
    return git_blob_sha(data), sha256_hex(data)


def fingerprint(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return sha256_hex(normalized.encode("utf-8"))


def load_roles(repo: Path) -> tuple[dict[str, dict[str, str]], dict[str, int], str]:
    path = repo / SOURCE_ROLES_PATH
    raw = path.read_bytes()
    if git_blob_sha(raw) != SOURCE_ROLES_BLOB_SHA:
        raise ToolError("source-role manifest Git blob SHA mismatch")
    first_lf = raw.find(b"\n")
    if first_lf < 0:
        raise ToolError("source-role manifest missing LF")
    first = raw[:first_lf].decode("ascii", errors="strict").split("\t")
    payload = raw[first_lf + 1:]
    if len(first) != 2 or first[0] != "roles_sha256":
        raise ToolError("malformed source-role digest line")
    if first[1] != SOURCE_ROLES_PAYLOAD_SHA256 or sha256_hex(payload) != SOURCE_ROLES_PAYLOAD_SHA256:
        raise ToolError("source-role payload SHA-256 mismatch")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise ToolError("source-role manifest must use LF and final LF")

    lines = payload.decode("utf-8", errors="strict").splitlines()
    if len(lines) < 10 or lines[0] != "A2-SOURCE-ROLES-V1":
        raise ToolError("source-role manifest magic mismatch")
    expected_meta = {
        "baseline_id": BASELINE_ID,
        "source_commit": "61bbd665535e942ef3b05c5ed45661639d3a37a9",
        "source_tree": "b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8",
        "input_manifest_blob_sha": "05daa81310b8259ca8ff968bd1715244ecf0d5d5",
        "included_count": "74",
        "destination_assertion_source_count": "16",
        "canonical_authority_source_count": "33",
        "assurance_context_source_count": "25",
    }
    for idx, (key, expected) in enumerate(expected_meta.items(), start=1):
        fields = lines[idx].split("\t")
        if fields != [key, expected]:
            raise ToolError(f"source-role metadata mismatch: {key}")

    roles: dict[str, dict[str, str]] = {}
    counts = {role: 0 for role in VALID_ROLES}
    ordered_paths: list[str] = []
    for line in lines[9:]:
        fields = line.split("\t")
        if len(fields) != 4:
            raise ToolError("malformed source-role record")
        role, source_path, blob_sha, policy = fields
        if role not in VALID_ROLES:
            raise ToolError(f"invalid source role: {role}")
        if source_path in roles:
            raise ToolError(f"duplicate source-role path: {source_path}")
        if not SHA1_RE.fullmatch(blob_sha):
            raise ToolError(f"invalid source-role blob SHA: {source_path}")
        if not policy:
            raise ToolError(f"empty source-role policy: {source_path}")
        roles[source_path] = {"role": role, "blob_sha": blob_sha, "policy": policy}
        counts[role] += 1
        ordered_paths.append(source_path)

    if len(roles) != 74 or counts != EXPECTED_ROLE_COUNTS:
        raise ToolError(f"source-role count mismatch: {counts}")
    if ordered_paths != sorted(ordered_paths, key=lambda value: value.encode("utf-8")):
        raise ToolError("source-role records are not bytewise UTF-8 path sorted")
    if {p for p, v in roles.items() if v["role"] == ROLE_DEST} != set(INITIAL_SOURCE_ORDER):
        raise ToolError("destination source set differs from fixed initial order")
    return roles, counts, sha256_hex(raw)


def load_state(repo: Path) -> tuple[dict[str, Any], bytes]:
    raw = (repo / STATE_PATH).read_bytes()
    try:
        state = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("allocation state is not valid UTF-8 JSON") from exc
    if raw != canonical_json_bytes(state):
        raise ToolError("allocation state is not canonical JSON with final LF")
    required = {
        "schema", "baseline_id", "extraction_schema", "source_roles_blob_sha",
        "source_roles_payload_sha256", "next_assertion_number", "allocated_count",
        "highest_allocated_assertion_id", "completed_initial_sources", "batches",
    }
    if set(state) != required:
        raise ToolError("allocation state fields differ from V1 schema")
    if state["schema"] != STATE_SCHEMA or state["baseline_id"] != BASELINE_ID:
        raise ToolError("allocation state baseline/schema mismatch")
    if state["extraction_schema"] != EXTRACTION_SCHEMA:
        raise ToolError("allocation state extraction-schema mismatch")
    if state["source_roles_blob_sha"] != SOURCE_ROLES_BLOB_SHA:
        raise ToolError("allocation state source-role blob mismatch")
    if state["source_roles_payload_sha256"] != SOURCE_ROLES_PAYLOAD_SHA256:
        raise ToolError("allocation state source-role payload mismatch")
    if not isinstance(state["allocated_count"], int) or state["allocated_count"] < 0:
        raise ToolError("invalid allocated_count")
    if state["next_assertion_number"] != state["allocated_count"] + 1:
        raise ToolError("next_assertion_number is inconsistent with allocated_count")
    expected_highest = None if state["allocated_count"] == 0 else f"A2-ASSERT-{state['allocated_count']:06d}"
    if state["highest_allocated_assertion_id"] != expected_highest:
        raise ToolError("highest_allocated_assertion_id mismatch")
    completed = state["completed_initial_sources"]
    if not isinstance(completed, list) or completed != INITIAL_SOURCE_ORDER[:len(completed)]:
        raise ToolError("completed_initial_sources is not an exact initial-order prefix")
    if not isinstance(state["batches"], list):
        raise ToolError("batches must be an array")
    batch_ids: set[str] = set()
    for batch in state["batches"]:
        if not isinstance(batch, dict):
            raise ToolError("batch record must be an object")
        expected_batch_fields = {
            "batch_id", "mode", "source_path", "first_assertion_id", "last_assertion_id",
            "assertion_count", "candidate_payload_sha256", "result_payload_sha256", "reason",
        }
        if set(batch) != expected_batch_fields:
            raise ToolError("batch record fields differ from V1 schema")
        if batch["batch_id"] in batch_ids:
            raise ToolError("duplicate allocation batch ID")
        batch_ids.add(batch["batch_id"])
        if batch["mode"] not in {"INITIAL", "AMENDMENT"}:
            raise ToolError("invalid batch mode")
        if not isinstance(batch["assertion_count"], int) or batch["assertion_count"] < 0:
            raise ToolError("invalid batch assertion_count")
        if not SHA256_RE.fullmatch(batch["candidate_payload_sha256"]):
            raise ToolError("invalid candidate payload SHA-256")
        if not SHA256_RE.fullmatch(batch["result_payload_sha256"]):
            raise ToolError("invalid result payload SHA-256")
    return state, raw


def load_ledger(repo: Path, roles: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], bytes]:
    path = repo / LEDGER_PATH
    if not path.exists():
        return [], b""
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ToolError("assertion ledger must end with LF")
    if b"\r" in raw:
        raise ToolError("assertion ledger contains CR")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ToolError(f"empty assertion ledger line {index}")
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError(f"invalid assertion ledger JSON line {index}") from exc
        if line + b"\n" != canonical_json_bytes(record):
            raise ToolError(f"noncanonical assertion ledger JSON line {index}")
        if set(record) != RECORD_KEYS or record["schema"] != RECORD_SCHEMA:
            raise ToolError(f"assertion ledger schema mismatch line {index}")
        expected_id = f"A2-ASSERT-{index:06d}"
        if record["assertion_id"] != expected_id:
            raise ToolError(f"assertion ledger ID sequence mismatch line {index}")
        source = roles.get(record["source_path"])
        if not source or source["role"] != ROLE_DEST:
            raise ToolError(f"assertion source is not destination-eligible: {record['source_path']}")
        if source["blob_sha"] != record["source_blob_sha"]:
            raise ToolError(f"assertion source blob mismatch: {record['source_path']}")
        if fingerprint(record["exact_text"]) != record["fingerprint_sha256"]:
            raise ToolError(f"assertion fingerprint mismatch: {record['assertion_id']}")
        records.append(record)
    return records, raw


def validate_candidate(record: dict[str, Any], source_path: str, roles: dict[str, dict[str, str]]) -> None:
    if set(record) != CANDIDATE_KEYS or record.get("schema") != CANDIDATE_SCHEMA:
        raise ToolError("candidate fields/schema differ from V1")
    source = roles.get(source_path)
    if not source or source["role"] != ROLE_DEST:
        raise ToolError(f"candidate source is not destination-eligible: {source_path}")
    if record["source_path"] != source_path or record["source_blob_sha"] != source["blob_sha"]:
        raise ToolError("candidate source path/blob mismatch")
    for name in ("section_heading", "section_anchor", "exact_text"):
        if not isinstance(record[name], str) or not record[name]:
            raise ToolError(f"candidate {name} must be non-empty")
    for name in ("section_ordinal", "assertion_ordinal", "source_start_line", "source_end_line"):
        if not isinstance(record[name], int) or record[name] <= 0:
            raise ToolError(f"candidate {name} must be positive integer")
    if record["source_end_line"] < record["source_start_line"]:
        raise ToolError("candidate source line range is reversed")
    if record["normative_kind"] not in NORMATIVE_KINDS:
        raise ToolError("candidate normative_kind invalid")
    if record["classification_review"] != "PASS":
        raise ToolError("candidate classification_review must be PASS")
    if not isinstance(record["review_note"], str):
        raise ToolError("candidate review_note must be a string")
    if fingerprint(record["exact_text"]) != record["fingerprint_sha256"]:
        raise ToolError("candidate fingerprint mismatch")


def load_candidates(path: Path, source_path: str, roles: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    if raw and (not raw.endswith(b"\n") or b"\r" in raw):
        raise ToolError("candidate JSONL must use LF and final LF")
    records: list[dict[str, Any]] = []
    for idx, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ToolError(f"empty candidate line {idx}")
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError(f"invalid candidate JSON line {idx}") from exc
        if line + b"\n" != canonical_json_bytes(record):
            raise ToolError(f"noncanonical candidate JSON line {idx}")
        validate_candidate(record, source_path, roles)
        records.append(record)
    locators = [(r["section_ordinal"], r["assertion_ordinal"]) for r in records]
    if len(locators) != len(set(locators)):
        raise ToolError("duplicate candidate section/assertion ordinal")
    if locators != sorted(locators):
        raise ToolError("candidate order is not section/assertion ordinal ascending")
    return records, raw


def make_record(candidate: dict[str, Any], assertion_id: str, batch_id: str) -> dict[str, Any]:
    return {
        "allocation_batch_id": batch_id,
        "assertion_id": assertion_id,
        "assertion_ordinal": candidate["assertion_ordinal"],
        "canonical_clause_ids": [],
        "contradiction_status": "NONE",
        "destination_edges": [],
        "exact_text": candidate["exact_text"],
        "fingerprint_sha256": candidate["fingerprint_sha256"],
        "normative_kind": candidate["normative_kind"],
        "requirement_owners": [],
        "review_note": candidate["review_note"],
        "schema": RECORD_SCHEMA,
        "section_anchor": candidate["section_anchor"],
        "section_heading": candidate["section_heading"],
        "section_ordinal": candidate["section_ordinal"],
        "semantic_review": "PENDING_AUTHORITY",
        "source_blob_sha": candidate["source_blob_sha"],
        "source_end_line": candidate["source_end_line"],
        "source_path": candidate["source_path"],
        "source_start_line": candidate["source_start_line"],
        "status": "ACTIVE",
        "superseded_by": [],
        "supersedes": [],
    }


def readiness(repo: Path, expect_zero: bool) -> dict[str, Any]:
    roles, role_counts, roles_file_sha256 = load_roles(repo)
    state, state_raw = load_state(repo)
    ledger, ledger_raw = load_ledger(repo, roles)
    if len(ledger) != state["allocated_count"]:
        raise ToolError("ledger record count differs from allocation state")
    if expect_zero and state["allocated_count"] != 0:
        raise ToolError("expected zero allocated assertions")
    next_source = (
        INITIAL_SOURCE_ORDER[len(state["completed_initial_sources"])]
        if len(state["completed_initial_sources"]) < len(INITIAL_SOURCE_ORDER)
        else None
    )
    tool_blob, tool_sha = tool_identity()
    return {
        "allocated_count": state["allocated_count"],
        "baseline_id": BASELINE_ID,
        "completed_initial_source_count": len(state["completed_initial_sources"]),
        "extraction_schema": EXTRACTION_SCHEMA,
        "ledger_record_count": len(ledger),
        "ledger_sha256": sha256_hex(ledger_raw),
        "next_assertion_id": f"A2-ASSERT-{state['next_assertion_number']:06d}",
        "next_initial_source": next_source,
        "result": "PASS",
        "role_counts": role_counts,
        "schema": "RC006-A2-ALLOCATOR-READINESS-V1",
        "source_roles_file_sha256": roles_file_sha256,
        "source_roles_git_blob_sha": SOURCE_ROLES_BLOB_SHA,
        "source_roles_payload_sha256": SOURCE_ROLES_PAYLOAD_SHA256,
        "state_sha256": sha256_hex(state_raw),
        "tool_git_blob_sha": tool_blob,
        "tool_sha256": tool_sha,
        "tool_version": TOOL_VERSION,
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def allocate(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    roles, _, _ = load_roles(repo)
    state, state_raw = load_state(repo)
    ledger, ledger_raw = load_ledger(repo, roles)

    if len(ledger) != state["allocated_count"]:
        raise ToolError("ledger record count differs from allocation state")
    if any(batch["batch_id"] == args.batch_id for batch in state["batches"]):
        raise ToolError("allocation batch ID already exists")
    if args.source_path not in roles or roles[args.source_path]["role"] != ROLE_DEST:
        raise ToolError("source path is not destination-eligible")

    if args.mode == "INITIAL":
        if len(state["completed_initial_sources"]) >= len(INITIAL_SOURCE_ORDER):
            raise ToolError("all initial sources are already complete")
        expected_source = INITIAL_SOURCE_ORDER[len(state["completed_initial_sources"])]
        if args.source_path != expected_source:
            raise ToolError(f"next INITIAL source must be {expected_source}")
        if args.reason is not None:
            raise ToolError("INITIAL mode reason must be omitted")
    else:
        if len(state["completed_initial_sources"]) != len(INITIAL_SOURCE_ORDER):
            raise ToolError("AMENDMENT mode prohibited until all initial sources complete")
        if not args.reason:
            raise ToolError("AMENDMENT mode requires non-empty reason")

    candidates, candidate_raw = load_candidates(Path(args.candidates), args.source_path, roles)
    candidate_hash = sha256_hex(candidate_raw)

    first_num = state["next_assertion_number"]
    new_records: list[dict[str, Any]] = []
    for offset, candidate in enumerate(candidates):
        assertion_id = f"A2-ASSERT-{first_num + offset:06d}"
        new_records.append(make_record(candidate, assertion_id, args.batch_id))

    first_id = new_records[0]["assertion_id"] if new_records else None
    last_id = new_records[-1]["assertion_id"] if new_records else None
    result_core = {
        "assertion_count": len(new_records),
        "batch_id": args.batch_id,
        "candidate_payload_sha256": candidate_hash,
        "first_assertion_id": first_id,
        "last_assertion_id": last_id,
        "mode": args.mode,
        "previous_state_sha256": sha256_hex(state_raw),
        "source_path": args.source_path,
    }
    result_payload_sha = sha256_hex(canonical_json_bytes(result_core))

    new_state = json.loads(json.dumps(state))
    new_state["allocated_count"] += len(new_records)
    new_state["next_assertion_number"] += len(new_records)
    new_state["highest_allocated_assertion_id"] = (
        None if new_state["allocated_count"] == 0 else f"A2-ASSERT-{new_state['allocated_count']:06d}"
    )
    if args.mode == "INITIAL":
        new_state["completed_initial_sources"].append(args.source_path)
    new_state["batches"].append({
        "batch_id": args.batch_id,
        "mode": args.mode,
        "source_path": args.source_path,
        "first_assertion_id": first_id,
        "last_assertion_id": last_id,
        "assertion_count": len(new_records),
        "candidate_payload_sha256": candidate_hash,
        "result_payload_sha256": result_payload_sha,
        "reason": args.reason,
    })

    new_ledger = ledger_raw + b"".join(canonical_json_bytes(r) for r in new_records)
    new_state_bytes = canonical_json_bytes(new_state)
    result = dict(result_core)
    result.update({
        "new_allocated_count": new_state["allocated_count"],
        "new_ledger_sha256": sha256_hex(new_ledger),
        "new_state_sha256": sha256_hex(new_state_bytes),
        "result": "PASS",
        "result_payload_sha256": result_payload_sha,
        "schema": "RC006-A2-ALLOCATION-RESULT-V1",
    })

    atomic_write(repo / LEDGER_PATH, new_ledger)
    atomic_write(repo / STATE_PATH, new_state_bytes)
    if args.output:
        atomic_write(Path(args.output), canonical_json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root or path inside repository")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check-state", help="Validate roles, state and ledger without allocating IDs")
    check.add_argument("--expect-zero", action="store_true")
    check.add_argument("--output")

    alloc = sub.add_parser("allocate", help="Allocate IDs from one frozen candidate batch")
    alloc.add_argument("--mode", choices=["INITIAL", "AMENDMENT"], required=True)
    alloc.add_argument("--source-path", required=True)
    alloc.add_argument("--candidates", required=True)
    alloc.add_argument("--batch-id", required=True)
    alloc.add_argument("--reason")
    alloc.add_argument("--output")

    args = parser.parse_args()
    if args.version:
        print(TOOL_VERSION)
        return 0
    repo = Path(args.repo).resolve()
    try:
        if args.command == "check-state":
            result = readiness(repo, args.expect_zero)
            rendered = canonical_json_bytes(result)
            if args.output:
                atomic_write(Path(args.output), rendered)
        elif args.command == "allocate":
            result = allocate(args)
            rendered = canonical_json_bytes(result)
        else:
            parser.error("a command is required")
            return 2
    except (OSError, ToolError, ValueError) as exc:
        print(f"A2_ALLOCATOR_ERROR\t{exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
