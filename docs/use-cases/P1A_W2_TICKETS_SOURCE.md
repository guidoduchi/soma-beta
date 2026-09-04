# P1A-W2 — Tickets & Source Intake Use Cases

Status: **Draft catalogue; UC-013..UC-026 pending owner review**

## UC-013 — Create a manual Service Request
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Create a valid local SR when no official source record exists yet.
- **Trigger/preconditions:** Operator needs an SR work item; no official SR identity is required at creation.
- **Main flow:** create SR with stable local identity; capture available business context; preserve incomplete fields as incomplete; open it in normal Ticket workflows.
- **Alternates/failures:** local SR remains usable when optional facts are missing; no fake official SR number is fabricated; later official adoption is reviewed.
- **Postconditions/evidence:** one stable SR with local `LSR-########` identity and history.
- **Authority:** `BETA-REQ-0011`, `0053`, `0057`, `0075`; Workbench/Import contracts.

## UC-014 — Discover and stage Advanced Search SR source data
Status: **Draft — pending owner review**
- **Actor:** System / Local Administrator.
- **Goal:** Detect eligible Advanced Search workbooks and stage trustworthy SR observations without mutating authoritative records before acceptance.
- **Trigger/preconditions:** Manual check or governed schedule; source directory configured.
- **Main flow:** discover candidates by accepted pattern; validate source/workbook safety; extract allowlisted SR observations; fingerprint/replay-check; stage proposals/diffs.
- **Alternates/failures:** malformed/unsafe source is rejected; unusable nonidentity fields do not fabricate values; missing file/row is not lifecycle authority; scheduled invocation cannot bypass review policy.
- **Postconditions/evidence:** immutable source/staging/proposal evidence; no unauthorized domain mutation.
- **Authority:** `BETA-REQ-0054..0062`, `0066`, `0068`, `0074..0076`, `0145..0147`, `0176..0177`.

## UC-015 — Review and accept/reject staged SR source changes
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Decide which staged SR observations become accepted current truth while preserving prior local relationships and evidence.
- **Trigger/preconditions:** SR import proposal exists.
- **Main flow:** inspect source/provenance/diff and warnings; partition safe/incompatible/stale/high-risk changes; accept/reject/correct permitted scope; apply accepted changes atomically with audit/evidence.
- **Alternates/failures:** high-risk terminal reversal, disappearance, identity, ownership/customer, chronology or similar changes remain explicit review; rejected proposal changes nothing authoritative; whole-import rejection only for genuine workbook-level failure.
- **Postconditions/evidence:** accepted SR facts/history updated; rejected/stale proposals preserved as review history.
- **Authority:** `BETA-REQ-0056..0066`, `0074..0076`, `0146..0148`, `0176`.

## UC-016 — Reconcile or correct an SR official identity and lifecycle observation
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Adopt/correct official SR identity or reviewed lifecycle evidence without replacing the surviving SR identity or erasing history.
- **Trigger/preconditions:** Local/provisional SR or conflicting source observation exists.
- **Main flow:** identify exact surviving SR; review official identity/lifecycle evidence; confirm high-risk correction where required; adopt/correct in place; preserve aliases and earlier terminal/nonterminal evidence; recalculate current projections.
- **Alternates/failures:** terminal-to-nonterminal is same-record high-risk correction, not a new episode; no duplicate SR is fabricated; invalid identity evidence is rejected.
- **Postconditions/evidence:** stable SR internal identity with corrected official alias/current lifecycle and preserved history.
- **Authority:** `BETA-REQ-0011`, `0057`, `0076`, `0148`, SLA/Communications boundaries.

