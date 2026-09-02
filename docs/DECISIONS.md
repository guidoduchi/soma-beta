# SOMA Beta Decision Ledger

This ledger distinguishes confirmed product decisions from deferred scope and genuinely open design work. IDs are stable references for future ADRs, issues, and pull requests.

## Confirmed

| ID | Decision |
|---|---|
| D-001 | Beta is a clean product/schema lineage in `soma-beta`; Zeus/Alpha are historical checkpoints and selective sources. |
| D-002 | Canonical navigation is Overview, Tickets, Objectives, Inventory, Infrastructure, Settings. |
| D-003 | One local authenticating user per installation; registered people are not login users. |
| D-004 | SOMA is fully local/offline in 1.0.0. |
| D-005 | The SOMA password is authentication-only and never derives or wraps encryption keys. Live data uses an independent random key protected through approved Windows-bound secure storage; exportable backups use independent authenticated encryption and a high-entropy portable recovery secret. Optional auto-login uses Windows-protected authentication material and never stores the password. |
| D-006 | WFM is a Task subtype owned by exactly one RFC, not a top-level Ticket. |
| D-007 | Objective means Maintenance Window; it requires one reviewed planned timeframe and at least one Task from creation. Every Task has its own ID. |
| D-008 | A Part Number/BOM groups parts. Every physical unit has a SOMA local identity; manufacturer serial identifies it when available but is optional. |
| D-009 | Every SR-level Spare Need aggregates matching Device Part Unit contributors by BOM across any number of Devices under one Service Request. Every persistent Spare Request record is created locally from or reconciled to selected Needs belonging to that same SR, receives a temporary tracking identity, derives Customer Organization, and retains that SR chain when official SR7 and C10 identifiers arrive. The real-world request may have been initiated outside SOMA. |
| D-010 | One C10 RMA is one two-sided obligation under one official Spare Request: it may target one Device Part Unit before receipt, later links to at most one direct inbound Spare Part Unit, and references the actual return unit separately after maintenance outcome review. No physical unit is embedded in or fabricated for the RMA. |
| D-011 | A reusable Cloud Type may appear at many Sites through distinct Cloud Deployments. Each Cloud Deployment belongs to exactly one Site; a regularized Network Element's assigned Cloud Deployment, when present, must belong to its physical Site. Network Element model and installed instance remain separate. |
| D-012 | Registering a Site creates one exclusive site-bound Dispatch Location that inherits its address. |
| D-013 | Population updates source-owned facts but preserves SOMA-owned relationships, notes, review, and history. |
| D-014 | Import review is default; safe classes may be auto-accepted, but high-risk conflicts always require review. |
| D-015 | SOMA reads PST/OST and generates MSG drafts but does not directly send or receive email. |
| D-016 | Contract Product Line classification and cohort-based SLA policy are core product capabilities. A Contract belongs to one Customer Organization; Product Line definitions are reusable, but each Contract Product Line owns its customer-and-contract-specific policy. Therefore different customers may apply different policies to the same Product Line. Each tier is a required cohort percentage within an inclusive duration, never a percentage of one ticket's deadline. An accepted policy revision recalculates every existing classified SR, including earlier and terminal SRs; completed report snapshots remain immutable while subsequent results use the revision. IT and NFV templates are confirmed; Cancelled SRs are excluded; Alpha's global age-risk and suspension-KPI severity schedules do not control Beta 1.0. |
| D-017 | Dependencies are deliberately minimal, pinned, auditable, and adapter-isolated—nearly dependency-free, not zero-dependency. |
| D-018 | Canonical SOMA logo, wordmark, colors, app icon, and tray icon carry forward under the brand contract. |
| D-019 | 1.0.0 includes responsive English UI, light/dark themes, and Windows tray behavior. |
| D-020 | Excel is the 1.0.0 report export format. |
| D-021 | Operator dates use `America/Guayaquil`, Monday–Sunday weeks, and UTC instant storage. |
| D-022 | RFC hierarchy is exactly two levels. A subordinate RFC cannot own subordinates or act as a master; direct SR↔RFC links target masters only. Local Task links are governed separately by D-024 and D-046. |
| D-023 | Master/subordinate WFM role is derived from the WFM's owning RFC, not stored as an independently editable hierarchy. |
| D-024 | A Task is either Local or WFM. Local Tasks may link to zero or many SRs, master or subordinate RFCs, Spare Part Units, and Network Elements; a WFM retains exactly one RFC owner. |
| D-025 | SR context reaches an Objective exclusively through its Tasks. One SR may participate in multiple unfinished Objectives; a Task belongs to at most one. |
| D-026 | Planned and actual Objective intervals are separate. Retry creates a new Task attempt: a Local Task receives a new local Task ID and a WFM receives a new Task No. Objective predecessor/successor context is derived from those Task attempts and normal overlap grouping. |
| D-027 | Hard deletion is limited to untouched manual RFCs/WFMs/Objectives with no import/adoption or protected operational evidence; otherwise history-preserving lifecycle transitions apply. |
| D-028 | Requested quantity `N` under one SR7 may yield `M ≤ N` C10 RMA positions; every rejected or unfulfilled position retains its outcome and reason. |
| D-029 | Each Site is one physical Datacenter owned by exactly one Customer Organization. Equal Site names or city codes across organizations remain distinct. Reusable Cloud Types appear at Sites through distinct site-bound Cloud Deployments, and a regularized Network Element derives its organization through its Site. |
| D-030 | Inventory's primary views are Stock, Spare Requests, and Fault Tags; Fault Tags are part of the Spare Request return lifecycle. |
| D-031 | Explicit Beta decisions supersede conflicting Alpha behavior, including navigation, manual SR creation, Task relationships, C10/RMA semantics, Dispatch Locations, and offline mail boundaries. |
| D-032 | Ticket workbenches open by double-click or keyboard Enter and use a left tabbed work area plus right local-email-evidence preview. |
| D-033 | Registered and unregistered device references are both valid operationally; a deliberate three-second pointer/touch/keyboard hold promotes a reference into Infrastructure without duplicating it. |
| D-034 | Spare Needs are reusable SR-level BOM aggregates rather than device-level duplicates. Device Part Units contribute derived demand; matching Stock is suggested first, but the operator may use local units, request externally, combine both by quantity, or request despite local availability. |
| D-035 | Device Part Units and Inventory Spare Part Units are separate physical entities. The reviewed Task outcome links the actual removed and installed units and determines which unit the RMA requires back; unused, faulty, incompatible, and dismantled inbound outcomes retain distinct return behavior. |
| D-036 | Actual received BOM may differ from requested BOM. Valid alternatives require reviewed compatibility; invalid units cannot be installed. |
| D-037 | Dismantled assemblies retain a parent disposition while extracted components receive individual local identities and per-device installation history. |
| D-038 | Future noncancelled scheduled Tasks enter reviewed Objective grouping; overlaps consolidate, unscheduled Tasks create no Objective, and accepted Objectives cannot overlap. |
| D-039 | Weekly is the default ticket period with Daily/Monthly alternatives; terminal tickets then remain in Historical view. Terminal import rows older than the configurable one-month default lookback are excluded. |
| D-040 | A manually created SR receives `LSR-` plus an eight-digit local sequence beginning at `00000001`; official reconciliation is reviewed. |
| D-041 | Each official workbook has an explicit active/deferred allowlist. Every other source column is discarded and cannot influence Beta behavior. |
| D-042 | An initially blank SR Suspension Duration means zero/no reported suspension; a later blank or zero conflicting with accepted nonzero evidence requires review. Suspend Planned End is active only for a currently suspended SR with a future end. Blank WFM Dispatch Progress is valid for Plan Cancel. |
| D-043 | WFM Customer Organization is an active reviewed reconciliation hint; Enhanced Excel remains authoritative for populated RFC facts. |
| D-044 | Contacts exist independently and may optionally belong to a Customer Organization. |
| D-045 | Beta 1.0.0 has no purge of operational history. |
| D-046 | A Local Task may be created under a master or subordinate RFC; the two-level RFC hierarchy invariant remains unchanged. |
| D-047 | Current source-owned SR facts use the newest accepted usable observation per field. Historical source evidence is stored as compact meaningful allowlisted deltas with provenance and warnings, never complete workbook copies, discarded Product, repeated unchanged values, or Alpha terminated-SR snapshots. |
| D-048 | Contact communication channels are optional for ordinary operational work. A recipient channel is required only by the communication action that uses it; failure blocks that action alone, and generated artifacts preserve the effective recipient evidence. |
| D-049 | Once its inbox is configured, Advanced Search supports an enabled-by-default 10:00 operator-timezone daily check, whole-minute configuration or disablement, one startup catch-up, and always-available manual checking. Scheduled invocation creates staging and cannot bypass review or safe-auto-accept policy. |
| D-050 | Recognized terminal SR status suppresses active-work and live SLA-risk reminders while preserving history. Resolved/Closed SRs retain applicable cohort evidence; Cancelled SRs are excluded. Overview/Needs Attention remain primary, and supplemental same-condition local notifications are limited to once per operator-local day across restarts. |
| D-051 | Beta replaces Alpha's single expiration/removal risk taxonomy with independent accessible dimensions for SLA classification, individual duration evidence, cohort compliance, suspension, source integrity, and terminal state. A valid future suspension end has a distinct configurable noncontractual ending-soon warning; individual duration evidence is not itself failure of a percentage tier. |
| D-052 | Daily, Weekly, and Monthly Excel reports use one consistent, data-minimized snapshot scoped to one Customer Organization or all organizations. Successful verified artifacts create immutable completed evidence; later drift affects only current and future reports. Failed/cancelled generation changes no operational state, and Beta 1.0 offers no report-triggered cleanup. |
| D-053 | Beta 1.0 has no report-, status-, disappearance-, age-, inactivity-, or timer-driven operational finalization or purge. Historical placement is presentation only. Alpha's immediate cleanup, 180-day timer, and 27-field final snapshot are rejected; any Beta 1.1 purge requires a new accepted contract and migration plan. |
| D-054 | Beta starts an independent clean schema and migration lineage. Alpha migrations and databases are not executed or upgraded. Accepted Beta migrations become immutable and later corrections are forward-only; schema and ledger commit atomically, with exact runner mechanics assigned to the LLD. |
| D-055 | All official imports expose proposal-oriented impact summaries before mutation. Absence is inferred only for declared authoritative scope; an empty authoritative population with prior records requires exact-source high-risk confirmation and remains nondestructive. Beta 1.0 shows nonempty population/distribution comparisons but uses no unvalidated numeric acceptance threshold. |
| D-056 | Advanced Search requires only SRNo universally. New SRs may remain incomplete; missing or unusable nonidentity facts preserve prior accepted values. Import capture time never becomes a synthetic Report Date or SLA evidence. Incomplete records remain visible and validate additional facts only at point of use. |
| D-057 | One official SRNo identifies one surviving Beta SR; there are no finalized episodes or tombstones. Terminal reversal is a high-risk same-record correction requiring explicit confirmation, preserved terminal history, and current recalculation. Unsigned workbook checks prove processing integrity, not publisher authenticity or absence of editing. |
| D-058 | Beta 1.0 has no operational retention clock or purge Settings. Daily/Weekly/Monthly controls main-view presentation only. Operational retention is installation-level governance; technical housekeeping is separate, and any Beta 1.1 policy must define its own scope, timing, dependencies, exceptions/holds, recovery, and audit without inheriting Alpha defaults. |
| D-059 | Single-user login requires only the Local Administrator password; stable actor identity is generated, display name is editable, username-like metadata is optional, and operational email/phone belong to Contacts. Live and backup encryption remain credential-independent. Managed backups default to five and prune only after verified replacement without deleting portable exports or the last restorable copy. |

