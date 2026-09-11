# RFC/WFM Import, Lifecycle, and Objective Grouping Contract

**Status:** Reconciled RC-002 — normative Beta 1.0.0 product contract  
**Authority:** accepted normalized RFC/WFM source, lifecycle, relationship, scheduling, grouping, customer, and terminal-cascade authority, especially `BETA-REQ-0145` through `BETA-REQ-0177` where applicable, together with governing identity/import requirements such as `BETA-REQ-0012` and `0013`.

## 1. Source discovery and authority

Enhanced RFC and WFM workbooks share one configurable operational import directory, with Downloads offered only as the initial suggestion. Each adapter owns its filename pattern, stabilization, source chronology, fingerprint, and accepted checkpoint. Only stable direct regular files are discovered. WFM uses its supported embedded export timestamp; RFC filesystem modification time is candidate-ranking metadata only. Collision suffixes are never chronology. Selection and ties are deterministic, and an invalid newest candidate fails visibly without older fallback. Manual file selection remains available.

Workbooks are untrusted observations, not replacement databases. Parsing, security checks, header resolution, normalization, row validation, logical fingerprinting, diff, and warnings finish before mutation. Exact replay is a no-op; newer identical logical content may update bounded run recency without record events; same chronology with different content conflicts; older replay requires an explicit recovery flow.

## 2. Presence, status, and history

Workbook omission has no record-level lifecycle meaning. It never closes, cancels, archives, hides, unlinks, stops tracking, or resumes an RFC/WFM. Beta has no separate `Stop tracking` state. Because supported reports contain current and historical rows—including Closed, Cancelled, Complete, and Plan Cancel—SOMA uses recognized status for lifecycle projection and performs operational filtering locally. Partial-export uncertainty may produce one workbook-level coverage warning, never thousands of disappearance warnings.

RFC status is a case-insensitive closed vocabulary. Closed and Cancelled are distinct terminal evidence. Unknown values warn without destructive authority. Progression does not silently regress; a post-Implement cancellation is possible but high risk. Evidence correction is append-only and targets the exact accepted source fact.

`Complete` and `Plan Cancel` WFM rows are historical evidence. Plan Cancel may create or adopt the exact WFM as cancelled history, but never activates it, promotes/reactivates an RFC, or creates an Objective. Any consequence for a current Objective is a separate reviewed proposal.

## 3. Identity, headers, and reconciliation

Exact canonical RFC or WFM identifiers adopt manually registered records in place while preserving internal identity, relationships, and history. Similar text never authorizes adoption. Source provenance derives irreversibly from accepted observations rather than a mutable `ever_imported` flag. SOMA `created_at` and source `external_created_at` are separate; unknown source time stays unknown.

A canonical RFC identifier is `NC` plus exactly fourteen digits. An imported Enhanced `Task ID` that contains that canonical form plus additional source-branch characters/digits is a recognized source branch artifact: it is review-visible as skipped, creates/updates no RFC, and is never truncated into the canonical parent. Other malformed RFC identifiers fail validation rather than being mislabeled as branch artifacts. WFM identity remains `TK` plus exactly fourteen digits.

Header registries are versioned and classify required identity, optional active, deferred, and discarded fields. RFC requires recognized Task ID and a usable canonical identity. Its supported optional active semantics include Summary, Status, Create Time, Creator, Customer Account Number/Name, Severity, Owner/Owner Name, L1/L2 handler, and Last Update. WFM requires usable RFC No. and Task No.; its governed status, planning, customer, name, and description fields are optional according to their field rules. Aliases are explicit normalized closed sets, never fuzzy or positional; duplicate aliases conflict. Missing optional-active coverage warns and preserves prior accepted truth rather than clearing it.

Repeated RFC No. across different WFM Task Nos is normal. Exact duplicate observations may collapse with warning. Conflicting observations for one identity block only their affected safe acceptance scope. An invalid identityless row does not automatically destroy unrelated valid rows. Outside-matrix content carries no operational meaning but remains within the workbook security scan. Resource ceilings and preview page sizes are measured LLD controls, not immutable product numbers; exact totals and unresolved conflicts remain visible.

## 4. Relationships and hierarchy

Only an Implement-eligible RFC owns active nonterminal WFM work. A WFM may provision a missing RFC and propose provisional eligibility, but cannot override accepted Enhanced RFC evidence showing a pre-Implement state. No import fabricates an SR.

