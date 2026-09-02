# RFC/WFM Import, Lifecycle, and Objective Grouping Contract

**Status:** Normative Beta 1.0.0 product contract  
**Authority:** `BETA-REQ-0145` through `BETA-REQ-0161`, with revised `BETA-REQ-0045`, `0050`, `0064`, `0065`, `0070`, and `0073`.

## 1. Source discovery and authority

Enhanced RFC and WFM workbooks share one configurable operational import directory, with Downloads offered only as the initial suggestion. Each adapter owns its filename pattern, stabilization, source chronology, fingerprint, and accepted checkpoint. Only stable direct regular files are discovered. WFM uses its supported embedded export timestamp; RFC filesystem modification time is candidate-ranking metadata only. Collision suffixes are never chronology. Selection and ties are deterministic, and an invalid newest candidate fails visibly without older fallback. Manual file selection remains available.

Workbooks are untrusted observations, not replacement databases. Parsing, security checks, header resolution, normalization, row validation, logical fingerprinting, diff, and warnings finish before mutation. Exact replay is a no-op; newer identical logical content may update bounded run recency without record events; same chronology with different content conflicts; older replay requires an explicit recovery flow.

## 2. Presence, status, and history

Workbook omission has no record-level lifecycle meaning. It never closes, cancels, archives, hides, unlinks, stops tracking, or resumes an RFC/WFM. Beta has no separate `Stop tracking` state. Because supported reports contain current and historical rows—including Closed, Cancelled, Complete, and Plan Cancel—SOMA uses recognized status for lifecycle projection and performs operational filtering locally. Partial-export uncertainty may produce one workbook-level coverage warning, never thousands of disappearance warnings.

RFC status is a case-insensitive closed vocabulary. Closed and Cancelled are distinct terminal evidence. Unknown values warn without destructive authority. Progression does not silently regress; a post-Implement cancellation is possible but high risk. Evidence correction is append-only and targets the exact accepted source fact.

`Complete` and `Plan Cancel` WFM rows are historical evidence. Plan Cancel may create or adopt the exact WFM as cancelled history, but never activates it, promotes/reactivates an RFC, or creates an Objective. Any consequence for a current Objective is a separate reviewed proposal.

## 3. Identity, headers, and reconciliation

Exact canonical RFC or WFM identifiers adopt manually registered records in place while preserving internal identity, relationships, and history. Similar text never authorizes adoption. Source provenance derives irreversibly from accepted observations rather than a mutable `ever_imported` flag. SOMA `created_at` and source `external_created_at` are separate; unknown source time stays unknown.

Header registries are versioned and classify required identity, optional active, deferred, and discarded fields. RFC requires recognized Task ID and a usable canonical identity. Its supported optional active fields include Summary, Status, Create Time, Creator, Customer Account Number/Name, Severity, Owner/Owner Name, L1/L2 handler, and Last Update. WFM requires usable RFC No. and Task No.; its governed status, planning, customer, name, and description fields are optional according to their field rules. Aliases are explicit normalized closed sets, never fuzzy or positional; duplicate aliases conflict.

Repeated RFC No. across different WFM Task Nos is normal. Exact duplicate observations may collapse with warning. Conflicting observations for one identity block their affected acceptance scope. An invalid identityless row does not automatically destroy unrelated valid rows. Outside-matrix content carries no operational meaning but remains within the workbook security scan. Resource ceilings and preview page sizes are measured LLD controls, not immutable product numbers; exact totals and unresolved conflicts remain visible.

## 4. Relationships and hierarchy

Only an Implement-eligible RFC owns active nonterminal WFM work. A WFM may provision a missing RFC and propose provisional eligibility, but cannot override accepted Enhanced RFC evidence showing a pre-Implement state. No import fabricates an SR.

SR candidates are extracted first from RFC Summary and secondarily from WFM Task Name. Labelled SR/TT plus exactly eight digits is strong; an isolated eight-digit token is lower-confidence; dates and substrings of longer values are excluded. Candidates can match existing SRs only and require review. Subordinate evidence creates the direct link to its master. SR and RFC lifecycles remain independent, including links to terminal/historical SRs after explicit review.

RFC hierarchy is an acyclic two-level forest. Roles derive from relationships; providers never infer them. Resolved branch members share Customer Organization, while unknown ownership stays provisional with warning. Used branches require high-risk correction to reparent. There is no arbitrary business maximum for direct subordinates; virtualization and measured safety ceilings govern scale.

Archival is reversible presentation, never terminal evidence. Branch archive/restore operates only on exact eligible RFC members recorded by that operation and never cascades into SR, WFM, Objective, provider status, or communication state.

## 5. Scheduling and grouping

WFM source planned time is separate from SOMA planning, the Objective envelope, and actual execution. Both timestamps blank means unscheduled. Otherwise both must be usable, with end later than start. Offsetless source time uses America/Guayaquil and persists as UTC whole seconds. Any valid minute is allowed. A malformed pair is a row-level error by default and creates no schedule. A changed interval for the same Task No. is a reviewed source revision; a retry uses a new Task No.

Automatic grouping computes global transitive components using strict interval overlap. Customer and master-RFC hierarchy are explanatory work-package partitions inside a component, not reasons to create overlapping Objectives. Exactly touching intervals do not overlap unless deliberately merged. Unknown-customer partitions remain separate within the shared Objective. Its envelope is minimum start through maximum end. A bridging Task proposes consolidation.

Import acceptance and regrouping are separate reviewed actions. Proposals carry exact base revisions and diffs. Planned Objectives may restructure; in-progress changes are limited high-risk actions; terminal Objectives never restructure. Rejection retains only minimized decision evidence, and only material grouping-input change or explicit reconsideration invalidates it.

An SR may be solved without any Task or Objective, including customer-resolved and Non-fault inquiry cases. No work is fabricated. Due Objective review records acceptance time separately from execution, preserves per-Task outcomes, never infers spare use, and creates new identities for retries.

## 6. Terminal cascade

Accepted terminal evidence creates a pending cascade proposal atomically but mutates local lifecycle only after an explicit three-second deliberate hold or accessible equivalent. A subordinate proposal targets that RFC and its active owned WFMs. A master proposal targets the exact two-level branch and its active WFMs. It never targets SRs or unrelated Local Tasks.

The cascade stores internal membership, persists across restart, and revalidates after the hold. Newer contradictory active evidence or changed membership blocks acceptance. Commit is all-or-nothing. Provider WFM status remains intact beside SOMA termination provenance. Surviving executable Objective work continues with warning; an in-progress Objective losing its last executable Task becomes incomplete awaiting review; terminal Objective history remains untouched.

After confirmation, direct RFC communication links follow the Communications Contract and only a dependency-free communication enters orphan grace. Erroneously recorded terminal/cascade evidence is append-correctable. Genuine later WFM work uses a new Task No.

## 7. Acceptance minimum

Automated acceptance covers deterministic discovery, unsafe input, replay/chronology conflict, partial and historical exports, omission neutrality, status correction, adoption, header aliases, duplicate/conflicting rows, hierarchy/reparenting, SR candidates, Plan Cancel, arbitrary-minute scheduling, strict-overlap grouping, stale regroup proposals, restart-persistent terminal review, hold/revalidation, cascade rollback, Objective effects, and communication orphan-grace integration.
