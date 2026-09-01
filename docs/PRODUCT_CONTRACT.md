# SOMA Beta Product Contract

Status: **Foundation review v0.3**  
Target: **SOMA Beta 1.0.0**  
Authority: confirmed product decisions; unresolved items are listed in `DECISIONS.md` and are not implementation permission.

Normative supporting contracts: [Import Contract](IMPORT_CONTRACT.md), [Ticket and Objective Workbench Contract](WORKBENCH_CONTRACT.md), [Inventory Lifecycle Contract](INVENTORY_LIFECYCLE.md), and [Contract Product Line and SLA Contract](PRODUCT_LINE_SLA.md).

## 1. Product intent

SOMA Beta is a locally deployed, offline-first Service Operations Management Application. It turns imported and manually registered operational evidence into a coherent view of service obligations, work, spare logistics, and infrastructure history.

SOMA uses a game-like interface language to make state, priority, progress, and consequences easy to interpret. It is not a game skin: clarity, trust, and auditability take priority over decoration.

## 2. Lineage and migration boundary

- SOMA Beta uses the `soma-beta` repository and a clean schema.
- Zeus and SOMA Alpha are historical checkpoints.
- Alpha work may be selectively reused only after it is evaluated against this contract.
- Alpha pull requests are not merged wholesale into Beta.
- Beta 1.0.0 has no Zeus/Alpha database migration requirement.
- High-level design precedes low-level design; implementation follows both.

## 3. Deployment and operator model

- An installation runs locally and remains functional offline.
- Each installation has exactly one authenticating **Local User Profile**, acting as local administrator.
- Registered people are operational/business records and do not receive login profiles. A Contact may optionally belong to a Customer Organization; organization assignment is never required merely to register the person.
- Password login is required; the operator may explicitly enable automatic login on that Windows account.
- A small internal Beta team means multiple evaluators may use separate local installations. It does not authorize a shared multi-user database in 1.0.0.

## 4. Canonical navigation

The primary navigation is fixed, in order:

1. Overview
2. Tickets
3. Objectives
4. Inventory
5. Infrastructure
6. Settings

## 5. Overview

Overview is a curated operational dashboard, not an arbitrary report builder.

The operator can select Daily, Weekly, or Monthly periods; compare the current period with its preceding equivalent; show, hide, and reorder approved sections; choose a default period; and configure approved warning thresholds.

Default sections include:

| Section | Measures |
|---|---|
| Tickets | New, active, resolved, at risk |
| Inventory | New Spare Requests, dispatched, awaiting identifiers, overdue |
| Objectives | Scheduled, completed, incomplete, awaiting review |

A delta is colored by operational desirability, not simply by whether its number increased or decreased.

Below the measures, Overview provides:

- **This period / Today:** a chronological narrative of Objectives and their Tasks, WFMs, Tickets, and warnings.
- **Needs attention:** clickable warnings that open the corresponding filtered workspace.

Examples include an RFC without a Service Request, a WFM without an Objective, an Objective awaiting review, and a Spare Request dispatched beyond its threshold.

Reporting uses `America/Guayaquil` for operator-facing dates, a Monday–Sunday week, and UTC storage. Excel is the 1.0.0 report export format.

## 6. Tickets

Tickets contains **Service Requests (SRs)** and **Requests for Change (RFCs)**. The ticket-opening behavior, split communication preview, tab order, device-reference workflow, and Objective grouping behavior are normative in the [Workbench Contract](WORKBENCH_CONTRACT.md).

- An SR may link directly to many **master RFCs**; an SR view shows their complete RFC/WFM branches nested beneath it.
- An RFC may link to many SRs through its master branch and owns its WFM Tasks.
- A record is stored once even when presented through several related views.
- Everything may exist without an SR, except entities whose rules explicitly require one. When an SR exists, it is the pivotal connection between work, spares, and infrastructure evidence.

### 6.1 Service Requests

- Official SR identity is exactly eight digits.
- An SR can be created manually.
- If its official ID is supplied, a later Advanced Search import populates the same record.
- If omitted, SOMA generates `LSR-` followed by an eight-digit installation-local sequence beginning at `00000001`. Later reconciliation to an official SR requires an explicit operator-reviewed mapping; SOMA does not guess.
- Imported cancelled, resolved, and closed SRs remain muted but visible during the configured Daily, Weekly, or Monthly main period, then move to Historical view. Weekly is the installation default.
- A source observation that appears to reopen an imported terminal SR is high risk and requires explicit confirmation and audit.

