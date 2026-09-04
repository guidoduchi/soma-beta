#!/usr/bin/env python3
"""Prepare the complete pre-allocation candidate set for PRODUCT_CONTRACT.md.

A2-BASELINE-002 is immutable. This generator records explicit human atomicity
choices for the Product Contract; it never allocates A2-ASSERT identities.
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

VERSION = "1.2.0"
SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_PATH = "docs/PRODUCT_CONTRACT.md"
SOURCE_BLOB = "6ba3ecb8eabd0845927aa4e6436ec09130a90263"
SCHEMA = "RC006-A2-ASSERTION-CANDIDATE-V1"

META_PREFIXES = (
    "Status:", "Target:", "Authority:", "Normative supporting contracts:",
    "The ticket-opening behavior, split communication preview, tab order, device-reference workflow, and Objective grouping behavior are normative in",
    "The complete discovery, identity, hierarchy, status, grouping, and terminal-cascade rules are governed by",
    "The complete lifecycle, cardinalities, deterministic assignment, request-origin rules, logistics snapshots, Fault Tag membership and lineage, manual and bulk alternatives, correction semantics, evidence boundary, and deletion behavior are normative in",
    "The complete normative behavior is in", "Its contract is defined in",
    "The exact active/deferred allowlists, discarded-column boundary, delimiters, conditional blanks, historical cutoff, source precedence, and aggregate sample evidence are normative in",
    "The complete normative lifecycle is defined by",
    "The confirmed IT/NFV templates, Non-fault inquiry derivation, cancelled exclusion, and normative calculation rules are in",
    "The [Foundation Runtime, Persistence, Audit, and Verification Contract]",
    "The Overview composition follows the [UI/UX Interaction Contract]",
)

EXACT_INFORMATIVE = {
    "Examples include an RFC without a Service Request, a WFM without an Objective, an Objective awaiting review, and a Spare Request dispatched beyond its threshold.",
    "This direction is informed by the clarity of mature infrastructure-management interfaces without copying their branding, assets, exact pixels, dense typography, or wide-screen assumptions.",
}

# Only these source lines are split below sentence boundaries. Every resulting
# span carries its own subject/modality or is a directly reviewable independent
# clause. Lines absent here are split only at sentence boundaries.
MANUAL_ATOMIC_SPANS: dict[int, list[str]] = {
    23: [
        "The canonical SOMA mark, wordmark, lockup, application icon, and tray icon retain their Alpha-origin provenance",
        "the project owner has confirmed the rights necessary to use and distribute them under SOMA Beta's proprietary/internal-use terms and that they contain no third-party material requiring a surviving third-party license.",
        "Alpha's Apache-2.0 license remains an Alpha-repository property and does not become the licensing basis for unrelated Beta material or those independently owned Beta assets.",
    ],
    24: ["High-level design precedes low-level design", "implementation follows both."],
    30: [
        "The Local Administrator has an automatically generated stable internal identity.",
        "Initial authentication setup requires a password and confirmation",
        "login requires no username.",
        "The editable display name defaults to `Local Administrator`",
        "any username-like label is optional display metadata.",
    ],
    32: [
        "Registered people are operational/business records and do not receive login profiles.",
        "A Contact may optionally belong to a Customer Organization",
        "organization assignment is never required merely to register the person.",
    ],
    33: [
        "Contact email, phone, and other communication channels are optional for ordinary Ticket, Task, Objective, and historical workflows.",
        "A channel is validated only when an action actually needs it",
        "failure blocks that communication action rather than the underlying operational record.",
    ],
    34: ["Password login is required", "the operator may explicitly enable automatic login on that Windows account."],
    52: [
        "The operator can select Daily, Weekly, or Monthly periods; compare the current period with its preceding equivalent; show, hide, and reorder approved sections; choose a default period; and configure approved noncontractual warning thresholds.",
        "Presentation thresholds cannot replace, weaken, or redefine a Contract Product Line SLA policy.",
    ],
    73: [
        "Daily, Weekly, and Monthly exports derive from one internally consistent accepted-state snapshot and may cover one Customer Organization or all organizations.",
        "Completed report evidence preserves only the report-time values, membership, calculation results, policy revisions, and provenance needed to interpret and reproduce the artifact.",
        "Later operational or policy changes affect current and future reports but never rewrite a completed report.",
        "A report is completed only after successful artifact verification",
        "failed or cancelled generation changes no operational record.",
        "Report generation never offers or initiates cleanup in Beta 1.0.",
    ],
    77: [
        "Overview summary cards are projections over accepted domain facts, not editable state.",
        "Every card identifies its scope, unknown/partial/coverage conditions, and actionable destination.",
        "The activity surface never replaces authoritative job, proposal, or audit records and owns its own hovered/focused scrolling.",
    ],
    83: ["An SR may link directly to many **master RFCs**", "an SR view shows their complete RFC/WFM branches nested beneath it."],
    95: [
        "A recognized terminal status immediately suppresses active-work reminders and live SLA-risk notifications.",
        "Resolved and Closed SRs retain their effective duration, applicable SLA-cohort, source, and audit evidence",
        "Cancelled SRs retain historical evidence but are excluded from SLA cohorts.",
    ],
    97: [
        "One official SR number always refers to the same surviving Beta SR",
        "Beta creates no finalized episodes, tombstones, or same-number replacement records.",
        "A confirmed terminal reversal updates that same SR, preserves prior terminal evidence, and recalculates current projections without rewriting completed reports.",
    ],
    105: ["A Local Task may be created under or linked to a master or subordinate RFC", "this does not allow a subordinate RFC to own another RFC."],
    107: [
        "RFC/WFM workbook absence has no lifecycle authority.",
        "Recognized status controls active, terminal, cancelled, and historical presentation",
        "SOMA performs filtering locally.",
    ],
    116: [
        "A WFM owned by a master RFC projects **master-RFC WFM context**",
        "a WFM owned by a subordinate RFC projects subordinate-RFC context.",
        "This role is derived from RFC ownership, is not an independently editable flag or WFM-to-WFM hierarchy, and does not imply one unique WFM per RFC, branch, or Objective.",
    ],
    118: ["Correcting the parent RFC of a manually registered WFM prompts the operator either to remove the now-unused provisional RFC or leave it orphaned", "no silent deletion occurs."],
    120: ["Deleting a manual RFC may cascade only through WFMs that are independently eligible for hard deletion.", "Otherwise SOMA uses termination/archive/cancellation and preserves history."],
    129: ["Every Objective requires one reviewed planned timeframe and at least one Task from creation", "there is no empty Objective state."],
    131: [
        "A Local Task requires only a Task Name from the operator.",
        "It may link independently to zero or many SRs, zero or many RFCs—including subordinate RFCs—zero or many Spare Part Units, and zero or many Device References.",
        "A Device Reference may remain external/unregistered or resolve to one Network Element",
        "regularization preserves the Task-to-Device-Reference relationship and its history rather than replacing it with a direct Network Element relationship.",
    ],
    133: ["A Local Task created inside an Objective may initialize its operational plan from the Objective's current planned timeframe", "the accepted Task plan remains independently reviewable and historically preserved."],
    135: ["The Objective planned envelope is derived from accepted member Task plans", "membership does not authorize the Objective to overwrite an established Task plan silently."],
    136: ["A Task belongs to at most one Objective", "one SR may participate through different Tasks in multiple unfinished Objectives."],
    138: [
        "Retrying work creates a new Task attempt while preserving the earlier Task unchanged.",
        "A Local Task retry receives a new local Task identity",
        "a WFM retry requires a new WFM Task No.",
        "The new attempt enters the normal overlap-grouping flow, so Objective retry lineage is derived from Task attempts rather than represented as a one-to-one Objective chain.",
    ],
    140: [
        "When an Objective timeframe is selected or reviewed, SOMA may locate eligible WFM Tasks whose accepted/source planning overlaps it.",
        "A previously unplanned WFM may initialize an operational plan through the reviewed Objective flow.",
        "A WFM with a conflicting established plan requires explicit review and, when it represents another attempt, a new Task No.",
        "SOMA never overwrites an established attempt silently.",
    ],
    142: [
        "Creating or importing a future, noncancelled Task with a valid interval enters reviewed Objective grouping.",
        "It creates a new Objective when no interval overlaps",
        "otherwise it is proposed into the overlapping Objective.",
        "A Task bridging multiple Objectives proposes their consolidation and union timeframe because accepted Objectives may not overlap.",
        "A Task without a timeframe remains unscheduled and creates no Objective.",
    ],
    144: ["Planned and actual Objective intervals are distinct.", "Task outcomes and actual Spare Part Unit use are reviewed individually.", "Corrections preserve prior actor/time/reason evidence", "the exact outcome transition table remains a low-level design item."],
    148: ["If one or more Tasks link to SRs, SOMA suggests the union of eligible Stock and pending spares related to those SRs.", "Physical-unit reservation belongs to a Task, not directly to the Objective", "the Objective displays the derived union of its Task allocations."],
    179: ["A known official SR7 requires canonical-format and uniqueness validation.", "Later communication appends evidence to the same identity", "duplicate candidates require review rather than silent creation or merge."],
    180: ["Missing acknowledgement produces a warning.", "An official SR7 may arrive alone or with zero, some, or all C10 RMAs", "partial responses preserve pending quantity and later responses append positions."],
    189: ["The operator may redistribute an assignment for priority", "prior and new targets, reason, actor, and chronology remain audited."],
    191: ["Each Spare Part Unit may have zero or one origin RMA.", "A dismantled assembly remains the direct inbound unit", "extracted components become independent units that may share its origin provenance."],
    199: ["One logistics event may cover multiple RMAs or units", "every participant remains independently addressable and correctable."],
    200: ["Partial and split dispatch or receipt are valid", "pending RMAs and quantities retain their state."],
    201: ["Actual facts may differ from requested intent.", "Both remain visible", "neither later master-data edits nor actual delivery rewrite the submission snapshot."],
    203: ["Local units receive no fabricated external-delivery evidence.", "A dismantled parent assembly retains the direct receipt", "extracted units inherit provenance and record later custody independently."],
    207: ["Inventory consumes reviewed Task/physical outcomes to record physical consequences", "it does not own Task execution, outcome, correction, cancellation, or retry lifecycle."],
    214: ["One obligation and physical unit may occupy at most one active submitted membership at a time", "a later resend follows preserved rejection history."],
    221: ["Each membership stores the RMA and physical-unit relationships", "Spare Request, Service Request, and Device context are derived and cannot be independently contradicted."],
    233: ["Final acceptance or rejection always requires explicit operator confirmation.", "Communication may propose any subset", "manual confirmation without evidence remains valid."],
    248: ["Beta 1.0 services accept optional evidence references", "the UI exposes no manual attachment or upload control."],
    254: ["**Infrastructure** is the canonical workspace.", "`Device Manager` and `Managed Element` are not canonical Beta domain terms.", "Tickets, Tasks, Objectives, and Inventory use a Device Reference that may remain unregistered/external or resolve to one registered Network Element", "deliberate promotion preserves its operational relationships without duplication."],
    263: ["Site contains Rooms", "Room contains Racks", "Rack records row and column.", "A Network Element may be site-level/unracked, placed in one same-Site Rack, or participate in compatible compound containment."],
    275: [
        "Beta 1.0 generates a versioned Infrastructure workbook family for empty device registration, human-readable current-device discovery export, and reviewed round-trip update.",
        "Imports are discovered only from one configured directory and always stage review",
        "exports use an operator-selected destination.",
        "Same-installation round-trip identity may target updates",
        "foreign-installation identity is provenance/matching evidence only.",
        "Missing rows never imply deletion or unlinking.",
    ],
    277: ["Infrastructure presentation uses a context explorer, selected-entity header, contextual actions, predictable tabs, modular summary cards, independent panes, and a collapsible activity surface for workbook jobs, reviews, warnings, and recent audited changes.", "The hierarchy is a projection over accepted Customer Organization, Site, placement, Cloud Deployment, containment, and Network Element relationships", "the UI must not turn one convenient tree into competing domain ownership."],
    285: ["Its role is operation-specific: a Spare Request may use it as delivery or self-pickup context", "a Fault Tag may use it as the pickup origin from which return units are dispatched or collected."],
    306: ["Current source-owned SR facts are derived field by field from the newest accepted usable observations.", "Historical source evidence is retained as compact meaningful allowlisted deltas with provenance and warnings, not full workbook copies or repeated unchanged values.", "Problem Summary revisions remain auditable.", "Historical view uses the surviving operational record, compact observations, and audit history", "Beta 1.0 does not recreate Alpha's terminated-SR snapshot or report-finalization purge model."],
    310: ["Advanced Search uses a configurable one-month default historical lookback for terminal source rows under its trusted source-specific recency rule.", "Active rows are not discarded by this rule.", "RFC/WFM workbooks are governed separately: their supported historical rows remain valid according to status and field rules", "workbook age or omission does not create record-level lifecycle disappearance."],
    320: [
        "Advanced Search requires only SRNo as its universal identity header.",
        "New SRs may remain incomplete",
        "later usable source values fill missing facts without changing identity.",
        "Import capture time is never substituted for a missing Report Date and cannot become SLA evidence.",
        "Incomplete records remain visible",
        "workflows validate additional facts only when genuinely required.",
        "Product remains discarded",
        "Current Handler remains optional source-owned information.",
    ],
    330: [
        "Automatic Communication Processing is eligible only after at least one registered trackable operational entity exists.",
        "Infrastructure or descriptive Device records alone do not activate it.",
        "The registry includes supported SR/TT, Spare Request, RMA/C10, RFC, WFM, Objective, and Fault Tag identities and aliases.",
        "Initial scanning is bounded by the earliest relevant accepted creation/report boundary, then continues incrementally from durable per-scope high-water marks with overlap.",
        "An older added target may request a bounded targeted backfill",
        "Deep Scan is an explicit scoped operator action.",
    ],
    336: [
        "An accepted terminal SR lifecycle transition removes that SR's direct communication links.",
        "For an RFC, direct communication unlink occurs only after the confirmed local terminal-cascade decision governed by the RFC/WFM contract",
        "parsing, staging, or merely accepting provider terminal evidence does not itself perform the local cascade consequence.",
        "A retained communication that then has no remaining protected operational dependency enters **Orphaned — Pending Purge** for a configurable positive installation-level grace period of seven exact elapsed days by default.",
        "Restoring a protected link cancels pending purge.",
        "At expiry SOMA transactionally revalidates dependencies before purging reconstructable content, while preserving a non-reconstructable purge record and frozen minimal terminal summary.",
        "It never modifies external PST/OST stores, exported MSG files, portable exports, or existing backups.",
        "Reversal after purge may use targeted backfill when the source remains available",
        "otherwise the workbench exposes a coverage warning.",
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
        "unresolved, ambiguous, unmatched, or cross-customer proposals remain unclassified for review, and the discarded Advanced Search `Product` field never selects a policy.",
        "Manual reclassification is audited.",
        "An accepted policy revision recalculates every existing SR under that Contract Product Line, including older and terminal SRs",
        "completed report snapshots remain immutable",
        "every later view and report uses the revised policy.",
    ],
    344: ["The built-in IT/NFV values are reusable templates, not global fallback policies.", "An unresolved SR remains operationally usable but SLA-unclassified.", "Custom Contract Product Lines may define validated tier structures without a mandatory 85%/100% pair.", "Non-fault inquiry preserves every Minor tier and multiplies its exact duration by 1.5 without whole-day rounding.", "Canonical SLA cohorts are monthly in `America/Guayaquil`", "Daily, Weekly, and selected-range outputs are progress snapshots of those cohorts."],
    346: ["Known instants persist as UTC whole-second values.", "The selectable IANA timezone is confined to Objective/Task scheduling and maintenance-window calendars.", "Ordinary operations and SLA stay in `America/Guayaquil`", "adapters apply their own source-profile timezone.", "Unknown or ambiguous source times remain unresolved rather than inheriting a convenient clock."],
    348: ["Warning presentation keeps classification, individual duration evidence, cohort compliance, suspension, source integrity, and terminal state as separate dimensions.", "A currently suspended SR receives a distinct suspension-ending-soon warning when its valid future planned end enters the configured noncontractual threshold.", "Individual duration evidence is never mislabeled as failure of a percentage-based cohort tier", "every warning uses text and/or iconography in addition to color."],
    358: ["Hard deletion exists only where an owning domain contract explicitly allows it.", "Across domains, imported/adopted provenance, accepted execution/lifecycle evidence, communication/review/spare-use history, or protected dependencies prevent hard deletion unless a narrower accepted rule explicitly states otherwise", "history-preserving lifecycle/correction actions are used instead."],
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

def sha256(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def fingerprint(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return sha256(normalized.encode("utf-8"))

def anchor(heading: str) -> str:
    text = unicodedata.normalize("NFC", heading).replace("`", "").replace("*", "").replace("_", "").lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in {" ", "-"})
    return re.sub(r"-+", "-", re.sub(r" +", "-", text)).strip("-")

def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")

def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?]) (?=(?:[A-Z]|`|\*|\[))", text) if p.strip()]

def kind_for(text: str) -> str:
    low = text.lower(); padded = f" {low} "
    boundaries = (" is not ", " are not ", " not a ", " not an ", "excluded from", "has no ", "have no ", "does not authorize", "do not authorize", "does not become", "do not become", "distinct from", "separate from", "rather than", " at most one ", " exactly one ", " zero or one ", " zero or many ", " one-to-one", " only after ", " only through ", " only when ", " only for ", " only from ", " is derived ", " are derived ", " is confined to ")
    prohibitions = (" must not ", " never ", " cannot ", " does not ", " do not ", " no silent", " no general", " no device", " no username")
    if any(term in padded for term in boundaries): return "DESIGN_BOUNDARY"
    if any(term in padded for term in prohibitions): return "PROHIBITION"
    if re.search(r"\bmay\b|\bcan\b|\ballowed\b|\bpermits?\b|\bis optional\b|\bare optional\b", low): return "PERMISSION"
    return "OBLIGATION"

def source(repo: Path) -> tuple[list[str], str]:
    blob = git(repo, "rev-parse", f"{SOURCE_COMMIT}:{SOURCE_PATH}").decode("ascii").strip()
    if blob != SOURCE_BLOB: raise RuntimeError(f"PRODUCT_CONTRACT blob mismatch: {blob}")
    raw = git(repo, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}")
    if b"\r" in raw: raise RuntimeError("PRODUCT_CONTRACT contains CR")
    return raw.decode("utf-8", errors="strict").splitlines(), blob

def headings(lines: list[str]) -> list[tuple[int, str, str, int]]:
    result=[]
    for line_no,line in enumerate(lines,start=1):
        m=re.match(r"^(#{2,3})\s+(.+?)\s*$",line)
        if m:
            visible=m.group(2); result.append((line_no,visible,anchor(visible),len(result)+1))
    return result

def owning(heads: list[tuple[int,str,str,int]], line_no:int)->tuple[str,str,int]:
    prior=[h for h in heads if h[0] < line_no]
    if not prior: raise RuntimeError(f"no eligible heading before line {line_no}")
    _,visible,norm,ordinal=prior[-1]; return visible,norm,ordinal

def find_line(lines:list[str], exact:str)->int:
    matches=[i for i,line in enumerate(lines,start=1) if line==exact]
    if len(matches)!=1: raise RuntimeError(f"expected one exact line for {exact!r}, found {len(matches)}")
    return matches[0]

def special_spans(lines:list[str])->dict[int,tuple[int,str,str]]:
    result={}
    for start_text,end_text,note in [
        ("The primary navigation is fixed, in order:","6. Settings","Reviewed as one atomic ordered-navigation obligation; list order is the rule."),
        ("Default sections include:","| Objectives | Scheduled, completed, incomplete, awaiting review |","Reviewed as one default Overview-section/measure composition obligation."),
        ("The official 1.0.0 sources are:","| WFM Tasks | Service Provider Plan Creation Excel export |","Reviewed as one authoritative operational-source table obligation."),
    ]:
        start=find_line(lines,start_text); end=find_line(lines,end_text)
        result[start]=(end,"\n".join(lines[start-1:end]),note)
    return result

def is_meta(text:str)->bool:
    s=text.strip()
    return (not s) or s in EXACT_INFORMATIVE or any(s.startswith(p) for p in META_PREFIXES)

def candidate_spans(lines:list[str])->list[tuple[int,int,str,str]]:
    specials=special_spans(lines); covered=set()
    for start,(end,_,_) in specials.items(): covered.update(range(start,end+1))
    spans=[]; i=1
    while i<=len(lines):
        if i in specials:
            end,text,note=specials[i]; spans.append((i,end,text,note)); i=end+1; continue
        if i in covered: i+=1; continue
        line=lines[i-1]; stripped=line.strip()
        if not stripped or stripped.startswith("#"): i+=1; continue
        if stripped.startswith("|") or re.match(r"^\d+\. ",stripped): i+=1; continue
        if stripped in {"Default sections include:","Below the measures, Overview provides:","The physical/organizational model is:"}: i+=1; continue
        if is_meta(stripped): i+=1; continue
        selected=stripped[2:] if stripped.startswith("- ") else stripped
        atoms=MANUAL_ATOMIC_SPANS.get(i, split_sentences(selected))
        for atom in atoms:
            if is_meta(atom): continue
            if atom not in line: raise RuntimeError(f"reviewed atom is not verbatim at line {i}: {atom!r}")
            spans.append((i,i,atom,"Human-reviewed as one independently reviewable normative Product Contract assertion; reverse authority remains pending."))
        i+=1
    return spans

def build(repo:Path)->tuple[list[dict[str,Any]],dict[str,Any]]:
    lines,blob=source(repo); heads=headings(lines); raw_spans=candidate_spans(lines); counts={}; records=[]
    for start,end,exact,note in raw_spans:
        visible,norm,section_ordinal=owning(heads,start); counts[section_ordinal]=counts.get(section_ordinal,0)+1
        records.append({"assertion_ordinal":counts[section_ordinal],"classification_review":"PASS","exact_text":exact,"fingerprint_sha256":fingerprint(exact),"normative_kind":kind_for(exact),"review_note":note,"schema":SCHEMA,"section_anchor":norm,"section_heading":visible,"section_ordinal":section_ordinal,"source_blob_sha":blob,"source_end_line":end,"source_path":SOURCE_PATH,"source_start_line":start})
    records.sort(key=lambda r:(r["section_ordinal"],r["assertion_ordinal"]))
    summary_sections=[{"section_anchor":norm,"section_heading":visible,"section_ordinal":ordinal,"candidate_count":counts.get(ordinal,0)} for _,visible,norm,ordinal in heads]
    return records,{"candidate_count":len(records),"generator_version":VERSION,"pinned_source_blob_sha":blob,"pinned_source_commit":SOURCE_COMMIT,"result":"PASS","schema":"RC006-A2-PRODUCT-CANDIDATE-PREPARATION-V1","sections":summary_sections,"source_path":SOURCE_PATH}

def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--repo",default="."); p.add_argument("--output",required=True); p.add_argument("--summary",required=True); args=p.parse_args()
    records,summary=build(Path(args.repo).resolve()); payload=b"".join(canonical_json(r) for r in records); summary["candidate_payload_sha256"]=sha256(payload)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_bytes(payload); Path(args.summary).write_bytes(canonical_json(summary)); print(json.dumps(summary,indent=2,ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
