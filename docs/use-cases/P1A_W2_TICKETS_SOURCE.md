# P1A-W2 — Tickets & Source Intake Use Cases

Status: **P1A-002 reconstruction complete — Goal Seeds pending Specification Gate; owner review paused pending RC-006-A2**

Except where explicitly noted, entries in this file are Goal Seeds rather than acceptance-ready specifications.

## UC-013 — Create a manual Service Request
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Create a valid local SR when no official source record exists yet.
- **Trigger/preconditions:** Operator needs an SR work item; no official SR identity is required at creation.
- **Main flow:** create SR with stable local identity; capture available business context; preserve incomplete fields as incomplete; open it in normal Ticket workflows.
- **Alternates/failures:** local SR remains usable when optional facts are missing; no fake official SR number is fabricated; later official adoption is reviewed.
- **Postconditions/evidence:** one stable SR with local `LSR-########` identity and history.
- **Candidate authority:** `BETA-REQ-0011`, `0053`, `0057`, `0075`; Workbench/Import contracts.

## UC-014 — Discover and stage Advanced Search SR source data
Status: **Goal Seed — Specification Gate pending**
- **Actor:** System / Local Administrator.
- **Goal:** Detect eligible Advanced Search workbooks and stage trustworthy SR observations without mutating authoritative records before acceptance.
- **Trigger/preconditions:** Manual check or governed schedule; source directory configured.
- **Main flow:** discover candidates by accepted pattern; validate source/workbook safety; extract allowlisted SR observations; fingerprint/replay-check; stage proposals/diffs.
- **Alternates/failures:** malformed/unsafe source is rejected; unusable nonidentity fields do not fabricate values; missing file/row is not lifecycle authority; scheduled invocation cannot bypass review policy.
- **Postconditions/evidence:** immutable source/staging/proposal evidence; no unauthorized domain mutation.
- **Candidate authority:** `BETA-REQ-0054..0062`, `0066`, `0068`, `0074..0076`, `0145..0147`, `0176..0177`.

## UC-015 — Review and accept/reject staged SR source changes
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Decide which staged SR observations become accepted current truth while preserving prior local relationships and evidence.
- **Trigger/preconditions:** SR import proposal exists.
- **Main flow:** inspect source/provenance/diff and warnings; partition safe/incompatible/stale/high-risk changes; accept/reject/correct permitted scope; apply accepted changes atomically with audit/evidence.
- **Alternates/failures:** high-risk terminal reversal, disappearance, identity, ownership/customer, chronology or similar changes remain explicit review; rejected proposal changes nothing authoritative; whole-import rejection only for genuine workbook-level failure.
- **Postconditions/evidence:** accepted SR facts/history updated; rejected/stale proposals preserved as review history.
- **Candidate authority:** `BETA-REQ-0056..0066`, `0074..0076`, `0146..0148`, `0176`.

## UC-016 — Reconcile or correct an SR official identity and lifecycle observation
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Adopt/correct official SR identity or reviewed lifecycle evidence without replacing the surviving SR identity or erasing history.
- **Trigger/preconditions:** Local/provisional SR or conflicting source observation exists.
- **Main flow:** identify exact surviving SR; review official identity/lifecycle evidence; confirm high-risk correction where required; adopt/correct in place; preserve aliases and earlier terminal/nonterminal evidence; recalculate current projections.
- **Alternates/failures:** terminal-to-nonterminal is same-record high-risk correction, not a new episode; no duplicate SR is fabricated; invalid identity evidence is rejected.
- **Postconditions/evidence:** stable SR internal identity with corrected official alias/current lifecycle and preserved history.
- **Candidate authority:** `BETA-REQ-0011`, `0057`, `0076`, `0148`, SLA/Communications boundaries.

## UC-017 — Work an SR through its workbench
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Inspect and maintain the SR-centered operational context without bypassing owning domain rules.
- **Trigger/preconditions:** SR exists.
- **Main flow:** open by double-click/Enter; review Overview; manage working/Device Reference context; navigate Spare Parts, RFCs, Tasks and Notes; inspect Communication evidence; follow cross-domain links while preserving owning identities.
- **Alternates/failures:** terminal/historical SR remains inspectable; incomplete SR stays usable where current action permits; unregistered Device Reference remains operationally valid; unsaved UI working copies do not alter authoritative summaries; Working Notes mutation follows `UC-094` rather than generic tab navigation.
- **Postconditions/evidence:** accepted domain-specific edits/links recorded under their owners; navigation itself creates no competing domain truth.
- **Candidate authority:** `BETA-REQ-0038`, `0045`, `0049`, `0051..0052`, `0075`; Workbench/UI contracts.

