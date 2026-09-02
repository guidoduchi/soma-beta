# SOMA Beta Product Contract

Status: **Foundation review v0.3**  
Target: **SOMA Beta 1.0.0**  
Authority: confirmed product decisions; unresolved items are listed in `DECISIONS.md` and are not implementation permission.

Normative supporting contracts: [Import Contract](IMPORT_CONTRACT.md), [Ticket and Objective Workbench Contract](WORKBENCH_CONTRACT.md), [Inventory Lifecycle Contract](INVENTORY_LIFECYCLE.md), [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md), [Communications Contract](COMMUNICATIONS_CONTRACT.md), [UI/UX Interaction Contract](UI_UX_CONTRACT.md), and [Contract Product Line and SLA Contract](PRODUCT_LINE_SLA.md).

## 1. Product intent

SOMA Beta is a locally deployed, offline-first Service Operations Management Application. It turns imported and manually registered operational evidence into a coherent view of service obligations, work, spare logistics, and infrastructure history.

SOMA uses a game-like interface language to make state, priority, progress, and consequences easy to interpret. It is not a game skin: clarity, trust, and auditability take priority over decoration.

## 2. Lineage and migration boundary

- SOMA Beta uses the `soma-beta` repository and a clean schema.
- Zeus and SOMA Alpha are historical checkpoints.
- Alpha work may be selectively reused only after it is evaluated against this contract.
- Alpha pull requests are not merged wholesale into Beta.
- Beta 1.0.0 has no Zeus/Alpha database migration requirement.
- Beta starts an independent schema and migration lineage. It does not execute, continue, or automatically upgrade Alpha migrations or databases. Any later Alpha-data importer requires a separately accepted contract.
- High-level design precedes low-level design; implementation follows both.

## 3. Deployment and operator model

- An installation runs locally and remains functional offline.
- Each installation has exactly one authenticating **Local User Profile**, acting as local administrator.
- The Local Administrator has an automatically generated stable internal identity. Initial authentication setup requires a password and confirmation; login requires no username. The editable display name defaults to `Local Administrator`, while any username-like label is optional display metadata.
- Local User email and phone are not mandatory profile fields. Operational channels belong to reusable Contact records rather than being duplicated into authentication identity.
- Registered people are operational/business records and do not receive login profiles. A Contact may optionally belong to a Customer Organization; organization assignment is never required merely to register the person.
- Contact email, phone, and other communication channels are optional for ordinary Ticket, Task, Objective, and historical workflows. A channel is validated only when an action actually needs it; failure blocks that communication action rather than the underlying operational record.
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

The operator can select Daily, Weekly, or Monthly periods; compare the current period with its preceding equivalent; show, hide, and reorder approved sections; choose a default period; and configure approved noncontractual warning thresholds. Presentation thresholds cannot replace, weaken, or redefine a Contract Product Line SLA policy.

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

Daily, Weekly, and Monthly exports derive from one internally consistent accepted-state snapshot and may cover one Customer Organization or all organizations. Completed report evidence preserves only the report-time values, membership, calculation results, policy revisions, and provenance needed to interpret and reproduce the artifact. Later operational or policy changes affect current and future reports but never rewrite a completed report. A report is completed only after successful artifact verification; failed or cancelled generation changes no operational record. Report generation never offers or initiates cleanup in Beta 1.0.

The Overview composition follows the [UI/UX Interaction Contract](UI_UX_CONTRACT.md). It uses a stable global shell, explicit Customer/period scope, a clear context header, restrained modular summaries, progressive detail, Needs Attention, the operational narrative, and a collapsible activity surface for background jobs, imports, reviews, warnings, and failures. This direction is informed by the clarity of mature infrastructure-management interfaces without copying their branding, assets, exact pixels, dense typography, or wide-screen assumptions.

Overview summary cards are projections over accepted domain facts, not editable state. Every card identifies its scope, unknown/partial/coverage conditions, and actionable destination. The activity surface never replaces authoritative job, proposal, or audit records and owns its own hovered/focused scrolling.

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
- A recognized terminal status immediately suppresses active-work reminders and live SLA-risk notifications. Resolved and Closed SRs retain their effective duration, applicable SLA-cohort, source, and audit evidence; Cancelled SRs retain historical evidence but are excluded from SLA cohorts.
- A source observation that appears to reopen an imported terminal SR is high risk and requires explicit confirmation and audit.
- One official SR number always refers to the same surviving Beta SR; Beta creates no finalized episodes, tombstones, or same-number replacement records. A confirmed terminal reversal updates that same SR, preserves prior terminal evidence, and recalculates current projections without rewriting completed reports.