## UC-017 — Work an SR through its workbench
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Inspect and maintain the SR-centered operational context without bypassing owning domain rules.
- **Trigger/preconditions:** SR exists.
- **Main flow:** open by double-click/Enter; review Overview; manage working/device context; navigate Spare Parts, RFC, Tasks and Notes; inspect Communication evidence; follow cross-domain links while preserving owning identities.
- **Alternates/failures:** terminal/historical SR remains inspectable; incomplete SR stays usable where current action permits; unregistered Device Reference remains operationally valid; unsaved UI working copies do not alter authoritative summaries.
- **Postconditions/evidence:** accepted domain-specific edits/links/notes recorded under their owners.
- **Authority:** `BETA-REQ-0038`, `0045`, `0049`, `0051..0052`, `0075`; Workbench/UI contracts.

## UC-018 — Create a manual RFC
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Create a valid RFC work item locally when source evidence is absent or not yet imported.
- **Trigger/preconditions:** Operator needs RFC context.
- **Main flow:** create RFC with exact official NC identity when known/required; capture available summary/context; allow later hierarchy/SR/Task relationships through governed actions.
- **Alternates/failures:** malformed NC identity is rejected; no hidden hierarchy is created; eligible untouched manual RFC may later qualify for hard deletion under its own rule.
- **Postconditions/evidence:** stable RFC identity/history.
- **Authority:** `BETA-REQ-0012`, `0040`, `0153..0155`; RFC/WFM Contract.

## UC-019 — Manage RFC hierarchy and SR relationships
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Establish and maintain the accepted two-level RFC forest and direct SR relationships to governing master/root RFCs.
- **Trigger/preconditions:** RFC/SR records exist.
- **Main flow:** designate/confirm master-subordinate relationship; prevent deeper/cyclic hierarchy; link SR directly to master/root; preserve subordinate-origin provenance; inspect derived subordinate context.
- **Alternates/failures:** subordinate cannot become a master; direct SR→subordinate relationship is not fabricated; relationship changes use reviewed merge/impact behavior and preserve history.
- **Postconditions/evidence:** valid two-level forest and reviewed SR/master relations.
- **Authority:** `BETA-REQ-0039..0040`, `0151..0154`; RFC/WFM/Workbench contracts.

## UC-020 — Discover and stage Enhanced Excel RFC source data
Status: **Draft — pending owner review**
- **Actor:** System / Local Administrator.
- **Goal:** Detect eligible RFC workbook evidence and stage source-owned RFC observations without treating file presence/omission as lifecycle mutation.
- **Trigger/preconditions:** Manual/scheduled source check; RFC source configured.
- **Main flow:** discover candidates; validate headers/identity/safety; parse active allowlisted fields including status, creation/customer/handler chronology; distinguish canonical IDs, source branch artifacts and invalid rows; stage diffs/proposals.
- **Alternates/failures:** file mtime ranks candidates only; highest chosen invalid candidate fails rather than silently falling back; missing optional-active values warn/preserve prior truth; no age-based RFC deletion/cutoff.
- **Postconditions/evidence:** staged RFC source observations/provenance only.
- **Authority:** `BETA-REQ-0012`, `0145..0152`, `0159`, `0176..0177`.

## UC-021 — Review RFC source changes and terminal evidence
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Accept/reject staged RFC mutations while keeping provider terminal evidence separate from local cascade consequences.
- **Trigger/preconditions:** RFC proposal exists.
- **Main flow:** inspect exact source/diff/hierarchy/customer/status chronology; accept valid mutations; when terminal evidence is accepted, append terminal evidence and atomically create/update pending cascade proposal; leave local cascade unexecuted.
- **Alternates/failures:** terminal acceptance does not cancel local work or unlink Communications; hierarchy/reparenting/customer/ownership changes remain high risk; omission does not close/remove RFC.
- **Postconditions/evidence:** RFC source truth updated; pending cascade proposal/history preserved separately.
- **Authority:** `BETA-REQ-0146..0152`, `0161`, `0176`; RFC/WFM/Communications contracts.

