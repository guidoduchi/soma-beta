# P1A-W4 — Inventory Use Cases

Status: **P1A-002 Rework — Goal Seeds pending Specification Gate; owner review paused**

## UC-038 — Record a faulty Device Part and create/contribute to a Spare Need
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Record the actual faulty component under an SR/device context and contribute its demand to the correct SR-level Spare Need.
- **Trigger/preconditions:** SR and operational Device Reference context exist; faulty component is known enough to record.
- **Main flow:** create/update Device Part Unit with BOM/serial/slot/condition/chronology as known; preserve Device Reference context; locate/create matching Spare Need within same SR by BOM; add contributor relationship; derive contributor count.
- **Alternates/failures:** unknown slot/serial allowed; same BOM across different SRs never merges; planned quantity remains operator-governed and is not overwritten by contributor changes.
- **Postconditions/evidence:** stable Device Part Unit and Spare Need contributor history.
- **Candidate authority:** `BETA-REQ-0079..0080`; Inventory Contract.

## UC-039 — Manage a Spare Need through its lifecycle
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Maintain, reuse, resolve/cancel/reactivate, or remove a Spare Need without losing prior fulfillment history.
- **Trigger/preconditions:** Spare Need exists.
- **Main flow:** review contributor/planned/allocated quantities; edit allowed planning quantity; reuse Need in multiple local/external attempts; resolve/cancel/reactivate with reason; remove/delete only when eligibility permits.
- **Alternates/failures:** active associated Spare Request blocks removal; all associated requests must be confirmed cancelled/rejected for history-preserving removal; hard delete only untouched manual Need with no contributor/allocation/import/protected evidence.
- **Postconditions/evidence:** stable Need identity/lifecycle and append-oriented allocation history.
- **Candidate authority:** `BETA-REQ-0079`, `0081`; Inventory Contract.

## UC-040 — Review Stock suggestions and choose a fulfillment strategy
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Decide whether a Spare Need will be fulfilled locally, externally, or by a mixture of both after seeing compatible Stock suggestions.
- **Trigger/preconditions:** Active Spare Need and relevant Device Reference context.
- **Main flow:** inspect compatible available Stock suggestions; compare planned quantity and local availability; choose local quantity, external quantity, or both; allow deliberate external request even with local stock.
- **Alternates/failures:** suggestions are side-effect free and never reserve/consume automatically; incompatible/unavailable Stock is not suggested as fulfillment; choice preserves Need/Device Reference/unit identities.
- **Postconditions/evidence:** reviewed fulfillment intent only; no physical state changes until allocation/request actions.
- **Candidate authority:** `BETA-REQ-0080..0081`; Inventory Contract.

## UC-041 — Allocate or release local Stock for planned work
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Explicitly reserve eligible physical Stock units against a Spare Need/Task context and release/correct allocations safely.
- **Trigger/preconditions:** Eligible available Spare Part Unit and demand context exist.
- **Main flow:** select exact physical unit(s); validate compatibility/availability; create governed allocation/reservation; link relevant Need/Task context; later release/correct if eligible.
- **Alternates/failures:** suggestion alone never allocates; same unit cannot be simultaneously consumed inconsistently; correction targets exact relationship/event and preserves history.
- **Postconditions/evidence:** physical unit reservation/allocation state and history.
- **Candidate authority:** `BETA-REQ-0080`, `0086..0088`, `0090`, `0092`; Inventory Contract.

## UC-042 — Prepare a Spare Request draft
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Build one local Spare Request from selected Needs belonging to one SR with explicit recipient/logistics context before actual submission.
- **Trigger/preconditions:** One or more selected Spare Needs under same SR.
- **Main flow:** create persistent Spare Request and temporary tracking ID; allocate Needs/quantities; derive governing SR/Customer; choose recipient Contact; choose delivery/self-pickup and required location; review planned/local/external quantities; save editable draft.
- **Alternates/failures:** Needs from different SRs cannot combine; unresolved Customer remains unresolved; recipient owner suggestion is not forced; weak similarity never silently merges requests.
- **Postconditions/evidence:** editable request draft with immutable internal/temp identities and reviewed allocations/context.
- **Candidate authority:** `BETA-REQ-0014`, `0032`, `0082..0083`, `0091`; Inventory Contract.

## UC-043 — Generate a Spare Request MSG draft
Status: **Merged/retired before acceptance by P1A-002 → `UC-069`**

This Goal Seed duplicated the common MSG-generation actor goal. Spare Request-specific preconditions/content and the invariants **Generate MSG ≠ Send** and **Generate MSG ≠ Submit Spare Request** remain mandatory acceptance scenarios under `UC-069` and the Spare Request workflow. `UC-043` was never accepted and is not reused.