### 6.2 Requests for Change

- Official RFC identity is `NC` followed by fourteen digits.
- RFC hierarchy is exactly two levels: one master RFC may own direct subordinate RFCs.
- A subordinate RFC cannot own another RFC, contain subordinate RFCs, or act as a master.
- Direct SR↔RFC links target master RFCs only. Subordinate RFC and WFM context is derived through the master branch.
- A Local Task may be created under or linked to a master or subordinate RFC; this does not allow a subordinate RFC to own another RFC.
- Correcting a provisional, manually created RFC identity must not rewrite historical identity silently.
- RFC/WFM workbook absence has no lifecycle authority. Recognized status controls active, terminal, cancelled, and historical presentation, while SOMA performs filtering locally.
- Archival is reversible presentation and is distinct from imported terminal evidence. SR and RFC lifecycles remain independent.
- The complete discovery, identity, hierarchy, status, grouping, and terminal-cascade rules are governed by the [RFC/WFM Contract](RFC_WFM_CONTRACT.md).

### 6.3 WFM Tasks

- A WFM is an externally generated **Task subtype**, never a third top-level Ticket type.
- Official WFM Task identity is `TK` followed by fourteen digits.
- A WFM belongs to exactly one RFC and at most one Objective.
- A WFM owned by a master RFC acts as the **master WFM** for that operational branch/timeframe. A WFM owned by a subordinate RFC acts as a subordinate WFM. This role is derived from RFC ownership and is not an independently editable flag.
- Registering a WFM requires Task No. and RFC No. If the RFC exists, Task Name is inherited from the RFC Summary. If it does not exist, Task Name is also required and creates a provisional parent RFC with that summary.
- Correcting the parent RFC of a manually registered WFM prompts the operator either to remove the now-unused provisional RFC or leave it orphaned; no silent deletion occurs.
- Hard deletion is available only for manually created RFCs/WFMs that were never imported or adopted and have no executed Objective, communication, review, spare-use, lifecycle, or other protected operational evidence.
- Deleting a manual RFC may cascade only through WFMs that are independently eligible for hard deletion. Otherwise SOMA uses termination/archive/cancellation and preserves history.
- `Complete` and `Plan Cancel` are historical WFM states. Plan Cancel may create or adopt an exact cancelled record but never activates work, promotes an RFC, or creates an Objective.

## 7. Objectives and Tasks

An **Objective** is a Maintenance Window composed of Tasks in one reviewed planned timeframe.

An SR may be resolved without an Objective or Task—for example by the customer or as a Non-fault inquiry. SOMA never fabricates maintenance work merely to justify SR completion.

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

If one or more Tasks link to SRs, SOMA suggests the union of eligible Stock and pending spares related to those SRs. Physical-unit reservation belongs to a Task, not directly to the Objective; the Objective displays the derived union of its Task allocations.

## 8. Inventory

Inventory has three principal views: **Stock**, **Spare Requests**, and **Fault Tags**. Spare Needs, Device Part Units, RMAs, and return obligations appear within the workflows that own them rather than becoming additional primary navigation.

### 8.1 Physical entities and Stock

- A **Device Part Unit** is one actual component installed in, removed from, or diagnosed under one Device and, when known, one slot. It owns its actual BOM, optional manufacturer serial, condition, and installation/removal history.
- A **Spare Part Unit** is one physical Inventory unit with immutable SOMA identity, actual BOM, optional manufacturer serial, condition, location/custody, and lifecycle history.
- Device Part Units, Spare Part Units, Spare Needs, RMA obligations, and submitted request allocations are separate entities.
- Stock shows physical Spare Part Units grouped by BOM and eligibility while preserving unit identity and history.
- Installed, reserved, quarantined, returned, dismantled, scrapped, or otherwise unavailable units do not appear as eligible Stock.
- Manual, local, legacy, extracted, or serial-less units remain valid through immutable `LSU-########` identity. Official request and origin-RMA provenance is optional.

### 8.2 SR-level Spare Needs and stock-first choice

