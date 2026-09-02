# SOMA Beta Inventory Lifecycle Contract

Status: **Foundation review v0.5**  
Target: **SOMA Beta 1.0.0**

## 1. Normative language boundary

- Normative requirements, UI copy, schemas, and documentation shall not name the external provider.
- Use neutral terms such as `external provider`, `official Spare Request identifier`, and `RMA` only where a role must be described.
- The seven-digit Spare Request identifier and C10 RMA are business identifiers, never relational identity.

## 2. Inventory purpose

Inventory exists to maintain traceable Stock of physical Spare Part Units and to accelerate replacement work.

When an SR-level Spare Need exists, SOMA shall first identify compatible, available Stock units for the relevant Devices and parts. The operator may allocate local Stock, start the external Spare Request flow, combine both approaches, or request externally despite available local Stock. Availability is a recommendation, not an automatic consumption decision.

## 3. Correct entity boundaries

### Service Request

- Owns the operational customer context.
- May reference many Devices.
- Owns SR-level Spare Needs.

### Device Part Unit

- Represents one actual component installed in, removed from, or diagnosed under one Device and, when known, one slot.
- Records actual Part Number/BOM code, manufacturer serial when available, condition, and chronology.
- A faulty slot registration creates or identifies the corresponding Device Part Unit.
- It is not a Spare Need and is not an Inventory Spare Part Unit.

### Spare Need

- Belongs to exactly one Service Request, not to exactly one Device.
- Aggregates demand by Part Number/BOM code across the relevant Device Part Units under that Service Request.
- Records BOM, description, and planned quantity.
- Contributor relationships preserve which Device Part Units generated the demand.
- Registering sixty faulty battery units with the same BOM across fifteen Devices produces one SR-level Spare Need with suggested quantity sixty, not sixty duplicate Needs.
- If the Need already exists, later matching Device Part Units contribute to the existing Need rather than create duplicates.
- If matching Device Part Units are registered first, SOMA automatically proposes or creates the aggregated Need.
- SOMA shall preserve the system-derived contributor count separately from any operator-confirmed planned or requested quantity.

### Spare Request

- Is the request/tracking container created from one or more SR-level Spare Needs belonging to the same Service Request.
- Receives SOMA's immutable temporary tracking identifier at creation.
- Inherits Customer Organization context through its Service Request.
- Suggests the Service Request's current customer ticket owner as the customer Contact.
- Captures selected Needs and quantities, delivery or self-pickup mode, receiver, and the applicable dispatch or pickup location.
- The temporary tracking identifier is placed in the generated request email subject, but omission from later correspondence does not prevent manual reconciliation.
- The official identifier is `SR` followed by seven digits and is attached later to the same request.

### RMA

- Uses the official C10 identifier and represents one two-sided obligation position under exactly one officially identified Spare Request.
- Initially represents the external provider's promise that one replacement item will be supplied.
- After receipt and maintenance disposition, it represents the return obligation for the physical item that must be sent back.
- It is the bridge between a target Device Part Unit and a future or received Inventory Spare Part Unit.
- It shall not contain a physical unit as a mutable embedded child record.
- Before physical receipt, it may target a Device Part Unit while its inbound Spare Part Unit relationship remains empty; SOMA shall not fabricate a placeholder physical unit.
- It preserves the promised/authorized BOM independently from the actual inbound and outbound physical-unit identities.
- One RMA may therefore begin with one promised BOM, later link to an inbound unit with its own BOM and serial, and ultimately require return of another unit with a different BOM and serial.

### Spare Part Unit

- Represents one actual physical Inventory unit, separate from the RMA and Device Part Unit.
- Has immutable SOMA identity, actual BOM, optional manufacturer serial, condition, location/custody, and lifecycle history.
- May have zero or one origin RMA and therefore zero or one parent official Spare Request through that RMA.
- A local unit without official provenance remains valid.
- Attaching later RMA provenance never replaces the unit's identity or history.
- One RMA has at most one directly received fulfillment unit.
- If that received unit is an assembly that is dismantled, extracted units become separate Spare Part Units. They may share origin-RMA provenance while the parent assembly remains the single direct fulfillment unit.

