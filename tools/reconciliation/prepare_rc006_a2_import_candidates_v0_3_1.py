#!/usr/bin/env python3
"""Import Contract candidate generator v0.3.1 completeness correction.

Pins v0.3.0 and repairs one fail-fast-detected omission: v0.3.0 replaced every
candidate sourced from line 9 with only the two newly split clauses, dropping
three other normative sentences on that same source line. This wrapper restores
all five reviewed line-9 assertions, re-numbers section 1 deterministically, and
leaves every other v0.3.0 candidate byte-for-byte semantically unchanged.

No A2 assertion IDs are allocated by this tool.
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

VERSION = "0.3.1-review"
V3_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_3.py"
V3_BLOB_SHA = "4a9e850894d480faf0863e9e018377ee0b37aca2"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"

LINE9_ASSERTIONS = [
    ("SOMA imports operational evidence", "OBLIGATION"),
    ("it does not mirror every column supplied by an external workbook.", "PROHIBITION"),
    ("Only fields explicitly allowlisted here may enter normalized Beta persistence.", "DESIGN_BOUNDARY"),
    ("A field may be retained as an active 1.0 fact or retained for a later release.", "DESIGN_BOUNDARY"),
    ("Every other source column is discarded after staging and cannot influence Beta behavior.", "DESIGN_BOUNDARY"),
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


def run_v3(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    script = repo / V3_PATH
    raw = script.read_bytes()
    if git_blob_sha(raw) != V3_BLOB_SHA:
        raise RuntimeError("Import candidate generator v0.3.0 blob mismatch")

    with tempfile.TemporaryDirectory(prefix="rc006-a2-import-v031-") as td:
        td_path = Path(td)
        output = td_path / "v3.jsonl"
        summary = td_path / "v3-summary.json"
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--repo",
                str(repo),
                "--output",
                str(output),
                "--summary",
                str(summary),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        summary_obj = json.loads(summary.read_text(encoding="utf-8"))
    return records, summary_obj


def repair(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    line9 = [r for r in records if r["section_ordinal"] == 1 and r["source_start_line"] == 9]
    if len(line9) != 2:
        raise RuntimeError(f"v0.3.0 line-9 shape changed: expected 2 records, found {len(line9)}")
    template = dict(line9[0])

    kept = [r for r in records if not (r["section_ordinal"] == 1 and r["source_start_line"] == 9)]
    restored: list[dict[str, Any]] = []
    for ordinal, (text, kind) in enumerate(LINE9_ASSERTIONS, start=1):
        record = dict(template)
        record.update(
            {
                "assertion_ordinal": ordinal,
                "classification_review": "PASS",
                "exact_text": text,
                "fingerprint_sha256": fingerprint(text),
                "normative_kind": kind,
                "review_note": "Final completeness-corrected human review v0.3.1; reverse authority remains pending.",
                "schema": SCHEMA,
                "source_start_line": 9,
                "source_end_line": 9,
            }
        )
        restored.append(record)

    section1_rest = sorted(
        [r for r in kept if r["section_ordinal"] == 1],
        key=lambda r: r["assertion_ordinal"],
    )
    for ordinal, record in enumerate(section1_rest, start=6):
        record["assertion_ordinal"] = ordinal

    others = [r for r in kept if r["section_ordinal"] != 1]
    final = restored + section1_rest + others
    final.sort(key=lambda r: (r["section_ordinal"], r["assertion_ordinal"]))
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    records, summary = run_v3(repo)
    records = repair(records)
    payload = b"".join(canonical_json(r) for r in records)

    sections = summary["sections"]
    for section in sections:
        if section["section_ordinal"] == 1:
            section["candidate_count"] = 12
            break
    summary.update(
        {
            "candidate_count": len(records),
            "candidate_payload_sha256": sha256(payload),
            "generator_version": VERSION,
            "parent_generator_git_blob_sha": V3_BLOB_SHA,
            "review_model": "v0.3.0 final review plus line-9 completeness correction",
            "line9_assertion_count": 5,
        }
    )

    if len(records) != 223:
        raise RuntimeError(f"final Import candidate count mismatch: {len(records)} != 223")

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