A Spare Need is one persistent Service-Request-level planning record aggregated by BOM across matching Device Part Units from any number of Devices under that SR. It records BOM, description, planned quantity, system-derived contributor count, and contributor relationships. Registering matching faulty Device Part Units creates or contributes to the same Need rather than duplicating one Need per Device or slot.

Before external requesting, SOMA shows compatible available Stock for the Need and affected Devices. The operator may use local Stock, request externally, combine both by quantity, or deliberately request externally despite local availability. A suggestion never reserves or consumes a unit automatically. A Need remains reusable across request attempts until explicitly resolved or cancelled.

### 8.3 Spare Requests and submission

- Every Spare Request receives an immutable temporary tracking identifier and selects one or more Needs belonging to one Service Request.
- The request derives its Service Request and Customer Organization and suggests the current customer ticket owner as a Contact.
- Before draft generation, the operator selects delivery or self-pickup, receiver, and applicable dispatch or pickup location.
- **Save Draft**, **Generate Email Draft**, and **Record External Submission** are distinct actions.
- A generated `.msg` contains the temporary tracking identifier but never proves submission or sending and never starts the response-warning timer. Beta 1.0 does not send email.
- Submission is accepted only through reviewed indexed sent communication or explicit manual confirmation without required evidence.
- Accepted submission locks the Need allocations, quantities, requested BOM values, receiver, temporary tracking identity, recipient context, and immutable requested-logistics snapshot.
- A request prepared or submitted outside SOMA receives the same normal internal and temporary identity and must reconcile to exactly one Service Request and one or more of its Needs. Missing Needs may be created through the reviewed registration.
- A known official SR7 requires canonical-format and uniqueness validation. Later communication appends evidence to the same identity; duplicate candidates require review rather than silent creation or merge.
- Missing acknowledgement produces a warning. An official SR7 may arrive alone or with zero, some, or all C10 RMAs; partial responses preserve pending quantity and later responses append positions.
- The 24-hour Needs Attention timer begins from accepted sent evidence or manual submission confirmation, not draft generation.

### 8.4 RMA obligation bridge

- One C10 RMA belongs to exactly one officially identified Spare Request and represents one two-sided obligation position rather than a physical unit or quantity container.
- Initially it represents the promise of one inbound replacement with a promised BOM.
- It may be preassigned to one compatible target Device Part Unit before receipt without fabricating a future physical unit.
- RMAs autoassign by compatible BOM, stable Device Part Unit creation order, and preserved accepted-response order. Later batches continue with the next eligible unassigned target.
- The operator may redistribute an assignment for priority; prior and new targets, reason, actor, and chronology remain audited.
- At receipt the RMA may link to at most one direct inbound Spare Part Unit. Actual inbound BOM and serial remain on that unit and may differ from the promise after review.
- Each Spare Part Unit may have zero or one origin RMA. A dismantled assembly remains the direct inbound unit while extracted components become independent units that may share its origin provenance.
- After Task outcome review the RMA references the actual return unit separately: normally the removed Device Part Unit after replacement, otherwise the inbound unit or parent assembly when unused, faulty, incompatible, or dismantled.
- Official C10 correction preserves internal identity and the former value as an immutable alias. A genuinely new authorization creates another RMA.

### 8.5 Requested and actual logistics

- Submission preserves requested delivery or self-pickup mode, intended receiver, selected dispatch or pickup location, and effective name, address, and recipient context as immutable intent.
- Actual dispatch, pickup, delivery, receipt, custody, receiver, chronology, and condition are separate append-oriented events.
- One logistics event may cover multiple RMAs or units, but every participant remains independently addressable and correctable.
- Partial and split dispatch or receipt are valid; pending RMAs and quantities retain their state.
- Actual facts may differ from requested intent. Both remain visible, and neither later master-data edits nor actual delivery rewrite the submission snapshot.
- A Dispatch Location is logistics master data, not an Infrastructure Site, even when a Site's dedicated Dispatch Location supplies the effective address.
- Local units receive no fabricated external-delivery evidence. A dismantled parent assembly retains the direct receipt; extracted units inherit provenance and record later custody independently.

### 8.6 Tasks and return-unit eligibility

