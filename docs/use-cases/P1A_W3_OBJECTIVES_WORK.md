# P1A-W3 — Objectives & Operational Work Use Cases

Status: **Draft catalogue; UC-027..UC-037 pending owner review**

## UC-027 — Create a Local Task
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Create a locally owned Task with its own identity and optional business relationships, without fabricating WFM/provider identity.
- **Trigger/preconditions:** Operator needs a work item; optional SR/RFC/Spare Unit/NE context may exist.
- **Main flow:** create Local Task; assign name/context; optionally link zero-many SRs, master/subordinate RFCs, Spare Part Units and Network Elements; leave unscheduled or establish operational plan; save.
- **Alternates/failures:** no fake TK; link validation preserves domain cardinality; task under Objective may initialize from Objective context but retains independent Task plan authority.
- **Postconditions/evidence:** stable Local Task identity and accepted relationships.
- **Authority:** `BETA-REQ-0024`, `0043..0046`, `0155`, `0166`.

## UC-028 — Maintain Task relationships and work context
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Add/remove permitted Task links while preserving the distinction between Local and WFM ownership.
- **Trigger/preconditions:** Task exists.
- **Main flow:** inspect current SR/RFC/spare-unit/NE links; edit eligible Local Task links; for WFM preserve exactly one RFC owner while deriving master/subordinate role/context; save reviewed relationship changes.
- **Alternates/failures:** WFM cannot gain arbitrary SR/spare/NE ownership; direct SR↔RFC master rules remain independent from Local Task subordinate links; history preserved.
- **Postconditions/evidence:** accepted relationships with audit/history.
- **Authority:** `BETA-REQ-0024`, `0039..0041`, `0044..0046`, `0163`, `0166`.

## UC-029 — Plan, schedule, or unschedule a Task
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Establish or change the accepted operational Task plan independently from WFM source evidence and actual execution.
- **Trigger/preconditions:** Task exists.
- **Main flow:** review current source-plan/Task-plan context; set or clear accepted Task planned interval where allowed; interpret schedule in selected Objective timezone; submit material plan change for any required Objective regrouping review.
- **Alternates/failures:** unscheduled Task has no Objective; raw WFM plan is only a candidate; changing Task plan does not fabricate actual execution; accepted Objective cannot silently overwrite established Task plan.
- **Postconditions/evidence:** accepted operational Task plan or explicit unscheduled state.
- **Authority:** `BETA-REQ-0047..0050`, `0156..0158`, `0166`, `0172`, `0177`.

## UC-030 — Create an Objective manually
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Create a Maintenance Window/Objective with a reviewed timeframe and at least one eligible Task.
- **Trigger/preconditions:** One or more eligible Tasks and intended timeframe exist.
- **Main flow:** select Task(s); define/review Objective interval in Objective timezone; validate no accepted overlap conflict; create Objective; derive contextual SR/RFC/WFM relationships through Tasks.
- **Alternates/failures:** empty Objective prohibited; accepted Objectives cannot overlap; direct mutable SR→Objective relation is not created; eligible untouched manual Objective may later qualify for hard deletion.
- **Postconditions/evidence:** stable Objective identity/tracking context, accepted members and envelope.
- **Authority:** `BETA-REQ-0007`, `0043..0051`, `0168..0169`.

## UC-031 — Propose automatic Objective grouping from overlapping Task plans
Status: **Draft — pending owner review**
- **Actor:** System.
- **Goal:** Detect future noncancelled scheduled Tasks whose accepted operational plans form a strict transitive overlap group and propose the resulting Objective membership/envelope.
- **Trigger/preconditions:** Accepted eligible Task plans change or are introduced.
- **Main flow:** evaluate strict positive overlap globally; compute connected transitive groups; derive candidate Objective envelope from member plans; present grouping/regrouping proposal rather than silently accepting it.
- **Alternates/failures:** touching boundaries without positive overlap do not merge; unscheduled/cancelled/ineligible tasks excluded; raw WFM source plan alone cannot trigger authoritative grouping.
- **Postconditions/evidence:** reviewed grouping proposal with affected Tasks/Objectives and rationale.
- **Authority:** `BETA-REQ-0038`, `0048`, `0157..0158`, `0166`, `0172`.

