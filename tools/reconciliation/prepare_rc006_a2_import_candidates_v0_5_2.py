#!/usr/bin/env python3
"""Review-only Import v0.5.2: clarify a referent without merging assertions.

The exact v0.5.0 payload is a prerequisite, not an assertion of semantic
completeness. Only one review_note changes. No freeze or allocation is performed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

VERSION = "0.5.2-review"
PARENT_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_5.py"
PARENT_BLOB = "e77c1667f96c52337d0c50db71233ee1f664f971"
PARENT_PAYLOAD = "ce0a6102cc72ef6e0ef4a00a12f0bb7ae8f15db5c7c6d12ddb301192e1663dfc"
SOURCE_BLOB = "08dcf31d23748d4269538baa6ee1fcd7499585e8"
SOURCE_PATH = "docs/IMPORT_CONTRACT.md"
EXPECTED_COUNT = 186
EXPECTED_SECTIONS = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 21, 25, 26, 27, 28, 29]
TARGET_TEXT = (
    "It contains no password, private key, token, reusable secret, credential-provider reference, "
    "or Beta 1.0 connectivity/topology/interface/port edge. Export never creates those facts, "
    "and import never infers connectivity from co-occurrence, placement, Cloud assignment, "
    "IP patterns, or containment."
)
REVIEW_NOTE = (
    "Referent clarification v0.5.2 (review metadata, not normative text): 'It' at B002 "
    "Import Contract section 9.2, line 258, refers to 'The format' in the immediately "
    "preceding source sentence at line 256: the Infrastructure workbook format. "
    "The line-256 permission remains a separate candidate. Assertion boundaries, kinds, "
    "locators and exact texts are unchanged from v0.5.0. Broader atomicity/completeness "
    "review and reverse authority remain pending; this note grants no freeze/allocation approval."
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def blob(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def annotate(records: list[dict]) -> list[dict]:
    """Pure transformation; refuse any unexpected target and never mutate input."""
    if len(records) != EXPECTED_COUNT:
        raise ValueError("parent candidate count mismatch")
    if sorted({r["section_ordinal"] for r in records}) != EXPECTED_SECTIONS:
        raise ValueError("parent section set mismatch")
    members = [r for r in records if r["section_ordinal"] == 26]
    if len(members) != 2:
        raise ValueError("expected two separate section-9.2 candidates")
    first, second = members
    for row, ordinal, line, kind in [(first, 1, 256, "PERMISSION"), (second, 2, 258, "PROHIBITION")]:
        expected = {"assertion_ordinal": ordinal, "source_start_line": line,
                    "source_end_line": line, "normative_kind": kind,
                    "source_path": SOURCE_PATH, "source_blob_sha": SOURCE_BLOB,
                    "section_heading": "9.2 Allowed capability boundary",
                    "section_anchor": "92-allowed-capability-boundary"}
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("unexpected section-9.2 identity or boundary")
    if not first["exact_text"].startswith("The format may represent ") or second["exact_text"] != TARGET_TEXT:
        raise ValueError("unexpected section-9.2 exact text")
    if "A2-ASSERT-" in json.dumps(records):
        raise ValueError("stable assertion identity present in review candidates")
    final = copy.deepcopy(records)
    target_index = next(i for i, row in enumerate(records) if row is second)
    final[target_index]["review_note"] = REVIEW_NOTE
    restored = copy.deepcopy(final)
    restored[target_index]["review_note"] = second["review_note"]
    if restored != records or final == records:
        raise ValueError("expected exactly one review-note change")
    return final


def transform(raw: bytes) -> list[dict]:
    # Parse exactly the bytes whose identity passed; do not reread a candidate file.
    if digest(raw) != PARENT_PAYLOAD:
        raise ValueError("v0.5.0 parent payload identity mismatch")
    records = [json.loads(line) for line in raw.decode("utf-8", errors="strict").splitlines()]
    return annotate(records)


def review_output_paths(repo: Path, paths: list[str]) -> list[Path]:
    resolved = [Path(path).resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("review output paths must be distinct")
    if any(path.is_relative_to(repo.resolve()) for path in resolved):
        raise ValueError("review outputs must be outside the repository; freeze is a separate operation")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    paths = review_output_paths(repo, [args.output, args.summary] + ([args.listing] if args.listing else []))
    parent_raw = (repo / PARENT_PATH).read_bytes()
    if blob(parent_raw) != PARENT_BLOB:
        raise ValueError("v0.5.0 parent generator blob mismatch")
    with tempfile.TemporaryDirectory(prefix="rc006-a2-import-v052-") as directory:
        temp = Path(directory)
        # Execute the exact parent bytes that were checked, preserving v0.5 evidence.
        script = temp / "parent-generator.py"
        script.write_bytes(parent_raw)
        output, summary_file = temp / "parent.jsonl", temp / "parent-summary.json"
        subprocess.run([sys.executable, str(script), "--repo", str(repo), "--output", str(output),
                        "--summary", str(summary_file)], check=True, capture_output=True)
        final = transform(output.read_bytes())
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    payload = b"".join(encode(row) for row in final)
    summary.update({"generator_version": VERSION, "candidate_count": len(final),
                    "candidate_payload_sha256": digest(payload), "parent_generator_git_blob_sha": PARENT_BLOB,
                    "parent_candidate_payload_sha256": PARENT_PAYLOAD,
                    "review_model": "v0.5.0 boundaries retained; section-9.2 review-note clarification only",
                    "changed_fields": [{"section_ordinal": 26, "assertion_ordinal": 2, "field": "review_note"}],
                    "semantic_review": "OPEN", "freeze_authorized": False, "allocation_authorized": False})
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    paths[0].write_bytes(payload)
    paths[1].write_bytes(encode(summary))
    if args.listing:
        lines = ["candidate\tsection\tline\tkind\texact_text\treview_note"]
        for number, row in enumerate(final, 1):
            values = [number, row["section_ordinal"], f"{row['source_start_line']}-{row['source_end_line']}",
                      row["normative_kind"], row["exact_text"], row["review_note"]]
            lines.append("\t".join(str(v).replace("\t", "\\t").replace("\n", "\\n") for v in values))
        paths[2].write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