## UC-018 — Create a manual RFC
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Create a valid RFC work item locally when source evidence is absent or not yet imported.
- **Trigger/preconditions:** Operator needs RFC context.
- **Main flow:** create RFC with exact official NC identity when known/required; capture available summary/context; allow later hierarchy/SR/Task relationships through governed actions.
- **Alternates/failures:** malformed NC identity is rejected; no hidden hierarchy is created; eligible untouched manual RFC may later qualify for hard deletion under its own rule.
- **Postconditions/evidence:** stable RFC identity/history.
- **Candidate authority:** `BETA-REQ-0012`, `0040`, `0153..0155`; RFC/WFM Contract.

## UC-019 — Manage RFC hierarchy and SR relationships
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Establish and maintain the accepted two-level RFC forest and direct SR relationships to governing master/root RFCs.
- **Trigger/preconditions:** RFC/SR records exist.
- **Main flow:** designate/confirm master-subordinate relationship; prevent deeper/cyclic hierarchy; link SR directly to master/root; preserve subordinate-origin provenance; inspect derived subordinate context.
- **Alternates/failures:** subordinate cannot become a master; direct SR→subordinate relationship is not fabricated; relationship changes use reviewed merge/impact behavior and preserve history.
- **Postconditions/evidence:** valid two-level forest and reviewed SR/master relations.
- **Candidate authority:** `BETA-REQ-0039..0040`, `0151..0154`; RFC/WFM/Workbench contracts.

## UC-020 — Discover and stage Enhanced Excel RFC source data
Status: **Goal Seed — Specification Gate pending**
- **Actor:** System / Local Administrator.
- **Goal:** Detect eligible RFC workbook evidence and stage source-owned RFC observations without treating file presence/omission as lifecycle mutation.
- **Trigger/preconditions:** Manual/scheduled source check; RFC source configured.
- **Main flow:** discover candidates; validate headers/identity/safety; parse active allowlisted fields including status, creation/customer/handler chronology; distinguish canonical IDs, source branch artifacts and invalid rows; stage diffs/proposals.
- **Alternates/failures:** file mtime ranks candidates only; highest chosen invalid candidate fails rather than silently falling back; missing optional-active values warn/preserve prior truth; no age-based RFC deletion/cutoff.
- **Postconditions/evidence:** staged RFC source observations/provenance only.
- **Candidate authority:** `BETA-REQ-0012`, `0145..0152`, `0159`, `0176..0177`.

## UC-021 — Review RFC source changes and terminal evidence
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Accept/reject staged RFC mutations while keeping provider terminal evidence separate from local cascade consequences.
- **Trigger/preconditions:** RFC proposal exists.
- **Main flow:** inspect exact source/diff/hierarchy/customer/status chronology; accept valid mutations; when terminal evidence is accepted, append terminal evidence and atomically create/update pending cascade proposal; leave local cascade unexecuted.
- **Alternates/failures:** terminal acceptance does not cancel local work or unlink Communications; hierarchy/reparenting/customer/ownership changes remain high risk; omission does not close/remove RFC.
- **Postconditions/evidence:** RFC source truth updated; pending cascade proposal/history preserved separately.
- **Candidate authority:** `BETA-REQ-0146..0152`, `0161`, `0176`; RFC/WFM/Communications contracts.

## UC-022 — Register a WFM Task manually
Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Register a WFM Task manually under exactly one RFC without conflating manual registration with provider-source discovery/import.
- **Trigger/preconditions:** Operator has a valid WFM identity/context; owning RFC exists or is deliberately created/reconciled through an allowed flow.
- **Main flow:** validate exact `TK` identity; bind exactly one RFC owner; capture known WFM/task name/provider facts without inventing source observations; preserve source-plan versus operational Task-plan separation; save manual registration evidence.
- **Alternates/failures:** malformed TK is rejected; no fake TK is assigned to Local Tasks; missing optional provider facts remain unknown; manual registration cannot fabricate imported provenance or silently create Objective membership.
- **Postconditions/evidence:** stable WFM Task identity, exact RFC owner, manual-origin history, and separate planning authorities.
- **Candidate authority:** `BETA-REQ-0013`, `0041..0042`, `0155..0156`, `0170..0172`; RFC/WFM Contract.

## UC-023 — Review WFM plan changes and competing attempts
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Decide how provider WFM source-plan observations affect accepted operational Task planning without silently regrouping Objectives or conflating attempts.
- **Trigger/preconditions:** WFM source proposal/competing attempt exists.
- **Main flow:** inspect source chronology/Task No/plan/status; distinguish same attempt from competing lineage; accept/reject source evidence; separately decide material operational plan change and any downstream regrouping proposal.
- **Alternates/failures:** source acceptance alone does not accept Objective membership/regroup; Plan Cancel/Complete remain source history; provider Complete may propose historical Objective context but does not prove execution/outcome.
- **Postconditions/evidence:** source lineage and accepted Task-plan proposal decisions preserved independently.
- **Candidate authority:** `BETA-REQ-0156..0158`, `0160`, `0170..0172`, `0176`.

