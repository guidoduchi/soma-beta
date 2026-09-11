#!/usr/bin/env python3
"""Context-closed Import Contract candidate generator v0.5.0.

Pins the proven v0.4.0 215-record review corpus and performs one final semantic
closure pass. Only candidate groups whose split fragments depend on a shared
subject, condition, or referent are recombined. Every combined assertion is
reconstructed as one exact contiguous B002 source span. Independent clauses
remain separate. No A2 assertion IDs are allocated by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

VERSION = "0.5.0-review"
PARENT_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_4.py"
PARENT_BLOB_SHA = "fd6947c353614d16a59c7b6362355682dc87c1d2"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/IMPORT_CONTRACT.md"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"
EXPECTED_PARENT_COUNT = 215
EXPECTED_FINAL_COUNT = 186

# Keys are (source_start_line, zero-based occurrence among parent candidates
# with that same source_start_line). Each group must be globally consecutive in
# the parent corpus. Multi-line allowlist candidates use their first source line.
# The final element is the reviewed normative kind for the combined assertion.
COMBINE_GROUPS: list[tuple[list[tuple[int, int]], str, str]] = [
    ([(21, 0), (21, 1), (21, 2)], "DESIGN_BOUNDARY", "Infrastructure workbook identity/absence context"),
    ([(34, 0), (34, 1), (34, 2)], "DESIGN_BOUNDARY", "authoritative-empty-population rule and consequences"),
    ([(36, 1), (36, 2), (36, 3)], "DESIGN_BOUNDARY", "missing nonidentity coverage consequence chain"),
    ([(38, 0), (38, 1), (38, 2)], "DESIGN_BOUNDARY", "Import capture-time provenance boundary"),
    ([(39, 1), (39, 2)], "DESIGN_BOUNDARY", "terminal observation/reappearance reconciliation context"),
    ([(41, 0), (41, 1), (41, 2)], "DESIGN_BOUNDARY", "RFC terminal proposal creation/nonexecution boundary"),
    ([(45, 1), (45, 2)], "DESIGN_BOUNDARY", "bounded provenance and user-managed original"),
    ([(47, 0), (47, 1), (47, 2)], "DESIGN_BOUNDARY", "communication eligibility versus later processing"),
    ([(56, 0), (56, 1)], "OBLIGATION", "current summary plus compact change history"),
    ([(58, 0), (58, 1)], "DESIGN_BOUNDARY", "Beta retained history versus Alpha snapshot exclusion"),
    ([(71, 1), (71, 2)], "DESIGN_BOUNDARY", "historical-row acceptance without operator prefilter"),
    ([(94, 0), (94, 1)], "DESIGN_BOUNDARY", "suspension inconsistency and active-future boundary"),
    ([(110, 4), (110, 5)], "DESIGN_BOUNDARY", "malformed-token isolation rule"),
    ([(114, 0), (114, 1)], "DESIGN_BOUNDARY", "Advanced Search discard and no-domain-creation boundary"),
    ([(118, 3), (118, 4)], "DESIGN_BOUNDARY", "WFM embedded chronology versus filename suffix"),
    ([(138, 0), (138, 1)], "DESIGN_BOUNDARY", "RFC branch artifact skip/nonmutation boundary"),
    ([(144, 0), (151, 0)], "DESIGN_BOUNDARY", "RFC future-use allowlist and prohibited Beta effects"),
    ([(176, 0), (176, 1)], "DESIGN_BOUNDARY", "absent WFM timestamps and unscheduled/otherwise rule"),
    ([(182, 0), (189, 0)], "DESIGN_BOUNDARY", "WFM future-use allowlist and prohibited Beta effects"),
    ([(202, 1), (202, 2)], "DESIGN_BOUNDARY", "Objective nonacceptance and grouping-review consequence"),
    ([(250, 2), (250, 3)], "DESIGN_BOUNDARY", "export destination and nonmutation boundary"),
    ([(252, 0), (252, 1)], "DESIGN_BOUNDARY", "workbook declaration plus human-readable representation"),
    ([(258, 0), (258, 1)], "PROHIBITION", "secret/topology exclusion and no-inference consequence"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def fingerprint(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return sha256(normalized.encode("utf-8"))


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def run_parent(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    script = repo / PARENT_PATH
    raw = script.read_bytes()
    if git_blob_sha(raw) != PARENT_BLOB_SHA:
        raise RuntimeError("Import candidate generator v0.4.0 blob mismatch")
    with tempfile.TemporaryDirectory(prefix="rc006-a2-import-v05-") as td:
        td_path = Path(td)
        output = td_path / "parent.jsonl"
        summary = td_path / "parent-summary.json"
        subprocess.run(
            [sys.executable, str(script), "--repo", str(repo), "--output", str(output), "--summary", str(summary)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        summary_obj = json.loads(summary.read_text(encoding="utf-8"))
    if len(records) != EXPECTED_PARENT_COUNT:
        raise RuntimeError(f"v0.4.0 parent count mismatch: {len(records)} != {EXPECTED_PARENT_COUNT}")
    return records, summary_obj


def load_source(repo: Path) -> list[str]:
    raw = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("pinned Import Contract must use LF with final LF")
    return raw.decode("utf-8", errors="strict").splitlines()


def global_index_map(records: list[dict[str, Any]]) -> dict[tuple[int, int], int]:
    seen: dict[int, int] = {}
    result: dict[tuple[int, int], int] = {}
    for global_index, record in enumerate(records):
        line = record["source_start_line"]
        occurrence = seen.get(line, 0)
        result[(line, occurrence)] = global_index
        seen[line] = occurrence + 1
    return result


def exact_span(source_lines: list[str], first: dict[str, Any], last: dict[str, Any]) -> str:
    start_line = first["source_start_line"]
    end_line = last["source_end_line"]
    first_text_lines = first["exact_text"].split("\n")
    last_text_lines = last["exact_text"].split("\n")

    if start_line == end_line:
        source = source_lines[start_line - 1]
        start_pos = source.index(first_text_lines[0])
        end_pos = source.index(last_text_lines[-1], start_pos) + len(last_text_lines[-1])
        return source[start_pos:end_pos]

    start_source = source_lines[start_line - 1]
    end_source = source_lines[end_line - 1]
    start_pos = start_source.index(first_text_lines[0])
    end_pos = end_source.index(last_text_lines[-1]) + len(last_text_lines[-1])
    parts = [start_source[start_pos:]]
    parts.extend(source_lines[start_line:end_line - 1])
    parts.append(end_source[:end_pos])
    return "\n".join(parts)


def close_context(repo: Path, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_lines = load_source(repo)
    index_map = global_index_map(records)
    consumed: set[int] = set()
    replacements: dict[int, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []

    for keys, reviewed_kind, reason in COMBINE_GROUPS:
        try:
            indices = [index_map[key] for key in keys]
        except KeyError as exc:
            raise RuntimeError(f"context-closure selector missing from parent: {exc}") from exc
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise RuntimeError(f"context-closure group is not globally consecutive: {keys} -> {indices}")
        if consumed.intersection(indices):
            raise RuntimeError(f"context-closure groups overlap: {keys}")
        consumed.update(indices)

        members = [records[i] for i in indices]
        if len({r["section_ordinal"] for r in members}) != 1:
            raise RuntimeError(f"context-closure group crosses sections: {keys}")
        combined_text = exact_span(source_lines, members[0], members[-1])
        # Every parent exact span must appear in-order inside the reconstructed B002 span.
        cursor = 0
        for member in members:
            pos = combined_text.find(member["exact_text"], cursor)
            if pos < 0:
                raise RuntimeError(f"parent assertion missing from reconstructed context span: {member['exact_text']!r}")
            cursor = pos + len(member["exact_text"])

        replacement = dict(members[0])
        replacement.update(
            {
                "exact_text": combined_text,
                "fingerprint_sha256": fingerprint(combined_text),
                "normative_kind": reviewed_kind,
                "review_note": f"Final context-closure review v0.5.0: {reason}; reverse authority remains pending.",
                "schema": SCHEMA,
                "source_start_line": members[0]["source_start_line"],
                "source_end_line": members[-1]["source_end_line"],
            }
        )
        replacements[indices[0]] = replacement
        audit.append(
            {
                "member_count": len(members),
                "reason": reason,
                "source_end_line": replacement["source_end_line"],
                "source_start_line": replacement["source_start_line"],
            }
        )

    final: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if index in replacements:
            final.append(replacements[index])
        elif index in consumed:
            continue
        else:
            final.append(dict(record))

    counters: dict[int, int] = {}
    for record in final:
        section = record["section_ordinal"]
        counters[section] = counters.get(section, 0) + 1
        record["assertion_ordinal"] = counters[section]

    if len(final) != EXPECTED_FINAL_COUNT:
        raise RuntimeError(f"context-closed Import count mismatch: {len(final)} != {EXPECTED_FINAL_COUNT}")
    return final, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    records, summary = run_parent(repo)
    records, audit = close_context(repo, records)
    payload = b"".join(canonical_json(record) for record in records)

    section_counts: dict[int, int] = {}
    for record in records:
        section_counts[record["section_ordinal"]] = section_counts.get(record["section_ordinal"], 0) + 1
    for section in summary["sections"]:
        section["candidate_count"] = section_counts.get(section["section_ordinal"], 0)

    summary.update(
        {
            "candidate_count": len(records),
            "candidate_payload_sha256": sha256(payload),
            "context_closure_group_count": len(audit),
            "context_closure_groups": audit,
            "generator_version": VERSION,
            "parent_generator_git_blob_sha": PARENT_BLOB_SHA,
            "review_model": "final context-closed atomic review over proven v0.4.0 corpus",
        }
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(payload)
    Path(args.summary).write_bytes(canonical_json(summary))
    if args.listing:
        lines = ["assertion\tsection\tline\tkind\texact_text"]
        for index, record in enumerate(records, start=1):
            text = record["exact_text"].replace("\t", "\\t").replace("\n", "\\n")
            lines.append(
                f"{index}\t{record['section_ordinal']}\t{record['source_start_line']}-{record['source_end_line']}\t{record['normative_kind']}\t{text}"
            )
        Path(args.listing).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
