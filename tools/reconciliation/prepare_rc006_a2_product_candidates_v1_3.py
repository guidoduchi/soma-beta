#!/usr/bin/env python3
"""Final reviewed Product Contract candidate generator (pre-allocation).

This wrapper pins and reuses generator v1.2.0, then applies the last explicit
human-review refinements without changing A2-BASELINE-002 or allocating IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

VERSION = "1.3.1"
BASE_PATH = "tools/reconciliation/prepare_rc006_a2_product_candidates.py"
BASE_BLOB_SHA = "93a246b3babf5b9fa28a13c6c0190cd6bd09bca1"

FINAL_SPANS = {
    93: [
        "If omitted, SOMA generates `LSR-` followed by an eight-digit installation-local sequence beginning at `00000001`.",
        "Later reconciliation to an official SR requires an explicit operator-reviewed mapping",
        "SOMA does not guess.",
    ],
    234: [
        "Partial processing is valid",
        "one membership never forces another's state.",
    ],
    338: [
        "Service Request, Spare Request, and RFC views distinguish received and sent counts, direction, last-interaction age, coverage/warnings, and canonical-message navigation without copying bodies.",
        "Terminal SR/RFC views retain their frozen minimal summary even after the body is purged.",
        "Beta 1.0 persistence accepts optional communication evidence references but exposes no attachment/upload control",
        "manual domain actions remain valid without evidence.",
    ],
    361: [
        "Beta 1.0.0 provides Historical views and archive-safe presentation and no general purge of operational domain records.",
        "The narrow orphaned-communication content transition in section 12 is the only elapsed-time operational-content exception",
        "it preserves domain records, link/purge history, and the frozen terminal summary.",
    ],
    342: [
        "Contract Product Line classification, SLA calculation, warnings, and reporting are core product capabilities, not an optional reporting add-on.",
        "Each Contract belongs to exactly one Customer Organization.",
        "Product Lines such as IT and NFV are reusable definitions",
        "every occurrence inside a Contract is a distinct Contract Product Line that owns its customer-and-contract-specific SLA policy",
        "two customers may therefore apply different policies to the same Product Line.",
        "An SLA tier measures the percentage of an eligible Service Request cohort resolved or closed within an inclusive duration",
        "it is not a percentage of one ticket's allowed time.",
        "Each SR has at most one active Contract Product Line classification, and its Contract must belong to the SR's resolved Customer Organization.",
        "Automatic import classification must be deterministic and based only on trusted allowlisted evidence",
        "unresolved, ambiguous, unmatched, or cross-customer proposals remain unclassified for review",
        "the discarded Advanced Search `Product` field never selects a policy.",
        "Manual reclassification is audited.",
        "An accepted policy revision recalculates every existing SR under that Contract Product Line, including older and terminal SRs",
        "completed report snapshots remain immutable",
        "every later view and report uses the revised policy.",
    ],
}

KIND_OVERRIDES = {
    "Daily, Weekly, and Monthly exports derive from one internally consistent accepted-state snapshot and may cover one Customer Organization or all organizations.": "OBLIGATION",
    "RFC hierarchy is exactly two levels: one master RFC may own direct subordinate RFCs.": "DESIGN_BOUNDARY",
    "Plan Cancel may create or adopt an exact cancelled record but never activates work, promotes an RFC, or creates an Objective.": "DESIGN_BOUNDARY",
    "A Task bridging multiple Objectives proposes their consolidation and union timeframe because accepted Objectives may not overlap.": "OBLIGATION",
    "A generated `.msg` contains the temporary tracking identifier but never proves submission or sending and never starts the response-warning timer.": "DESIGN_BOUNDARY",
    "Actual inbound BOM and serial remain on that unit and may differ from the promise after review.": "DESIGN_BOUNDARY",
    "Actual pickup is a separate event and may preserve a reviewed difference.": "DESIGN_BOUNDARY",
    "Indexed communications create idempotent reviewed proposals and never mutate Inventory before acceptance.": "DESIGN_BOUNDARY",
    "Tickets, Tasks, Objectives, and Inventory use a Device Reference that may remain unregistered/external or resolve to one registered Network Element": "DESIGN_BOUNDARY",
    "Manufacturer serial is optional evidence and never relational identity.": "DESIGN_BOUNDARY",
    "A later graph engine may exist only as a measured, rebuildable, disposable derived projection without independent authoritative writes or unique facts.": "DESIGN_BOUNDARY",
    "Beta 1.0 persistence accepts optional communication evidence references but exposes no attachment/upload control": "DESIGN_BOUNDARY",
    "An unresolved SR remains operationally usable but SLA-unclassified.": "DESIGN_BOUNDARY",
    "Current Handler remains optional source-owned information.": "DESIGN_BOUNDARY",
    "Partial processing is valid": "PERMISSION",
    "one membership never forces another's state.": "PROHIBITION",
    "Later reconciliation to an official SR requires an explicit operator-reviewed mapping": "OBLIGATION",
    "SOMA does not guess.": "PROHIBITION",
    "The narrow orphaned-communication content transition in section 12 is the only elapsed-time operational-content exception": "DESIGN_BOUNDARY",
    "it preserves domain records, link/purge history, and the frozen terminal summary.": "OBLIGATION",
    "unresolved, ambiguous, unmatched, or cross-customer proposals remain unclassified for review": "OBLIGATION",
    "the discarded Advanced Search `Product` field never selects a policy.": "PROHIBITION",
}


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def load_base(repo: Path):
    path = repo / BASE_PATH
    raw = path.read_bytes()
    if git_blob_sha(raw) != BASE_BLOB_SHA:
        raise RuntimeError("Product candidate generator v1.2.0 blob mismatch")
    spec = importlib.util.spec_from_file_location("rc006_product_candidates_v1_2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Product candidate generator v1.2.0")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    base = load_base(repo)

    base.MANUAL_ATOMIC_SPANS.update(FINAL_SPANS)
    original_kind = base.kind_for

    def reviewed_kind(text: str) -> str:
        return KIND_OVERRIDES.get(text, original_kind(text))

    base.kind_for = reviewed_kind
    records, summary = base.build(repo)
    payload = b"".join(base.canonical_json(record) for record in records)
    summary["generator_version"] = VERSION
    summary["candidate_payload_sha256"] = base.sha256(payload)
    summary["review_model"] = "sentence-granularity plus explicit human atomicity overrides"
    summary["intentional_shared_modal_semicolon_rows"] = [52]
    summary["base_generator_git_blob_sha"] = BASE_BLOB_SHA

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    Path(args.summary).write_bytes(base.canonical_json(summary))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