### Replacement outcome

- Records what actually occurred during a Task.
- May link one target Device Part Unit, one installed Spare Part Unit, the applicable RMA assignment when present, Device, slot, Task, and chronology.
- Local Stock replacement remains valid without an RMA.
- The actual installed/removed relationship shall not be inferred merely from the RMA assignment.

### Submission-logistics snapshot

- Belongs to the accepted Spare Request submission and preserves requested delivery or self-pickup intent.
- Records intended receiver, selected dispatch or pickup location, effective name and address, recipient context, and accepted chronology.
- It is immutable evidence of requested intent and never proof of actual dispatch, delivery, pickup, or receipt.

### Actual logistics event

- Records an actual dispatch, pickup, delivery, receipt, location, custody, receiver, chronology, or observed-condition occurrence.
- May apply to one or more RMAs or physical units through independently addressable participation relationships.
- Remains distinct from the submission-logistics snapshot and from mutable Contact, Dispatch Location, and Site master data.

### Fault Tag

- Groups actual return obligations and physical return units.
- May contain items originating from different Service Requests, Spare Requests, temporary tracking identifiers, and RMAs.
- Membership is determined from the physical outcome associated with each RMA, not from a requirement that all items share one parent request.

## 4. Principal cardinalities

| Relationship | Cardinality and rule |
|---|---|
| Service Request → Device | `1 → 0..N` |
| Device → Device Part Unit | `1 → 0..N`; slot is recorded when known |
| Service Request → Spare Need | `1 → 0..N`; active Needs aggregate by BOM |
| Spare Need ↔ Device Part Unit | `1 ↔ 0..N` contributor units; one contributor belongs to the applicable SR/BOM Need at a time |
| Spare Request ↔ Spare Need | `1..N ↔ 0..N` through quantity-bearing allocations; all selected Needs share one Service Request |
| Spare Request → RMA | `1 → 0..N`; RMAs may arrive incrementally |
| RMA → target Device Part Unit | `0..1` current assignment; assignment history is preserved and may be redistributed |
| RMA → direct inbound Spare Part Unit | `0..1`; empty before receipt |
| Spare Request submission → submission-logistics snapshot | `1 → 1` after accepted submission; immutable intent |
| Actual logistics event ↔ RMA/Spare Part Unit | `0..N ↔ 1..N`; every participant relationship is independently addressable |
| Spare Part Unit → origin RMA | `0..1`; local units may have none |
| RMA → return unit | `0..1` current return obligation at a time, derived from the physical outcome |
| Fault Tag ↔ return obligation/unit | `0..N ↔ 0..N`; cross-request grouping is permitted |

## 5. Spare Need aggregation example

Given one Service Request with fifteen Devices, each containing four registered faulty batteries with BOM `battery_bomcode`:

- SOMA records sixty Device Part Units.
- SOMA produces one Spare Need for `battery_bomcode`.
- The derived contributor count is sixty.
- The Need preserves links to all sixty contributing Device Part Units and therefore to their fifteen Devices.
- The user does not create four identical Need rows per Device.

## 6. RMA discovery and deterministic assignment

- An accepted response may provide the official SR7 alone, SR7 with some RMAs, SR7 with all RMAs, or neither.
- No detected SR7/RMA keeps the request awaiting response and creates a warning; it does not invent identifiers.
- An SR7 without all expected RMAs is valid partial progress. Later accepted responses append additional RMAs.
- Every detected RMA preserves its C10 and promised BOM from the response.
- SOMA assigns RMAs to unassigned matching Device Part Units by stable Device Part Unit creation order.
- RMAs within an accepted response use their preserved response order; later response batches continue with the next eligible unassigned target.
- Example: sixty matching faulty battery units and thirty received RMAs assign four RMAs to each of the earliest seven Devices and two to the eighth when Device Part Unit creation order follows Device registration.
- The operator may redistribute any RMA assignment to another compatible target, including prioritizing another Device.
- Redistribution changes only the reviewed assignment relationship; it does not rewrite the RMA, response communication, Spare Need, or Device Part Unit.
- Every redistribution records prior target, new target, reason, operator, and chronology.
- Ambiguous or incompatible BOM mappings require review and shall not be forced silently.