- Physical Spare Part Units are reserved through Tasks, not direct Objective ownership.
- After maintenance the operator records each target and unit outcome. A successful replacement links the actual removed Device Part Unit and installed Spare Part Unit.
- The reviewed outcome determines the RMA return obligation without overwriting requested, inbound, installed, or return BOM/serial facts.
- A Fault Tag membership requires one open RMA return obligation and its one selected physical return unit.
- Eligible units include the removed Device Part Unit, an unused/faulty/incompatible inbound unit, the dismantled parent assembly, or another explicitly reviewed RMA outcome.
- Condition, apparent newness, BOM, serial, or provenance alone never establishes eligibility.
- One obligation and physical unit may occupy at most one active submitted membership at a time; a later resend follows preserved rejection history.

### 8.7 Fault Tag identity, membership, submission, and pickup origin

- Fault Tags are a mandatory Beta 1.0 primary Inventory view.
- Each draft receives immutable internal and non-reusable operator-visible tracking identities.
- Memberships may span different Service Requests, Spare Requests, temporary tracking identifiers, and RMAs.
- Each membership stores the RMA and physical-unit relationships; Spare Request, Service Request, and Device context are derived and cannot be independently contradicted.
- Current RMA and unit values remain source-owned. Accepted first submission may preserve a data-minimized immutable snapshot of values represented in the artifact.
- Draft membership remains editable until accepted first submission. Draft generation never proves sending.
- Every draft records return method. Pickup requires exactly one Dispatch Location in the pickup-origin role—the place from which units are dispatched or collected, not the warehouse destination.
- Non-pickup return creates no pickup-origin snapshot. Any destination remains separate.
- Accepted first submission locks membership and the applicable pickup-origin, recipient, and submitted display snapshot.
- Later master-data edits never rewrite that snapshot. Actual pickup is a separate event and may preserve a reviewed difference.

### 8.8 Warehouse decisions, replacement, resend, and removal

- Warehouse receipt and final acceptance or rejection are distinct per-membership stages.
- Receipt does not close the RMA obligation. Final acceptance closes it. Final rejection preserves the failed attempt, leaves the obligation unresolved, and permits a later resend.
- Final acceptance or rejection always requires explicit operator confirmation. Communication may propose any subset; manual confirmation without evidence remains valid.
- Partial processing is valid and one membership never forces another's state.
- A false submission record may be corrected back to Draft when no real submission occurred.
- A materially wrong submitted membership or pickup instruction requires one explicit correction replacement with new identities and linear `corrects/replaces` lineage.
- A genuine rejection/resend uses distinct `resend of` lineage. It is new operational history, not correction.
- Hard deletion applies only to a truly untouched manual draft. Otherwise the UI exposes Cancel, Supersede and Replace, Archive, or Create Resend according to state and dependencies.
- Archive is presentation only. Destructive preview and transaction rules preserve every independently surviving RMA, unit, ticket, location, Contact, communication, exported artifact, and audit record.

### 8.9 Manual, proposed, bulk, and correction actions

- Every supported milestone remains manually recordable without required uploaded evidence.
- Indexed communications create idempotent reviewed proposals and never mutate Inventory before acceptance.
- Bulk actions require one compatible transition and prerequisites, preview eligible and excluded targets, commit transactionally, and append one independently correctable event per target under a common batch identifier.
- A correction targets the exact accepted event or relationship, preserves the original history, and recalculates the projection.
- Entity identity remains immutable when an assignment, allocation, receipt, installation, removal, return selection, Fault Tag membership, warehouse decision, replacement, or resend relationship is corrected.
- Beta 1.0 services accept optional evidence references, but the UI exposes no manual attachment or upload control.

The complete lifecycle, cardinalities, deterministic assignment, request-origin rules, logistics snapshots, Fault Tag membership and lineage, manual and bulk alternatives, correction semantics, evidence boundary, and deletion behavior are normative in the [Inventory Lifecycle Contract](INVENTORY_LIFECYCLE.md).

## 9. Infrastructure

**Infrastructure** is the canonical workspace. `Device Manager` and `Managed Element` are not canonical Beta domain terms. Tickets, Tasks, Objectives, and Inventory use a Device Reference that may remain unregistered/external or resolve to one registered Network Element; deliberate promotion preserves its operational relationships without duplication.

The physical/organizational model is:

- A Customer Organization owns Contracts and Sites.
- A Site is one physical Datacenter and belongs to exactly one Customer Organization. Equal names or city codes across organizations remain distinct records.
- A Cloud Type is reusable—such as PRV, B2B, AMS, BES, or NFV—and appears at a Site through a distinct Cloud Deployment. Each Deployment belongs to exactly one Cloud Type and one Site.
- A registered Network Element has immutable internal identity, nonblank operational name, and exactly one physical Site. Model, serial, Rack/U placement, Cloud Deployment, and IP inventory may be completed progressively.
- Customer Organization derives through Site. A Network Element may use at most one Cloud Deployment and it must belong to that Site.
- Site contains Rooms; Room contains Racks; Rack records row and column. A Network Element may be site-level/unracked, placed in one same-Site Rack, or participate in compatible compound containment.
- A Network Element Model is reusable. Manufacturer serial is optional evidence and never relational identity.
- A Network Element supports zero-many optional IP addresses and at most one primary. IP inventory is not identity, interface modeling, reachability, connectivity, topology, or SSH.
- Network Element and compound-sub-element containment is an acyclic forest, distinct from placement, Cloud assignment, Component installation, and connectivity.
- Devices of the same Model may contain different installed Components. Components use BOM codes, immutable local physical-unit identities, optional manufacturer serials, and immutable installation/replacement events.

BOM **compatibility** with a Model and BOM **historical use** in an instance are distinct facts. Replacement events link installed and removed units, target Network Element/slot, and applicable SR, Objective, and Task. Unknown legacy facts may be registered progressively.

Beta 1.0 stores no device password, key, token, or credential-provider reference in ordinary records, Notes, evidence, audit, logs, or workbooks and exposes no device-credential control. Connectivity, topology, discovery, reachability, interfaces/ports, and SSH are excluded from 1.0.0 and are never inferred from placement, Cloud assignment, IP patterns, co-occurrence, import, or containment.

SQLite is authoritative for every Infrastructure fact and invariant. A later graph engine may exist only as a measured, rebuildable, disposable derived projection without independent authoritative writes or unique facts.

Beta 1.0 generates a versioned Infrastructure workbook family for empty device registration, human-readable current-device discovery export, and reviewed round-trip update. Imports are discovered only from one configured directory and always stage review; exports use an operator-selected destination. Same-installation round-trip identity may target updates, while foreign-installation identity is provenance/matching evidence only. Missing rows never imply deletion or unlinking. The complete normative behavior is in the [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md).

Infrastructure presentation uses a context explorer, selected-entity header, contextual actions, predictable tabs, modular summary cards, independent panes, and a collapsible activity surface for workbook jobs, reviews, warnings, and recent audited changes. The hierarchy is a projection over accepted Customer Organization, Site, placement, Cloud Deployment, containment, and Network Element relationships; the UI must not turn one convenient tree into competing domain ownership.

The reviewed vSphere interface is a directional information-architecture reference only. SOMA shall reinterpret its useful hierarchy, density, progressive disclosure, and activity patterns through the proprietary SOMA identity, larger accessible typography, clearer labelled actions, responsive behavior, and accepted domain terminology.

## 10. Dispatch Locations

- `Dispatch Site` is renamed **Dispatch Location**.
- A Dispatch Location has a name and address and represents one physical logistics location independent of customer ownership.
- Its role is operation-specific: a Spare Request may use it as delivery or self-pickup context, while a Fault Tag may use it as the pickup origin from which return units are dispatched or collected.
- A Fault Tag pickup-origin Dispatch Location is not the warehouse destination. Any known destination remains a separate logistics fact.
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