## UC-044 — Register a Spare Request that was initiated outside SOMA
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Bring an externally prepared/submitted spare request into SOMA without inventing missing history or losing its real-world origin.
- **Trigger/preconditions:** External request exists; governing SR/Need context can be reviewed/reconciled.
- **Main flow:** create local Spare Request identity/temp tracking if needed; reconcile to one SR and selected Needs; capture known submission/request context; mark external-origin evidence; continue normal response/RMA lifecycle.
- **Alternates/failures:** missing information remains unknown; weak matching never silently merges; manual reconciliation preserves exact record identity.
- **Postconditions/evidence:** locally tracked request with external-origin and reconciliation history.
- **Candidate authority:** `BETA-REQ-0014`, `0082..0083`, `0091..0092`; Inventory Contract.

## UC-045 — Accept actual Spare Request submission
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Record that the real request was actually submitted and freeze the exact request evidence relevant at that moment.
- **Trigger/preconditions:** Draft/request exists with valid allocations and required recipient/logistics context.
- **Main flow:** review submission payload/context; confirm actual submission from accepted sent evidence or explicit manual confirmation as governed; freeze allocations, requested part facts, recipient, logistics and tracking snapshot; start response-wait timing from accepted submission; retain later responses separately.
- **Alternates/failures:** saving/generating MSG does not submit; false submission can be corrected under exact-event rules; later source/provider response cannot rewrite frozen request snapshot.
- **Postconditions/evidence:** immutable accepted submission evidence and active request-response lifecycle.
- **Candidate authority:** `BETA-REQ-0083`, `0089`, `0091`, `0093`; Inventory/Communications contracts.

## UC-046 — Reconcile provider response and RMA obligations
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Apply incremental provider response evidence to the exact Spare Request and create/update per-position C10 obligations without fabricating units.
- **Trigger/preconditions:** Submitted Spare Request; response evidence/manual input available.
- **Main flow:** reconcile response to exact request; assign official SR7 when available; create/update `M ≤ N` RMA positions with C10 identities/outcomes; autoassign compatible positions to unassigned Device Part Units in stable order; allow audited redistribution where needed.
- **Alternates/failures:** rejected/unfulfilled positions remain explicit; incremental batches continue sequence; RMA is obligation, not physical unit; mismatched/ambiguous response requires review.
- **Postconditions/evidence:** official request/RMA identities, outcomes, target relationships and source/manual history.
- **Candidate authority:** `BETA-REQ-0014..0015`, `0083..0084`, `0089`, `0091..0093`; Inventory/Communications contracts.

## UC-047 — Record inbound spare dispatch, receipt, and physical unit identity
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Track promised/dispatched/received inbound replacement material and register the actual physical Spare Part Unit separately from the RMA obligation.
- **Trigger/preconditions:** RMA position exists; logistics/receipt event occurs.
- **Main flow:** record requested-versus-actual logistics milestones; on receipt create/link exact inbound unit with local identity, actual BOM and optional serial; evaluate valid alternative vs invalid/incompatible material; preserve custody/condition.
- **Alternates/failures:** actual BOM may differ from requested; valid alternative needs reviewed compatibility; invalid unit cannot be installed; one RMA links at most one direct inbound unit.
- **Postconditions/evidence:** inbound physical unit and logistics/receipt history.
- **Candidate authority:** `BETA-REQ-0015..0016`, `0020`, `0084..0086`, `0088..0093`; Inventory Contract.

## UC-048 — Allocate a Spare Part Unit to a Task
Status: **Goal Seed — Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Bind an exact eligible physical spare unit to planned maintenance work without claiming it was installed.
- **Trigger/preconditions:** Task and eligible physical unit exist.
- **Main flow:** select Task and exact unit; validate current eligibility/compatibility; create Task-to-unit allocation; preserve originating Need/Request/RMA context by relationships where applicable.
- **Alternates/failures:** allocation is not consumption/installation; manual unit may be allocated with required warning; stale/ineligible unit blocks allocation.
- **Postconditions/evidence:** accepted Task/unit allocation and history.
- **Candidate authority:** `BETA-REQ-0086..0088`, `0090`, `0166..0167`; Inventory/Workbench contracts.

## UC-049 — Record reviewed physical maintenance consequences
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Record Inventory-owned installed/removed/unused/faulty/incompatible/dismantled physical consequences from an already reviewed Task outcome.
- **Trigger/preconditions:** Task lifecycle has accepted relevant outcome/execution evidence; physical units/context exist.
- **Main flow:** consume reviewed Task outcome context; identify actual installed and removed units; record accepted physical consequence and unit state/history; derive which physical unit satisfies each RMA return obligation.
- **Alternates/failures:** Inventory cannot create/override Task outcome; requested vs actual BOM/serial remain distinct; dismantled assemblies/components retain separate identities/dispositions.
- **Postconditions/evidence:** authoritative Inventory physical consequence/history and RMA return-unit selection.
- **Candidate authority:** `BETA-REQ-0085..0088`, `0090`, `0092..0093`, `0167`; Inventory/Workbench contracts.