## 7. RMA obligation lifecycle

1. **Awaiting acknowledgement** — the Spare Request has been submitted but no official SR7/RMA response is accepted.
2. **Acknowledged** — SR7 is known; zero or more RMAs may be known.
3. **Partially authorized** — fewer RMAs exist than the requested quantity and more may arrive later.
4. **Promised** — an RMA exists and may be preassigned to a compatible target Device Part Unit before receipt.
5. **Dispatched** — item dispatch is detected from indexed communication or confirmed manually.
6. **Received** — the actual inbound Spare Part Unit is registered and linked; actual BOM and serial may differ from the promise.
7. **Maintenance outcome recorded** — the inbound unit was installed, unused, faulty, incompatible, dismantled, or otherwise dispositioned.
8. **Return obligation resolved** — the RMA points to the physical unit that must be returned:
   - successful replacement: the removed Device Part Unit;
   - unused replacement: the same inbound Spare Part Unit;
   - inbound faulty/incompatible item: the inbound Spare Part Unit;
   - dismantled assembly: the parent assembly under its own identity.
9. **Fault-tagged** — the return obligation is included in a Fault Tag, possibly with unrelated requests.
10. **Warehouse received** — physical receipt is detected or confirmed, but final acceptance remains pending.
11. **Warehouse accepted** — the return obligation is finally closed.
12. **Warehouse rejected** — the same physical unit may be returned to the operator, explanation/correction work continues, and the obligation reopens for a later resend.

An erroneous detected or manual milestone may be rolled back through a targeted correction. A genuine rejection/resend is a new operational transition and shall not erase the earlier receipt or rejection.

## 8. Request creation, draft generation, and submission

SOMA distinguishes three operator actions:

1. **Save Draft** — creates the local Spare Request, assigns its immutable temporary tracking identifier, and preserves editable Need allocations and logistics intent.
2. **Generate Email Draft** — produces a `.msg` draft from the existing request and places the temporary tracking identifier in the subject.
3. **Record External Submission** — registers a request that was prepared or submitted outside SOMA while creating the same normal internal identity and temporary tracking identifier.

Generating, exporting, saving, or opening a `.msg` does not prove sending, delivery, or receipt. It shall not mark the request submitted, lock submission facts, or start the response-warning timer. Beta 1.0 does not send email.

Submission becomes accepted only through operator acceptance of matching indexed sent communication or explicit manual confirmation. At that point SOMA preserves the submitted Need membership, quantities, requested BOMs, receiver, delivery or self-pickup choice, submission-logistics snapshot, recipient context, temporary tracking identity, and known chronology as immutable evidence.

An externally initiated request shall reconcile to exactly one Service Request and one or more Spare Needs belonging to that Service Request; the reviewed registration may create missing Needs required to represent the submitted BOMs and quantities. A known SR7 requires format and uniqueness validation. Later communication discovery appends evidence to the same request. Possible duplication between a manually registered request and a communication-derived proposal requires reviewed reconciliation and never silent creation or merge.

## 9. Dispatch, actual logistics, and partial receipt

