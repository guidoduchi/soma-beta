# P1A-W7 — Overview & Cross-Domain Operations Use Cases

Status: **P1A-002 reconstruction complete — Goal Seeds pending Specification Gate; owner review paused pending RC-006-A2**

## UC-070 — Navigate SOMA workspaces, lists, and workbenches
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Move predictably among Overview, Tickets, Objectives, Inventory, Infrastructure, and Settings while preserving context and using consistent selection/open behavior.
- **Trigger/preconditions:** Authenticated application session.
- **Main flow:** select workspace; use lists/filters/search/tree context; distinguish focus, active row, selection and opening; open default record by double-click/Enter; navigate cross-domain links; return with applicable filters/selection/scroll/focus preserved.
- **Alternates/failures:** nested controls do not accidentally open rows; touch has explicit Open action; removed/stale results use deterministic fallback and explanation; responsive layout preserves capability.
- **Postconditions/evidence:** navigation context only; no business mutation from selection/open/scroll.
- **Candidate authority:** `BETA-REQ-0051`, `0123..0130`; UI/UX/Workbench contracts.

## UC-071 — Manage unsaved working copies and save/discard/recover edits
Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Edit supported records safely while keeping unsaved values distinct from authoritative state and allowing governed save, discard, and protected draft recovery.
- **Trigger/preconditions:** Editable UI surface/working copy exists.
- **Main flow:** modify working copy; identify dirty scope; validate/save whole or valid selective scope; discard whole/selective changes; recover protected draft where supported; preserve authoritative state until a valid domain command commits.
- **Alternates/failures:** navigation warns before abandonment; save failure preserves safe user input; invalid fields do not partially become authoritative; no hidden autosave may overwrite accepted evidence/lifecycle state.
- **Postconditions/evidence:** authoritative state changes only through valid save/domain command; working-copy/recovery state remains distinct.
- **Candidate authority:** `BETA-REQ-0123..0130`, applicable `0136`; UI/UX/Runtime contracts.

## UC-072 — Use Overview and Needs Attention to understand current operations
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** See Customer/period-scoped operational health across Tickets, Objectives, Inventory, SLA, Communications, and current attention items without creating competing domain truth.
- **Trigger/preconditions:** Relevant domain data exists or empty-state is valid.
- **Main flow:** choose Customer/all and Daily/Weekly/Monthly context; inspect summary counts/trends, SLA/cohort health, Communication coverage, Inventory/Objective context and operational narrative; open Needs Attention item into preserved filtered/domain view.
- **Alternates/failures:** unknown/partial/stale coverage shown explicitly; summaries derive from owning domains; no reconstructed discarded `Resolved Status Date`; empty states remain truthful.
- **Postconditions/evidence:** read-only derived projection/navigation context.
- **Candidate authority:** `BETA-REQ-0039`, `0051`, `0069..0071`, `0123..0130`; UI/UX Contract.

## UC-073 — Generate a Daily, Weekly, or Monthly Excel report
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Produce a Customer-scoped or all-customer Excel report from one internally consistent snapshot/context without mutating operational truth.
- **Trigger/preconditions:** Operator selects report period/scope; required data may be complete/partial according to report contract.
- **Main flow:** choose Daily/Weekly/Monthly and Customer/all scope; establish report as-of/timezone/population/policy context; calculate domain/SLA metrics consistently; generate/verify Excel artifact; record completed report evidence.
- **Alternates/failures:** generation failure/cancel changes no operational state; report does not trigger cleanup; exact internal persisted/on-demand/both representation remains `O-001`; safe export nondeterminism is normalized only where explicitly allowed.
- **Postconditions/evidence:** verified Excel artifact and immutable completed calculation context/evidence.
- **Candidate authority:** `BETA-REQ-0071`, `0137..0139`, `0174..0175`; SLA/UI/Runtime contracts.

## UC-074 — Review completed report evidence against current recalculated truth
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Inspect an immutable completed report while understanding that later CPL/SLA policy or source corrections affect current/future results rather than rewriting the old report.
- **Trigger/preconditions:** Completed report evidence exists; current data/policy may have changed.
- **Main flow:** open completed report/context; inspect its as-of scope/population/policy/result evidence; compare to current derived values where useful; preserve report as historical evidence.
- **Alternates/failures:** policy revision recalculates current and terminal classified SRs but not completed artifact; terminal correction may alter current projection while preserving prior report; report persistence mechanics remain `O-001`.
- **Postconditions/evidence:** no mutation of completed report; current truth remains separately derived.
- **Candidate authority:** `BETA-REQ-0064`, `0071`, `0174..0175`.

