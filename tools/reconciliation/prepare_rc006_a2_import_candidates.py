#!/usr/bin/env python3
"""Prepare reviewed pre-allocation candidates for the pinned B002 Import Contract.

This tool is deliberately source-specific. It extracts normative prose, preserves
mapping-table rows as atomic mapping assertions, preserves future-use allowlists
and workbook-mode lists as multi-line assertions, and excludes the explicitly
historical sample-profile evidence in section 8. It never allocates A2 IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

VERSION = "0.1.0-review"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/IMPORT_CONTRACT.md"
SOURCE_BLOB = "08dcf31d23748d4269538baa6ee1fcd7499585e8"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"

META_PREFIXES = (
    "Status:",
    "Target:",
    "Authority:",
    "The complete governing rules are in",
)

# Section 8 is explicitly aggregate historical evidence, not a promise of future
# completeness. Its sample rows/narratives do not receive assertion identities.
INFORMATIVE_HEADINGS = {
    "8. Observed historical blank profile",
    "Service Requests — 263 rows",
    "RFCs — 22 source rows",
    "WFM Tasks — 17 rows",
}

# Tables under these headings are normative mapping tables. Each data row is a
# complete mapping/design-boundary assertion because its source-column context is
# required to interpret the rule safely.
NORMATIVE_TABLE_HEADINGS = {
    "4.1 Active in Beta 1.0",
    "5.1 Active in Beta 1.0",
    "6.1 Active in Beta 1.0",
}

# Explicit reviewed multi-line assertions that must not be lost by generic list/
# table skipping. Start/end strings must each occur exactly once in the B002 file.
SPECIAL_BLOCKS = [
    (
        "The official source families are:",
        "| WFM Tasks | Service Provider Plan Creation | WFM source facts and provisional parent-RFC hints |",
        "DESIGN_BOUNDARY",
        "Reviewed as one authoritative source-family table assertion.",
    ),
    (
        "These values may be normalized and retained with provenance, but they drive no Beta 1.0 workflow, SLA calculation, relationship, warning, or UI decision unless another accepted contract explicitly says otherwise:",
        "- `Pr Number`",
        "DESIGN_BOUNDARY",
        "Reviewed as one retained-for-future Advanced Search allowlist assertion.",
    ),
    (
        "- `Service Type`",
        "- `Product Name`",
        "DESIGN_BOUNDARY",
        "Reviewed as one retained-for-future Enhanced Excel allowlist assertion.",
    ),
    (
        "- `Request Type`",
        "- `Product`",
        "DESIGN_BOUNDARY",
        "Reviewed as one retained-for-future WFM allowlist assertion.",
    ),
    (
        "SOMA generates one versioned, macro-free `.xlsx` workbook family with three modes:",
        "3. a round-trip export for reviewed updates.",
        "DESIGN_BOUNDARY",
        "Reviewed as one ordered Infrastructure workbook-family capability assertion.",
    ),
]

# Only lines listed here are split below sentence granularity. Each resulting
# span is verbatim and preserves its own normative force/context.
MANUAL_ATOMIC_SPANS: dict[str, list[str]] = {
    "SOMA imports operational evidence; it does not mirror every column supplied by an external workbook.": [
        "SOMA imports operational evidence",
        "it does not mirror every column supplied by an external workbook.",
    ],
    "Enhanced Excel remains authoritative for RFC facts. WFM RFC fields may create or provisionally populate a missing parent RFC, but cannot silently override an accepted Enhanced Excel fact.": [
        "Enhanced Excel remains authoritative for RFC facts.",
        "WFM RFC fields may create or provisionally populate a missing parent RFC, but cannot silently override an accepted Enhanced Excel fact.",
    ],
    "A field may be retained as an active 1.0 fact or retained for a later release. Every other source column is discarded after staging and cannot influence Beta behavior.": [
        "A field may be retained as an active 1.0 fact or retained for a later release.",
        "Every other source column is discarded after staging and cannot influence Beta behavior.",
    ],
    "It is an operator-authored, versioned bulk registration/update format and human-readable discovery export governed by section 9 and the [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md). Absence from that workbook never means disappearance, deletion, archival, relocation, unlinking, or clearing.": [
        "It is an operator-authored, versioned bulk registration/update format and human-readable discovery export governed by section 9 and the [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md).",
        "Absence from that workbook never means disappearance, deletion, archival, relocation, unlinking, or clearing.",
    ],
    "The workbook declares its format version, mode, source-installation scope, generation chronology, and included filter/scope. The exact representation belongs in the LLD, but it must remain human-readable in ordinary spreadsheet software and usable without SOMA for device discovery.": [
        "The workbook declares its format version, mode, source-installation scope, generation chronology, and included filter/scope.",
        "it must remain human-readable in ordinary spreadsheet software and usable without SOMA for device discovery.",
    ],
}

KIND_OVERRIDES = {
    "SOMA imports operational evidence": "OBLIGATION",
    "it does not mirror every column supplied by an external workbook.": "PROHIBITION",
    "Enhanced Excel remains authoritative for RFC facts.": "DESIGN_BOUNDARY",
    "WFM RFC fields may create or provisionally populate a missing parent RFC, but cannot silently override an accepted Enhanced Excel fact.": "DESIGN_BOUNDARY",
    "Every other source column is discarded after staging and cannot influence Beta behavior.": "DESIGN_BOUNDARY",
    "Absence from that workbook never means disappearance, deletion, archival, relocation, unlinking, or clearing.": "PROHIBITION",
    "it must remain human-readable in ordinary spreadsheet software and usable without SOMA for device discovery.": "OBLIGATION",
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return sha256(normalized.encode("utf-8"))


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def anchor(heading: str) -> str:
    text = unicodedata.normalize("NFC", heading).replace("`", "").replace("*", "").replace("_", "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in {" ", "-"})
    return re.sub(r"-+", "-", re.sub(r" +", "-", text)).strip("-")


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?]) (?=(?:[A-Z]|`|\*|\[))", text) if p.strip()]


def kind_for(text: str) -> str:
    if text in KIND_OVERRIDES:
        return KIND_OVERRIDES[text]
    low = text.lower()
    padded = f" {low} "
    boundaries = (
        " is not ", " are not ", " distinct from ", " separate from ", " only when ", " only from ",
        " only for ", " at most one ", " exactly one ", " remains optional ", " retained for future ",
        " authoritative ", " provenance only ", " does not grant ", " does not prove ",
    )
    prohibitions = (
        " must not ", " never ", " cannot ", " does not ", " do not ", " shall not ",
        " no automatic ", " no silent", " not committed ", " not persisted ",
    )
    if any(term in padded for term in boundaries):
        return "DESIGN_BOUNDARY"
    if any(term in padded for term in prohibitions):
        return "PROHIBITION"
    if re.search(r"\bmay\b|\bcan\b|\ballowed\b|\bpermits?\b|\boptional\b", low):
        return "PERMISSION"
    return "OBLIGATION"


def source(repo: Path) -> tuple[list[str], str, bytes]:
    blob = git(repo, "rev-parse", f"{SOURCE_COMMIT}:{SOURCE_PATH}").decode("ascii").strip()
    if blob != SOURCE_BLOB:
        raise RuntimeError(f"IMPORT_CONTRACT blob mismatch: {blob} != {SOURCE_BLOB}")
    raw = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}")
    if git_blob_sha(raw) != SOURCE_BLOB:
        raise RuntimeError("IMPORT_CONTRACT raw Git blob identity mismatch")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("IMPORT_CONTRACT must use LF with final LF")
    return raw.decode("utf-8", errors="strict").splitlines(), blob, raw


def headings(lines: list[str]) -> list[tuple[int, str, str, int]]:
    result = []
    for line_no, line in enumerate(lines, start=1):
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if m:
            visible = m.group(2)
            result.append((line_no, visible, anchor(visible), len(result) + 1))
    return result


def owning(heads: list[tuple[int, str, str, int]], line_no: int) -> tuple[str, str, int]:
    prior = [h for h in heads if h[0] < line_no]
    if not prior:
        raise RuntimeError(f"no eligible heading before line {line_no}")
    _, visible, norm, ordinal = prior[-1]
    return visible, norm, ordinal


def find_line(lines: list[str], exact: str) -> int:
    matches = [i for i, line in enumerate(lines, start=1) if line == exact]
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact line for {exact!r}, found {len(matches)}")
    return matches[0]


def special_spans(lines: list[str]) -> dict[int, tuple[int, str, str, str]]:
    result: dict[int, tuple[int, str, str, str]] = {}
    for start_text, end_text, kind, note in SPECIAL_BLOCKS:
        start = find_line(lines, start_text)
        end = find_line(lines, end_text)
        if end < start:
            raise RuntimeError(f"invalid special span order: {start_text!r}")
        result[start] = (end, "\n".join(lines[start - 1 : end]), kind, note)
    return result


def is_table_separator(line: str) -> bool:
    if not line.startswith("|"):
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def is_table_header(line: str) -> bool:
    return line.startswith("| Source column |") or line.startswith("| Domain |") or line.startswith("| Field |")


def candidate_spans(lines: list[str], heads: list[tuple[int, str, str, int]]) -> list[tuple[int, int, str, str, str | None]]:
    specials = special_spans(lines)
    covered: set[int] = set()
    for start, (end, _, _, _) in specials.items():
        covered.update(range(start, end + 1))

    spans: list[tuple[int, int, str, str, str | None]] = []
    i = 1
    while i <= len(lines):
        if i in specials:
            end, text, kind, note = specials[i]
            spans.append((i, end, text, note, kind))
            i = end + 1
            continue
        if i in covered:
            i += 1
            continue

        line = lines[i - 1]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        heading, _, _ = owning(heads, i)
        if heading in INFORMATIVE_HEADINGS:
            i += 1
            continue
        if any(stripped.startswith(prefix) for prefix in META_PREFIXES):
            i += 1
            continue

        if stripped.startswith("|"):
            if heading in NORMATIVE_TABLE_HEADINGS and not is_table_header(stripped) and not is_table_separator(stripped):
                spans.append((i, i, stripped, "Reviewed as one complete source-column mapping assertion; reverse authority remains pending.", "DESIGN_BOUNDARY"))
            i += 1
            continue

        # Numbered/bulleted list members are skipped only when they belong to an
        # explicit special block. Other bullet prose is normative and processed.
        selected = stripped[2:] if stripped.startswith("- ") else stripped
        if re.match(r"^\d+\. ", selected):
            selected = re.sub(r"^\d+\. ", "", selected)

        atoms = MANUAL_ATOMIC_SPANS.get(selected, split_sentences(selected))
        for atom in atoms:
            if atom not in line:
                raise RuntimeError(f"reviewed atom is not verbatim at line {i}: {atom!r}")
            spans.append((i, i, atom, "Human-reviewed candidate at sentence or explicit atomic-span granularity; reverse authority remains pending.", None))
        i += 1
    return spans


def build(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines, blob, raw = source(repo)
    heads = headings(lines)
    raw_spans = candidate_spans(lines, heads)
    counts: dict[int, int] = {}
    records: list[dict[str, Any]] = []

    for start, end, exact, note, forced_kind in raw_spans:
        visible, norm, section_ordinal = owning(heads, start)
        counts[section_ordinal] = counts.get(section_ordinal, 0) + 1
        records.append(
            {
                "assertion_ordinal": counts[section_ordinal],
                "classification_review": "PASS",
                "exact_text": exact,
                "fingerprint_sha256": fingerprint(exact),
                "normative_kind": forced_kind or kind_for(exact),
                "review_note": note,
                "schema": SCHEMA,
                "section_anchor": norm,
                "section_heading": visible,
                "section_ordinal": section_ordinal,
                "source_blob_sha": blob,
                "source_end_line": end,
                "source_path": SOURCE_PATH,
                "source_start_line": start,
            }
        )

    records.sort(key=lambda r: (r["section_ordinal"], r["assertion_ordinal"]))
    sections = [
        {
            "section_anchor": norm,
            "section_heading": visible,
            "section_ordinal": ordinal,
            "candidate_count": counts.get(ordinal, 0),
        }
        for _, visible, norm, ordinal in heads
    ]
    payload = b"".join(canonical_json(r) for r in records)
    summary = {
        "candidate_count": len(records),
        "candidate_payload_sha256": sha256(payload),
        "generator_version": VERSION,
        "pinned_source_blob_sha": blob,
        "pinned_source_commit": SOURCE_COMMIT,
        "pinned_source_payload_sha256": sha256(raw),
        "result": "PASS",
        "schema": "RC006-A2-IMPORT-CANDIDATE-PREPARATION-V1",
        "sections": sections,
        "source_path": SOURCE_PATH,
    }
    return records, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()

    records, summary = build(Path(args.repo).resolve())
    payload = b"".join(canonical_json(r) for r in records)
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
