# P1A-W4 — Inventory Use Cases

Status: **Draft catalogue; UC-038..UC-052 pending owner review**

## UC-038 — Record a faulty Device Part and create/contribute to a Spare Need
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Record the actual faulty component under an SR/device context and contribute its demand to the correct SR-level Spare Need.
- **Trigger/preconditions:** SR and operational Device context exist; faulty component is known enough to record.
- **Main flow:** create/update Device Part Unit with BOM/serial/slot/condition/chronology as known; preserve Device context; locate/create matching Spare Need within same SR by BOM; add contributor relationship; derive contributor count.
- **Alternates/failures:** unknown slot/serial allowed; same BOM across different SRs never merges; planned quantity remains operator-governed and is not overwritten by contributor changes.
- **Postconditions/evidence:** stable Device Part Unit and Spare Need contributor history.
- **Authority:** `BETA-REQ-0079..0080`; Inventory Contract.

## UC-039 — Manage a Spare Need through its lifecycle
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Maintain, reuse, resolve/cancel/reactivate, or remove a Spare Need without losing prior fulfillment history.
- **Trigger/preconditions:** Spare Need exists.
- **Main flow:** review contributor/planned/allocated quantities; edit allowed planning quantity; reuse Need in multiple local/external attempts; resolve/cancel/reactivate with reason; remove/delete only when eligibility permits.
- **Alternates/failures:** active associated Spare Request blocks removal; all associated requests must be confirmed cancelled/rejected for history-preserving removal; hard delete only untouched manual Need with no contributor/allocation/import/protected evidence.
- **Postconditions/evidence:** stable Need identity/lifecycle and append-oriented allocation history.
- **Authority:** `BETA-REQ-0079`, `0081`; Inventory Contract.

## UC-040 — Review Stock suggestions and choose a fulfillment strategy
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Decide whether a Spare Need will be fulfilled locally, externally, or by a mixture of both after seeing compatible Stock suggestions.
- **Trigger/preconditions:** Active Spare Need and relevant Device context.
- **Main flow:** inspect compatible available Stock suggestions; compare planned quantity and local availability; choose local quantity, external quantity, or both; allow deliberate external request even with local stock.
- **Alternates/failures:** suggestions are side-effect free and never reserve/consume automatically; incompatible/unavailable Stock is not suggested as fulfillment; choice preserves Need/Device identities.
- **Postconditions/evidence:** reviewed fulfillment intent only; no physical state changes until allocation/request actions.
- **Authority:** `BETA-REQ-0080..0081`.

## UC-041 — Allocate or release local Stock for planned work
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Explicitly reserve eligible physical Stock units against a Spare Need/Task context and release/correct allocations safely.
- **Trigger/preconditions:** Eligible available Spare Part Unit and demand context exist.
- **Main flow:** select exact physical unit(s); validate compatibility/availability; create governed allocation/reservation; link relevant Need/Task context; later release/correct if eligible.
- **Alternates/failures:** suggestion alone never allocates; same unit cannot be simultaneously consumed inconsistently; correction targets exact relationship/event and preserves history.
- **Postconditions/evidence:** physical unit reservation/allocation state and history.
- **Authority:** `BETA-REQ-0080`, `0086..0088`, `0090`, `0092`.

## UC-042 — Prepare a Spare Request draft
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Build one local Spare Request from selected Needs belonging to one SR with explicit recipient/logistics context before actual submission.
- **Trigger/preconditions:** One or more selected Spare Needs under same SR.
- **Main flow:** create persistent Spare Request and temporary tracking ID; allocate Needs/quantities; derive governing SR/Customer; choose recipient Contact; choose delivery/self-pickup and required location; review planned/local/external quantities; save editable draft.
- **Alternates/failures:** Needs from different SRs cannot combine; unresolved Customer remains unresolved; recipient owner suggestion is not forced; weak similarity never silently merges requests.
- **Postconditions/evidence:** editable request draft with immutable internal/temp identities and reviewed allocations/context.
- **Authority:** `BETA-REQ-0014`, `0082..0083`, `0091`.