| D-060 | Incremental SR7/C10 responses are valid. RMAs autoassign to compatible unassigned Device Part Units by stable target creation order and preserved response order; later batches continue the sequence, and audited manual redistribution supports operational priority without rewriting source evidence. |
| D-061 | Spare Request acknowledgement, partial RMA authorization, per-item dispatch, receipt, Task use, Fault Tag generation, warehouse receipt, and warehouse acceptance/rejection are distinct milestones. A genuine rejection/resend reopens the return obligation as new history; rollback corrects an erroneous recorded milestone. |
| D-062 | Fault Tags may group return obligations and physical units from different Service Requests, Spare Requests, temporary tracking identifiers, and RMAs. Warehouse receipt does not equal final acceptance. |
| D-063 | Beta 1.0 persistence and application services accept optional evidence references, and indexed PST/OST communications may supply them. Manual Inventory actions require no evidence, and Beta 1.0 exposes no manual attachment or upload control anywhere in the UI. |
| D-064 | Every supported Inventory milestone remains manually recordable. Communication detection creates reviewed idempotent proposals only. Compatible bulk actions preview eligibility and consequences, commit transactionally, and create one independently correctable event per target under a common batch identity. |
| D-065 | Saving a Spare Request draft, generating a `.msg`, and accepting submission are distinct. Draft generation never proves sending or starts the response timer. A request prepared or submitted outside SOMA is registered with normal SOMA and temporary identities and reviewed reconciliation to one Service Request and its Needs. |
| D-066 | Inventory entities and accepted events have immutable internal identities. Correction targets the exact disputed event or relationship, preserves original evidence, and may replace only the relationship effect. Similar external identifiers, BOMs, serials, or labels never authorize silent identity merge or reassignment. |
| D-067 | Accepted submission preserves requested delivery/self-pickup intent separately from actual dispatch, pickup, delivery, receipt, and custody events. Shared logistics events may cover multiple RMAs or units while every participant remains independently addressable; partial progress and requested-versus-actual differences remain visible. |

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
| F-008 | Local-Task MOP generation from reviewed DOCX templates | 1.1.0 |
| F-009 | Operational-data purge policies | 1.1.0 |

