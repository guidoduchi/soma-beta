# SOMA Beta Ticket and Objective Workbench Contract

Status: **Foundation review v0.3**  
Target: **SOMA Beta 1.0.0**

## 1. Shared interaction model

Tickets open into a focused workbench rather than a sequence of disconnected dialogs.

- Double-clicking a selected ticket opens its workbench.
- Pressing Enter while a ticket is selected through keyboard navigation performs the same action.
- The wide layout has a left working area with small tabs and a right communication-evidence preview.
- The narrow responsive layout keeps the same information and actions through switchable panes; it does not remove the communication side.
- The right pane previews locally indexed relevant email evidence. SOMA does not contact an email service.
- All pointer actions have a keyboard equivalent, visible focus, and non-color state cues.
- Relationship consolidation uses a reviewed merge preview. SOMA shows retained records, incoming context, conflicts, and consequences before applying the merge.

## 2. Service Request workbench

The accepted tab order is:

1. **Overview**
2. **Devices**
3. **Spare Parts**
4. **RFCs**
5. **Tasks**
6. **Notes**

### 2.1 Overview

Overview displays the complete accepted SR information supplied by the active Advanced Search allowlist, local identity/provenance, status, Contract Product Line/SLA context, and review warnings. Deferred fields do not become active workflow controls.

### 2.2 Devices

The operator can register one or more involved device references.

- A hostname match against Infrastructure proposes the existing Network Element for confirmation.
- A device that is not in Infrastructure remains a valid unregistered device reference. It can participate in Tasks, Spare Needs, Spare Requests, Fault Parts, and the complete SR workflow.
- SOMA warns when the operator deliberately keeps an external/unregistered device, but does not prohibit it.
- Holding the Promote control continuously for three seconds creates a corresponding Infrastructure Network Element and regularizes the reference. Releasing early resets the timer.
- Pointer, touch, and keyboard hold have equivalent behavior. A basic yes/no confirmation is not substituted for the deliberate hold interaction.
- Promotion preserves the original reference and its relationships; it does not create a second operational device.
- After promotion the operator may add IP address and other Infrastructure details.

### 2.3 Spares

Spares presents the SR-level BOM demand aggregated from Device Part Units across every involved Device and connects that demand to Stock, Spare Requests, RMAs, Task outcomes, actual logistics, and return status.

- Recording a faulty slot creates or identifies one Device Part Unit with Device, slot when known, BOM, optional manufacturer serial, condition, and chronology.
- Matching Device Part Units contribute to one Spare Need per SR/BOM rather than creating duplicate Needs per Device or slot.
- The UI shows contributor count, planned quantity, eligible local Stock, quantities allocated locally, quantities submitted externally, accepted RMAs, pending quantity, and return progress without collapsing their meanings.
- Before starting a Spare Request, SOMA suggests compatible available Stock. The operator may select local units, request externally, combine both by quantity, or continue externally despite local availability.
- One Spare Request may select one or more Needs from this SR and records receiver plus delivery or self-pickup logistics.
- **Save Draft**, **Generate Email Draft**, and **Record External Submission** are separate controls. Draft generation never appears as sending.
- Recording a request prepared or submitted outside SOMA creates the normal internal and temporary identities, guides reviewed reconciliation to this Service Request and its Needs, and warns about possible duplicate requests.
- Requested logistics and actual dispatch, pickup, delivery, receipt, and custody appear separately. Partial progress remains visible per RMA and physical unit.
- A shared actual logistics event may cover several RMAs or units, but each participant remains independently addressable, inspectable, and correctable.
- A Need remains reusable across multiple request attempts until explicitly resolved or cancelled.
- Detected C10 RMAs autoassign to compatible unassigned Device Part Units by stable creation order. The operator may redistribute assignments with an audited reason.
- The tab exposes acknowledgement, partial RMA, dispatch, receipt, Task outcome, Fault Tag membership, warehouse receipt, and final acceptance/rejection as separate states.
- Eligible RMA return obligations show the selected physical return unit and provide navigation to the cross-request Fault Tag workflow without duplicating C10, SR7, unit, or Device facts.
- The Fault Tag workflow identifies pickup Dispatch Location as the origin from which return units are dispatched, never as the warehouse destination.
- Draft, submitted, replacement, resend, warehouse-received, accepted, and rejected attempts remain distinguishable; partial outcomes are visible per membership.
- The UI offers state-specific Delete Draft, Cancel, Supersede and Replace, Archive, and Create Resend actions rather than generic deletion.
- Communication-derived milestones appear as review proposals. The operator may accept or reject them individually.
- A bulk action previews eligible, excluded, and conflicting targets before transactional confirmation and reports one result per target.
- Correction selects the exact event or relationship, displays the original and proposed effect, and leaves unaffected batch members unchanged.
- Manual identifiers and milestone confirmations remain available without evidence when communication detection fails.
- Beta 1.0 exposes no manual attachment or upload control.
- Deletion, correction, rollback, and rejection/resend rules are governed by the Inventory Lifecycle Contract.

