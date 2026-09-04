# P1A-W7 — Overview & Cross-Domain Operations Use Cases

Status: **Draft catalogue; UC-070..UC-077 pending owner review**

## UC-070 — Navigate SOMA workspaces, lists, and workbenches
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Move predictably among Overview, Tickets, Objectives, Inventory, Infrastructure, and Settings while preserving context and using consistent selection/open behavior.
- **Trigger/preconditions:** Authenticated application session.
- **Main flow:** select workspace; use lists/filters/search/tree context; distinguish focus, active row, selection and opening; open default record by double-click/Enter; navigate cross-domain links; return with applicable filters/selection/scroll/focus preserved.
- **Alternates/failures:** nested controls do not accidentally open rows; touch has explicit Open action; removed/stale results use deterministic fallback and explanation; responsive layout preserves capability.
- **Postconditions/evidence:** navigation context only; no business mutation from selection/open/scroll.
- **Authority:** `BETA-REQ-0051`, `0123..0130`, UI/UX/Workbench contracts.

## UC-071 — Manage unsaved working copies, save/discard, conflicts, and safe Undo
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Edit supported records safely without unsaved values becoming authoritative truth or overwriting newer accepted state.
- **Trigger/preconditions:** Editable UI surface/working copy exists.
- **Main flow:** modify working copy; identify dirty scope; validate/save whole or valid selective scope; discard whole/selective changes; recover protected draft where supported; on stale base review conflict and reapply safe changes; invoke bounded action-scoped Undo only when inverse remains valid.
- **Alternates/failures:** navigation warns before abandonment; failure preserves safe input; no last-write-wins for identity/evidence/lifecycle; Undo cannot reverse accepted evidence when owning correction/supersession is required.
- **Postconditions/evidence:** accepted state changes only on valid save/domain command; working-copy/history state remains distinct.
- **Authority:** `BETA-REQ-0123..0130`, `0136`; UI/UX/Runtime contracts.

## UC-072 — Use Overview and Needs Attention to understand current operations
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** See Customer/period-scoped operational health across Tickets, Objectives, Inventory, SLA, Communications, and current attention items without creating competing domain truth.
- **Trigger/preconditions:** Relevant domain data exists or empty-state is valid.
- **Main flow:** choose Customer/all and Daily/Weekly/Monthly context; inspect summary counts/trends, SLA/cohort health, Communication coverage, Inventory/Objective context and operational narrative; open Needs Attention item into preserved filtered/domain view.
- **Alternates/failures:** unknown/partial/stale coverage shown explicitly; summaries derive from owning domains; no reconstructed discarded `Resolved Status Date`; empty states remain truthful.
- **Postconditions/evidence:** read-only derived projection/navigation context.
- **Authority:** `BETA-REQ-0039`, `0051`, `0069..0071`, `0123..0130`, UI/UX Contract.

## UC-073 — Generate a Daily, Weekly, or Monthly Excel report
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Produce a Customer-scoped or all-customer Excel report from one internally consistent snapshot/context without mutating operational truth.
- **Trigger/preconditions:** Operator selects report period/scope; required data may be complete/partial according to report contract.
- **Main flow:** choose Daily/Weekly/Monthly and Customer/all scope; establish report as-of/timezone/population/policy context; calculate domain/SLA metrics consistently; generate/verify Excel artifact; record completed report evidence.
- **Alternates/failures:** generation failure/cancel changes no operational state; report does not trigger cleanup; exact internal persisted/on-demand/both representation remains `O-001`; safe export nondeterminism is normalized only where explicitly allowed.
- **Postconditions/evidence:** verified Excel artifact and immutable completed calculation context/evidence.
- **Authority:** `BETA-REQ-0071`, `0137..0139`, `0174..0175`; SLA/UI/Runtime contracts.

## UC-074 — Review completed report evidence against current recalculated truth
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Inspect an immutable completed report while understanding that later CPL/SLA policy or source corrections affect current/future results rather than rewriting the old report.
- **Trigger/preconditions:** Completed report evidence exists; current data/policy may have changed.
- **Main flow:** open completed report/context; inspect its as-of scope/population/policy/result evidence; compare to current derived values where useful; preserve report as historical evidence.
- **Alternates/failures:** policy revision recalculates current and terminal classified SRs but not completed artifact; terminal correction may alter current projection while preserving prior report; report persistence mechanics remain `O-001`.
- **Postconditions/evidence:** no mutation of completed report; current truth remains separately derived.
- **Authority:** `BETA-REQ-0064`, `0071`, `0174..0175`.

## UC-075 — Review notifications, warnings, and actionable attention states
Status: **Draft — pending owner review**
- **Actor:** Local Administrator / System.
- **Goal:** Surface time-sensitive or integrity/action conditions without converting warnings into domain state or duplicating notifications excessively.
- **Trigger/preconditions:** Accepted facts satisfy a warning/attention rule or scheduled evaluation occurs.
- **Main flow:** System evaluates governed conditions; show Needs Attention/in-app warning and permitted supplemental local notification; operator opens exact affected context; acknowledge presentation where supported without changing underlying fact.
- **Alternates/failures:** terminal SR suppresses active-work/live-risk reminders as governed; supplemental same-condition local notification limited to accepted cadence; warning dimensions remain independent (SLA, duration, suspension, source integrity, terminal, etc.).
- **Postconditions/evidence:** presentation/notification history as governed; underlying domain truth unchanged except explicit follow-up action.
- **Authority:** `BETA-REQ-0049`, `0068..0070`, `0089`, UI/UX/SLA/Workbench contracts.

## UC-076 — Execute bulk, destructive, or consequential actions safely
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Apply supported multi-target or consequential commands with truthful eligibility partitioning and proportionate confirmation safeguards.
- **Trigger/preconditions:** Operator selects one or more targets and a supported action.
- **Main flow:** preflight each target as eligible/incompatible/stale/missing-input/individual-review; show impact preview where required; use deliberate hold only for allowlisted actions; freshly revalidate; execute owning transactional/per-target contract; present exact results.
- **Alternates/failures:** no target silently skipped/coerced; hold never substitutes for impact preview; Device Reference new-NE promotion always uses 3-second hold; stale/failed target keeps truthful state and independently correctable result.
- **Postconditions/evidence:** accepted per-target/batch events and audit, or no mutation on rejected/failed preflight.
- **Authority:** `BETA-REQ-0064`, `0090`, `0123..0130`, `0139`; UI/UX + owning contracts.

## UC-077 — Inspect combined domain history, audit, jobs, and activity
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Understand what operationally happened, what SOMA accepted/changed, what background processing proposed/did, and what technical failures occurred without conflating those authorities.
- **Trigger/preconditions:** Relevant target/job/run history exists.
- **Main flow:** open History/activity surface; inspect separately labeled domain lifecycle evidence, application audit, proposal/job history, and technical diagnostics; follow immutable identities/correlation references; inspect source/effective/recording chronology where applicable.
- **Alternates/failures:** projection/rendering does not fabricate events; diagnostics remain non-authoritative/redacted; hard deletion retains only allowed minimized non-reconstructable audit; unknown external time remains unknown.
- **Postconditions/evidence:** read-only interpretability across independent history classes.
- **Authority:** `BETA-REQ-0019..0020`, `0135`, `0141..0144`; Runtime/UI/owning domain contracts.