- The dispatch communication is distinct from the initial SR7/RMA acknowledgement.
- It commonly contains the SR7, applicable C10 identifiers, and the eight-digit Service Request shown in the communication's `TT ########` context.
- Dispatch may cover only some RMAs while other requested items remain pending.
- The immutable submission-logistics snapshot records requested delivery or self-pickup mode, intended receiver, selected dispatch or pickup location, and the effective name, address, and recipient context. It is intent, not proof of dispatch or receipt.
- Actual dispatch, pickup, delivery, receipt, location, custody, receiver, chronology, and observed condition are recorded independently through append-oriented logistics and receipt events.
- One actual logistics event may cover multiple RMAs or physical units, but every participating RMA and unit remains independently addressable, reviewable, and correctable.
- Split dispatch and receipt are valid. Some RMAs or units may progress while other quantities remain pending, undispatched, or unreceived.
- Differences between requested and actual logistics are reviewed and preserved; they never rewrite the submission snapshot.
- Changes to Contacts, Dispatch Locations, linked Infrastructure Sites, or current addresses do not rewrite historical logistics evidence.
- A local unit with no external delivery receives no fabricated request, dispatch, or receipt event.
- A dismantled parent assembly retains the direct receipt and logistics event. Extracted units inherit origin and receipt provenance through the parent without fabricated independent deliveries; their later custody movements are their own events.
- The operator may manually register the SR7, RMAs, per-item BOMs, dispatch, receipt, Fault Tag generation, warehouse receipt, and warehouse acceptance or rejection when detection is missing or incorrect.

## 10. Task outcome and return selection

- Inventory units are allocated to Tasks, not directly to Objectives.
- After maintenance, the operator confirms the outcome for every relevant unit and target: installed/used, unused, inbound faulty, incompatible, dismantled, or another accepted outcome.
- The RMA uses that outcome to determine which physical unit becomes the return obligation.
- The return obligation is not stored by overwriting inbound serial/BOM fields on the RMA; it references the actual physical unit.

## 11. Manual actions, reviewed proposals, bulk operations, and correction

- Every supported Inventory transition provides a manual action when detection is absent, incomplete, delayed, or incorrect.
- A manual action identifies the exact target, operator, recording time, effective time when known, and reason or relevant facts.
- Indexed communication creates an idempotent reviewed proposal tied to the exact source communication. It never mutates Inventory before acceptance and may be accepted or rejected individually.
- A bulk action applies only to targets compatible with the same transition and prerequisites.
- Before a bulk mutation, SOMA shows eligible targets, excluded or conflicting targets, resulting states, warnings, and material dependencies.
- Bulk acceptance is transactional and appends one independently addressable lifecycle event per affected target under a common batch identifier. It never collapses multiple units or obligations into one shared status record.
- Correcting one member of a batch does not alter unaffected members.
- A correction or superseding decision targets the exact accepted event or relationship, preserves the original event and evidence, and reproducibly recalculates the current projection.
- Correcting an RMA assignment, Task allocation, receipt link, installation, removal, return-unit selection, Fault Tag membership, or warehouse decision preserves the identities of the participating entities and supersedes only the disputed relationship.
- Internal identities are immutable. SR7/C10 correction retains the previous official identifier as a non-reusable alias; a genuinely different request or authorization receives a different internal identity.
- Equal BOMs, manufacturer serials, official identifiers, names, or labels create reconciliation candidates only and never authorize silent merge or reassignment.
- A genuine later development—including warehouse rejection, return to the operator, explanation work, and resend—is new lifecycle history rather than correction or rollback.
- Hard deletion is not the ordinary correction mechanism for accepted Inventory history.

## 12. Evidence boundary for Beta 1.0

- Evidence is optional for every manual Inventory action in Beta 1.0.
- Ordinary workflows shall not request or require an evidence upload.
- Beta 1.0 persistence and application services shall accept optional evidence references from supported internal adapters and future callers.
- Beta 1.0 shall expose no manual attachment or upload control anywhere in the UI.
- Indexed PST/OST communications are first-class evidence when SOMA detects them.
- Manual confirmation without evidence remains valid and auditable through operator, reason, target, and chronology.
- Later activation of any evidence attachment control, mandatory evidence collection, or additional evidence-ingestion source requires a separately accepted product decision and UI/LLD change.