### 6.2 Requests for Change

- Official RFC identity is `NC` followed by fourteen digits.
- RFC hierarchy is exactly two levels: one master RFC may own direct subordinate RFCs.
- A subordinate RFC cannot own another RFC, contain subordinate RFCs, or act as a master.
- Direct SR↔RFC links target master RFCs only. Subordinate RFC and WFM context is derived through the master branch.
- A Local Task may be created under or linked to a master or subordinate RFC; this does not allow a subordinate RFC to own another RFC.
- Correcting a provisional, manually created RFC identity must not rewrite historical identity silently.

### 6.3 WFM Tasks

- A WFM is a Huawei-generated **Task subtype**, never a third top-level Ticket type.
- Official WFM Task identity is `TK` followed by fourteen digits.
- A WFM belongs to exactly one RFC and at most one Objective.
- A WFM owned by a master RFC acts as the **master WFM** for that operational branch/timeframe. A WFM owned by a subordinate RFC acts as a subordinate WFM. This role is derived from RFC ownership and is not an independently editable flag.
- Registering a WFM requires Task No. and RFC No. If the RFC exists, Task Name is inherited from the RFC Summary. If it does not exist, Task Name is also required and creates a provisional parent RFC with that summary.
- Correcting the parent RFC of a manually registered WFM prompts the operator either to remove the now-unused provisional RFC or leave it orphaned; no silent deletion occurs.
- Hard deletion is available only for manually created RFCs/WFMs that were never imported or adopted and have no executed Objective, communication, review, spare-use, lifecycle, or other protected operational evidence.
- Deleting a manual RFC may cascade only through WFMs that are independently eligible for hard deletion. Otherwise SOMA uses termination/archive/cancellation and preserves history.

## 7. Objectives and Tasks

An **Objective** is a Maintenance Window composed of Tasks in one reviewed planned timeframe.

- Every Objective requires one reviewed planned timeframe and at least one Task from creation; there is no empty Objective state.
- A Task is first-class, has its own identity, and is either a Local Task or a WFM Task.
- A Local Task requires only a Task Name from the operator. It may link independently to zero or many SRs, zero or many RFCs—including subordinate RFCs—zero or many Spare Part Units, and zero or many Network Elements.
- A WFM Task retains its one owning RFC. Its master/subordinate branch and SR context are derived through that RFC hierarchy rather than copied as independent Objective relationships.
- A local Task created inside an Objective inherits the Objective **planned timeframe**, not its identity.
- Every Task assigned to an Objective uses the Objective planned timeframe.
- A Task belongs to at most one Objective, but one SR may participate through different Tasks in multiple unfinished Objectives.
- There is no independent Objective↔SR authority: an Objective's effective SR context is derived exclusively through its Local and WFM Tasks.
- Retrying work creates a new Task attempt while preserving the earlier Task unchanged. A Local Task retry receives a new local Task identity; a WFM retry requires a new WFM Task No. The new attempt enters the normal overlap-grouping flow, so Objective retry lineage is derived from Task attempts rather than represented as a one-to-one Objective chain.

When an Objective timeframe is selected, SOMA locates available WFM Tasks whose authoritative WFM planned windows overlap it. An unplanned WFM may inherit the Objective window. A WFM with a conflicting established window requires explicit review and, when it represents another attempt, a new Task No.; SOMA never overwrites an established attempt silently.

Creating or importing a future, noncancelled Task with a valid interval enters reviewed Objective grouping. It creates a new Objective when no interval overlaps; otherwise it is proposed into the overlapping Objective. A Task bridging multiple Objectives proposes their consolidation and union timeframe because accepted Objectives may not overlap. A Task without a timeframe remains unscheduled and creates no Objective.

Planned and actual Objective intervals are distinct. Task outcomes and actual Spare Part Unit use are reviewed individually. Corrections preserve prior actor/time/reason evidence; the exact outcome transition table remains a low-level design item.

If one or more Tasks link to SRs, the Objective suggests the union of spares related to those SRs. The operator may also attach any other eligible spare to the Objective.

## 8. Inventory

Inventory has three principal views: **Stock**, **Spare Requests**, and **Fault Tags**. Spare Needs and RMAs appear inside the workflows where they provide operational context rather than becoming additional primary navigation.