## UC-024 — Classify an SR to a Contract Product Line
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Assign or correct the one active customer-compatible CPL classification governing an SR.
- **Trigger/preconditions:** SR Customer and eligible CPL candidates exist or classification remains unresolved.
- **Main flow:** inspect compatible CPLs; select one active eligible CPL; review classification consequence; accept assignment/reclassification; preserve prior history.
- **Alternates/failures:** Advanced Search Product never auto-classifies; archived/inactive/incompatible CPL is rejected; unresolved inputs leave SR unclassified; batch selection partitions incompatible/stale/unresolved targets.
- **Postconditions/evidence:** at most one active CPL classification with independent audit/history.
- **Candidate authority:** `BETA-REQ-0064..0065`, `0173`; Product Line/SLA/Workbench contracts.

## UC-025 — Evaluate current SR SLA and cohort status
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator / System.
- **Goal:** Understand an SR's current SLA calculability, individual duration evidence and cohort compliance under its current CPL policy.
- **Trigger/preconditions:** SR exists; classification/Report Date/evidence may be complete or incomplete.
- **Main flow:** determine classification separately from calculability; compute eligible duration from accepted Report Date to current/terminal endpoint minus accepted source suspension; evaluate current policy tier/cohort state; expose Pending/Currently Met/At Risk/Breached/Final Met as applicable.
- **Alternates/failures:** missing Report Date yields uncalculable SLA but does not erase valid classification; Cancelled leaves cohort; policy revisions recalc current/terminal SRs; no premature rounding/fallback deadline.
- **Postconditions/evidence:** current derived SLA projection; no mutation of completed reports.
- **Candidate authority:** `BETA-REQ-0063..0065`, `0069..0071`, `0173..0175`.

## UC-026 — Browse active, terminal, and historical Tickets
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Find and inspect Tickets across Daily/Weekly/Monthly and Historical presentation without treating presentation movement as lifecycle or retention.
- **Trigger/preconditions:** Ticket data exists.
- **Main flow:** select period/view/filter; inspect active and terminal rows with truthful state; open ticket/workbench; preserve historical visibility and local filters.
- **Alternates/failures:** terminal SR/RFC/WFM history is not purged by age/omission; Advanced Search's one-month terminal-row lookback remains source-specific presentation; no official reopen episode is created by display.
- **Postconditions/evidence:** no lifecycle mutation; operator context preserved.
- **Candidate authority:** `BETA-REQ-0038`, `0039`, `0069..0077`, `0147`; Workbench/UI contracts.

## UC-081 — Discover and stage provider WFM source data
Status: **Goal Seed — extracted from former UC-022 by P1A-002**
- **Actor:** System / Local Administrator.
- **Goal:** Discover, validate, parse, and stage Service Provider WFM source evidence without treating source presence as accepted Task-plan or Objective authority.
- **Trigger/preconditions:** Manual/scheduled WFM source check; provider source available according to configured import boundary.
- **Main flow:** discover eligible source; validate source structure and WFM/RFC identities; parse provider plan/status/context; preserve source chronology/provenance; identify same/competing attempts; stage proposals/diffs for reviewed acceptance.
- **Alternates/failures:** malformed identity/source fails safely; provider RFC status remains provisional relative to accepted RFC authority; source omission does not delete/cancel a WFM; parsing alone cannot mutate Task plan, Objective membership, execution, or outcome.
- **Postconditions/evidence:** staged WFM source observations and immutable provenance only.
- **Candidate authority:** `BETA-REQ-0013`, `0041..0042`, `0155..0160`, `0170..0172`, `0176..0177`; Import + RFC/WFM contracts.

## UC-094 — Manage Working Notes
Status: **Goal Seed — added by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Create, edit, and remove operational Working Notes while preserving original creation chronology and auditable prior content.
- **Trigger/preconditions:** A supported workbench/record exists and Notes are available for that context.
- **Main flow:** create or select a note; edit or remove it; preserve immutable original creation timestamp; record modification/removal chronology and prior content; keep source/import operations from overwriting local notes.
- **Alternates/failures:** failed save preserves prior accepted note; deletion/removal does not rewrite earlier audit evidence; imported/source data cannot replace the local note merely because related record data changes.
- **Postconditions/evidence:** current note projection plus creation/modification/removal history with prior content where governed.
- **Candidate authority:** `BETA-REQ-0052` (`NOTE-HIST`); Workbench Contract Notes sections; UI/UX/Runtime audit support as applicable.