SR candidates are extracted first from RFC Summary and secondarily from WFM Task Name. Labelled SR/TT plus exactly eight digits is strong; an isolated eight-digit token is lower-confidence; dates and substrings of longer values are excluded. Candidates can match existing SRs only and require review. Evidence originating from a subordinate RFC or its WFM proposes the direct relationship to the governing Master/root RFC while preserving subordinate-source provenance; it does not create the relationship before acceptance. SR and RFC lifecycles remain independent, including links to terminal/historical SRs after explicit review.

RFC hierarchy is an acyclic two-level forest. Roles derive from relationships; providers never infer them. Resolved branch members share Customer Organization, while unknown ownership stays provisional with warning. Used branches require high-risk correction to reparent. There is no arbitrary business maximum for direct subordinates; virtualization and measured safety ceilings govern scale.

Archival is reversible presentation, never terminal evidence. Branch archive/restore operates only on exact eligible RFC members recorded by that operation and never cascades into SR, WFM, Objective, provider status, or communication state.

## 5. Scheduling and grouping

WFM source planned time is immutable provider evidence separate from the accepted SOMA operational Task plan, the Objective envelope, and actual execution. Both timestamps blank means unscheduled. Otherwise both must be usable, with end later than start. Explicit offsets are preserved; offsetless WFM source time uses `America/Guayaquil` under the accepted source profile and persists as UTC whole seconds. Any valid minute is allowed. A malformed pair is a row-level error by default and creates no schedule. A changed interval for the same Task No. is a reviewed source revision; a retry uses a new Task No.

The valid WFM source plan is the default reviewed operational-plan candidate. Accepting source evidence does not itself accept a Task plan, Objective membership, or regrouping consequence. A conflicting manual plan is shown beside it; the operator may adopt the source value, retain the manual value with reason, correct the operational plan, or leave the conflict unresolved. Execution, terminal evidence, or an explicit plan lock stops automatic recalculation; wall-clock position alone does not.

Automatic Objective grouping consumes eligible accepted operational Task-plan intervals and computes maximal global transitive components using strict positive-duration overlap. Customer and Master/root-RFC hierarchy are explanatory work-package partitions inside a component, not reasons to create overlapping Objectives. Exactly touching intervals do not overlap unless deliberately reviewed together. Unknown/multi-customer context remains explicit within the shared temporal component. The Objective envelope is the minimum accepted member-plan start through maximum accepted member-plan end. A bridging Task proposes consolidation.

Import/source acceptance and Objective regrouping are separate reviewed actions. Proposals carry exact base revisions and diffs. Planned Objectives may restructure; in-progress changes are limited high-risk history-preserving actions; terminal Objectives never restructure. Rejection retains only bounded decision/equivalence evidence sufficient to recognize materially unchanged proposals, and only material grouping-input change or explicit reconsideration invalidates that equivalence. Acceptance freshly revalidates revisions, locks, membership, and global non-overlap before atomic commit.

An SR may be solved without any Task or Objective, including customer-resolved and Non-fault inquiry cases. No work is fabricated. Objective review records acceptance time separately from execution, preserves per-Task outcomes, never infers spare use, and creates new identities for retries.

Distinct WFM Task Nos remain distinct attempts. Multiple WFMs under one RFC may share an Objective when reviewed as genuinely different activities. Only competing active attempts of the same reviewed activity lineage conflict. SOMA preserves both identities and reviews whether they are distinct work, a retry, a cancellation, source error, or unresolved; it never creates overlapping Objectives to evade that review.

Local Tasks are first-class Tasks with internal identity and no fabricated provider identifier. Task Name is the only universal descriptive requirement. They may be unscheduled or belong to at most one Objective. A Task created inside an Objective may initialize its plan from that Objective, but its accepted plan is independent and the Objective envelope remains derived.

Planned and actual intervals are distinct. Starting an Objective does not start every Task. An unstarted member may be cancelled during or after the activity while other work continues. Per-Task outcomes include Completed, Incomplete, Cancelled without execution, and Awaiting Review. Mixed outcomes remain visible; whole-Objective Cancelled is valid only when no Task began. Recording and effective times remain separate.

Objective schedule entry, calendar grouping, and presentation use the operator-selected IANA Objective timezone. Changing that setting changes display of existing UTC instants, not the instants; preserving local wall-clock time requires explicit reviewed rescheduling. This setting has no authority over RFC/WFM source chronology or other domains.

## 6. Terminal cascade