## UC-050 — Create and submit a Fault Tag return
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Group eligible open return obligations/physical units into a Fault Tag and submit the real return with correct pickup-origin evidence when applicable.
- **Trigger/preconditions:** One or more open RMA return obligations with selected physical return units.
- **Main flow:** create tag with immutable internal/visible identities; add memberships each referencing one RMA + one unit; choose return method; for pickup select Dispatch Location origin and freeze snapshot at first submission; review and submit actual tag.
- **Alternates/failures:** membership may cross SR/Spare Request/RMA origins; non-pickup fabricates no pickup snapshot; condition/newness/BOM/serial alone never determines eligibility; draft membership remains editable before submission.
- **Postconditions/evidence:** submitted Fault Tag and immutable submitted membership/logistics snapshot.
- **Candidate authority:** `BETA-REQ-0020`, `0023`, `0094..0097`; Inventory Contract.

## UC-051 — Process Fault Tag warehouse receipt and final decision
Status: **Goal Seed — authority corrected by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Record warehouse receipt separately from per-membership final acceptance/rejection and close or continue each RMA obligation correctly.
- **Trigger/preconditions:** Submitted Fault Tag membership exists.
- **Main flow:** record warehouse receipt for applicable membership; review returned unit/evidence; explicitly accept or reject final disposition; acceptance closes RMA return obligation; rejection leaves it unresolved for resend.
- **Alternates/failures:** warehouse receipt is not final acceptance; partial membership processing valid; Communication evidence optional; decision requires explicit confirmation.
- **Postconditions/evidence:** per-membership warehouse/final-decision history and RMA obligation state.
- **Candidate authority:** `BETA-REQ-0097`, `0099`, `0101`; Inventory Contract.

## UC-052 — Correct an accepted Inventory event or relationship
Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Actor:** Local Administrator.
- **Goal:** Correct an erroneous accepted Inventory event or relationship by targeting the exact disputed fact without erasing the original evidence or converting genuine lifecycle transitions into corrections.
- **Trigger/preconditions:** Accepted Inventory event/relationship exists and correction is justified.
- **Main flow:** target exact identity/event/relationship; inspect original/current consequence; provide governed correction/reason; append correction/supersession; recompute current Inventory projection while preserving unaffected records.
- **Alternates/failures:** rejection/resend is not correction; materially wrong submitted Fault Tag may require replacement lineage; Task outcome itself is corrected only by Objectives/Task lifecycle; stale target requires refreshed review.
- **Postconditions/evidence:** corrected current projection with immutable original/correction history.
- **Candidate authority:** `BETA-REQ-0088`, `0090`, `0092..0093`, `0101`; Inventory Contract.

## UC-084 — Register a manual Spare Part Unit
Status: **Goal Seed — added by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Register a real local/legacy/installed/removed/extracted/scrapped Spare Part Unit even when official Spare Request, RMA, or manufacturer serial provenance is unavailable.
- **Trigger/preconditions:** A physical Inventory unit needs to be represented locally.
- **Main flow:** create immutable `LSU-########` identity; record actual BOM and optional manufacturer serial; record origin/custody/condition/disposition independently; optionally attach valid origin-RMA provenance later; derive Stock eligibility from accepted lifecycle facts.
- **Alternates/failures:** missing serial/provenance does not invalidate local unit; an RMA may be attached only consistently with its parent Spare Request; later provenance never replaces LSU identity/history; incompatible/invalid relationships are rejected.
- **Postconditions/evidence:** stable physical unit identity, current physical facts and append-oriented provenance/lifecycle history.
- **Candidate authority:** `BETA-REQ-0016`, `0085..0086`, `0090`, `0092`; Inventory Contract.

## UC-085 — Cancel an eligible Spare Request
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Cancel a Spare Request only through its accepted lifecycle while preserving submission/response/RMA history and dependent Need allocation history.
- **Candidate authority:** `BETA-REQ-0081..0084`, `0091..0093`; Inventory Contract.

## UC-086 — Cancel an eligible Fault Tag
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Cancel an eligible Fault Tag/return attempt without erasing memberships, submission evidence, or independent RMA/unit identity.
- **Candidate authority:** `BETA-REQ-0094..0101`; Inventory Contract.

## UC-087 — Replace a materially incorrect submitted Fault Tag
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Supersede a materially incorrect submitted Fault Tag with a correction replacement while preserving linear replacement lineage and the original submitted evidence.
- **Candidate authority:** `BETA-REQ-0097..0098`, `0101`; Inventory Contract.

## UC-088 — Resend a rejected Fault Tag return
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Create a new resend attempt after warehouse rejection while preserving the genuine prior submission/receipt/rejection history and keeping resend distinct from correction replacement.
- **Candidate authority:** `BETA-REQ-0097`, `0099..0101`; Inventory Contract.

## UC-089 — Archive or reactivate an eligible Inventory record
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Move an eligible Inventory record out of or back into active operation using history-preserving archival/reactivation without deleting protected evidence.
- **Candidate authority:** `BETA-REQ-0019`, applicable `0081..0101`; Inventory Contract.

## UC-090 — Hard-delete an untouched eligible Inventory record
Status: **Goal Seed — extracted from former UC-052 by P1A-002**
- **Actor:** Local Administrator.
- **Goal:** Permanently remove only an untouched manually created Inventory draft/Need/other record when its exact domain deletion rule permits hard deletion.
- **Candidate authority:** `BETA-REQ-0019`, `0081`, applicable Inventory deletion families; Inventory/UI contracts.