### 8.1 Catalog and physical identity

- A **Part Number/BOM code** is the catalog and grouping unit.
- A **Spare Part Unit** has an immutable SOMA local physical-unit identity. Manufacturer serial number is authoritative when available but optional, because components such as CPUs may have no serial label.
- Inventory shows quantities by BOM and state, while preserving unit-level identity and history.
- Installing a unit removes it from available stock but retains it as an installed Infrastructure component.
- Removing a unit requires a disposition; it never silently returns to available stock.

### 8.2 Spare Needs

A Spare Need is the planning step before a Spare Request. It belongs to one open or registered SR and one involved registered or unregistered device reference, and records BOM/Part Number, description, and quantity. One Need may feed many Spare Requests; one Spare Request may combine many Needs from the same SR. Use does not consume eligibility. Exact request, Fault Part, replacement, discrepancy, and deletion behavior is normative in the [Inventory Lifecycle Contract](INVENTORY_LIFECYCLE.md).

### 8.3 Spare Requests and RMAs

- Official Spare Request identity is `SR` followed by seven digits.
- Every official Spare Request is linked to exactly one Service Request through one or more selected Spare Needs from that SR.
- After verifiable sent evidence, absence of a matching confirmation response for 24 hours produces a Needs Attention warning. Draft generation alone does not start the timer.
- For a requested quantity `N`, one Spare Request may receive `M` accepted C10 RMA positions where `M ≤ N`.
- Every requested position remains explainable. Positions without a C10 record their rejected/unfulfilled outcome and reason, such as EOS, unavailable, incompatible, or another reviewed status; they do not disappear from history.
- An RMA identity is `C` followed by ten digits.
- One RMA belongs to exactly one Spare Request, represents exactly one accepted ordered BOM position, and is never a quantity container.
- Before receipt, an RMA has no received physical unit. At Received state it has exactly one received unit and the resulting unit initially has condition `new`; manufacturer serial is recorded when available.
- An RMA records the actual received BOM separately from the requested BOM and can record the serial number or SOMA local identity returned to the supplier.
- The return serial equals the received serial only when that same unit is returned, such as unused, incompatible, or dead-on-arrival stock.
- If a different replaced unit should be returned and its serial is unavailable, SOMA records `unknown` plus a reason; it never copies the received serial as fabricated evidence.
- RMA logistics state and Spare Part Unit condition/location are separate concepts.

Contradictory Service Request relationships are blocked or corrected through an audited review. A manually registered Spare Part Unit may be confirmed installed without an SR, but SOMA shows a warning and requires explicit acknowledgment.

### 8.4 Fault Tags

A Fault Tag is the return leg of the Spare Request lifecycle and groups one or more physical units that must be returned or dispositioned.

- Fault Tags retain their related Spare Request, RMA, SR, unit, and Infrastructure context without duplicating identity.
- Sending the first Fault Tag locks its membership and sent identity. A later correction cancels/replaces the tag rather than rewriting what was sent.
- Pickup/location evidence uses an immutable logistics snapshot.
- Warehouse confirmation requires evidence for the affected units plus explicit operator confirmation.
- A closed Fault Tag is terminal. Hard deletion is limited to an untouched, unsent manual draft with no dependent evidence.

## 9. Infrastructure

The physical/organizational model is:

- A Customer Organization owns Contracts and Sites.
- A Site is one physical Datacenter and belongs to exactly one Customer Organization. Equal names or city codes across organizations remain distinct records and never imply the same physical location.
- A Cloud Type is reusable—such as PRV, B2B, AMS, BES, or NFV—and appears at a Site through a distinct Cloud Deployment. Each Cloud Deployment belongs to exactly one Site; the same Cloud Type may therefore have separate deployments at GYE, UIO, GLP1, GLP2, MAP, INC, and other Sites.
- A regularized Network Element belongs to its physical Site and may be assigned to one of that Site's Cloud Deployments. Its Customer Organization is derived through the Site. Unregistered/external Device References remain valid without forced placement or ownership.
- Site contains Rooms; Room contains Racks; Rack records row and column.
- A Network Element is an installed device instance and may be standalone/unplaced or located in a Rack.
- A Network Element Model is reusable across customers and device instances.
- Devices of the same model may contain different installed Components.
- A Network Element may contain compound sub-elements; circular containment is invalid.
- Components use BOM codes, immutable local physical-unit identities, optional manufacturer serials, and immutable installation/replacement events.

