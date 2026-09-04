# P1A-W3 — Objectives & Operational Work Use Cases

Status: **P1A-002 reconstruction complete — Goal Seeds pending Specification Gate; owner review paused pending RC-006-A2**

## UC-027 — Create a Local Task
Status: **Goal Seed — terminology/authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Create a locally owned Task with its own identity and optional business relationships, without fabricating WFM/provider identity.
- **Trigger/preconditions:** Operator needs a work item; optional SR/RFC/Spare Part Unit/Device Reference context may exist.
- **Main flow:** create Local Task; assign name/context; optionally link zero-many SRs, master/subordinate RFCs, Spare Part Units and participating Device References; leave unscheduled or establish operational plan; save.
- **Alternates/failures:** no fake TK; link validation preserves domain cardinality; a resolved Device Reference may point to a Network Element but the Task relationship remains to the operational Device Reference; Task created under an Objective may initialize from Objective context but retains independent Task-plan authority.
- **Postconditions/evidence:** stable Local Task identity and accepted relationships.
- **Candidate authority:** `BETA-REQ-0039`, `0043..0046`, `0049`, `0155`, `0163`, `0166`; Workbench/RFC-WFM contracts.

## UC-028 — Maintain Task relationships and work context
Status: **Goal Seed — terminology/authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Add/remove permitted Task links while preserving the distinction between Local and WFM ownership.
- **Trigger/preconditions:** Task exists.
- **Main flow:** inspect current SR/RFC/spare-unit/Device-Reference links; edit eligible Local Task links; for WFM preserve exactly one RFC owner while deriving master/subordinate role/context; save reviewed relationship changes.
- **Alternates/failures:** WFM cannot gain arbitrary SR/spare/Device-Reference ownership; direct SR↔RFC master rules remain independent from Local Task subordinate links; Network Element identity is not substituted for participating Device Reference identity; history preserved.
- **Postconditions/evidence:** accepted relationships with audit/history.
- **Candidate authority:** `BETA-REQ-0039..0046`, `0049`, `0163`, `0166`; Workbench/RFC-WFM contracts.

## UC-029 — Plan, schedule, or unschedule a Task
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Establish or change the accepted operational Task plan independently from WFM source evidence and actual execution.
- **Trigger/preconditions:** Task exists.
- **Main flow:** review current source-plan/Task-plan context; set or clear accepted Task planned interval where allowed; interpret schedule in selected Objective timezone; submit material plan change for any required Objective regrouping review.
- **Alternates/failures:** unscheduled Task has no Objective; raw WFM plan is only a candidate; changing Task plan does not fabricate actual execution; accepted Objective cannot silently overwrite established Task plan.
- **Postconditions/evidence:** accepted operational Task plan or explicit unscheduled state.
- **Candidate authority:** `BETA-REQ-0047..0050`, `0156..0158`, `0166`, `0172`, `0177`.

## UC-030 — Create an Objective manually
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Create a Maintenance Window/Objective with a reviewed timeframe and at least one eligible Task.
- **Trigger/preconditions:** One or more eligible Tasks and intended timeframe exist.
- **Main flow:** select Task(s); define/review Objective interval in Objective timezone; validate no accepted overlap conflict; create Objective; derive contextual SR/RFC/WFM relationships through Tasks.
- **Alternates/failures:** empty Objective prohibited; accepted Objectives cannot overlap; direct mutable SR→Objective relation is not created; eligible untouched manual Objective may later qualify for hard deletion under its own rule.
- **Postconditions/evidence:** stable Objective identity/tracking context, accepted members and envelope.
- **Candidate authority:** `BETA-REQ-0043..0051`, `0168..0169`; Workbench/RFC-WFM contracts.

## UC-031 — Propose automatic Objective grouping from overlapping Task plans
Status: **Goal Seed — Specification Gate pending**
- **Actor:** System.
- **Goal:** Detect future noncancelled scheduled Tasks whose accepted operational plans form a strict transitive overlap group and propose the resulting Objective membership/envelope.
- **Trigger/preconditions:** Accepted eligible Task plans change or are introduced.
- **Main flow:** evaluate strict positive overlap globally; compute connected transitive groups; derive candidate Objective envelope from member plans; present grouping/regrouping proposal rather than silently accepting it.
- **Alternates/failures:** touching boundaries without positive overlap do not merge; unscheduled/cancelled/ineligible tasks excluded; raw WFM source plan alone cannot trigger authoritative grouping.
- **Postconditions/evidence:** reviewed grouping proposal with affected Tasks/Objectives and rationale.
- **Candidate authority:** `BETA-REQ-0048`, `0157..0158`, `0166`, `0172`; Workbench/RFC-WFM contracts.

## UC-032 — Review, reassign, or regroup Objective membership
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Accept or deliberately adjust proposed Task/Objective grouping while preserving non-overlap and Task-plan authority.
- **Trigger/preconditions:** Grouping/regrouping proposal or existing Objective membership exists.
- **Main flow:** inspect members/envelopes/conflicts; accept proposal or reassign eligible Tasks; revalidate global overlap/non-overlap invariants; commit accepted membership/envelope change.
- **Alternates/failures:** rejection/alternative choice remains bounded and explainable; accepted Objective cannot overlap another; changing Objective membership does not silently rewrite Task plans.
- **Postconditions/evidence:** accepted Objective membership and derived envelope with review history.
- **Candidate authority:** `BETA-REQ-0048..0051`, `0157..0158`, `0168`.

