#!/usr/bin/env python3
"""Context-safe final Import Contract candidate generator v0.4.0.

Pins v0.3.1 and recombines only those split assertions whose meaning depends on
an anaphoric or conditional fragment (for example: "it", "this boundary",
"that local consequence", "otherwise", "such a WFM", "that proposal", or
"those facts"). Splits with independent explicit subjects remain split.

Every touched source line is replaced as a COMPLETE per-line candidate set so a
review edit cannot silently drop sibling assertions. No A2 IDs are allocated.
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

VERSION = "0.4.0-review"
PARENT_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_3_1.py"
PARENT_BLOB_SHA = "22e5d863b88ad6baa28dc70106a5ba32ece61853"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/IMPORT_CONTRACT.md"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"

# Complete candidate outputs for each touched B002 source line.
COMPLETE_LINE_SETS: dict[int, list[tuple[str, str]]] = {
    9: [
        ("SOMA imports operational evidence; it does not mirror every column supplied by an external workbook.", "DESIGN_BOUNDARY"),
        ("Only fields explicitly allowlisted here may enter normalized Beta persistence.", "DESIGN_BOUNDARY"),
        ("A field may be retained as an active 1.0 fact or retained for a later release.", "DESIGN_BOUNDARY"),
        ("Every other source column is discarded after staging and cannot influence Beta behavior.", "DESIGN_BOUNDARY"),
    ],
    39: [
        ("One official SRNo identifies one surviving SR.", "DESIGN_BOUNDARY"),
        ("Later terminal observations reconcile normally", "OBLIGATION"),
        ("a valid reappearance may clear a source-disappearance warning.", "PERMISSION"),
        ("A recognized nonterminal Status after accepted terminal evidence is a high-risk proposal that never auto-accepts; explicit acceptance updates the same SR while preserving prior terminal evidence and completed report snapshots.", "DESIGN_BOUNDARY"),
    ],
    48: [
        ("An accepted terminal SR lifecycle transition may invoke its governed direct-communication unlink consequence.", "PERMISSION"),
        ("For RFCs, accepted source terminal evidence alone does not unlink Communications: only the separately reviewed and confirmed RFC terminal cascade may perform that local consequence under the RFC/WFM and Communications contracts.", "DESIGN_BOUNDARY"),
        ("Staged, rejected, invalid, merely parsed, or merely source-accepted-but-uncascaded RFC terminal values never unlink or purge communication evidence.", "PROHIBITION"),
    ],
    49: [
        ("An accepted terminal reversal during orphan grace restores the applicable same-entity relationship when its evidence remains available and cancels pending purge.", "OBLIGATION"),
        ("After content purge, the independent communication workflow may run a targeted backfill if the source remains available; otherwise the workbench records a coverage warning.", "DESIGN_BOUNDARY"),
        ("Import never fabricates reconstructed content.", "PROHIBITION"),
    ],
    62: [
        ("After an Advanced Search inbox is configured, its automatic daily check is enabled by default at 10:00 in the fixed operational timezone `America/Guayaquil`; changing the Objective scheduling timezone does not reinterpret this boundary.", "DESIGN_BOUNDARY"),
    ],
    176: [
        ("Both planned timestamps may be absent; such a WFM remains unscheduled.", "DESIGN_BOUNDARY"),
        ("Otherwise both must be usable, with end after start.", "OBLIGATION"),
        ("Any valid minute is accepted.", "OBLIGATION"),
        ("Exactly one timestamp or an invalid interval is a row-level failure by default and shall not fabricate scheduling or automatically reject unrelated valid rows.", "DESIGN_BOUNDARY"),
    ],
    204: [
        ("`Complete` and `Plan Cancel` rows remain historical provider evidence.", "DESIGN_BOUNDARY"),
        ("`Plan Cancel` may create or adopt its exact identity but cannot promote/reactivate an RFC or create an Objective.", "DESIGN_BOUNDARY"),
        ("An accepted provider-`Complete` WFM with no Objective and a usable accepted source interval may produce a separate reviewed historical-Objective proposal; that proposal proves neither actual execution nor SOMA Task outcome or downstream Inventory/Device effects.", "DESIGN_BOUNDARY"),
    ],
    258: [
        ("It contains no password, private key, token, reusable secret, credential-provider reference, or Beta 1.0 connectivity/topology/interface/port edge.", "PROHIBITION"),
        ("Export never creates those facts, and import never infers connectivity from co-occurrence, placement, Cloud assignment, IP patterns, or containment.", "PROHIBITION"),
    ],
}


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
        raise RuntimeError("Import candidate generator v0.3.1 blob mismatch")
    with tempfile.TemporaryDirectory(prefix="rc006-a2-import-v04-") as td:
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
    return records, summary_obj


def source_lines(repo: Path) -> list[str]:
    raw = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}")
    return raw.decode("utf-8", errors="strict").splitlines()


def repair(repo: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = source_lines(repo)
    touched = set(COMPLETE_LINE_SETS)
    kept = [r for r in records if r["source_start_line"] not in touched]
    replacements: list[dict[str, Any]] = []

    for line_no in sorted(touched):
        existing = [r for r in records if r["source_start_line"] == line_no]
        if not existing:
            raise RuntimeError(f"parent corpus has no candidate at reviewed line {line_no}")
        template = dict(existing[0])
        source_line = lines[line_no - 1]
        for text, kind in COMPLETE_LINE_SETS[line_no]:
            if text not in source_line:
                raise RuntimeError(f"reviewed text is not a contiguous B002 span at line {line_no}: {text!r}")
            record = dict(template)
            record.update(
                {
                    "exact_text": text,
                    "fingerprint_sha256": fingerprint(text),
                    "normative_kind": kind,
                    "review_note": "Context-safe final human review v0.4.0; reverse authority remains pending.",
                    "schema": SCHEMA,
                    "source_start_line": line_no,
                    "source_end_line": line_no,
                }
            )
            replacements.append(record)

    final = kept + replacements
    final.sort(key=lambda r: (r["section_ordinal"], r["source_start_line"], r["source_end_line"], r["assertion_ordinal"]))

    # Re-number each section after the context-safe recombination. Order inside a
    # touched source line is the COMPLETE_LINE_SETS order as appended above.
    # Re-sort using source location plus desired text index for touched lines.
    order_index = {
        (line_no, text): idx
        for line_no, items in COMPLETE_LINE_SETS.items()
        for idx, (text, _) in enumerate(items)
    }
    final.sort(
        key=lambda r: (
            r["section_ordinal"],
            r["source_start_line"],
            r["source_end_line"],
            order_index.get((r["source_start_line"], r["exact_text"]), 100000 + r["assertion_ordinal"]),
        )
    )
    counters: dict[int, int] = {}
    for record in final:
        section = record["section_ordinal"]
        counters[section] = counters.get(section, 0) + 1
        record["assertion_ordinal"] = counters[section]
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    records, summary = run_parent(repo)
    records = repair(repo, records)
    payload = b"".join(canonical_json(r) for r in records)

    counts: dict[int, int] = {}
    for record in records:
        counts[record["section_ordinal"]] = counts.get(record["section_ordinal"], 0) + 1
    for section in summary["sections"]:
        section["candidate_count"] = counts.get(section["section_ordinal"], 0)

    summary.update(
        {
            "candidate_count": len(records),
            "candidate_payload_sha256": sha256(payload),
            "generator_version": VERSION,
            "parent_generator_git_blob_sha": PARENT_BLOB_SHA,
            "review_model": "context-safe sentence/atomic-span review with complete per-line replacements",
            "context_safe_replacement_lines": sorted(COMPLETE_LINE_SETS),
        }
    )

    if len(records) != 215:
        raise RuntimeError(f"context-safe Import candidate count mismatch: {len(records)} != 215")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(payload)
    Path(args.summary).write_bytes(canonical_json(summary))

    if args.listing:
        lines_out = ["assertion\tsection\tline\tkind\texact_text"]
        for index, record in enumerate(records, start=1):
            text = record["exact_text"].replace("\t", "\\t").replace("\n", "\\n")
            lines_out.append(
                f"{index}\t{record['section_ordinal']}\t{record['source_start_line']}-{record['source_end_line']}\t{record['normative_kind']}\t{text}"
            )
        Path(args.listing).write_text("\n".join(lines_out) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
