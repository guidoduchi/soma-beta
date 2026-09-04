#!/usr/bin/env python3
"""Human-reviewed Import Contract candidate generator v0.2.0.

Pins the v0.1.0 generator and replaces only explicitly reviewed source lines.
Generic punctuation splitting is intentionally avoided: a split is made only
when each resulting verbatim span preserves an independently reviewable subject
and normative force. No A2 assertion IDs are allocated by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

VERSION = "0.2.0-review"
BASE_PATH = "tools/reconciliation/prepare_rc006_a2_import_candidates.py"
BASE_BLOB_SHA = "a28eb94744d67ea6ae3ed2edcb669e23401a17f3"

# Entire candidate output for each listed B002 source line. Every string is an
# exact contiguous substring of that source line. This table is the human
# atomicity decision record for v0.2.0.
LINE_REPLACEMENTS: dict[int, list[tuple[str, str | None]]] = {
    36: [
        ("`SRNo` is the only universal Advanced Search header and row identity requirement.", "DESIGN_BOUNDARY"),
        ("Missing allowlisted nonidentity headers create coverage warnings", "OBLIGATION"),
        ("a new SR may remain incomplete", "PERMISSION"),
        ("unusable values do not erase prior accepted facts unless the field contract explicitly permits clearing.", "PROHIBITION"),
    ],
    39: [
        ("One official SRNo identifies one surviving SR.", "DESIGN_BOUNDARY"),
        ("Later terminal observations reconcile normally", "OBLIGATION"),
        ("a valid reappearance may clear a source-disappearance warning.", "PERMISSION"),
        ("A recognized nonterminal Status after accepted terminal evidence is a high-risk proposal that never auto-accepts", "DESIGN_BOUNDARY"),
        ("explicit acceptance updates the same SR while preserving prior terminal evidence and completed report snapshots.", "OBLIGATION"),
    ],
    45: [
        ("Unallowlisted values are not persisted as generic metadata, searchable text, an opaque copy of the row, or a retained workbook copy.", "PROHIBITION"),
        ("SOMA retains the file fingerprint and bounded provenance", "OBLIGATION"),
        ("the external original remains user-managed.", "DESIGN_BOUNDARY"),
    ],
    47: [
        ("Acceptance that creates the installation's first trackable communication entity makes Communication Processing eligible", "OBLIGATION"),
        ("the import transaction never fetches, scans, matches, advances a communication high-water mark, or accepts a communication-derived proposal.", "PROHIBITION"),
        ("The independent scheduler or **Check now** command performs that work afterward.", "OBLIGATION"),
    ],
    48: [
        ("An accepted terminal SR lifecycle transition may invoke its governed direct-communication unlink consequence.", "PERMISSION"),
        ("For RFCs, accepted source terminal evidence alone does not unlink Communications", "PROHIBITION"),
        ("only the separately reviewed and confirmed RFC terminal cascade may perform that local consequence under the RFC/WFM and Communications contracts.", "DESIGN_BOUNDARY"),
        ("Staged, rejected, invalid, merely parsed, or merely source-accepted-but-uncascaded RFC terminal values never unlink or purge communication evidence.", "PROHIBITION"),
    ],
    49: [
        ("An accepted terminal reversal during orphan grace restores the applicable same-entity relationship when its evidence remains available and cancels pending purge.", "OBLIGATION"),
        ("After content purge, the independent communication workflow may run a targeted backfill if the source remains available", "PERMISSION"),
        ("otherwise the workbench records a coverage warning.", "OBLIGATION"),
        ("Import never fabricates reconstructed content.", "PROHIBITION"),
    ],
    56: [
        ("Current Problem Summary is stored on the SR", "OBLIGATION"),
        ("accepted changes remain in audit/delta history rather than repeating the same summary in every observation.", "OBLIGATION"),
    ],
    62: [
        ("After an Advanced Search inbox is configured, its automatic daily check is enabled by default at 10:00 in the fixed operational timezone `America/Guayaquil`", "OBLIGATION"),
        ("changing the Objective scheduling timezone does not reinterpret this boundary.", "PROHIBITION"),
    ],
    67: [
        ("Satisfied schedule-boundary persistence prevents duplicate scheduled invocation", "OBLIGATION"),
        ("logical-content fingerprinting and idempotence independently prevent duplicate import mutation.", "OBLIGATION"),
    ],
    110: [
        ("`Related SR` uses a comma delimiter.", "OBLIGATION"),
        ("Each nonblank token is trimmed and validated as an eight-digit SR identity.", "OBLIGATION"),
        ("`Pr Number` uses a semicolon delimiter.", "OBLIGATION"),
        ("Each nonblank token is trimmed and validated as `SR` followed by seven digits.", "OBLIGATION"),
        ("Malformed tokens are reported independently", "OBLIGATION"),
        ("one bad token does not erase valid tokens from the same cell.", "PROHIBITION"),
    ],
    118: [
        ("Enhanced RFC and WFM discovery share one configured operational import directory, initially suggested as Downloads, while retaining separate exact source patterns.", "OBLIGATION"),
        ("Only stable direct regular files are considered.", "DESIGN_BOUNDARY"),
        ("RFC filesystem modification time may rank candidates but is not business chronology.", "DESIGN_BOUNDARY"),
        ("WFM uses its supported embedded source timestamp", "OBLIGATION"),
        ("filename collision suffixes never determine recency.", "PROHIBITION"),
        ("The newest invalid candidate fails visibly without silent fallback", "OBLIGATION"),
        ("explicit manual selection remains available.", "PERMISSION"),
    ],
    176: [
        ("Both planned timestamps may be absent", "PERMISSION"),
        ("such a WFM remains unscheduled.", "OBLIGATION"),
        ("Otherwise both must be usable, with end after start.", "OBLIGATION"),
        ("Any valid minute is accepted.", "OBLIGATION"),
        ("Exactly one timestamp or an invalid interval is a row-level failure by default and shall not fabricate scheduling or automatically reject unrelated valid rows.", "DESIGN_BOUNDARY"),
    ],
    202: [
        ("A valid accepted nonterminal WFM source interval is the default reviewed operational-plan candidate.", "OBLIGATION"),
        ("Accepting the import never silently accepts Objective membership or regrouping", "PROHIBITION"),
        ("eligible accepted Task planning enters the separate Objective grouping review governed by the RFC/WFM and Workbench contracts.", "OBLIGATION"),
    ],
    204: [
        ("`Complete` and `Plan Cancel` rows remain historical provider evidence.", "DESIGN_BOUNDARY"),
        ("`Plan Cancel` may create or adopt its exact identity but cannot promote/reactivate an RFC or create an Objective.", "DESIGN_BOUNDARY"),
        ("An accepted provider-`Complete` WFM with no Objective and a usable accepted source interval may produce a separate reviewed historical-Objective proposal", "PERMISSION"),
        ("that proposal proves neither actual execution nor SOMA Task outcome or downstream Inventory/Device effects.", "DESIGN_BOUNDARY"),
    ],
    205: [
        ("RFC/WFM source omission never changes lifecycle, archival, links, tracking, or Communication state.", "PROHIBITION"),
    ],
    250: [
        ("Infrastructure imports are discovered only from one operator-configured directory through an explicit **Check now** action.", "DESIGN_BOUNDARY"),
        ("SOMA does not recurse into unrelated directories or fall back to broad scanning.", "PROHIBITION"),
        ("Exports are written to an operator-selected destination", "OBLIGATION"),
        ("successful export does not register an import or mutate Infrastructure.", "PROHIBITION"),
    ],
    252: [
        ("The workbook declares its format version, mode, source-installation scope, generation chronology, and included filter/scope.", "OBLIGATION"),
        ("The exact representation belongs in the LLD, but it must remain human-readable in ordinary spreadsheet software and usable without SOMA for device discovery.", "DESIGN_BOUNDARY"),
    ],
    258: [
        ("It contains no password, private key, token, reusable secret, credential-provider reference, or Beta 1.0 connectivity/topology/interface/port edge.", "PROHIBITION"),
        ("Export never creates those facts", "PROHIBITION"),
        ("import never infers connectivity from co-occurrence, placement, Cloud assignment, IP patterns, or containment.", "PROHIBITION"),
    ],
    272: [
        ("Missing rows do not imply deletion, archival, movement, unlinking, or clearing.", "PROHIBITION"),
        ("Blank or unusable optional cells preserve prior valid data unless a future explicit clearing operation is accepted in the contract.", "OBLIGATION"),
        ("Batch acceptance commits transactionally or rolls back", "OBLIGATION"),
        ("replay of identical accepted content is idempotent.", "OBLIGATION"),
    ],
    278: [
        ("LLD must define exact workbook/header-version detection, data types, formula handling, cell-size limits, date-system handling, file stabilization, fingerprints, replay/idempotency, the centrally governed/versioned low-risk safe-auto-accept classes permitted by `O-007`, review presentation, import transaction boundaries, and sanitized export golden fixtures under the UI/UX Interaction Contract.", "OBLIGATION"),
        ("Those implementation choices shall preserve the RC-002 exclusions: terminal, hierarchy, ownership, material timeframe, disappearance/empty-population, Objective-regrouping consequence, and competing-attempt cases are not safe auto-accept classes.", "DESIGN_BOUNDARY"),
        ("Each fixture identifies format/schema version, synthetic or irreversibly sanitized inputs, expected normalized structure/content/rendering, and explicitly allowlisted nondeterminism", "OBLIGATION"),
        ("raw package-byte equality is not a substitute for semantic validation.", "DESIGN_BOUNDARY"),
        ("The automated contract suite required by `BETA-REQ-0137` covers the Infrastructure Device template, discovery export, same-installation round trip, foreign identity, duplicates, ambiguity, malformed/modified workbooks, partial failure, and authoritative hierarchy preservation.", "OBLIGATION"),
        ("Those choices must implement this allowlist and may not reintroduce discarded columns without a Product Contract change.", "DESIGN_BOUNDARY"),
    ],
}

KIND_OVERRIDES = {
    "SOMA imports operational evidence; it does not mirror every column supplied by an external workbook.": "DESIGN_BOUNDARY",
    "It does **not** execute the cascade.": "PROHIBITION",
    "These fields drive no Beta 1.0 actor assignment, Product Line or Contract Product Line selection, SLA policy, or Infrastructure creation.": "DESIGN_BOUNDARY",
    "If its RFC does not exist, the WFM creates a provisional RFC using the WFM Task Name as provisional Summary and may use WFM RFC Status and Customer Organization as reviewed provisional hints.": "DESIGN_BOUNDARY",
    "Only an Implement-eligible RFC may ordinarily own active nonterminal WFM work.": "DESIGN_BOUNDARY",
    "Names, hostnames, Models, manufacturer serials, IP addresses, and placement labels are candidate evidence, not identity proof.": "DESIGN_BOUNDARY",
}


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

    original_candidate_spans = base.candidate_spans
    def reviewed_candidate_spans(lines, heads):
        spans = original_candidate_spans(lines, heads)
        replacement_lines = set(LINE_REPLACEMENTS)
        out = []
        emitted = set()
        for start, end, exact, note, forced_kind in spans:
            if start == end and start in replacement_lines:
                if start in emitted:
                    continue
                emitted.add(start)
                source_line = lines[start - 1]
                for atom, kind in LINE_REPLACEMENTS[start]:
                    if atom not in source_line:
                        raise RuntimeError(f"reviewed atom is not verbatim at line {start}: {atom!r}")
                    out.append((start, start, atom, "Explicit human atomicity review v0.2.0; reverse authority remains pending.", kind))
                continue
            out.append((start, end, exact, note, forced_kind))
        missing = replacement_lines - emitted
        if missing:
            raise RuntimeError(f"reviewed replacement lines were not encountered: {sorted(missing)}")
        return out
    base.candidate_spans = reviewed_candidate_spans

    original_kind = base.kind_for
    def reviewed_kind(text):
        return KIND_OVERRIDES.get(text, original_kind(text))
    base.kind_for = reviewed_kind

    records, summary = base.build(repo)
    payload = b"".join(base.canonical_json(r) for r in records)
    summary["generator_version"] = VERSION
    summary["base_generator_git_blob_sha"] = BASE_BLOB_SHA
    summary["candidate_payload_sha256"] = base.sha256(payload)
    summary["review_model"] = "sentence/table-row granularity plus explicit human line replacements"
    summary["reviewed_replacement_lines"] = sorted(LINE_REPLACEMENTS)

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
