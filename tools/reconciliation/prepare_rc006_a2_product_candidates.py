#!/usr/bin/env python3
"""Prepare the complete pre-allocation candidate set for PRODUCT_CONTRACT.md.

The source is always read from A2-BASELINE-002. This script encodes the
human-review decisions for what is normative in the Product Contract; it does
not allocate A2-ASSERT identities.
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

VERSION = "1.0.0"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/PRODUCT_CONTRACT.md"
SOURCE_BLOB = "6ba3ecb8eabd0845927aa4e6436ec09130a90263"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"

# Whole-line/paragraph metadata or delegation text that is intentionally not an
# independent Product Contract destination assertion.
META_PREFIXES = (
    "Status:",
    "Target:",
    "Authority:",
    "Normative supporting contracts:",
    "The ticket-opening behavior, split communication preview, tab order, device-reference workflow, and Objective grouping behavior are normative in",
    "The complete discovery, identity, hierarchy, status, grouping, and terminal-cascade rules are governed by",
    "The complete lifecycle, cardinalities, deterministic assignment, request-origin rules, logistics snapshots, Fault Tag membership and lineage, manual and bulk alternatives, correction semantics, evidence boundary, and deletion behavior are normative in",
    "The complete normative behavior is in",
    "Its contract is defined in",
    "The exact active/deferred allowlists, discarded-column boundary, delimiters, conditional blanks, historical cutoff, source precedence, and aggregate sample evidence are normative in",
    "The complete normative lifecycle is defined by",
    "The confirmed IT/NFV templates, Non-fault inquiry derivation, cancelled exclusion, and normative calculation rules are in",
    "The [Foundation Runtime, Persistence, Audit, and Verification Contract]",
)

EXACT_INFORMATIVE = {
    "Examples include an RFC without a Service Request, a WFM without an Objective, an Objective awaiting review, and a Spare Request dispatched beyond its threshold.",
    "This direction is informed by the clarity of mature infrastructure-management interfaces without copying their branding, assets, exact pixels, dense typography, or wide-screen assumptions.",
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


def anchor(heading: str) -> str:
    text = unicodedata.normalize("NFC", heading)
    text = text.replace("`", "").replace("*", "").replace("_", "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in {" ", "-"})
    text = re.sub(r" +", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def split_sentences(text: str) -> list[str]:
    # Product Contract prose uses ordinary sentence punctuation. Keep semicolon-
    # connected clauses together when they form one tightly coupled rule.
    parts = re.split(r"(?<=[.!?]) (?=(?:[A-Z]|`|\*|\[))", text)
    return [part.strip() for part in parts if part.strip()]


def kind_for(text: str) -> str:
    low = text.lower()
    boundary_terms = (
        " is not ", " are not ", " not a ", " not an ", "excluded from",
        "has no ", "have no ", "does not authorize", "do not authorize",
        "does not become", "do not become", "distinct from", "separate from",
        "is confined to", "are confined to", "rather than", "only where",
    )
    prohibition_terms = (
        " must not ", " never ", " cannot ", " does not ", " do not ",
        " no silent", " no general", " no device", " no username",
    )
    padded = f" {low} "
    if any(term in padded for term in boundary_terms):
        return "DESIGN_BOUNDARY"
    if any(term in padded for term in prohibition_terms):
        return "PROHIBITION"
    if re.search(r"\bmay\b|\bcan\b|\boptional\b|\ballowed\b|\bpermits?\b", low):
        return "PERMISSION"
    return "OBLIGATION"


def source(repo: Path) -> tuple[list[str], str]:
    blob = git(repo, "rev-parse", f"{SOURCE_COMMIT}:{SOURCE_PATH}").decode("ascii").strip()
    if blob != SOURCE_BLOB:
        raise RuntimeError(f"PRODUCT_CONTRACT blob mismatch: {blob}")
    raw = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}")
    if b"\r" in raw:
        raise RuntimeError("PRODUCT_CONTRACT contains CR")
    return raw.decode("utf-8", errors="strict").splitlines(), blob


def headings(lines: list[str]) -> list[tuple[int, str, str, int]]:
    result: list[tuple[int, str, str, int]] = []
    for line_no, line in enumerate(lines, start=1):
        match = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if match:
            visible = match.group(2)
            result.append((line_no, visible, anchor(visible), len(result) + 1))
    return result


def owning(heads: list[tuple[int, str, str, int]], line_no: int) -> tuple[str, str, int]:
    prior = [entry for entry in heads if entry[0] < line_no]
    if not prior:
        raise RuntimeError(f"no eligible heading before line {line_no}")
    _, visible, normalized, ordinal = prior[-1]
    return visible, normalized, ordinal


def find_line(lines: list[str], exact: str) -> int:
    matches = [i for i, line in enumerate(lines, start=1) if line == exact]
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact line for {exact!r}, found {len(matches)}")
    return matches[0]


def special_spans(lines: list[str]) -> dict[int, tuple[int, str, str]]:
    # start_line -> (end_line, exact_text, note)
    result: dict[int, tuple[int, str, str]] = {}

    nav_start = find_line(lines, "The primary navigation is fixed, in order:")
    nav_end = find_line(lines, "6. Settings")
    result[nav_start] = (
        nav_end,
        "\n".join(lines[nav_start - 1 : nav_end]),
        "Reviewed as one atomic ordered-navigation obligation; list order is the rule.",
    )

    overview_start = find_line(lines, "Default sections include:")
    overview_end = find_line(lines, "| Objectives | Scheduled, completed, incomplete, awaiting review |")
    result[overview_start] = (
        overview_end,
        "\n".join(lines[overview_start - 1 : overview_end]),
        "Reviewed as one default Overview-section/measure composition obligation.",
    )

    import_start = find_line(lines, "The official 1.0.0 sources are:")
    import_end = find_line(lines, "| WFM Tasks | Service Provider Plan Creation Excel export |")
    result[import_start] = (
        import_end,
        "\n".join(lines[import_start - 1 : import_end]),
        "Reviewed as one authoritative operational-source table obligation.",
    )
    return result


def is_meta(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in EXACT_INFORMATIVE:
        return True
    return any(stripped.startswith(prefix) for prefix in META_PREFIXES)


def candidate_spans(lines: list[str]) -> list[tuple[int, int, str, str]]:
    specials = special_spans(lines)
    special_covered: set[int] = set()
    for start, (end, _, _) in specials.items():
        special_covered.update(range(start, end + 1))

    spans: list[tuple[int, int, str, str]] = []
    i = 1
    while i <= len(lines):
        if i in specials:
            end, text, note = specials[i]
            spans.append((i, end, text, note))
            i = end + 1
            continue
        if i in special_covered:
            i += 1
            continue

        line = lines[i - 1]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if stripped.startswith("|") or re.match(r"^\d+\. ", stripped):
            # Tables/ordered navigation are consumed only through explicit special spans.
            i += 1
            continue
        if stripped in {"Default sections include:", "Below the measures, Overview provides:", "The physical/organizational model is:"}:
            i += 1
            continue
        if is_meta(stripped):
            i += 1
            continue

        selected = stripped[2:] if stripped.startswith("- ") else stripped
        for sentence in split_sentences(selected):
            if is_meta(sentence):
                continue
            # Exact sentence text must occur verbatim on this source line. The Product
            # Contract has no multi-line prose paragraphs outside explicit special spans.
            if sentence not in line:
                raise RuntimeError(f"sentence split is not verbatim at line {i}: {sentence!r}")
            note = "Reviewed as an independent normative Product Contract statement; reverse authority remains pending."
            spans.append((i, i, sentence, note))
        i += 1
    return spans


def build(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines, blob = source(repo)
    heads = headings(lines)
    raw_spans = candidate_spans(lines)

    section_counts: dict[int, int] = {}
    records: list[dict[str, Any]] = []
    for start, end, exact, note in raw_spans:
        visible, normalized, section_ordinal = owning(heads, start)
        section_counts[section_ordinal] = section_counts.get(section_ordinal, 0) + 1
        assertion_ordinal = section_counts[section_ordinal]
        records.append({
            "assertion_ordinal": assertion_ordinal,
            "classification_review": "PASS",
            "exact_text": exact,
            "fingerprint_sha256": fingerprint(exact),
            "normative_kind": kind_for(exact),
            "review_note": note,
            "schema": SCHEMA,
            "section_anchor": normalized,
            "section_heading": visible,
            "section_ordinal": section_ordinal,
            "source_blob_sha": blob,
            "source_end_line": end,
            "source_path": SOURCE_PATH,
            "source_start_line": start,
        })

    # Candidate order and section assertion ordinals must be deterministic.
    records.sort(key=lambda r: (r["section_ordinal"], r["assertion_ordinal"]))
    summary_sections = []
    for _, visible, normalized, ordinal in heads:
        count = section_counts.get(ordinal, 0)
        summary_sections.append({
            "section_anchor": normalized,
            "section_heading": visible,
            "section_ordinal": ordinal,
            "candidate_count": count,
        })

    summary = {
        "candidate_count": len(records),
        "generator_version": VERSION,
        "pinned_source_blob_sha": blob,
        "pinned_source_commit": SOURCE_COMMIT,
        "result": "PASS",
        "schema": "RC006-A2-PRODUCT-CANDIDATE-PREPARATION-V1",
        "sections": summary_sections,
        "source_path": SOURCE_PATH,
    }
    return records, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    records, summary = build(repo)
    candidate_bytes = b"".join(canonical_json(record) for record in records)
    summary["candidate_payload_sha256"] = sha256(candidate_bytes)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(candidate_bytes)
    Path(args.summary).write_bytes(canonical_json(summary))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
