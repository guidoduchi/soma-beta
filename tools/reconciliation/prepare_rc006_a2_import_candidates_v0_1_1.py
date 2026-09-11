#!/usr/bin/env python3
"""Import Contract candidate generator v0.1.1 review wrapper.

Pins v0.1.0 and fixes only pre-section metadata handling. No source text or
candidate semantics are changed by the wrapper beyond allowing Status/Target/
Authority metadata before the first eligible heading to be skipped safely.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

VERSION = "0.1.1-review"
BASE_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates.py"
BASE_BLOB_SHA = "a28eb94744d67ea6ae3ed2edcb669e23401a17f3"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def load_base(repo: Path):
    path = repo / BASE_PATH
    raw = path.read_bytes()
    if git_blob_sha(raw) != BASE_BLOB_SHA:
        raise RuntimeError("Import candidate generator v0.1.0 blob mismatch")
    spec = importlib.util.spec_from_file_location("rc006_import_candidates_v0_1_0", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Import candidate generator v0.1.0")
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
    base = load_base(repo)

    original_owning = base.owning

    def safe_owning(heads, line_no):
        prior = [h for h in heads if h[0] < line_no]
        if not prior:
            return "__PREAMBLE__", "__preamble__", 0
        return original_owning(heads, line_no)

    base.owning = safe_owning
    records, summary = base.build(repo)
    summary["generator_version"] = VERSION
    summary["base_generator_git_blob_sha"] = BASE_BLOB_SHA
    payload = b"".join(base.canonical_json(r) for r in records)
    summary["candidate_payload_sha256"] = base.sha256(payload)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(payload)
    Path(args.summary).write_bytes(base.canonical_json(summary))
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