Accepted RFC terminal source evidence atomically appends that evidence and creates a pending cascade proposal, but executes no local cascade consequence. A subordinate proposal targets that exact RFC and its applicable active owned WFMs. A Master proposal targets the exact current two-level branch and its applicable active WFMs. It never targets SRs or unrelated Local Tasks.

The pending cascade stores exact internal membership, persists across restart, exposes an impact preview, and requires the governed three-second deliberate hold or accessible equivalent before execution. After the hold, the scope is freshly revalidated. Newer contradictory active evidence, material hierarchy/scope change, or changed applicable membership blocks stale acceptance. Commit is all-or-nothing. Provider WFM status remains intact beside SOMA termination provenance. Surviving executable Objective work continues with warning; an in-progress Objective losing its last executable Task becomes `Incomplete — Awaiting Review`; terminal Objective history remains untouched.

Only after confirmed cascade execution do direct RFC communication links follow the Communications Contract; only a dependency-free retained communication may then enter orphan grace. Import review and safe auto-accept can never execute the cascade or bypass its deliberate confirmation. Erroneously recorded terminal/cascade evidence is append-correctable. Genuine later WFM work uses a new Task No.

If executable members survive an accepted loss, an in-progress Objective continues with a warning. If none survive, it becomes `Incomplete — Awaiting Review`. Locks derive from accepted execution/history rather than the current clock. Started or evidenced Tasks/Objectives are never hard-deleted.

A provider `Complete` WFM without Objective membership may propose a historical Objective only when a usable accepted source interval exists. This proves neither actual execution nor local Task outcome nor downstream Device/Inventory effects. The operator may exclude historical Tasks from operational counting without deleting history; excluding all members marks the Objective `Excluded from operational counts` and reports disclose both included and excluded populations.

`Plan Cancel` may create or adopt its exact WFM identity as cancelled history. It never activates work, promotes an RFC, or creates an Objective; any conflict with existing planned or in-progress local work is separately reviewed.

## 7. Customer, import review, and derived context

Every RFC has at most one current Customer Organization. Customer Account Number is the strongest supported external reconciliation key; names remain labels. WFM and linked-SR facts may propose reviewed reconciliation, while Infrastructure context never proves ownership. Resolved branch membership must agree; unresolved customer context remains a warned work-package partition and does not block temporal grouping.

A WFM's master/subordinate/root context derives only from its owning RFC hierarchy, including outside an Objective. There is no WFM hierarchy, master flag, or `master_wfm_id`. Hierarchy correction recalculates current context while preserving identities and history.

Every workbook produces an exact-source staged result. Observed valid source presence is distinct from accepting a mutation, so rejected, deferred, or unresolved proposals do not fabricate disappearance. Independent targets receive dispositions at the smallest safe explainable idempotent scope. Terminal RFC proposals are individually rejectable; acceptance appends terminal evidence and its pending cascade proposal atomically, while local cascade still requires its own impact preview, deliberate hold, and fresh revalidation. Whole-workbook rejection is reserved for failures that prevent safe trustworthy target-level disposition.

Auto-accept is limited to centrally governed/versioned low-risk classes whose exact field/change allowlist remains `O-007`. It shall not include terminal evidence with material consequence, hierarchy/reparenting, Customer/ownership changes, material Task/WFM timeframe changes, disappearance/empty-population interpretation, Objective-regrouping consequences, or suspected competing-attempt disposition. Auto-accept never executes a terminal cascade.

## 8. Acceptance minimum

Automated acceptance covers deterministic discovery, unsafe input, replay/chronology conflict, exact-source presence versus mutation acceptance, partial and historical exports, omission neutrality, status correction, adoption, RFC branch-artifact versus malformed identity treatment, header aliases/optional coverage, duplicate/conflicting rows, smallest-safe-scope disposition, hierarchy/reparenting, Customer reconciliation, SR candidates, Plan Cancel, arbitrary-minute source planning, source-plan versus accepted Task-plan separation, strict-overlap grouping over accepted Task plans, stale regroup proposals, competing-attempt review, provider-Complete historical Objective proposals, restart-persistent terminal review, impact preview, hold/revalidation, cascade rollback, Objective effects, and communication orphan-grace integration. Tests shall prove safe auto-accept excludes terminal, hierarchy, ownership, timeframe, disappearance/empty-population, regrouping-consequence, and competing-attempt cases, while whole-import rejection remains reserved for genuine workbook-level failure.