## Open for HLD/LLD review

Open items are not permission to choose silently.

| ID | Question | Required before |
|---|---|---|
| O-001 | Are Overview/report snapshots persisted internally, generated on demand, or both? | Reporting schema LLD |
| O-003 | Which exact Objective/Task outcome transitions and correction reasons are valid within the confirmed new-identity retry model? | Objective state-machine LLD |
| O-004 | Which library and supported subset provide safe PST/OST read and MSG generation? | Communications adapter ADR |
| O-005 | Which database/encryption design, KDF parameters, recovery, rotation, backup, and export-protection policy satisfy the threat model? | Persistence/security LLD |
| O-006 | What Windows, Python, and embedded/supported browser versions form the 1.0.0 support matrix? | Packaging ADR |
| O-007 | Which field-level changes inside the accepted Import Contract allowlists qualify as safe auto-accept? | Import reconciliation LLD |
| O-010 | What exact tray actions and background lifecycle are supported? | Windows shell UX/packaging LLD |

## Resolved former open items

| ID | Resolution |
|---|---|
| O-002 | Resolved by D-039: Weekly is the default; Daily and Monthly remain selectable. |
| O-008 | Resolved by D-040 and the Workbench Contract. |
| O-009 | Resolved for 1.0.0 by D-045; purge policy is deferred as F-009. |

## Decision process

A material technical choice becomes an Architecture Decision Record only after it is checked against the Product Contract. An ADR may explain *how* to satisfy a product rule; it may not weaken or replace the rule without an explicit product-contract change.