## UC-022 — Create or import a WFM Task
Status: **Draft — pending owner review**
- **Actor:** Local Administrator / System.
- **Goal:** Establish a WFM Task under exactly one RFC from manual input or Service Provider source evidence.
- **Trigger/preconditions:** Owning RFC exists or is created/reconciled according to allowed flow.
- **Main flow:** accept exact TK identity; bind one RFC; capture provider source-plan evidence and status/context; keep source plan separate from operational Task plan and Objective membership.
- **Alternates/failures:** malformed/branch-artifact identity follows source classification; no fake TK for Local Task; provider RFC status is provisional relative to accepted Enhanced RFC truth.
- **Postconditions/evidence:** stable WFM Task identity, RFC owner, source-plan/history.
- **Authority:** `BETA-REQ-0013`, `0041..0042`, `0155..0156`, `0160`, `0170..0172`.

## UC-023 — Review WFM plan changes and competing attempts
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Decide how provider WFM source-plan observations affect accepted operational Task planning without silently regrouping Objectives or conflating attempts.
- **Trigger/preconditions:** WFM source proposal/competing attempt exists.
- **Main flow:** inspect source chronology/Task No/plan/status; distinguish same attempt from competing lineage; accept/reject source evidence; separately decide material operational plan change and any downstream regrouping proposal.
- **Alternates/failures:** source acceptance alone does not accept Objective membership/regroup; Plan Cancel/Complete remain source history; provider Complete may propose historical Objective context but does not prove execution/outcome.
- **Postconditions/evidence:** source lineage and accepted Task-plan proposal decisions preserved independently.
- **Authority:** `BETA-REQ-0156..0158`, `0160`, `0170..0172`, `0176`.

## UC-024 — Classify an SR to a Contract Product Line
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Assign or correct the one active customer-compatible CPL classification governing an SR.
- **Trigger/preconditions:** SR Customer and eligible CPL candidates exist or classification remains unresolved.
- **Main flow:** inspect compatible CPLs; select one active eligible CPL; review classification consequence; accept assignment/reclassification; preserve prior history.
- **Alternates/failures:** Advanced Search Product never auto-classifies; archived/inactive/incompatible CPL is rejected; unresolved inputs leave SR unclassified; batch selection partitions incompatible/stale/unresolved targets.
- **Postconditions/evidence:** at most one active CPL classification with independent audit/history.
- **Authority:** `BETA-REQ-0064..0065`, `0173`; Product Line/SLA/Workbench contracts.

## UC-025 — Evaluate current SR SLA and cohort status
Status: **Draft — pending owner review**
- **Actor:** Local Administrator / System.
- **Goal:** Understand an SR's current SLA calculability, individual duration evidence and cohort compliance under its current CPL policy.
- **Trigger/preconditions:** SR exists; classification/Report Date/evidence may be complete or incomplete.
- **Main flow:** determine classification separately from calculability; compute eligible duration from accepted Report Date to current/terminal endpoint minus accepted source suspension; evaluate current policy tier/cohort state; expose Pending/Currently Met/At Risk/Breached/Final Met as applicable.
- **Alternates/failures:** missing Report Date yields uncalculable SLA but does not erase valid classification; Cancelled leaves cohort; policy revisions recalc current/terminal SRs; no premature rounding/fallback deadline.
- **Postconditions/evidence:** current derived SLA projection; no mutation of completed reports.
- **Authority:** `BETA-REQ-0063..0065`, `0069..0071`, `0173..0175`.

## UC-026 — Browse active, terminal, and historical Tickets
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Find and inspect Tickets across Daily/Weekly/Monthly and Historical presentation without treating presentation movement as lifecycle or retention.
- **Trigger/preconditions:** Ticket data exists.
- **Main flow:** select period/view/filter; inspect active and terminal rows with truthful state; open ticket/workbench; preserve historical visibility and local filters.
- **Alternates/failures:** terminal SR/RFC/WFM history is not purged by age/omission; Advanced Search's one-month terminal-row lookback remains source-specific presentation; no official reopen episode is created by display.
- **Postconditions/evidence:** no lifecycle mutation; operator context preserved.
- **Authority:** `BETA-REQ-0038`, `0039`, `0069..0077`, `0147`; Workbench/UI contracts.