## UC-043 — Generate a Spare Request MSG draft
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Generate a local `.msg` draft from the current reviewed Spare Request without treating generation as sending/submission evidence.
- **Trigger/preconditions:** Request draft contains the required communication recipient/context.
- **Main flow:** validate action-specific Contact channel; generate MSG with temporary tracking identity and request facts; persist/export according to accepted MSG behavior; present artifact to operator.
- **Alternates/failures:** missing recipient channel blocks this action only; generation does not start response timer, freeze submission, or prove sending; external file remains operator-managed.
- **Postconditions/evidence:** generated MSG draft identity/history; Spare Request remains Draft unless separately submitted.
- **Authority:** `BETA-REQ-0067`, `0082..0083`, `0091`, `0111..0122`; Inventory/Communications contracts.

## UC-044 — Register a Spare Request that was initiated outside SOMA
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Bring an externally prepared/submitted spare request into SOMA without inventing missing history or losing its real-world origin.
- **Trigger/preconditions:** External request exists; governing SR/Need context can be reviewed/reconciled.
- **Main flow:** create local Spare Request identity/temp tracking if needed; reconcile to one SR and selected Needs; capture known submission/request context; mark external-origin evidence; continue normal response/RMA lifecycle.
- **Alternates/failures:** missing information remains unknown; weak matching never silently merges; manual reconciliation preserves exact record identity.
- **Postconditions/evidence:** locally tracked request with external-origin and reconciliation history.
- **Authority:** `BETA-REQ-0091`, `0092`.

## UC-045 — Accept actual Spare Request submission
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Record that the real request was actually submitted and freeze the exact request evidence relevant at that moment.
- **Trigger/preconditions:** Draft/request exists with valid allocations and required recipient/logistics context.
- **Main flow:** review submission payload/context; confirm actual submission; freeze allocations, requested part facts, recipient, logistics and tracking snapshot; start response-wait timing from accepted submission; retain later responses separately.
- **Alternates/failures:** saving/generating MSG does not submit; false submission can be corrected under exact-event rules; later source/provider response cannot rewrite frozen request snapshot.
- **Postconditions/evidence:** immutable accepted submission evidence and active request-response lifecycle.
- **Authority:** `BETA-REQ-0083`, `0089`, `0091`, `0093`.

## UC-046 — Reconcile provider response and RMA obligations
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Apply incremental provider response evidence to the exact Spare Request and create/update per-position C10 obligations without fabricating units.
- **Trigger/preconditions:** Submitted Spare Request; response evidence/manual input available.
- **Main flow:** reconcile response to exact request; assign official SR7 when available; create/update `M ≤ N` RMA positions with C10 identities/outcomes; autoassign compatible positions to unassigned Device Part Units in stable order; allow audited redistribution where needed.
- **Alternates/failures:** rejected/unfulfilled positions remain explicit; incremental batches continue sequence; RMA is obligation, not physical unit; mismatched/ambiguous response requires review.
- **Postconditions/evidence:** official request/RMA identities, outcomes, target relationships and source/manual history.
- **Authority:** `BETA-REQ-0014..0015`, `0028`, `0084`, `0094`.

## UC-047 — Record inbound spare dispatch, receipt, and physical unit identity
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Track promised/dispatched/received inbound replacement material and register the actual physical Spare Part Unit separately from the RMA obligation.
- **Trigger/preconditions:** RMA position exists; logistics/receipt event occurs.
- **Main flow:** record requested-versus-actual logistics milestones; on receipt create/link exact inbound unit with local identity, actual BOM and optional serial; evaluate valid alternative vs invalid/incompatible material; preserve custody/condition.
- **Alternates/failures:** actual BOM may differ from requested; valid alternative needs reviewed compatibility; invalid unit cannot be installed; one RMA links at most one direct inbound unit.
- **Postconditions/evidence:** inbound physical unit and logistics/receipt history.
- **Authority:** `BETA-REQ-0015..0016`, `0036`, `0067`, `0084..0086`, `0093`.