BOM **compatibility** with a model and BOM **historical use** in an instance are distinct facts. Replacement events link the installed and removed units, target Network Element/slot, and applicable SR, Objective, and Task. An unknown legacy component can be registered progressively when it is first replaced.

Device connectivity, topology, and SSH are excluded from 1.0.0.

## 10. Dispatch Locations

- `Dispatch Site` is renamed **Dispatch Location**.
- A Dispatch Location has a name and address and represents one physical logistics location independent of customer ownership.
- A standalone Dispatch Location stores its own address.
- Registering a Site automatically creates one exclusive Dispatch Location for it.
- A site-bound Dispatch Location is one-to-one, cannot be reused or reassigned, and inherits the Site address.
- Logistics records preserve an immutable address snapshot even if the current address later changes.

## 11. Imports and population

The official 1.0.0 sources are:

| Domain | Source |
|---|---|
| Service Requests | Advanced Search Excel export |
| RFCs | Enhanced Excel Data Export |
| WFM Tasks | Service Provider Plan Creation Excel export |

The exact active/deferred allowlists, discarded-column boundary, delimiters, conditional blanks, historical cutoff, source precedence, and aggregate sample evidence are normative in the [Import Contract](IMPORT_CONTRACT.md).

The default historical lookback is one month and is configurable. Terminal source rows older than that boundary are excluded using the trusted source-specific recency field; active, future, and unscheduled work is not discarded by this rule.

Population matches immutable official identities and updates source-owned fields. It must preserve local notes, relationships, Objectives, inventory and infrastructure links, review results, audit history, and other SOMA-owned meaning.

Imports are reviewed by default. The operator may opt into automatic acceptance of safe new data per source/change class. Identity changes, hierarchy or ownership changes, WFM reassignment, time conflicts, terminal-state reversal, disappearance/deletion, and hardware serial contradictions always require review.

An imported source cannot correct an official identity in place. Identity reconciliation is an explicit audited operation.

## 12. Offline mail evidence

SOMA does not connect to an email server and cannot send or receive mail directly.

- It reads PST/OST files without modifying them, indexes selected folders such as Inbox and Sent, and matches supported operational identifiers.
- It generates `.msg` draft items with recipient, subject, body, and attachments for the operator to send manually.
- Generating a draft is not evidence that it was sent.
- Sent evidence exists only after a later PST/OST scan finds it or the operator explicitly records manual confirmation.
- Locked, corrupted, or unsupported stores fail safely without modification.

## 13. Contract Product Lines and SLA

Contract Product Line classification, SLA calculation, warnings, and reporting are core product capabilities, not an optional reporting add-on. An SLA tier measures the percentage of an eligible Service Request cohort resolved or closed within an inclusive duration; it is not a percentage of one ticket's allowed time. Each SR has at most one active Contract Product Line classification. Automatic import classification must be deterministic and based only on trusted allowlisted evidence; ambiguous or unmatched SRs remain unclassified for review, and the discarded Advanced Search `Product` field never selects a policy. Manual reclassification is audited and recalculates current results without rewriting completed report snapshots. The confirmed IT/NFV tiers, Non-fault inquiry derivation, cancelled exclusion, and normative calculation rules are in the [Contract Product Line and SLA Contract](PRODUCT_LINE_SLA.md).

## 14. Audit and deletion principles

- Imported facts retain source and import-run provenance.
- Material manual changes record when, what, and why.
- Derived states are recalculated from source facts and policy rather than silently persisted as independent truth.
- Destructive cascades require impact preview and confirmation.
- Hard deletion is restricted to untouched manual records with no imported/adopted provenance, executed Objective, communication, review, spare-use, lifecycle, or dependent history.
- Removing a Task from an unexecuted Objective is allowed only when the Objective retains at least one Task, or when the complete untouched Objective is removed atomically.
- Business history is preserved when a relationship changes.
- Beta 1.0.0 provides Historical views and archive-safe presentation but no purge of operational records. Purge policy is deferred to Beta 1.1.0.

## 15. 1.0.0 acceptance boundary

Beta 1.0.0 is not complete until all six work areas function together, Contract Product Line/SLA rules are enforced, supported Excel imports and exports work, offline PST/OST and MSG workflows work, local data is protected, and the UI supports responsive light/dark operation plus Windows tray behavior.
