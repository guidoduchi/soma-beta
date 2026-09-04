#!/usr/bin/env python3
"""Import Contract candidate generator v0.5.1 final referent closure.

Pins the proven v0.5.0 186-record corpus and combines the two section-9.2
assertions so the exclusion sentence's subject ("It" = the workbook format) is
carried inside the same exact B002 span as the allowed-capability sentence.
No other candidate is changed. No A2 assertion IDs are allocated.
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

VERSION = "0.5.1-review"
PARENT_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_5.py"
PARENT_BLOB_SHA = "e77c1667f96c52337d0c50db71233ee1f664f971"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/IMPORT_CONTRACT.md"
EXPECTED_PARENT_COUNT = 186
EXPECTED_FINAL_COUNT = 185


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
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def run_parent(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    script = repo / PARENT_PATH
    raw = script.read_bytes()
    if git_blob_sha(raw) != PARENT_BLOB_SHA:
        raise RuntimeError("Import candidate generator v0.5.0 blob mismatch")
    with tempfile.TemporaryDirectory(prefix="rc006-a2-import-v051-") as td:
        td_path = Path(td)
        out = td_path / "parent.jsonl"
        summary = td_path / "parent-summary.json"
        subprocess.run([sys.executable, str(script), "--repo", str(repo), "--output", str(out), "--summary", str(summary)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        summary_obj = json.loads(summary.read_text(encoding="utf-8"))
    if len(records) != EXPECTED_PARENT_COUNT:
        raise RuntimeError(f"v0.5.0 parent count mismatch: {len(records)} != {EXPECTED_PARENT_COUNT}")
    return records, summary_obj


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    records, summary = run_parent(repo)
    members = [r for r in records if r["section_ordinal"] == 26]
    if len(members) != 2 or [(r["source_start_line"], r["assertion_ordinal"]) for r in members] != [(256, 1), (258, 2)]:
        raise RuntimeError("unexpected v0.5.0 section-9.2 shape")

    source_lines = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}").decode("utf-8", errors="strict").splitlines()
    first, second = members
    start_line, end_line = first["source_start_line"], second["source_end_line"]
    start_source = source_lines[start_line - 1]
    end_source = source_lines[end_line - 1]
    start_pos = start_source.index(first["exact_text"])
    end_pos = end_source.index(second["exact_text"]) + len(second["exact_text"])
    combined = "\n".join([start_source[start_pos:], *source_lines[start_line:end_line - 1], end_source[:end_pos]])
    if first["exact_text"] not in combined or second["exact_text"] not in combined:
        raise RuntimeError("section-9.2 combined span lost parent text")

    replacement = dict(first)
    replacement.update({
        "exact_text": combined,
        "fingerprint_sha256": fingerprint(combined),
        "normative_kind": "DESIGN_BOUNDARY",
        "review_note": "Final referent-closure review v0.5.1: allowed workbook-format capability and its exclusions/no-inference rule are one context-complete boundary; reverse authority remains pending.",
        "source_start_line": start_line,
        "source_end_line": end_line,
    })

    final: list[dict[str, Any]] = []
    inserted = False
    for record in records:
        if record is first or (record["section_ordinal"] == 26 and record["assertion_ordinal"] == 1):
            if not inserted:
                final.append(replacement)
                inserted = True
            continue
        if record["section_ordinal"] == 26 and record["assertion_ordinal"] == 2:
            continue
        final.append(dict(record))

    counters: dict[int, int] = {}
    for record in final:
        sec = record["section_ordinal"]
        counters[sec] = counters.get(sec, 0) + 1
        record["assertion_ordinal"] = counters[sec]

    if len(final) != EXPECTED_FINAL_COUNT:
        raise RuntimeError(f"final Import candidate count mismatch: {len(final)} != {EXPECTED_FINAL_COUNT}")

    payload = b"".join(canonical_json(r) for r in final)
    for section in summary["sections"]:
        if section["section_ordinal"] == 26:
            section["candidate_count"] = 1
    summary.update({
        "candidate_count": len(final),
        "candidate_payload_sha256": sha256(payload),
        "generator_version": VERSION,
        "parent_generator_git_blob_sha": PARENT_BLOB_SHA,
        "review_model": "v0.5.0 context closure plus final section-9.2 referent closure",
        "final_referent_closure": {"source_start_line": 256, "source_end_line": 258, "member_count": 2},
    })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(payload)
    Path(args.summary).write_bytes(canonical_json(summary))
    if args.listing:
        lines = ["assertion\tsection\tline\tkind\texact_text"]
        for index, record in enumerate(final, start=1):
            text = record["exact_text"].replace("\t", "\\t").replace("\n", "\\n")
            lines.append(f"{index}\t{record['section_ordinal']}\t{record['source_start_line']}-{record['source_end_line']}\t{record['normative_kind']}\t{text}")
        Path(args.listing).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