## UC-048 — Allocate a Spare Part Unit to a Task
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Bind an exact eligible physical spare unit to planned maintenance work without claiming it was installed.
- **Trigger/preconditions:** Task and eligible physical unit exist.
- **Main flow:** select Task and exact unit; validate current eligibility/compatibility; create Task-to-unit allocation; preserve originating Need/Request/RMA context by relationships where applicable.
- **Alternates/failures:** allocation is not consumption/installation; manual unit may be allocated with required warning; stale/ineligible unit blocks allocation.
- **Postconditions/evidence:** accepted Task/unit allocation and history.
- **Authority:** `BETA-REQ-0086..0088`, `0090`, `0166..0167`.

## UC-049 — Record reviewed physical maintenance consequences
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Record Inventory-owned installed/removed/unused/faulty/incompatible/dismantled physical consequences from an already reviewed Task outcome.
- **Trigger/preconditions:** Task lifecycle has accepted relevant outcome/execution evidence; physical units/context exist.
- **Main flow:** consume reviewed Task outcome context; identify actual installed and removed units; record accepted physical consequence and unit state/history; derive which physical unit satisfies each RMA return obligation.
- **Alternates/failures:** Inventory cannot create/override Task outcome; requested vs actual BOM/serial remain distinct; dismantled assemblies/components retain separate identities/dispositions.
- **Postconditions/evidence:** authoritative Inventory physical consequence/history and RMA return-unit selection.
- **Authority:** `BETA-REQ-0035..0037`, `0085..0088`, `0092..0096`, `0167`.

## UC-050 — Create and submit a Fault Tag return
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Group eligible open return obligations/physical units into a Fault Tag and submit the real return with correct pickup-origin evidence when applicable.
- **Trigger/preconditions:** One or more open RMA return obligations with selected physical return units.
- **Main flow:** create tag with immutable internal/visible identities; add memberships each referencing one RMA + one unit; choose return method; for pickup select Dispatch Location origin and freeze snapshot at first submission; review and submit actual tag.
- **Alternates/failures:** membership may cross SR/Spare Request/RMA origins; non-pickup fabricates no pickup snapshot; condition/newness/BOM/serial alone never determines eligibility; draft membership remains editable before submission.
- **Postconditions/evidence:** submitted Fault Tag and immutable submitted membership/logistics snapshot.
- **Authority:** `BETA-REQ-0068`, `0097..0100`; Inventory Contract.

## UC-051 — Process Fault Tag warehouse receipt and final decision
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Record warehouse receipt separately from per-membership final acceptance/rejection and close or continue each RMA obligation correctly.
- **Trigger/preconditions:** Submitted Fault Tag membership exists.
- **Main flow:** record warehouse receipt for applicable membership; review returned unit/evidence; explicitly accept or reject final disposition; acceptance closes RMA return obligation; rejection leaves it unresolved for resend.
- **Alternates/failures:** warehouse receipt is not final acceptance; partial membership processing valid; Communication evidence optional; decision requires explicit confirmation.
- **Postconditions/evidence:** per-membership warehouse/final-decision history and RMA obligation state.
- **Authority:** `BETA-REQ-0061..0064`, `0098..0102`.

## UC-052 — Correct, cancel, replace, resend, archive, or delete eligible Inventory records
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Repair Inventory mistakes or advance exception lifecycles using exact history-preserving commands rather than destructive rewrites.
- **Trigger/preconditions:** Inventory event/relationship/request/tag is eligible for a supported correction/removal action.
- **Main flow:** target exact disputed identity/event/relationship; choose correction/cancel/supersede-replace/resend/archive/delete; inspect dependencies/impact; commit governed action; preserve lineage and independent records.
- **Alternates/failures:** false submission may return to Draft only under accepted rule; materially wrong actual Fault Tag submission requires replacement lineage; rejection resend is not correction; hard deletion only untouched eligible drafts/Needs; exported files are not deleted by domain action.
- **Postconditions/evidence:** corrected current projection with immutable original/correction/replacement/resend history.
- **Authority:** `BETA-REQ-0066`, `0081`, `0088..0092`, `0099..0102`; Inventory/UI contracts.