## UC-075 — Review notifications, warnings, and actionable attention states
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator / System.
- **Goal:** Surface time-sensitive or integrity/action conditions without converting warnings into domain state or duplicating notifications excessively.
- **Trigger/preconditions:** Accepted facts satisfy a warning/attention rule or scheduled evaluation occurs.
- **Main flow:** System evaluates governed conditions; show Needs Attention/in-app warning and permitted supplemental local notification; operator opens exact affected context; acknowledge presentation where supported without changing underlying fact.
- **Alternates/failures:** terminal SR suppresses active-work/live-risk reminders as governed; supplemental same-condition local notification limited to accepted cadence; warning dimensions remain independent.
- **Postconditions/evidence:** presentation/notification history as governed; underlying domain truth unchanged except explicit follow-up action.
- **Candidate authority:** `BETA-REQ-0068..0070`, `0089`, applicable UI/Workbench authority.

## UC-076 — Execute a supported bulk action safely
Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Apply one supported multi-target domain command while truthfully partitioning target eligibility and preserving per-target results.
- **Trigger/preconditions:** Operator selects multiple targets and an owning domain exposes a supported bulk command.
- **Main flow:** preflight each target as eligible/incompatible/stale/missing-input/individual-review; show action-specific impact preview where required by owning authority; freshly revalidate; execute the owning transactional/per-target contract; present exact result per target.
- **Alternates/failures:** no target silently skipped/coerced; stale/failed target remains truthful and independently correctable; bulk operation never broadens the owning command's eligibility; generic confirmation tiers/holds remain cross-cutting UI acceptance obligations rather than the purpose of this UC.
- **Postconditions/evidence:** accepted per-target/batch events and audit, or no mutation for rejected/failed targets according to owning transactional semantics.
- **Candidate authority:** `BETA-REQ-0123..0130`, `0139`, plus exact owning-domain authority for each supported bulk command; UI/UX + owning contracts.

## UC-077 — Inspect combined domain history, audit, jobs, and activity
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Understand what operationally happened, what SOMA accepted/changed, what background processing proposed/did, and what technical failures occurred without conflating those authorities.
- **Trigger/preconditions:** Relevant target/job/run history exists.
- **Main flow:** open History/activity surface; inspect separately labeled domain lifecycle evidence, application audit, proposal/job history, and technical diagnostics; follow immutable identities/correlation references; inspect source/effective/recording chronology where applicable.
- **Alternates/failures:** projection/rendering does not fabricate events; diagnostics remain non-authoritative/redacted; hard deletion retains only allowed minimized non-reconstructable audit; unknown external time remains unknown.
- **Postconditions/evidence:** read-only interpretability across independent history classes.
- **Candidate authority:** `BETA-REQ-0019..0020`, `0135`, `0141..0144`; Runtime/UI/owning domain contracts.

## UC-093 — Resolve a stale accepted-state edit conflict
Status: **Goal Seed — extracted from former UC-071 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Reconcile an edit whose base revision is stale against newer accepted state without last-write-wins corruption.
- **Trigger/preconditions:** Operator attempts to commit a working copy based on an older accepted revision.
- **Main flow:** block blind overwrite; show current accepted state versus the stale working copy and material conflicts; allow safe reapply/re-entry of still-valid changes; revalidate against current domain invariants; commit only an explicitly reviewed valid result.
- **Alternates/failures:** identity/evidence/lifecycle conflicts never auto-merge; if safe reconciliation cannot be established, preserve both the current accepted state and the user's recoverable work without mutation.
- **Postconditions/evidence:** current accepted state remains authoritative until a reviewed reconciled command commits; conflict/review history recorded where governed.
- **Candidate authority:** `BETA-REQ-0123..0130`, applicable `0136`; UI/UX/Runtime contracts.

## UC-095 — Perform bounded safe Undo of an eligible recent action
Status: **Goal Seed — extracted from former UC-071 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Reverse only an eligible recent application action whose exact inverse remains valid, without using Undo to erase protected evidence or bypass an owning correction/supersession workflow.
- **Trigger/preconditions:** An action exposes bounded Undo and its inverse is still eligible against current state.
- **Main flow:** invoke Undo; identify exact action/inverse; revalidate current revision/dependencies; execute inverse transaction if valid; record resulting history.
- **Alternates/failures:** stale/dependent state blocks Undo; accepted evidence/lifecycle facts that require correction/supersession cannot be undone as if they never occurred; failed inverse leaves current accepted state unchanged.
- **Postconditions/evidence:** valid inverse applied with audit/history, or no mutation if eligibility is lost.
- **Candidate authority:** `BETA-REQ-0123..0130`, `0136`; UI/UX/Runtime + owning domain contracts.