## UC-032 — Review, reassign, or regroup Objective membership
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Accept or deliberately adjust proposed Task/Objectives grouping while preserving non-overlap and Task-plan authority.
- **Trigger/preconditions:** Grouping/regrouping proposal or existing Objective membership exists.
- **Main flow:** inspect members/envelopes/conflicts; accept proposal or reassign eligible Tasks; revalidate global overlap/non-overlap invariants; commit accepted membership/envelope change.
- **Alternates/failures:** rejection/alternative choice remains bounded and explainable; accepted Objective cannot overlap another; changing Objective membership does not silently rewrite Task plans.
- **Postconditions/evidence:** accepted Objective membership and derived envelope with review history.
- **Authority:** `BETA-REQ-0048..0051`, `0157..0158`, `0168`.

## UC-033 — Execute a Task and record its actual outcome
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Record actual Task execution and one accepted operational outcome without transferring lifecycle authority to Inventory.
- **Trigger/preconditions:** Task is eligible for execution/review.
- **Main flow:** begin/record actual execution evidence as governed; record actual chronology; choose accepted outcome from approved vocabulary; review completion evidence; commit Task outcome; expose resulting physical-consequence work to Inventory where applicable.
- **Alternates/failures:** planned interval remains separate from actual; WFM provider Complete does not prove local outcome; Inventory does not create/override Task outcome; incomplete/failure/cancelled outcomes retain distinct semantics.
- **Postconditions/evidence:** accepted Task actual interval/outcome/history.
- **Authority:** `BETA-REQ-0050`, `0087..0088`, `0167`, `0171`; Workbench/Inventory contracts.

## UC-034 — Review or correct a Task execution/outcome record
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Correct erroneous accepted execution/outcome evidence without erasing prior evidence or reusing retry identity.
- **Trigger/preconditions:** Accepted Task execution/outcome exists and correction is justified.
- **Main flow:** target exact disputed event/fact; review correction reason/impact; append correction/supersession as governed; recompute current Task/Objective/Inventory projections from accepted corrected truth.
- **Alternates/failures:** correction is not retry; physical Inventory consequences require their own exact-event/relationship corrections where affected; exact reason/state mechanics remain `O-003`.
- **Postconditions/evidence:** original and corrective evidence preserved; current projections consistent.
- **Authority:** `BETA-REQ-0050`, `0088`, `0167`; `O-003` boundary.

## UC-035 — Retry operational work as a new Task attempt
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Retry work after an outcome requiring another attempt while preserving immutable predecessor history.
- **Trigger/preconditions:** Prior Task attempt exists and retry is eligible.
- **Main flow:** invoke retry; create new Task identity (new Local Task ID or new WFM Task No as applicable); establish predecessor/successor lineage; plan/schedule new attempt normally; let Objective membership derive through accepted plans.
- **Alternates/failures:** prior Task is never cloned/reopened/reused; retry does not inherit actual execution as truth; new attempt may end in a different Objective.
- **Postconditions/evidence:** new Task attempt plus immutable lineage to predecessor.
- **Authority:** `BETA-REQ-0046`, `0156`, `0166..0167`, `0170`.

## UC-036 — Cancel, archive, or delete eligible operational work records
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Remove work from active operation using the correct history-preserving lifecycle or narrow hard-deletion rule.
- **Trigger/preconditions:** RFC/WFM/Objective/Task record qualifies for a supported action.
- **Main flow:** choose cancel/archive/delete action; inspect dependencies and consequence preview; revalidate eligibility; execute accepted transition; preserve independent records/history.
- **Alternates/failures:** hard deletion only for independently eligible untouched manual records with no protected/adopted evidence; archive is reversible/noncascading unless owning contract says otherwise; rejected action changes nothing.
- **Postconditions/evidence:** correct active/historical state and audit trail.
- **Authority:** `BETA-REQ-0025`, `0027`, `0153..0155`; Product/RFC-WFM contracts.

## UC-037 — Confirm the local RFC terminal cascade
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Deliberately execute the local consequences of accepted RFC terminal evidence after reviewing exact impact.
- **Trigger/preconditions:** RFC has accepted terminal source evidence and a pending cascade proposal.
- **Main flow:** inspect exact RFC/WFM/local-work/Communication membership and impact; perform required deliberate confirmation/hold; freshly revalidate; execute all-or-nothing local cascade according to accepted scope; only then remove RFC direct Communication links.
- **Alternates/failures:** source terminal acceptance alone never executes cascade; stale membership blocks/requires refreshed review; import/auto-accept cannot bypass confirmation; unrelated records remain untouched.
- **Postconditions/evidence:** confirmed cascade event, affected local state, Communication unlink consequences and audit/history.
- **Authority:** `BETA-REQ-0149`, `0161`, `0176`; RFC/WFM/Communications/UI contracts.