## UC-033 — Execute a Task and record its actual outcome
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Record actual Task execution and one accepted operational outcome without transferring lifecycle authority to Inventory.
- **Trigger/preconditions:** Task is eligible for execution/review.
- **Main flow:** begin/record actual execution evidence as governed; record actual chronology; choose accepted outcome from approved vocabulary; review completion evidence; commit Task outcome; expose resulting physical-consequence work to Inventory where applicable.
- **Alternates/failures:** planned interval remains separate from actual; WFM provider Complete does not prove local outcome; Inventory does not create/override Task outcome; incomplete/failure/cancelled outcomes retain distinct semantics.
- **Postconditions/evidence:** accepted Task actual interval/outcome/history.
- **Candidate authority:** `BETA-REQ-0050`, `0087..0088`, `0167`, `0171`; Workbench/Inventory contracts.

## UC-034 — Review or correct a Task execution/outcome record
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Correct erroneous accepted execution/outcome evidence without erasing prior evidence or reusing retry identity.
- **Trigger/preconditions:** Accepted Task execution/outcome exists and correction is justified.
- **Main flow:** target exact disputed event/fact; review correction reason/impact; append correction/supersession as governed; recompute current Task/Objective/Inventory projections from accepted corrected truth.
- **Alternates/failures:** correction is not retry; physical Inventory consequences require their own exact-event/relationship corrections where affected; exact reason/state mechanics remain `O-003`.
- **Postconditions/evidence:** original and corrective evidence preserved; current projections consistent.
- **Candidate authority:** `BETA-REQ-0050`, `0088`, `0167`; `O-003` boundary.

## UC-035 — Retry operational work as a new Task attempt
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Retry work after an outcome requiring another attempt while preserving immutable predecessor history.
- **Trigger/preconditions:** Prior Task attempt exists and retry is eligible.
- **Main flow:** invoke retry; create new Task identity (new Local Task ID or new WFM Task No as applicable); establish predecessor/successor lineage; plan/schedule new attempt normally; let Objective membership derive through accepted plans.
- **Alternates/failures:** prior Task is never cloned/reopened/reused; retry does not inherit actual execution as truth; new attempt may end in a different Objective.
- **Postconditions/evidence:** new Task attempt plus immutable lineage to predecessor.
- **Candidate authority:** `BETA-REQ-0046`, `0156`, `0166..0167`, `0170`.

## UC-036 — Cancel eligible operational work
Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Cancel an eligible Task/WFM/Objective operation using its owning lifecycle without conflating cancellation with archival or hard deletion.
- **Trigger/preconditions:** Target operational record is eligible for a supported cancellation action.
- **Main flow:** select cancellation action; inspect current execution/membership/dependency consequence; revalidate eligibility; confirm governed cancellation; update derived Objective/Task projections without deleting protected history.
- **Alternates/failures:** started/executed evidence may constrain cancellation semantics; cancellation never becomes hard deletion; rejected/stale action changes nothing; provider Plan Cancel evidence remains distinct from locally accepted cancellation where contracts distinguish them.
- **Postconditions/evidence:** accepted cancelled state/consequence with preserved prior evidence and audit.
- **Candidate authority:** `BETA-REQ-0046..0050`, `0155..0158`, `0166..0172`; Workbench/RFC-WFM contracts.

## UC-037 — Confirm the local RFC terminal cascade
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Deliberately execute the local consequences of accepted RFC terminal evidence after reviewing exact impact.
- **Trigger/preconditions:** RFC has accepted terminal source evidence and a pending cascade proposal.
- **Main flow:** inspect exact RFC/WFM/local-work/Communication membership and impact; perform required deliberate confirmation/hold; freshly revalidate; execute all-or-nothing local cascade according to accepted scope; only then remove RFC direct Communication links.
- **Alternates/failures:** source terminal acceptance alone never executes cascade; stale membership blocks/requires refreshed review; import/auto-accept cannot bypass confirmation; unrelated records remain untouched.
- **Postconditions/evidence:** confirmed cascade event, affected local state, Communication unlink consequences and audit/history.
- **Candidate authority:** `BETA-REQ-0149`, `0161`, `0176`; RFC/WFM/Communications/UI contracts.

## UC-082 — Archive or reactivate eligible operational work records
Status: **Goal Seed — extracted from former UC-036 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Remove eligible operational records from active selection through reversible/history-preserving archival, and reactivate them when the owning lifecycle permits.
- **Trigger/preconditions:** Record supports archival/reactivation and dependency constraints are satisfied.
- **Main flow:** inspect dependencies and active relationships; archive or reactivate exact record; preserve immutable identity/history; update active selectors/projections without deleting evidence.
- **Alternates/failures:** archival cannot strand protected active dependencies; archival does not cascade unless owning authority explicitly says so; reactivation is explicit and audited.
- **Postconditions/evidence:** current active/archive state plus preserved lifecycle history.
- **Candidate authority:** `BETA-REQ-0019`, `0025`, applicable `0153..0155`; Product/RFC-WFM contracts.

## UC-083 — Hard-delete an untouched eligible manual operational record
Status: **Goal Seed — extracted from former UC-036 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Permanently remove only an untouched manually created operational record when the narrow accepted deletion rule allows it.
- **Trigger/preconditions:** Manual target is independently eligible for hard deletion and has no imported/adopted/executed/protected dependent history.
- **Main flow:** inspect exact target/dependencies; show destructive impact preview; freshly revalidate deletion eligibility; confirm; delete transactionally; retain only the minimized audit evidence allowed by the governing retention rule.
- **Alternates/failures:** any protected/imported/executed/dependent history blocks hard deletion and redirects to lifecycle/correction behavior; stale preview blocks execution; failure rolls back.
- **Postconditions/evidence:** eligible target removed without orphaning protected state; required non-reconstructable audit evidence preserved.
- **Candidate authority:** `BETA-REQ-0019`, applicable `0153..0155`; Product/RFC-WFM/UI contracts.
