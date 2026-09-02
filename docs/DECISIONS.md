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
| D-045 | Beta 1.0.0 has no general purge of operational history. The narrow communication-content minimization in D-090 preserves non-reconstructable decision/purge history and does not authorize domain-record purge. |
| D-046 | A Local Task may be created under a master or subordinate RFC; the two-level RFC hierarchy invariant remains unchanged. |
| D-047 | Current source-owned SR facts use the newest accepted usable observation per field. Historical source evidence is stored as compact meaningful allowlisted deltas with provenance and warnings, never complete workbook copies, discarded Product, repeated unchanged values, or Alpha terminated-SR snapshots. |
| D-048 | Contact communication channels are optional for ordinary operational work. A recipient channel is required only by the communication action that uses it; failure blocks that action alone, and generated artifacts preserve the effective recipient evidence. |
| D-049 | Once its inbox is configured, Advanced Search supports an enabled-by-default 10:00 operator-timezone daily check, whole-minute configuration or disablement, one startup catch-up, and always-available manual checking. Scheduled invocation creates staging and cannot bypass review or safe-auto-accept policy. |
| D-050 | Recognized terminal SR status suppresses active-work and live SLA-risk reminders while preserving history. Resolved/Closed SRs retain applicable cohort evidence; Cancelled SRs are excluded. Overview/Needs Attention remain primary, and supplemental same-condition local notifications are limited to once per operator-local day across restarts. |
| D-051 | Beta replaces Alpha's single expiration/removal risk taxonomy with independent accessible dimensions for SLA classification, individual duration evidence, cohort compliance, suspension, source integrity, and terminal state. A valid future suspension end has a distinct configurable noncontractual ending-soon warning; individual duration evidence is not itself failure of a percentage tier. |
| D-052 | Daily, Weekly, and Monthly Excel reports use one consistent, data-minimized snapshot scoped to one Customer Organization or all organizations. Successful verified artifacts create immutable completed evidence; later drift affects only current and future reports. Failed/cancelled generation changes no operational state, and Beta 1.0 offers no report-triggered cleanup. |
| D-053 | Beta 1.0 has no general report-, status-, disappearance-, age-, inactivity-, or timer-driven domain-record finalization or purge. Historical placement is presentation only. Alpha's immediate cleanup, 180-day timer, and 27-field final snapshot are rejected. D-090 is the sole narrow Beta 1.0 orphaned-communication content exception; any broader Beta 1.1 purge requires a new accepted contract and migration plan. |
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
| D-068 | Fault Tags and the complete return lifecycle are mandatory Beta 1.0 scope and one of Inventory's primary views; they do not depend on future manual-evidence upload capability. |
| D-069 | Every Fault Tag has immutable internal and visible tracking identities and projected state. Pickup uses one Dispatch Location as the origin from which returns are dispatched, not the warehouse destination; first submission locks the applicable pickup-origin snapshot. |
| D-070 | Fault Tag eligibility is determined by one open RMA return obligation and the physical unit selected through the reviewed maintenance outcome, not by condition, apparent newness, BOM, serial, or provenance alone. |
| D-071 | Every Fault Tag membership references one RMA obligation and one physical return unit. Spare Request, Service Request, and Device context are derived; current RMA/unit values are not copied as competing truth, while submitted display facts may survive in an immutable snapshot. |
| D-072 | Draft membership remains editable until accepted real submission. A false submission may be corrected back to Draft; a materially wrong actual submission requires a new correction replacement with linear `corrects/replaces` lineage. Alias-only corrections do not replace the tag. |
| D-073 | Warehouse receipt and final decision are distinct per membership. Final acceptance closes the RMA obligation; rejection leaves it unresolved for a later `resend of` attempt. Communication is optional evidence, partial processing is valid, and final acceptance/rejection requires explicit operator confirmation. |
| D-074 | Fault Tag hard deletion is limited to a truly untouched manual draft. Other states use Cancel, Supersede and Replace, Archive, or Create Resend with impact preview, transactional audit, and no cascade into independent records or exported files. |
| D-075 | Pickup-origin evidence is conditional on a pickup return method and cannot exist without exactly one selected Dispatch Location. Non-pickup methods fabricate no pickup snapshot; actual pickup remains separate, and replacement or resend attempts receive their own logistics snapshots. |