The SOMA-generated Infrastructure workbook is a separate operator-authored bulk registration/update and discovery-export format, not a fourth authoritative operational source. Omitted devices or fields carry no disappearance meaning. Its contract is defined in [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md) and [Import Contract §9](IMPORT_CONTRACT.md#9-infrastructure-workbook-import-and-export).

The exact active/deferred allowlists, discarded-column boundary, delimiters, conditional blanks, historical cutoff, source precedence, and aggregate sample evidence are normative in the [Import Contract](IMPORT_CONTRACT.md).

Current source-owned SR facts are derived field by field from the newest accepted usable observations. Historical source evidence is retained as compact meaningful allowlisted deltas with provenance and warnings, not full workbook copies or repeated unchanged values. Problem Summary revisions remain auditable. Historical view uses the surviving operational record, compact observations, and audit history; Beta 1.0 does not recreate Alpha's terminated-SR snapshot or report-finalization purge model.

After the Advanced Search inbox is configured, SOMA supports a default 10:00 daily check in the operator timezone, a configurable whole-minute schedule, schedule disablement, one missed-boundary startup catch-up, and an always-available **Check now** action. Scheduled discovery never opens a file picker and never bypasses staging, required review, or configured safe-auto-accept rules.

The default historical lookback is one month and is configurable. Terminal source rows older than that boundary are excluded using the trusted source-specific recency field; active, future, and unscheduled work is not discarded by this rule.

Population matches immutable official identities and updates source-owned fields. It must preserve local notes, relationships, Objectives, inventory and infrastructure links, review results, audit history, and other SOMA-owned meaning.

Imports are reviewed by default. The operator may opt into automatic acceptance of safe new data per source/change class. Identity changes, hierarchy or ownership changes, WFM reassignment, time conflicts, terminal-state correction, supported authoritative-population disappearance, deletion, and hardware serial contradictions always require review. RFC/WFM omission is never such an authoritative-population disappearance.

Every import presents a pre-mutation proposal summary with source-appropriate counts and conflicts. Absence is meaningful only for a declared authoritative scope. An empty authoritative population affecting existing in-scope records always requires confirmation bound to the exact source identity and remains nondestructive. Nonempty count and Customer Organization distribution comparisons are informational in Beta 1.0 and do not alone trigger automatic acceptance or rejection.

Workbook validation and logical fingerprinting establish structural and processing integrity, not proof that an unsigned source was published by a particular person or remained unedited.

Advanced Search requires only SRNo as its universal identity header. New SRs may remain incomplete, and later usable source values fill missing facts without changing identity. Import capture time is never substituted for a missing Report Date and cannot become SLA evidence. Incomplete records remain visible; workflows validate additional facts only when genuinely required. Product remains discarded and Current Handler remains optional source-owned information.

An imported source cannot correct an official identity in place. Identity reconciliation is an explicit audited operation.

## 12. Offline mail evidence

The complete normative lifecycle is defined by the [Communications Contract](COMMUNICATIONS_CONTRACT.md).

SOMA does not connect to an email service and cannot send or receive mail directly. It reads configured PST/OST Communication Source Scopes without modifying them and generates MSG drafts for the operator to send through an external application. Saving or exporting a draft does not prove sending.

Automatic Communication Processing is eligible only after at least one registered trackable operational entity exists. Infrastructure or descriptive Device records alone do not activate it. The registry includes supported SR/TT, Spare Request, RMA/C10, RFC, WFM, Objective, and Fault Tag identities and aliases. Initial scanning is bounded by the earliest relevant accepted creation/report boundary, then continues incrementally from durable per-scope high-water marks with overlap. An older added target may request a bounded targeted backfill; Deep Scan is an explicit scoped operator action.

Only matched communications persist. Each retained communication is canonical within its Communication Source Scope, may link independently to multiple operational entities, stores structured participant roles, and uses a provider-stable origin identifier or a versioned collision-safe fallback. Entity links carry matching and review facts rather than duplicate message bodies. Communication-derived proposals require review and never write domain state implicitly.

One local fetch-and-match pipeline runs hourly by default, using a configurable positive whole-minute interval or an explicit disabled setting. Check now, one bounded catch-up, non-overlap, progress, phase/count reporting, cancellation, bounded retry, restart-safe checkpoints, and redacted diagnostics are required. Advanced Search synchronization, communication processing, communication-derived proposal acceptance, and local MSG draft persistence remain independent workflows with no implicit cross-write.

Accepted terminal SR or RFC state removes its direct communication links. A retained communication that then has no remaining protected operational dependency enters **Orphaned — Pending Purge** for a configurable positive installation-level grace period of seven exact elapsed days by default. Restoring a protected link cancels pending purge. At expiry SOMA transactionally revalidates dependencies before purging reconstructable content, while preserving a non-reconstructable purge record and frozen minimal terminal summary. It never modifies external PST/OST stores, exported MSG files, portable exports, or existing backups. Reversal after purge may use targeted backfill when the source remains available; otherwise the workbench exposes a coverage warning.

Service Request, Spare Request, and RFC views distinguish received and sent counts, direction, last-interaction age, coverage/warnings, and canonical-message navigation without copying bodies. Terminal SR/RFC views retain their frozen minimal summary even after the body is purged. Beta 1.0 persistence accepts optional communication evidence references but exposes no attachment/upload control; manual domain actions remain valid without evidence.

## 13. Contract Product Lines and SLA

Contract Product Line classification, SLA calculation, warnings, and reporting are core product capabilities, not an optional reporting add-on. Each Contract belongs to exactly one Customer Organization. Product Lines such as IT and NFV are reusable definitions, but every occurrence inside a Contract is a distinct Contract Product Line that owns its customer-and-contract-specific SLA policy; two customers may therefore apply different policies to the same Product Line. An SLA tier measures the percentage of an eligible Service Request cohort resolved or closed within an inclusive duration; it is not a percentage of one ticket's allowed time. Each SR has at most one active Contract Product Line classification, and its Contract must belong to the SR's resolved Customer Organization. Automatic import classification must be deterministic and based only on trusted allowlisted evidence; unresolved, ambiguous, unmatched, or cross-customer proposals remain unclassified for review, and the discarded Advanced Search `Product` field never selects a policy. Manual reclassification is audited. An accepted policy revision recalculates every existing SR under that Contract Product Line, including older and terminal SRs; completed report snapshots remain immutable, while every later view and report uses the revised policy. The confirmed IT/NFV templates, Non-fault inquiry derivation, cancelled exclusion, and normative calculation rules are in the [Contract Product Line and SLA Contract](PRODUCT_LINE_SLA.md).

Warning presentation keeps classification, individual duration evidence, cohort compliance, suspension, source integrity, and terminal state as separate dimensions. A currently suspended SR receives a distinct suspension-ending-soon warning when its valid future planned end enters the configured noncontractual threshold. Individual duration evidence is never mislabeled as failure of a percentage-based cohort tier, and every warning uses text and/or iconography in addition to color.

## 14. Audit and deletion principles

The [Foundation Runtime, Persistence, Audit, and Verification Contract](FOUNDATION_RUNTIME_CONTRACT.md) governs the separation of lifecycle evidence, application audit, proposal/job history, and technical diagnostics; atomic mutation/event/audit commitment; append-only `audit_events`; and named/versioned minimal audit payloads.

- Imported facts retain source and import-run provenance.
- Material manual changes record when, what, and why.
- Derived states are recalculated from source facts and policy rather than silently persisted as independent truth.
- Destructive cascades require impact preview and confirmation.
- Hard deletion is restricted to untouched manual records with no imported/adopted provenance, executed Objective, communication, review, spare-use, lifecycle, or dependent history.
- Removing a Task from an unexecuted Objective is allowed only when the Objective retains at least one Task, or when the complete untouched Objective is removed atomically.
- Business history is preserved when a relationship changes.
- Beta 1.0.0 provides Historical views and archive-safe presentation and no general purge of operational domain records. The narrow orphaned-communication content transition in section 12 is the only elapsed-time operational-content exception; it preserves domain records, link/purge history, and the frozen terminal summary.
- Report completion, terminal status, source disappearance, source age, inactivity, or elapsed time never finalizes or minimizes domain records in Beta 1.0. Movement to Historical view is presentation only. Accepted SR/RFC termination may remove direct communication links and begin the section 12 orphan grace only when no protected link remains. Alpha's 180-day record timer, terminated-episode snapshot, 27-field final snapshot, and general report-triggered cleanup are not Beta behavior.
- Technical cache reconstruction, temporary staging cleanup, diagnostic-log rotation, and verified backup rotation are separate from operational-history retention.
- Beta 1.0 exposes no general operational-record retention countdown, due timestamp, scheduled purge, per-user retention, postponement, or legal-hold control. Daily/Weekly/Monthly affects main-view visibility only. The section 12 installation-level orphan grace is a domain-specific positive timer, seven exact elapsed days by default, and does not authorize broader retention. Any broader policy requires a new accepted contract rather than inheriting Alpha's 180-day default.

## 15. 1.0.0 acceptance boundary

Beta 1.0.0 is not complete until all six work areas function together, Contract Product Line/SLA rules are enforced, supported Excel imports and exports work, the complete target-gated PST/OST processing, matching, coverage, backfill, proposal, terminal unlink, orphan grace/purge, summary, and MSG workflows work, local data is protected, the complete UI/UX Interaction Contract passes across responsive light/dark/high-contrast presentation, keyboard/pointer/touch input, hovered scroll ownership, deliberate confirmation, drafts/conflicts, accessibility, sanitized visual/export fixtures, and Windows tray behavior, and the Foundation Runtime Contract passes for SQLite connections, migrations/status, JSON, audit, local-instance trust, diagnostics/redaction, Windows/Python CI, and application acceptance.
