#!/usr/bin/env python3
"""RC-006-A2 frozen-corpus allocator with single-read allocation semantics.

V1.2.0 closes two allocation-path gaps left by v1.1.0:

1. INITIAL allocation is bound to an explicitly registered frozen candidate
   corpus (canonical repository path, Git blob SHA, raw SHA-256, record count,
   and complete section set).
2. Allocation records are built from the same in-memory byte stream that was
   identity-checked and source-span validated. The allocator never validates
   one candidate read and then reopens the candidate file for allocation.

The allocation-state and assertion-ledger schemas remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

TOOL_VERSION = "1.2.1"
V11_PATH = "tools/reconciliation/allocate_rc006_a2_assertions_v1_1.py"
V11_BLOB_SHA = "88345216426ed4e3bbd9ac52c4aaf1e507ce2dac"

PRODUCT_SOURCE = "docs/PRODUCT_CONTRACT.md"
PRODUCT_CANDIDATE_PATH = "docs/reconciliation/candidates/RC006_A2_PRODUCT_CONTRACT_CANDIDATES.jsonl"
PRODUCT_CANDIDATE_BLOB_SHA = "3fdbad0c4b9484735020a1dec2698c0e7e14ef95"
PRODUCT_CANDIDATE_PAYLOAD_SHA256 = "97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7"
PRODUCT_CANDIDATE_COUNT = 431
PRODUCT_SECTION_COUNT = 27
PRODUCT_BATCH_ID = "A2-BATCH-0001-PRODUCT-CONTRACT"

RFC_WFM_SOURCE = "docs/RFC_WFM_CONTRACT.md"
RFC_WFM_CANDIDATE_PATH = "docs/reconciliation/candidates/RC006_A2_RFC_WFM_CONTRACT_CANDIDATES.jsonl"
RFC_WFM_CANDIDATE_BLOB_SHA = "bc50d2dffbb5d1b45a9e7ee67ba1088bc4ec1a72"
RFC_WFM_CANDIDATE_PAYLOAD_SHA256 = "e9e5aa9bbcd6a252aa527c07e532840871e89e9e7158d085cc3e3965c5d99aa3"
RFC_WFM_CANDIDATE_COUNT = 171
RFC_WFM_SECTION_COUNT = 8
RFC_WFM_BATCH_ID = "A2-BATCH-0003-RFC-WFM-CONTRACT"

FROZEN_INITIAL_BATCHES: dict[str, dict[str, Any]] = {
    PRODUCT_SOURCE: {
        "batch_id": PRODUCT_BATCH_ID,
        "candidate_path": PRODUCT_CANDIDATE_PATH,
        "candidate_git_blob_sha": PRODUCT_CANDIDATE_BLOB_SHA,
        "candidate_payload_sha256": PRODUCT_CANDIDATE_PAYLOAD_SHA256,
        "candidate_count": PRODUCT_CANDIDATE_COUNT,
        "section_ordinals": list(range(1, PRODUCT_SECTION_COUNT + 1)),
    },
    RFC_WFM_SOURCE: {
        "batch_id": RFC_WFM_BATCH_ID,
        "candidate_path": RFC_WFM_CANDIDATE_PATH,
        "candidate_git_blob_sha": RFC_WFM_CANDIDATE_BLOB_SHA,
        "candidate_payload_sha256": RFC_WFM_CANDIDATE_PAYLOAD_SHA256,
        "candidate_count": RFC_WFM_CANDIDATE_COUNT,
        "section_ordinals": list(range(1, RFC_WFM_SECTION_COUNT + 1)),
    },
}


class FrozenAllocatorError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _git(repo: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FrozenAllocatorError("git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise FrozenAllocatorError(f"git {' '.join(args)} failed: {stderr}") from exc
    return completed.stdout


def _load_v11(repo: Path):
    path = repo / V11_PATH
    raw = path.read_bytes()
    if _git_blob_sha(raw) != V11_BLOB_SHA:
        raise FrozenAllocatorError("hardened allocator v1.1 Git blob mismatch")
    spec = importlib.util.spec_from_file_location("rc006_a2_allocator_v1_1", path)
    if spec is None or spec.loader is None:
        raise FrozenAllocatorError("cannot load hardened allocator v1.1 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool_identity() -> tuple[str, str]:
    raw = Path(__file__).resolve().read_bytes()
    return _git_blob_sha(raw), _sha256(raw)


def _canonical_candidate_path(repo: Path, source_path: str) -> tuple[Path, dict[str, Any]]:
    frozen = FROZEN_INITIAL_BATCHES.get(source_path)
    if frozen is None:
        raise FrozenAllocatorError(
            f"no frozen INITIAL candidate identity is registered for source: {source_path}"
        )
    return (repo / frozen["candidate_path"]).resolve(), frozen


def _resolve_requested_candidate_path(repo: Path, requested: str) -> Path:
    path = Path(requested)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _parse_candidate_bytes(
    raw: bytes,
    source_path: str,
    roles: dict[str, dict[str, str]],
    base: Any,
) -> list[dict[str, Any]]:
    if not raw:
        raise FrozenAllocatorError("frozen candidate corpus may not be empty")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise FrozenAllocatorError("candidate JSONL must use LF and final LF")

    records: list[dict[str, Any]] = []
    for idx, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise FrozenAllocatorError(f"empty candidate line {idx}")
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenAllocatorError(f"invalid candidate JSON line {idx}") from exc
        if line + b"\n" != base.canonical_json_bytes(record):
            raise FrozenAllocatorError(f"noncanonical candidate JSON line {idx}")
        base.validate_candidate(record, source_path, roles)
        records.append(record)

    locators = [(r["section_ordinal"], r["assertion_ordinal"]) for r in records]
    if len(locators) != len(set(locators)):
        raise FrozenAllocatorError("duplicate candidate section/assertion ordinal")
    if locators != sorted(locators):
        raise FrozenAllocatorError("candidate order is not section/assertion ordinal ascending")
    return records


def _validate_frozen_stream(
    repo: Path,
    source_path: str,
    requested_candidates: str,
) -> tuple[list[dict[str, Any]], bytes, dict[str, Any], Any]:
    """Read once, then perform every identity/content validation on those bytes."""

    v11 = _load_v11(repo)
    base = v11._load_base(repo)
    roles, role_counts, _ = base.load_roles(repo)
    source = roles.get(source_path)
    if not source or source["role"] != base.ROLE_DEST:
        raise FrozenAllocatorError(f"source is not destination-eligible: {source_path}")

    canonical_path, frozen = _canonical_candidate_path(repo, source_path)
    requested_path = _resolve_requested_candidate_path(repo, requested_candidates)
    if requested_path != canonical_path:
        raise FrozenAllocatorError(
            f"allocation candidate path must be canonical frozen path {frozen['candidate_path']}"
        )

    try:
        head_blob = _git(repo, "rev-parse", f"HEAD:{frozen['candidate_path']}").decode("ascii").strip()
    except FrozenAllocatorError as exc:
        raise FrozenAllocatorError("frozen candidate corpus is not committed at HEAD") from exc
    if head_blob != frozen["candidate_git_blob_sha"]:
        raise FrozenAllocatorError(
            f"HEAD frozen candidate Git blob mismatch: {head_blob} != {frozen['candidate_git_blob_sha']}"
        )

    # SINGLE READ. No allocation path may reopen requested_candidates after here.
    raw = canonical_path.read_bytes()
    raw_blob = _git_blob_sha(raw)
    raw_sha = _sha256(raw)
    if raw_blob != frozen["candidate_git_blob_sha"]:
        raise FrozenAllocatorError(
            f"working-tree candidate Git blob mismatch: {raw_blob} != {frozen['candidate_git_blob_sha']}"
        )
    if raw_sha != frozen["candidate_payload_sha256"]:
        raise FrozenAllocatorError(
            f"candidate payload SHA-256 mismatch: {raw_sha} != {frozen['candidate_payload_sha256']}"
        )

    candidates = _parse_candidate_bytes(raw, source_path, roles, base)
    if len(candidates) != frozen["candidate_count"]:
        raise FrozenAllocatorError(
            f"candidate count mismatch: {len(candidates)} != {frozen['candidate_count']}"
        )

    section_ordinals = sorted({r["section_ordinal"] for r in candidates})
    if section_ordinals != frozen["section_ordinals"]:
        raise FrozenAllocatorError(
            f"candidate section set mismatch: {section_ordinals} != {frozen['section_ordinals']}"
        )

    lines, source_blob = v11._load_pinned_source(repo, source_path, source["blob_sha"])
    headings = v11._eligible_headings(lines)
    if not headings:
        raise FrozenAllocatorError("pinned source contains no eligible ##/### headings")

    per_section_ordinals: dict[int, list[int]] = {}
    for candidate in candidates:
        v11._validate_exact_span(candidate, lines, headings)
        per_section_ordinals.setdefault(candidate["section_ordinal"], []).append(
            candidate["assertion_ordinal"]
        )

    for section_ordinal, ordinals in per_section_ordinals.items():
        expected = list(range(1, len(ordinals) + 1))
        if ordinals != expected:
            raise FrozenAllocatorError(
                f"assertion_ordinal sequence is not contiguous in section {section_ordinal}: {ordinals}"
            )

    identity = {
        "baseline_id": base.BASELINE_ID,
        "candidate_count": len(candidates),
        "candidate_git_blob_sha": raw_blob,
        "candidate_path": frozen["candidate_path"],
        "candidate_payload_sha256": raw_sha,
        "extraction_schema": base.EXTRACTION_SCHEMA,
        "pinned_source_blob_sha": source_blob,
        "pinned_source_commit": v11.SOURCE_COMMIT,
        "role_counts": role_counts,
        "section_count_with_candidates": len(per_section_ordinals),
        "section_ordinals": section_ordinals,
        "source_path": source_path,
    }
    return candidates, raw, identity, base


def validate_frozen(repo: Path, source_path: str, requested_candidates: str) -> dict[str, Any]:
    _, _, identity, _ = _validate_frozen_stream(repo, source_path, requested_candidates)
    tool_blob, tool_sha = _tool_identity()
    return {
        **identity,
        "result": "PASS",
        "schema": "RC006-A2-FROZEN-CANDIDATE-VALIDATION-V1",
        "tool_git_blob_sha": tool_blob,
        "tool_sha256": tool_sha,
        "tool_version": TOOL_VERSION,
    }


def _check_allocation_preconditions(
    args: argparse.Namespace,
    base: Any,
    state: dict[str, Any],
    ledger: list[dict[str, Any]],
    roles: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if len(ledger) != state["allocated_count"]:
        raise FrozenAllocatorError("ledger record count differs from allocation state")
    if any(batch["batch_id"] == args.batch_id for batch in state["batches"]):
        raise FrozenAllocatorError("allocation batch ID already exists")
    if args.source_path not in roles or roles[args.source_path]["role"] != base.ROLE_DEST:
        raise FrozenAllocatorError("source path is not destination-eligible")

    frozen = FROZEN_INITIAL_BATCHES.get(args.source_path)
    if args.mode == "INITIAL":
        if frozen is None:
            raise FrozenAllocatorError(
                f"INITIAL allocation prohibited until a frozen identity is registered for {args.source_path}"
            )
        if args.batch_id != frozen["batch_id"]:
            raise FrozenAllocatorError(
                f"INITIAL batch ID mismatch: {args.batch_id} != {frozen['batch_id']}"
            )
        if len(state["completed_initial_sources"]) >= len(base.INITIAL_SOURCE_ORDER):
            raise FrozenAllocatorError("all initial sources are already complete")
        expected_source = base.INITIAL_SOURCE_ORDER[len(state["completed_initial_sources"])]
        if args.source_path != expected_source:
            raise FrozenAllocatorError(f"next INITIAL source must be {expected_source}")
        if args.reason is not None:
            raise FrozenAllocatorError("INITIAL mode reason must be omitted")
    else:
        # V1.2 deliberately does not invent amendment-corpus identity rules.
        raise FrozenAllocatorError(
            "AMENDMENT allocation is fail-closed in v1.2 until an explicit frozen amendment identity is registered"
        )
    return frozen


def _build_allocation_from_verified_stream(
    repo: Path,
    args: argparse.Namespace,
    mutate: bool,
) -> dict[str, Any]:
    # This returns the exact candidate objects and raw bytes that were verified.
    # Neither this function nor any called allocation step reopens the candidate file.
    candidates, candidate_raw, identity, base = _validate_frozen_stream(
        repo, args.source_path, args.candidates
    )

    roles, _, _ = base.load_roles(repo)
    state, state_raw = base.load_state(repo)
    ledger, ledger_raw = base.load_ledger(repo, roles)
    _check_allocation_preconditions(args, base, state, ledger, roles)

    first_num = state["next_assertion_number"]
    new_records: list[dict[str, Any]] = []
    for offset, candidate in enumerate(candidates):
        assertion_id = f"A2-ASSERT-{first_num + offset:06d}"
        new_records.append(base.make_record(candidate, assertion_id, args.batch_id))

    if not new_records:
        raise FrozenAllocatorError("frozen INITIAL batch may not allocate zero assertions")

    first_id = new_records[0]["assertion_id"]
    last_id = new_records[-1]["assertion_id"]
    candidate_hash = _sha256(candidate_raw)
    result_core = {
        "assertion_count": len(new_records),
        "batch_id": args.batch_id,
        "candidate_payload_sha256": candidate_hash,
        "first_assertion_id": first_id,
        "last_assertion_id": last_id,
        "mode": args.mode,
        "previous_state_sha256": base.sha256_hex(state_raw),
        "source_path": args.source_path,
    }
    result_payload_sha = base.sha256_hex(base.canonical_json_bytes(result_core))

    new_state = json.loads(json.dumps(state))
    new_state["allocated_count"] += len(new_records)
    new_state["next_assertion_number"] += len(new_records)
    new_state["highest_allocated_assertion_id"] = f"A2-ASSERT-{new_state['allocated_count']:06d}"
    new_state["completed_initial_sources"].append(args.source_path)
    new_state["batches"].append(
        {
            "batch_id": args.batch_id,
            "mode": args.mode,
            "source_path": args.source_path,
            "first_assertion_id": first_id,
            "last_assertion_id": last_id,
            "assertion_count": len(new_records),
            "candidate_payload_sha256": candidate_hash,
            "result_payload_sha256": result_payload_sha,
            "reason": args.reason,
        }
    )

    new_ledger = ledger_raw + b"".join(base.canonical_json_bytes(record) for record in new_records)
    new_state_bytes = base.canonical_json_bytes(new_state)
    tool_blob, tool_sha = _tool_identity()

    result = {
        **result_core,
        **identity,
        "new_allocated_count": new_state["allocated_count"],
        "new_ledger_sha256": base.sha256_hex(new_ledger),
        "new_state_sha256": base.sha256_hex(new_state_bytes),
        "mutation_performed": mutate,
        "result": "PASS",
        "result_payload_sha256": result_payload_sha,
        "schema": "RC006-A2-ALLOCATION-RESULT-V2" if mutate else "RC006-A2-PREALLOCATION-RESULT-V1",
        "tool_git_blob_sha": tool_blob,
        "tool_sha256": tool_sha,
        "tool_version": TOOL_VERSION,
    }

    if mutate:
        # Candidate data is not read again. Writes occur only after the complete
        # in-memory allocation result has been constructed from verified bytes.
        base.atomic_write(repo / base.LEDGER_PATH, new_ledger)
        base.atomic_write(repo / base.STATE_PATH, new_state_bytes)
        if args.output:
            base.atomic_write(Path(args.output), base.canonical_json_bytes(result))
    return result


def _write_output(path: str | None, value: dict[str, Any], base: Any | None = None) -> None:
    if base is not None:
        rendered = base.canonical_json_bytes(value)
    else:
        rendered = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    if path:
        Path(path).write_bytes(rendered)
    sys.stdout.buffer.write(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check-state", help="Run allocator readiness checks without allocation")
    check.add_argument("--expect-zero", action="store_true")
    check.add_argument("--output")

    validate = sub.add_parser("validate-frozen", help="Validate the registered frozen corpus identity and contents")
    validate.add_argument("--source-path", required=True)
    validate.add_argument("--candidates", required=True)
    validate.add_argument("--output")

    for name, help_text in (
        ("preallocate", "Compute the exact allocation from frozen bytes without writing state or ledger"),
        ("allocate", "Allocate IDs from the exact verified frozen byte stream"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--mode", choices=["INITIAL", "AMENDMENT"], required=True)
        command.add_argument("--source-path", required=True)
        command.add_argument("--candidates", required=True)
        command.add_argument("--batch-id", required=True)
        command.add_argument("--reason")
        command.add_argument("--output")

    args = parser.parse_args()
    if args.version:
        print(TOOL_VERSION)
        return 0

    repo = Path(args.repo).resolve()
    try:
        v11 = _load_v11(repo)
        base = v11._load_base(repo)
        if args.command == "check-state":
            result = dict(base.readiness(repo, args.expect_zero))
            tool_blob, tool_sha = _tool_identity()
            result.update(
                {
                    "frozen_allocator_git_blob_sha": tool_blob,
                    "frozen_allocator_sha256": tool_sha,
                    "frozen_allocator_version": TOOL_VERSION,
                }
            )
            _write_output(args.output, result, base)
            return 0
        if args.command == "validate-frozen":
            result = validate_frozen(repo, args.source_path, args.candidates)
            _write_output(args.output, result, base)
            return 0
        if args.command == "preallocate":
            result = _build_allocation_from_verified_stream(repo, args, mutate=False)
            _write_output(args.output, result, base)
            return 0
        if args.command == "allocate":
            result = _build_allocation_from_verified_stream(repo, args, mutate=True)
            _write_output(None, result, base)
            return 0
        parser.error("a command is required")
        return 2
    except Exception as exc:
        # Imported v1.0/v1.1 classes are dynamically loaded; broad catch keeps
        # every unexpected validation/allocation error fail-closed.
        print(f"A2_FROZEN_ALLOCATOR_ERROR\t{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
