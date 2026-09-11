#!/usr/bin/env python3
"""Final reviewed Import Contract candidate generator v0.3.0.

Pins the v0.2.0 human-review decisions, adds the final opening-clause atomic
split, and corrects optionality/provisional-evidence classification labels.
This remains pre-allocation tooling and never allocates A2 assertion IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

VERSION = "0.3.0-review"
V2_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates_v0_2.py"
V2_BLOB_SHA = "0bac691212067ab7d320f872503b2614ad20eb91"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def load_v2(repo: Path):
    path = repo / V2_PATH
    raw = path.read_bytes()
    if git_blob_sha(raw) != V2_BLOB_SHA:
        raise RuntimeError("Import candidate generator v0.2.0 blob mismatch")
    spec = importlib.util.spec_from_file_location("rc006_import_candidates_v0_2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Import candidate generator v0.2.0")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--listing")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    v2 = load_v2(repo)
    base = v2.load_base(repo)

    original_owning = base.owning
    def safe_owning(heads, line_no):
        prior = [h for h in heads if h[0] < line_no]
        if not prior:
            return "__PREAMBLE__", "__preamble__", 0
        return original_owning(heads, line_no)
    base.owning = safe_owning

    replacements = dict(v2.LINE_REPLACEMENTS)
    replacements[9] = [
        ("SOMA imports operational evidence", "OBLIGATION"),
        ("it does not mirror every column supplied by an external workbook.", "PROHIBITION"),
    ]

    original_candidate_spans = base.candidate_spans
    def reviewed_candidate_spans(lines, heads):
        spans = original_candidate_spans(lines, heads)
        replacement_lines = set(replacements)
        out = []
        emitted = set()
        for start, end, exact, note, forced_kind in spans:
            if start == end and start in replacement_lines:
                if start in emitted:
                    continue
                emitted.add(start)
                source_line = lines[start - 1]
                for atom, kind in replacements[start]:
                    if atom not in source_line:
                        raise RuntimeError(f"reviewed atom is not verbatim at line {start}: {atom!r}")
                    out.append((start, start, atom, "Explicit final human atomicity review v0.3.0; reverse authority remains pending.", kind))
                continue
            out.append((start, end, exact, note, forced_kind))
        missing = replacement_lines - emitted
        if missing:
            raise RuntimeError(f"reviewed replacement lines were not encountered: {sorted(missing)}")
        return out
    base.candidate_spans = reviewed_candidate_spans

    kind_overrides = dict(v2.KIND_OVERRIDES)
    kind_overrides.update({
        "It may record reviewed disappearance warnings but cannot delete or finalize operational records.": "DESIGN_BOUNDARY",
        "All active RFC fields other than canonical identity remain optional according to their field rules.": "DESIGN_BOUNDARY",
        "Missing optional-active headers or values warn/preserve prior accepted truth rather than silently clearing current facts.": "DESIGN_BOUNDARY",
        "All active WFM fields other than `RFC No.` and `Task No.` remain optional according to their field rules.": "DESIGN_BOUNDARY",
        "Missing optional-active coverage warns/preserves prior accepted truth rather than silently clearing current facts.": "DESIGN_BOUNDARY",
        "WFM evidence may support separately reviewed provisional eligibility for a missing RFC but cannot override accepted Enhanced pre-Implement evidence.": "DESIGN_BOUNDARY",
    })
    original_kind = base.kind_for
    def reviewed_kind(text):
        return kind_overrides.get(text, original_kind(text))
    base.kind_for = reviewed_kind

    records, summary = base.build(repo)
    payload = b"".join(base.canonical_json(r) for r in records)
    summary["generator_version"] = VERSION
    summary["parent_generator_git_blob_sha"] = V2_BLOB_SHA
    summary["candidate_payload_sha256"] = base.sha256(payload)
    summary["review_model"] = "final explicit human atomicity/classification review"
    summary["reviewed_replacement_lines"] = sorted(replacements)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(payload)
    Path(args.summary).write_bytes(base.canonical_json(summary))
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
