# SOMA Beta Decision Ledger

This ledger distinguishes confirmed product decisions from deferred scope and genuinely open design work. IDs are stable references for future ADRs, issues, and pull requests.

## Confirmed

| ID | Decision |
|---|---|
| D-001 | Beta is a clean product/schema lineage in `soma-beta`; Zeus/Alpha are historical checkpoints and selective sources. |
| D-002 | Canonical navigation is Overview, Tickets, Objectives, Inventory, Infrastructure, Settings. |
| D-003 | One local authenticating user per installation; registered people are not login users. |
| D-004 | SOMA is fully local/offline in 1.0.0. |
| D-005 | Password-derived key wrapping protects a random data key; optional auto-login uses Windows user protection, never a plaintext password. |
| D-006 | WFM is a Task subtype owned by exactly one RFC, not a top-level Ticket. |
| D-007 | Objective means Maintenance Window; it requires one reviewed planned timeframe and at least one Task from creation. Every Task has its own ID. |
| D-008 | A Part Number/BOM groups parts; a serial identifies a physical Spare Part Unit. |
| D-009 | Spare Need requires an SR; official Spare Request/RMA flows also require their SR relationship. |
| D-010 | One C10 RMA is one accepted BOM position under one Spare Request and yields exactly one received serial at receipt; it is not a quantity container. |
| D-011 | Cloud–Site is many-to-many; Network Element model and installed instance are separate. |
| D-012 | Registering a Site creates one exclusive site-bound Dispatch Location that inherits its address. |
| D-013 | Population updates source-owned facts but preserves SOMA-owned relationships, notes, review, and history. |
| D-014 | Import review is default; safe classes may be auto-accepted, but high-risk conflicts always require review. |
| D-015 | SOMA reads PST/OST and generates MSG drafts but does not directly send or receive email. |
| D-016 | Product Line and SLA policy are core product capabilities. |
| D-017 | Dependencies are deliberately minimal, pinned, auditable, and adapter-isolated—nearly dependency-free, not zero-dependency. |
| D-018 | Canonical SOMA logo, wordmark, colors, app icon, and tray icon carry forward under the brand contract. |
| D-019 | 1.0.0 includes responsive English UI, light/dark themes, and Windows tray behavior. |
| D-020 | Excel is the 1.0.0 report export format. |
| D-021 | Operator dates use `America/Guayaquil`, Monday–Sunday weeks, and UTC instant storage. |
| D-022 | RFC hierarchy is exactly two levels. A subordinate RFC cannot own subordinates or act as a master; direct SR and Local Task RFC links target masters only. |
| D-023 | Master/subordinate WFM role is derived from the WFM's owning RFC, not stored as an independently editable hierarchy. |
| D-024 | A Task is either Local or WFM. Local Tasks may link to zero or many SRs, master RFCs, Spare Part Units, and Network Elements; a WFM retains exactly one RFC owner. |
| D-025 | SR context reaches an Objective exclusively through its Tasks. One SR may participate in multiple unfinished Objectives; a Task belongs to at most one. |
| D-026 | Planned and actual Objective intervals are separate. Objective retry creates a new Objective; Local Task clone creates a new Task ID; a new WFM attempt uses a new Task No. |
| D-027 | Hard deletion is limited to untouched manual RFCs/WFMs/Objectives with no import/adoption or protected operational evidence; otherwise history-preserving lifecycle transitions apply. |
| D-028 | Requested quantity `N` under one SR7 may yield `M ≤ N` C10 RMA positions; every rejected or unfulfilled position retains its outcome and reason. |
| D-029 | Sites are customer-neutral physical datacenters. Customer/Cloud/Network Element responsibility is explicit and is not inferred from Site placement. |
| D-030 | Inventory's primary views are Stock, Spare Requests, and Fault Tags; Fault Tags are part of the Spare Request return lifecycle. |
| D-031 | Explicit Beta decisions supersede conflicting Alpha behavior, including navigation, manual SR creation, Task relationships, C10/RMA semantics, Dispatch Locations, and offline mail boundaries. |

## Deferred beyond 1.0.0

| ID | Deferred capability | Earliest intent |
|---|---|---|
| F-001 | SSH/device operations | 1.x.0 |
| F-002 | Infrastructure connectivity/topology | 1.x.0 or later |
| F-003 | Language switching | 1.x.0 |
| F-004 | Shared multi-user deployment | Later product decision |
| F-005 | Direct email/cloud integrations | Later product decision |
| F-006 | Arbitrary dashboard/report builder | Later product decision |
| F-007 | Zeus/Alpha database migration | Later product decision |

## Open for HLD/LLD review

Open items are not permission to choose silently.

| ID | Question | Required before |
|---|---|---|
| O-001 | Are Overview/report snapshots persisted internally, generated on demand, or both? | Reporting schema LLD |
| O-002 | Is Weekly the installation default, with Daily/Monthly operator-selectable? | Overview UX contract |
| O-003 | Which exact Objective/Task outcome transitions and correction reasons are valid within the confirmed new-identity retry model? | Objective state-machine LLD |
| O-004 | Which library and supported subset provide safe PST/OST read and MSG generation? | Communications adapter ADR |
| O-005 | Which database/encryption design, KDF parameters, recovery, rotation, backup, and export-protection policy satisfy the threat model? | Persistence/security LLD |
| O-006 | What Windows, Python, and embedded/supported browser versions form the 1.0.0 support matrix? | Packaging ADR |
| O-007 | Which imported fields are source-owned for each official Excel layout and which changes qualify as safe auto-accept? | Import mapping contracts |
| O-008 | What local SR identity format and operator workflow reconcile it with a later official 8-digit SR? | Ticket identity LLD |
| O-009 | What retention action follows the 180-day warning: archive, export, purge, or operator choice? | Retention policy |
| O-010 | What exact tray actions and background lifecycle are supported? | Windows shell UX/packaging LLD |

## Decision process

A material technical choice becomes an Architecture Decision Record only after it is checked against the Product Contract. An ADR may explain *how* to satisfy a product rule; it may not weaken or replace the rule without an explicit product-contract change.