### 2.4 RFCs

The RFC tab appears between Spares and Tasks. It shows linked master RFCs with subordinate RFCs and their WFM branches nested beneath them. Linking, unlinking, or consolidating RFC context uses an impact/merge preview and cannot silently duplicate devices, Tasks, notes, or relationships.

### 2.5 Tasks

From the SR workbench, the operator may:

- create a Local Task;
- select an existing eligible WFM;
- view imported and local Tasks connected to the SR; and
- select which device references of this SR participate in the Task.

An Objective reaches this SR only through such a Task. There is no independent Objective-to-SR relationship.

### 2.6 Notes

Notes are operational journal entries.

- The operator may edit or remove a note from the active workbench.
- Editing never changes its original creation timestamp.
- Creation, modification, and deletion/removal are audited with prior content and event time.
- Imported population cannot overwrite local notes.

## 3. RFC workbench

The RFC workbench uses the same open behavior, split layout, communication preview, responsive behavior, Notes rules, and merge-review principles.

The accepted tab order is:

1. **Overview**
2. **Service Requests and Devices**
3. **Related RFCs**
4. **Tasks**
5. **Notes**

### 3.1 Overview

Overview displays accepted Enhanced Excel facts, provisional/import provenance, hierarchy role, status, and warnings. A WFM-created provisional RFC remains visibly provisional until authoritative RFC population is reviewed or safely accepted.

### 3.2 Service Requests and Devices

- The operator may relate the RFC branch to an existing SR or create a new SR from this flow.
- When related to an SR, the tab exposes applicable device references from that SR and from the RFC's subordinate branches.
- If no SR is linked, the operator may still add involved registered or unregistered device references directly to the RFC.
- Linking an SR previews the proposed consolidation rather than silently merging working context.
- Direct SR links target a master RFC; subordinate context is visible through the branch.

### 3.3 Related RFCs

- A master RFC may search for and manage direct subordinate RFCs.
- A subordinate RFC cannot become the master of another RFC.
- Each subordinate RFC may have different involved devices and Tasks.
- Source branch-suffixed Enhanced Excel identifiers are not interpreted as subordinate RFCs.

### 3.4 Tasks

- The tab shows WFMs under their owning master or subordinate RFC.
- A Local Task may be created under a master or a subordinate RFC.
- If no WFM exists, the absence does not block a Local Task.
- WFM ownership remains exactly one RFC; a Local Task may relate to zero or many RFCs, including subordinate RFCs.

## 4. Objective creation and grouping

An Objective is the reviewed grouping of scheduled Tasks, not an independently linked ticket container.

- Creating or importing a future, noncancelled Task with a complete valid timeframe starts Objective grouping.
- A Task whose interval overlaps an existing Objective is proposed for that Objective.
- If it bridges multiple Objectives, SOMA proposes one consolidation and the union timeframe; overlapping Objectives cannot remain after acceptance.
- The operator reviews and may correct the Task interval or manually reassign Tasks before accepting a grouping conflict.
- Adding or removing a Task recalculates the Objective timeframe from its accepted Task windows.
- A Local Task created inside an Objective inherits that Objective timeframe, not its identity.
- A Task without a timeframe remains unscheduled and creates no Objective.
- A cancelled Task does not create an Objective automatically.
- Every accepted Objective contains at least one Task. Removing the last Task requires atomic removal of an otherwise deletable untouched Objective.

## 5. Ticket visibility and status safety

- Imported cancelled, resolved, and closed SRs remain visible and are visually muted in the configured Daily, Weekly, or Monthly main period.
- Weekly is the installation default; Daily and Monthly are selectable.
- After the configured period, terminal tickets leave the main view and remain accessible in Historical view.
- Imports older than the configured historical lookback are governed by the Import Contract.
- Imported tickets cannot be officially reopened by SOMA. A source observation implying reopening is treated as possible parsing or external-data manipulation: high risk, but permitted after explicit operator confirmation and audit.
- Manual SRs may use their accepted local lifecycle until official reconciliation.

## 6. Deferred behavior

MOP generation belongs to Beta 1.1.0. It will be initiated from Local Tasks and may use accepted SR workbench information to populate a reviewed DOCX template. It is not part of Beta 1.0.0.
