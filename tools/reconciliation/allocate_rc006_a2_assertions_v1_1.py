#!/usr/bin/env python3
"""Hardened RC-006-A2 assertion candidate validator and allocator wrapper.

V1.1.0 preserves A2-EXTRACTION-SCHEMA-V1 and the v1.0 allocation state/ledger
formats while adding exact pinned-source verification required by
RC006_A2_SCHEMA_AMENDMENT_001.md.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

TOOL_VERSION = "1.1.0"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
BASE_TOOL_PATH = "tools/reconciliation/allocate_rc006_a2_assertions.py"
BASE_TOOL_BLOB_SHA = "216bf8b5dc77f05b257ad70dc4133aa37370828b"
SOURCE_ROLES_BLOB_SHA = "d6ad8f0f40fe860315ea4b8952545987ee29ca9d"
AMENDMENT_PATH = "docs/reconciliation/RC006_A2_SCHEMA_AMENDMENT_001.md"


class HardenedError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _git(repo: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HardenedError("git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise HardenedError(f"git {' '.join(args)} failed: {stderr}") from exc
    return completed.stdout


def _load_base(repo: Path):
    path = repo / BASE_TOOL_PATH
    raw = path.read_bytes()
    if _git_blob_sha(raw) != BASE_TOOL_BLOB_SHA:
        raise HardenedError("base allocator v1.0 Git blob mismatch")
    spec = importlib.util.spec_from_file_location("rc006_a2_allocator_v1_0", path)
    if spec is None or spec.loader is None:
        raise HardenedError("cannot load base allocator module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_anchor(heading: str) -> str:
    text = unicodedata.normalize("NFC", heading)
    text = text.replace("`", "").replace("*", "").replace("_", "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in {" ", "-"})
    text = re.sub(r" +", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _eligible_headings(lines: list[str]) -> list[tuple[int, str, str]]:
    headings: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(lines, start=1):
        match = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if match:
            visible = match.group(2)
            headings.append((line_no, visible, _normalize_anchor(visible)))
    return headings


def _owning_heading(headings: list[tuple[int, str, str]], start_line: int) -> tuple[int, str, str, int]:
    eligible = [entry for entry in headings if entry[0] < start_line]
    if not eligible:
        raise HardenedError(f"candidate at line {start_line} has no preceding eligible section heading")
    line_no, visible, anchor = eligible[-1]
    ordinal = headings.index((line_no, visible, anchor)) + 1
    return line_no, visible, anchor, ordinal


def _load_pinned_source(repo: Path, source_path: str, expected_blob_sha: str) -> tuple[list[str], str]:
    resolved_blob = _git(repo, "rev-parse", f"{SOURCE_COMMIT}:{source_path}").decode("ascii").strip()
    if resolved_blob != expected_blob_sha:
        raise HardenedError(
            f"pinned source blob mismatch for {source_path}: {resolved_blob} != {expected_blob_sha}"
        )
    raw = _git(repo, "show", f"{SOURCE_COMMIT}:{source_path}")
    if b"\r" in raw:
        raise HardenedError(f"pinned source contains CR: {source_path}")
    text = raw.decode("utf-8", errors="strict")
    return text.splitlines(), resolved_blob


def _validate_exact_span(record: dict[str, Any], lines: list[str], headings: list[tuple[int, str, str]]) -> None:
    start = record["source_start_line"]
    end = record["source_end_line"]
    if start > len(lines) or end > len(lines):
        raise HardenedError("candidate source line range exceeds pinned source")

    segment = "\n".join(lines[start - 1 : end])
    exact = record["exact_text"]
    occurrence_count = segment.count(exact)
    if occurrence_count != 1:
        raise HardenedError(
            f"candidate exact_text must occur exactly once in claimed line range; found {occurrence_count}"
        )
    offset = segment.index(exact)
    if "\n" in segment[:offset]:
        raise HardenedError("candidate exact_text does not begin on source_start_line")
    exact_end_line = start + exact.count("\n")
    if exact_end_line != end:
        raise HardenedError(
            f"candidate exact_text ends on line {exact_end_line}, not claimed source_end_line {end}"
        )

    _, visible, anchor, ordinal = _owning_heading(headings, start)
    if record["section_heading"] != visible:
        raise HardenedError(
            f"section_heading mismatch at candidate line {start}: {record['section_heading']!r} != {visible!r}"
        )
    if record["section_ordinal"] != ordinal:
        raise HardenedError(
            f"section_ordinal mismatch for {visible}: {record['section_ordinal']} != {ordinal}"
        )
    if record["section_anchor"] != anchor:
        raise HardenedError(
            f"section_anchor mismatch for {visible}: {record['section_anchor']!r} != {anchor!r}"
        )


def validate_candidates(repo: Path, source_path: str, candidates_path: Path) -> dict[str, Any]:
    base = _load_base(repo)
    roles, role_counts, _ = base.load_roles(repo)
    source = roles.get(source_path)
    if not source or source["role"] != base.ROLE_DEST:
        raise HardenedError(f"source is not destination-eligible: {source_path}")

    candidates, raw = base.load_candidates(candidates_path, source_path, roles)
    if not candidates:
        raise HardenedError("complete initial candidate batch may not be empty")

    lines, resolved_blob = _load_pinned_source(repo, source_path, source["blob_sha"])
    headings = _eligible_headings(lines)
    if not headings:
        raise HardenedError("pinned source contains no eligible ##/### headings")

    per_section_ordinals: dict[int, list[int]] = {}
    for candidate in candidates:
        _validate_exact_span(candidate, lines, headings)
        per_section_ordinals.setdefault(candidate["section_ordinal"], []).append(candidate["assertion_ordinal"])

    for section_ordinal, ordinals in per_section_ordinals.items():
        expected = list(range(1, len(ordinals) + 1))
        if ordinals != expected:
            raise HardenedError(
                f"assertion_ordinal sequence is not contiguous in section {section_ordinal}: {ordinals}"
            )

    tool_raw = Path(__file__).resolve().read_bytes()
    return {
        "baseline_id": base.BASELINE_ID,
        "candidate_count": len(candidates),
        "candidate_payload_sha256": _sha256(raw),
        "extraction_schema": base.EXTRACTION_SCHEMA,
        "pinned_source_blob_sha": resolved_blob,
        "pinned_source_commit": SOURCE_COMMIT,
        "result": "PASS",
        "role_counts": role_counts,
        "schema": "RC006-A2-CANDIDATE-VALIDATION-RESULT-V1",
        "section_count_with_candidates": len(per_section_ordinals),
        "source_path": source_path,
        "source_roles_git_blob_sha": SOURCE_ROLES_BLOB_SHA,
        "tool_git_blob_sha": _git_blob_sha(tool_raw),
        "tool_sha256": _sha256(tool_raw),
        "tool_version": TOOL_VERSION,
    }


def _write_output(path: str | None, value: dict[str, Any]) -> bytes:
    rendered = _canonical_json_bytes(value)
    if path:
        Path(path).write_bytes(rendered)
    sys.stdout.buffer.write(rendered)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check-state", help="Run base readiness checks without allocation")
    check.add_argument("--expect-zero", action="store_true")
    check.add_argument("--output")

    validate = sub.add_parser("validate-candidates", help="Validate one candidate file against pinned source")
    validate.add_argument("--source-path", required=True)
    validate.add_argument("--candidates", required=True)
    validate.add_argument("--output")

    alloc = sub.add_parser("allocate", help="Hardened validation followed by deterministic allocation")
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
        base = _load_base(repo)
        if args.command == "check-state":
            result = base.readiness(repo, args.expect_zero)
            result = dict(result)
            tool_raw = Path(__file__).resolve().read_bytes()
            result["hardened_tool_git_blob_sha"] = _git_blob_sha(tool_raw)
            result["hardened_tool_sha256"] = _sha256(tool_raw)
            result["hardened_tool_version"] = TOOL_VERSION
            _write_output(args.output, result)
            return 0
        if args.command == "validate-candidates":
            result = validate_candidates(repo, args.source_path, Path(args.candidates))
            _write_output(args.output, result)
            return 0
        if args.command == "allocate":
            validate_candidates(repo, args.source_path, Path(args.candidates))
            result = base.allocate(args)
            result = dict(result)
            tool_raw = Path(__file__).resolve().read_bytes()
            result["hardened_tool_git_blob_sha"] = _git_blob_sha(tool_raw)
            result["hardened_tool_sha256"] = _sha256(tool_raw)
            result["hardened_tool_version"] = TOOL_VERSION
            _write_output(None, result)
            return 0
        parser.error("a command is required")
        return 2
    except (OSError, ValueError, HardenedError, Exception) as exc:
        # Base allocator raises its own ToolError class loaded dynamically, so the
        # broad catch is intentional here; validation/allocation remain fail-closed.
        print(f"A2_HARDENED_ALLOCATOR_ERROR\t{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