| D-076 | Infrastructure is the canonical workspace; Managed Element is retired. Device Reference is operational identity that may remain unregistered or resolve to one Network Element without relationship duplication. |
| D-077 | A registered Network Element has immutable identity, nonblank name, and one physical Site while Model, serial, Rack/U, Cloud Deployment, and other facts may be completed progressively. Placement and ownership are derived through accepted relationships; SSH credential fields are absent from 1.0. |
| D-078 | Beta 1.0 retains zero-many stored IP addresses per Network Element and at most one primary. IP is optional descriptive inventory and candidate matching evidence, not identity, connectivity, discovery, reachability, topology, or SSH. |
| D-079 | Network Element and compound-sub-element containment is an acyclic forest, distinct from physical placement, Cloud assignment, component compatibility, and connectivity. |
| D-080 | Reusable Cloud Types appear through site-bound Cloud Deployments. Each Network Element belongs to one Site and may use at most one Deployment at that Site; Customer Organization derives through Site. |
| D-081 | Connectivity remains separate from containment, placement, Cloud assignment, and IP inventory and is deferred to 1.x.0. Beta 1.0 infers no topology from proximity, co-occurrence, addressing, import, or containment. |
| D-082 | Device credentials and reusable secrets never enter ordinary persistence, Notes, evidence, audit, logs, or workbooks. Beta 1.0 exposes no device-credential control; a future capability may retain only opaque approved-provider references. |
| D-083 | SQLite is authoritative for all 1.0 operational truth. A later graph engine requires representative measurements and may only be a rebuildable, disposable, read-derived projection with no independent authoritative writes or unique facts. |
| D-084 | Beta 1.0 generates versioned Infrastructure workbooks for empty registration, human-readable device discovery, and reviewed round-trip update. Imports come only from one configured directory, stage every mutation, preserve absence nondestructively, scope update identity to its source installation, prohibit credentials/topology, and remain idempotent; exports go to an operator-selected location. |


