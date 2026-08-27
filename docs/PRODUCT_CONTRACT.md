# SOMA Beta Product Contract

Status: **Foundation draft v0.1**  
Target: **SOMA Beta 1.0.0**  
Authority: confirmed product decisions; unresolved items are listed in `DECISIONS.md` and are not implementation permission.

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
- Registered people are operational/business records and do not receive login profiles.
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

Tickets contains **Service Requests (SRs)** and **Requests for Change (RFCs)**.

- An SR may link to many RFCs; an SR view shows those RFCs nested beneath it.
- An RFC may link to an SR and contains its WFM Tasks.
- A record is stored once even when presented through several related views.
- Everything may exist without an SR, except entities whose rules explicitly require one. When an SR exists, it is the pivotal connection between work, spares, and infrastructure evidence.

### 6.1 Service Requests

- Official SR identity is exactly eight digits.
- An SR can be created manually.
- If its official ID is supplied, a later Advanced Search import populates the same record.
- If omitted, SOMA generates a local SR identity. Later reconciliation to an official SR requires an explicit operator-reviewed mapping; SOMA does not guess.

### 6.2 Requests for Change

- Official RFC identity is `NC` followed by fourteen digits.
- Master/subordinate RFC rules are preserved. SR relationships normally attach to the master RFC and are inherited by its subordinate view where applicable.
- Correcting a provisional, manually created RFC identity must not rewrite historical identity silently.

### 6.3 WFM Tasks

- A WFM is a Huawei-generated **Task subtype**, never a third top-level Ticket type.
- Official WFM Task identity is `TK` followed by fourteen digits.
- A WFM belongs to exactly one RFC and at most one Objective.
- Registering a WFM requires Task No. and RFC No. If the RFC exists, Task Name is inherited from the RFC Summary. If it does not exist, Task Name is also required and creates a provisional parent RFC with that summary.
- Correcting the parent RFC of a manually registered WFM prompts the operator either to remove the now-unused provisional RFC or leave it orphaned; no silent deletion occurs.
- Deleting a WFM deletes only that WFM. Deleting an RFC requires explicit confirmation and deletes its assigned WFMs.

## 7. Objectives and Tasks

An **Objective** is a Maintenance Window composed of Tasks in one reviewed timeframe.

- A new Objective requires a timeframe.
- A draft Objective may be temporarily empty; a non-draft Objective has one or more Tasks.
- A Task is first-class and has its own identity.
- A local Task requires only a Task Name from the operator; it may be standalone or link to an SR, RFC, Infrastructure item, Inventory item, or a valid combination.
- A local Task created inside an Objective inherits the Objective **timeframe**, not its identity.
- Every Task assigned to an Objective uses the Objective timeframe.
- A Task belongs to at most one Objective.
- Cloning a local Task creates a new Task identity and may place it in a new timeframe/Objective.

When an Objective timeframe is selected, SOMA locates available WFM Tasks whose authoritative WFM planned windows overlap it. An unplanned WFM may inherit the Objective window. A WFM with a conflicting established window requires explicit rescheduling review; SOMA never overwrites it silently.

Task outcomes are reviewed individually. Retrying work preserves the original attempt and outcome; the exact retry decision table remains a low-level design item.

If one or more Tasks link to SRs, the Objective suggests the union of spares related to those SRs. The operator may also attach any other eligible spare to the Objective.

## 8. Inventory

### 8.1 Catalog and physical identity

- A **Part Number/BOM code** is the catalog and grouping unit.
- A **Spare Part Unit** is a physical item identified by serial number.
- Inventory shows quantities by BOM and state, while preserving unit-level identity and history.
- Installing a unit removes it from available stock but retains it as an installed Infrastructure component.
- Removing a unit requires a disposition; it never silently returns to available stock.

### 8.2 Spare Needs

A Spare Need is mandatorily linked to an open or registered SR and may target a device, BOM, or slot. It may be fulfilled by an official Spare Request or by an eligible unit already in stock. Linking a Spare Need to a device also establishes which replacement was performed under which SR.

### 8.3 Spare Requests and RMAs

- Official Spare Request identity is `SR` followed by seven digits.
- Every official Spare Request is linked to a Service Request.
- One Spare Request has one or more RMAs.
- An RMA identity is `C` followed by ten digits.
- One RMA belongs to exactly one Spare Request and represents exactly one ordered BOM position.
- Before receipt, an RMA may have no physical serial. At Received state it has exactly one received serial number and the resulting unit initially has condition `new`.
- An RMA can record the serial number returned to the supplier.
- The return serial equals the received serial only when that same unit is returned, such as unused, incompatible, or dead-on-arrival stock.
- If a different replaced unit should be returned and its serial is unavailable, SOMA records `unknown` plus a reason; it never copies the received serial as fabricated evidence.
- RMA logistics state and Spare Part Unit condition/location are separate concepts.

Contradictory Service Request relationships are blocked or corrected through an audited review. A manually registered Spare Part Unit may be confirmed installed without an SR, but SOMA shows a warning and requires explicit acknowledgment.

## 9. Infrastructure

The physical/organizational model is:

- Customer Organization owns Clouds.
- Clouds and Sites have a many-to-many relationship: a Cloud may span Sites and a Site may host Clouds.
- A Site means a datacenter.
- Site contains Rooms; Room contains Racks; Rack records row and column.
- A Network Element is an installed device instance and may be standalone/unplaced or located in a Rack.
- A Network Element Model is reusable across customers and device instances.
- Devices of the same model may contain different installed Components.
- A Network Element may contain compound sub-elements; circular containment is invalid.
- Components use BOM codes, physical unit serials, and immutable installation/replacement events.

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

## 13. Product Line and SLA

Product Line classification, SLA calculation, warnings, and reporting are core product capabilities, not an optional reporting add-on. The normative rules are in [Product Line and SLA Contract](PRODUCT_LINE_SLA.md).

## 14. Audit and deletion principles

- Imported facts retain source and import-run provenance.
- Material manual changes record when, what, and why.
- Derived states are recalculated from source facts and policy rather than silently persisted as independent truth.
- Destructive cascades require impact preview and confirmation.
- Business history is preserved when a relationship changes.

## 15. 1.0.0 acceptance boundary

Beta 1.0.0 is not complete until all six work areas function together, Product Line/SLA rules are enforced, supported Excel imports and exports work, offline PST/OST and MSG workflows work, local data is protected, and the UI supports responsive light/dark operation plus Windows tray behavior.