| D-085 | PST/OST processing remains idle until one accepted supported trackable entity exists. Configuration, proposals, Devices/Infrastructure, and workbook exchange alone never activate message reads. |
| D-086 | Communication trackability uses Beta Ticket/Inventory/Objective/Fault Tag identities and RMA aliases; descriptive customer/device/hardware/location facts are never communication identity, and terminated SR/RFC identities stop direct matching while remaining historical suppression facts. |
| D-087 | Initial mail coverage derives from accepted domain chronology without fabricated times; later progress uses exact source/folder/profile high-water state, bounded idempotent overlap, and successful durable advancement only. |
| D-088 | Older identities receive exact bounded targeted backfill; every Deep Scan is explicit. Historical coverage is separate from forward progress and partial work claims only durable completed ranges. |
| D-089 | Only accepted/safely matched communications persist. One canonical message may have many independently correctable entity links; unmatched/rejected content leaves only bounded non-reconstructable processing/decision evidence. |
| D-090 | Accepted SR/RFC termination removes only its direct communication links. A genuinely dependency-free communication enters configurable positive **Orphaned — Pending Purge** grace, default seven exact elapsed days; restored dependencies cancel it and due purge revalidates transactionally before removing reconstructable content. This is a narrow communication-content exception to Beta 1.0's no-general-operational-purge rule. |
| D-091 | Ordinary local PST/OST source reading and matching are one hourly-by-default configurable pipeline with one catch-up and nonoverlapping jobs. Backfill/Deep Scan and orphan housekeeping remain separate; scheduling never accepts lifecycle effects. |
| D-092 | Retained message uniqueness is Communication-Source-Scope scoped and path/folder independent. Participants are structured role evidence, not Contact identity, and JSON is optional versioned serialization rather than the domain contract. |
| D-093 | Stable provider-origin identity is preferred; fallback identity is versioned, deterministic, collision-safe, and non-authenticating. Stronger later identity preserves aliases/internal identity, and MSG draft identity never proves sending. |
| D-094 | Long communication work uses inspectable nonblocking jobs with honest progress, safe checkpoint cancellation, durable restart behavior, bounded idempotent transient retry, and non-reconstructable redacted diagnostics. |
| D-095 | Communication processing, official imports, Infrastructure workbook exchange, MSG generation, and orphan housekeeping own independent jobs/transactions/state; cooperation uses explicit services/proposals and no implicit cross-write. |
| D-096 | Trackable views show deduplicated direction/count/last-interaction and coverage summaries from canonical links. Drafts do not count; unknown chronology/coverage stays visible; terminated SR/RFC views keep only a frozen non-reconstructable terminal summary. |
| D-097 | Selection, active row, focus, multi-selection, and opened record are distinct. Single click selects, double-click/Enter opens, and wheel/trackpad scrolls the nearest hovered scrollable surface without chaining into another pane at its boundary. |
| D-098 | Autocomplete is deliberately query- or disclosure-triggered, bounded, internally hovered-scrollable, accessible, stale-result-safe, and never turns typed/highlighted text into an entity or relationship without explicit acceptance. |
| D-099 | Responsive layouts preserve complete capability, state, panes, tables, overlays, drafts, and accessible labels. Three-second deliberate hold is an allowlisted confirmation tier—mandatory for Device Reference promotion and optional after impact preview for approved consequential actions—not universal ritual friction. |
| D-100 | One semantic token system governs typography, status, focus, dialogs, themes, contrast, and purposeful reduced motion. Color/blinking never carries sole meaning, and game-inspired presentation remains subordinate to operational truth. |
| D-101 | Unsaved UI working copies, persistent domain Draft entities, and accepted history are distinct. Selective save must be transaction-valid, stale drafts never overwrite, and generic Undo applies only to safe bounded inverses rather than immutable evidence. |
| D-102 | SR dashboards derive Customer, communication, Inventory, Objective, SLA, and main-view summaries from owning domains. `Resolved Status Date` remains discarded and cannot be reconstructed or replaced by unrelated chronology. |
| D-103 | Inventory actions are lifecycle-contextual; compatible bulk work is preflighted with per-target results; manual paths survive absent evidence; export is not transition; and every valid nonterminal state exposes continuation or actionable remediation. |
| D-104 | UI evidence is classified as directional reference, visual fixture, or export golden. vSphere is approved only as information-architecture inspiration; SOMA copies no third-party assets/trade dress and pixel/artifact acceptance uses sanitized versioned deterministic fixtures rather than guesses. |
| D-105 | Every authoritative SQLite connection uses one verified foreign-key-enabled factory, and child-side foreign-key paths have effective leading-prefix index coverage; isolated rebuild exceptions receive post-checks. |
| D-106 | Migration schema/data and ledger commit atomically under one data-instance migrator; concurrent startup, interruption, retry, and readiness checks cannot publish partial or duplicate migration state. |
| D-107 | Branch-only migration candidates remain editable until primary-branch acceptance, when canonical bytes, name/order/content/checksum/manifest freeze; accepted correction is forward-only and drift is never hidden. |
| D-108 | Migration status is purely observational and creates or mutates no database, sidecar, directory, lock, settings, or invalid target; unsafe live/offline inspection reports limitation rather than disturbing ownership. |
| D-109 | Domain lifecycle evidence, application audit, proposal/job history, and technical diagnostics are separate authorities. Required mutation, lifecycle evidence, and audit commit together, while corrections append against exact identities. |
| D-110 | Persisted JSON is typed, named, versioned, bounded, semantically validated, atomically written/upgraded, and never substitutes for normalized domain authority; UI working copies and domain Drafts remain distinct. |
| D-111 | Automated verification proves identifiers, hierarchies, immutability, lifecycles, referential/schema/migration integrity, and every governed import/export including Infrastructure Device workbook discovery and round trip; percentage coverage alone is insufficient. |
| D-112 | Required Windows CI covers Python 3.13 and 3.14 on the current revision. Drafts retain a fast safety subset; stale/cancelled/missing results never pass, primary/release runs are complete, and representative desktop acceptance supplements hosted CI. |
| D-113 | Application acceptance covers keyboard/pointer/touch, hovered-pane scrolling, responsive/focus/reduced-motion/semantic behavior, proposal review, and confirmation tiers. The three-second Device hold has an accessible deliberate equivalent and never replaces necessary impact preview. |
| D-114 | Local startup proves canonical data-instance ownership, per-run process/birth/health identity, exact loopback origin, and request authority before serving; proxy/redirect/forged-registry/port/PID confusion cannot authorize activation or shutdown. |
| D-115 | Structured bounded technical diagnostics live outside SQLite and are fail-open only for emission: logger failure does not break valid work but never converts a failed migration, audit, security, integrity, or domain operation into success. |
| D-116 | Sensitive-data prevention begins at the diagnostic call site through allowlists and semantic classification; all outputs sanitize before queuing, pattern redaction is defense in depth only, and canary tests prove non-disclosure. |
| D-117 | `audit_events` is append-only through ordinary application/SQL paths: update/delete/replace/upsert/conflict-skip are forbidden, duplicate event identity is error, command idempotency is separate, and corrections append. |
| D-118 | Audit JSON uses permanent named/versioned action-specific closed schemas with relational core facts and minimal differences/references; whole objects, secrets, bodies, provider payloads, arbitrary exceptions, and tombstones are prohibited. |

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
| O-006 | Which exact supported Windows editions/builds, browser versions, runner images, and packaging combinations complete the already confirmed Windows 10/11 and Python 3.13/3.14 matrix? | Packaging ADR |
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
