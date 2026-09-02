# SOMA Beta Delivery Roadmap

Status: **Roadmap reviewed; 138/138 merged Alpha requirements complete; unmerged proposal review checkpoint 23/43 complete (20 remain)**

This roadmap takes SOMA Beta from historical requirement recovery to an accepted, fully offline local web application. It is contract-first, use-case-driven, and traceable from every historical decision to the final UI and acceptance evidence.

Dates are intentionally absent until the Product Contract, use cases, HLD, and complete Beta 1.0.0 LLD make the remaining work estimable. No production code may begin before the entire LLD is accepted.

## Delivery chain

~~~mermaid
flowchart TD
    A["0. Traceability and product stabilization"] --> B["1. Use cases and HLD"]
    B --> C["2. Complete Beta 1.0 LLD"]
    C --> D["3. Synthetic-data Tickets and Objectives MVP"]
    D --> E["4. Security and recovery"]
    E --> F["5. Remaining domains and integration"]
    F --> G["6. Overview and complete UI/UX"]
    G --> H["7. Beta 1.0.0 acceptance"]
~~~

A later phase may expose a disproven assumption. When this happens, SOMA uses controlled design correction: reopen the owning accepted artifact, record the reason and impact, update downstream traceability, and reaccept the affected design before implementation continues. Product behavior always returns to Phase 0; implementation must never silently invent policy.

## Phase 0 — Requirement traceability and product stabilization (current)

### Purpose

Turn SOMA Alpha into a controlled historical source and establish the complete normative business truth for SOMA Beta 1.0.0.

### Historical scope and traceability

- Create ALPHA_TRACEABILITY.md with one row per Alpha requirement or decision ID.
- Catalogue:
  - every requirement and decision accepted on Alpha main; and
  - every paused or unmerged Alpha proposal, clearly marked as non-normative historical material until disposition.
- Do not treat Alpha code, schemas, migrations, tests, fixtures, or safeguards as normative requirements.
- Record for each Alpha ID:
  - source and authority;
  - merge or proposal status;
  - Beta disposition: **Retain**, **Replace**, **Defer**, **Reject**, or **Open**;
  - rationale where the outcome is not Retain;
  - immutable Beta requirement reference where applicable; and
  - destination layer, kept separate from release disposition.
- Destination layers include Product Contract, use case, HLD, LLD, implementation, and acceptance evidence. **Defer** means a later release; it never means “belongs in LLD.”
- Assign neutral immutable normative identifiers in the form **BETA-REQ-0001**. Workspace, domain, release, status, and destination remain metadata rather than part of the identifier.
- The merged Alpha requirement pass is complete at 138 exact source rows mapped to 144 sequential Beta requirements. This milestone does not close Phase 0 while unmerged proposals remain undispositioned.

### Gaps and product contracts

- Maintain contradictions and omissions separately in [FOUNDATION_GAPS.md](FOUNDATION_GAPS.md).
- Give every gap a stable ID that traceability rows can reference.
- Resolve all discovered Beta product questions, including candidate Alpha proposals, before Phase 0 closes.
- Stabilize the Product Contract, glossary, decision ledger, release boundary, and focused contracts for:
  - Service Request identity, notes, source population, lifecycle, period visibility, historical presentation, source observations, and the Beta 1.0 no-purge boundary;
  - RFC master/subordinate hierarchy, WFM ownership, adoption, correction, attempts, archive, tracking, and terminal cascade behavior;
  - Objective and Task composition, scheduling, execution, review, correction, cloning, and retry;
  - Inventory lifecycle covering stock-first eligibility, SR-level Spare Need aggregation from Device Part Units, local/external quantity choice, Spare Request draft and external-submission origin, C10 RMA obligations, direct inbound and return-unit relationships, requested-versus-actual logistics, partial dispatch/receipt, Task outcomes, compatible bulk actions, exact-event correction, and the mandatory Fault Tag return workflow: cross-request membership, conditional pickup-origin snapshots, warehouse receipt, explicit final acceptance/rejection, correction replacement, rejection resend, and state-specific removal;
  - Infrastructure terminology, Device Reference promotion, Network Element identity and progressive completion, Site/Rack placement, Cloud Deployment assignment, zero-many IP inventory, acyclic containment, component compatibility, installation/replacement history, SQLite authority, topology/SSH deferral, and versioned workbook import/export;
  - registered people, Customer Organizations, Local User Profile, Contracts, Product Lines, Contract Product Lines, Cloud Types, Cloud Deployments, Sites, Rooms, Racks, and Dispatch Locations;
  - source-specific import and population behavior;
  - target-gated PST/OST processing, source scopes, canonical matching, coverage/high-water marks, backfill/Deep Scan, reviewed proposals, terminal orphan grace/purge, workbench summaries, and MSG draft behavior; and
  - Contract Product Line classification, cohort SLA calculations, warnings, and Overview presentation; and
  - the [Foundation Runtime Contract](FOUNDATION_RUNTIME_CONTRACT.md): owned foreign-key SQLite connections, atomic immutable migrations, observational status, typed/versioned JSON, evidence/audit/diagnostic separation, append-only minimal audit, local-instance trust, redacted diagnostics, Windows/Python CI, and accessible application acceptance.
- Define product-level deletion, correction, archive, replacement, restoration, and historical-evidence rules.
- Confirm Beta 1.0.0 acceptance scope and explicit Beta 1.x.0 deferrals.

### Reuse, ownership, and licensing

- The only Phase 0 Alpha reuse candidates are canonical SOMA brand assets.
- Alpha code, schemas, migrations, adapters, fixtures, and tests may inform historical analysis but are not migration or reuse candidates.
- SOMA Beta is a private proprietary project for the internal team only.
- Preserve required Apache-2.0 origin attribution for reused Alpha brand assets through a narrowly scoped origin/third-party notice unless sole-rights relicensing is established.
- Do not imply that the proprietary Beta codebase as a whole is Apache-2.0.

### Exit gate

- Every merged Alpha ID and every unmerged proposal has a final recorded disposition.
- No row remains **Open**.
- Every retained or replaced outcome maps to an authoritative BETA-REQ identifier and normative Beta destination.
- Every gap is resolved in an accepted product contract or deliberately rejected or deferred.
- No product question, identity rule, lifecycle, cardinality, relationship, deletion consequence, or release-scope ambiguity remains.
- Terminology and rules agree across all foundation documents.
- The proprietary boundary, internal-team restriction, brand provenance, and required notices are accepted.

## Phase 1 — Complete business use cases and high-level design

### Purpose

Prove that the accepted Product Contract supports every Beta 1.0.0 operator goal and system-triggered behavior, then assign each flow to explicit architectural boundaries.

### 1A. Business use-case catalogue

- Catalogue **all** Beta 1.0.0 business use cases before HLD acceptance.
- Define one use case per meaningful operator goal, not per screen action or individual lifecycle command.
- Model scheduled and background behavior as separate system-triggered use cases.
- Each use case records:
  - stable ID and goal;
  - human or system actor, trigger, and preconditions;
  - main success flow;
  - applicable warning, conflict, correction, cancellation, retry, and failure flows;
  - postconditions and preserved evidence;
  - affected workspaces and domain owners;
  - Product Contract and BETA-REQ references; and
  - acceptance scenarios without prescribing tables, classes, or libraries.
- Cover setup, login, automatic login, locking, backup, recovery, Settings, both ticket workbenches, device-reference promotion, Tickets, Contract Product Line/SLA, Objective grouping, every Inventory discrepancy/return scenario, Infrastructure, offline communications, Overview, reporting, archive, retention, destructive previews, and restoration.

### 1B. High-level design

- Define the conceptual domain model across all six workspaces.
- Establish aggregate ownership and cross-module relationship rules.
- Express lifecycle and state models in business vocabulary.
- Define trust boundaries for the local UI, application API, persistence, retained files, Windows protection, imports, exports, backups, communications evidence, and diagnostics.
- Define source staging, review, optional safe auto-accept, provenance, and failure recovery.
- Separate audit history, business evidence, source history, and technical diagnostics.
- Define atomicity, local process ownership, single-instance behavior, loopback boundaries, tray lifecycle, startup, shutdown, and complete offline operation.
- Define encryption coverage and recovery objectives without selecting exact algorithms prematurely.
- Establish information architecture, routes, navigation, and cross-workspace task flows.
- Produce clickable low-fidelity prototypes for critical and cross-workspace flows.
- Produce static responsive wireframes for the remaining flows.
- Map every use case to its owning module and architectural boundary.

### Exit gate

- Every BETA-REQ is exercised by a use case or identified as a structural invariant.
- Every use case has an owner, state effects, trust boundary, and failure outcome.
- All Beta 1.0.0 use cases are accepted.
- Clickable critical flows and static remainder wireframes reveal no unresolved domain or navigation dead end.
- No HLD ambiguity remains.
- Questions intentionally reserved for LLD are explicitly identified, bounded, assigned, and confirmed not to alter product behavior or HLD ownership.

## Phase 2 — Complete Beta 1.0.0 low-level design

### Purpose

Translate the accepted Product Contract, use cases, and HLD into one complete, implementable, testable technical design before any code is written.

### Organization

- Maintain modular LLD specifications with one authoritative index.
- Define shared rules once and reference them from domain modules.
- Keep each module traceable to BETA-REQ IDs, use cases, HLD ownership, implementation units, and tests.
- Do not permit scaffolds, prototypes, disposable spikes, production code, or implementation-led framework selection before this phase is accepted.

### Deliverables

- Clean relational schema, constraints, indexes, immutable evidence, and migration strategy.
- Independent Beta migration lineage with atomic schema-and-ledger application, immutable accepted migrations, forward-only corrections, startup integrity checks, and no Alpha database upgrade path.
- Exact state transitions, proposal review, compatible bulk operations, per-target and batch identity, requested and actual logistics events, Fault Tag membership and submitted snapshots, conditional pickup-origin snapshots, warehouse receipt and final-decision events, typed correction-replacement and resend lineage, Infrastructure placement/containment/IP invariants, versioned workbook exchange and installation-scoped identity, correction and supersession mechanisms, and retention behavior.
- Command/query contracts, validation order, transaction boundaries, concurrency, stable errors, idempotency, and no-op behavior.
- Local API routes and request/response contracts.
- Exact parsers, types, validation, and transactions implementing the accepted allowlists and semantics in `IMPORT_CONTRACT.md` for Advanced Search SR data, Enhanced Excel RFC data, and Service Provider WFM plans.
- File discovery, stabilization, fingerprinting, replay, absence, validation, resource limits, preview, review, and acceptance rules.
- Sanitized golden import fixtures and expected normalized observations.
- Exact Contract Product Line cohort membership, tier calculations, percentage rounding, snapshots, and golden vectors.
- Threat model and ADRs for:
  - database and retained-file encryption;
  - authentication-only password verification, independent random data-key protection, and encrypted-database packaging;
  - optional Windows-user automatic-login protection;
  - independent portable-backup encryption and high-entropy recovery-secret handling;
  - key recovery and rotation;
  - WAL-safe backup, verification, pruning, and restore;
  - PST/OST read-only source scopes, provider/fallback identity, coverage/high-water processing, target registry, backfill/Deep Scan, matched-message/link persistence, background jobs, terminal orphan grace/purge, workbench summaries, and MSG generation;
  - packaging; and
  - supported Windows, Python, and browser versions.
- Concrete action-versioned audit allowlists, append-only SQL/application protections, duplicate/idempotency behavior, atomic rollback, exact correction, restoration validation, housekeeping boundaries, structured external diagnostics, prevention-first redaction, and canary fixtures.
- One owned SQLite connection factory; effective foreign-key index map; atomic migration/ledger protocol; canonical migration-byte manifest and drift checks; exclusive migrator; truly observational status; versioned JSON schema/upgrade registry; and post-migration/restore integrity verification.
- Exact local runtime ownership, loopback binding, runtime-registry, process-birth, authenticated health/session/origin/shutdown, proxy/redirect bypass, stale-registry, PID/port reuse, crash, restart, and forced-termination contracts.
- Current-revision Windows CI on Python 3.13 and 3.14, draft/non-draft/primary/release trigger policy, reproducible synthetic fixtures, representative Windows desktop matrix, and traced invariant/application acceptance suites including hovered-pane scrolling and deliberate-hold accessibility.
- Frontend architecture covering routes, functional layouts, shared interaction components, drafts, conflicts, responsive behavior, keyboard and pointer access, accessibility, and every loading, empty, warning, error, stale, locked, destructive, and recovery state.
- A dependency policy requiring few, pinned, justified, adapter-isolated production libraries while remaining nearly dependency-free rather than dependency-free.
- A complete implementation and verification plan.

### Exit gate

- Every Beta 1.0.0 use case maps to commands/queries, persistence, adapters, UI states, and tests.
- Every invariant has an application owner and database backstop decision where appropriate.
- Security, recovery, import, destructive-operation, accessibility, and failure designs have explicit verification methods.
- The **entire** Beta 1.0.0 LLD is accepted.
- Only after this gate may production implementation or technical scaffolding begin.
- If implementation later disproves an accepted assumption, controlled design correction reopens and reaccepts the affected specifications before work proceeds.

## Phase 3 — Synthetic-data engineering foundation and Tickets/Objectives MVP

### Purpose

Prove the core business architecture through functional Tickets and Objectives workflows before security and recovery become operational.

### Data restriction

- Use disposable synthetic data only.
- Pre-security databases are development-only, recreatable, non-operational, and non-migratable.
- Do not use real, sanitized operational, or internally identifying data.
- Do not import operational files, inspect operational PST/OST content, or begin internal operational use.

### Deliverables

- Minimal local application lifecycle, loopback service, schema runner, unit of work, audit, identity, clock, errors, and transaction foundation.
- Just enough Settings/reference support for the MVP.
- Tickets and Objectives MVP including:
  - manual SR, RFC, and WFM workflows;
  - reviewed SR, RFC, and WFM Excel imports using synthetic fixtures;
  - Contract Product Line classification and cohort SLA calculation;
  - Objective and Task scheduling;
  - execution and review; and
  - required correction, warning, and failure paths.
- Functional responsive UI for every implemented flow.
- Keyboard and pointer access, visible focus, readable state communication, and basic accessibility from the first UI.
- No canonical brand styling, light/dark visual polish, animation polish, or final design-system finish yet.
- Automated traceability and regression evidence for every implemented requirement.

### Exit gate

- The Tickets and Objectives MVP works end-to-end exclusively with disposable synthetic data.
- Contract Product Line/SLA calculations and all three reviewed import families pass golden synthetic fixtures.
- Scheduling, execution, and review preserve accepted lifecycle evidence.
- No operational data has entered any pre-security database or retained file.
- The implementation still conforms to the accepted LLD.

## Phase 4 — Authentication, encryption, backup, and recovery

### Purpose

Make SOMA safe for authorized internal operational data before any real-data pilot or operational use.

### Deliverables

- Local-admin password authentication and lock/unlock behavior.
- Optional automatic login protected by the accepted local Windows-user mechanism.
- Accepted encryption envelope for the database and every retained sensitive artifact in scope.
- Protected working paths, temporary-file handling, diagnostics, and communication indexes.
- Verified encrypted backup, integrity checks, retention/pruning, restore, and recovery.
- Configurable managed-backup count defaulting to five, with verified replacement before pruning, last-restorable-copy protection, and no automatic pruning of operator-exported portable backups.
- Wrong-password, damaged-backup, key-recovery, last-recoverable-copy, interruption, and atomic rollback tests.
- Fresh offline setup, start, stop, restart, authentication, backup, and restore on the supported platform matrix.
- Security and recovery operator documentation.

### Exit gate

- Authentication, encryption, backup, and recovery are operational and demonstrated, not merely implemented or documented.
- A clean offline installation can launch, authenticate, lock, back up, restore, restart, and recover.
- Retained operational data cannot bypass the accepted protection boundary.
- Only after this gate may controlled real internal data be used.

## Phase 5 — Remaining domains and cross-domain integration

### Purpose

Complete every operational domain through functional, responsive web workflows before Overview and final brand polish.

### Required order

#### 5.1 Inventory

- Stock, registered/unregistered device references, Device Part Units, SR-level aggregated Spare Needs, local/external quantity selection, Spare Request drafts and externally initiated registration, incremental C10 RMA obligations, units with or without manufacturer serials, promised-versus-inbound-versus-return BOM review, deterministic assignment and redistribution, requested-versus-actual logistics, partial dispatch and receipt, reservation, dismantling, installation, reviewed proposals, compatible bulk actions, and exact-event and relationship correction. Complete the mandatory Fault Tag return workflow with immutable tag identity, one RMA obligation and one selected return unit per membership, cross-request grouping, conditional pickup-origin snapshots, per-membership warehouse receipt and explicit final acceptance/rejection, linear correction replacement, rejection resend, and state-specific removal.
- Implement accepted Infrastructure-facing contracts, but keep device-targeted installation and replacement unavailable until the corresponding Infrastructure capability exists.

#### 5.2 Infrastructure

- Customer Organization, Site, Cloud Type, Cloud Deployment, Room, Rack, Device Reference promotion, Network Element models and progressively completed instances, zero-many IP inventory with one primary, acyclic compound containment, placement, component compatibility, installation, replacement, and history.
- Generate versioned Infrastructure workbooks for empty registration, human-readable current-device discovery export, and safe round-trip updates. Discover imports only from the configured directory, stage every mutation, scope update identity to the source installation, preserve absence nondestructively, and expose import/export history.
- Keep credential fields, connectivity, discovery, reachability, topology, interfaces/ports, and SSH unavailable in 1.0.0.
- Activate Inventory-to-device installation and replacement workflows after their cross-domain invariants pass.

#### 5.3 Offline communications

- Implement the target gate and versioned registry for SR/TT, Spare Request, RMA/C10, RFC, WFM, Objective, and Fault Tag identifiers; Infrastructure and descriptive Device data alone do not activate scanning.
- Implement path-independent read-only Communication Source Scopes, structured participants, provider-stable identity, versioned collision-safe fallback identity, canonical messages, and independent multi-entity links.
- Implement initial relevant-time boundaries, per-scope high-water marks with overlap, coverage warnings, bounded targeted backfill, and explicit scoped Deep Scan.
- Run one local combined fetch-and-match pipeline hourly by default with positive whole-minute configuration, disable and Check now controls, one catch-up, non-overlap, restart-safe progress, cancellation, bounded retry/backoff, and redacted diagnostics.
- Persist only matched communications; keep unmatched parse results transient. Produce reviewed domain proposals without implicit writes.
- On accepted SR/RFC termination, remove direct communication links. When no protected dependency remains, apply the configurable positive orphan grace of seven exact elapsed days by default, cancel it on relink, revalidate at expiry, purge reconstructable content, and preserve the purge record plus frozen terminal summary.
- Expose received/sent counts, direction, last-interaction age, coverage, and canonical navigation without body duplication. Keep Advanced Search synchronization, communication processing, proposal acceptance, and local MSG draft persistence independent.
- Generate MSG drafts without treating them as sent evidence. Beta 1.0 never sends or receives email directly, exposes no manual attachment/upload control, and keeps valid manual domain actions independent of evidence.

#### 5.4 Domain completion and integration

- Complete Settings and any remaining Tickets/Objectives behavior.
- Complete SR-centered relationships across Tickets, Objectives, Inventory, Infrastructure, and communications evidence.
- Verify master/subordinate RFC and WFM ownership, Contract Product Line/SLA behavior, spare suggestions, installation/replacement history, retention, archive, and destructive consequences across public application contracts.

### UI rule during this phase

- Every workflow must already be functionally understandable, responsive, keyboard/pointer operable, and accessible enough to test safely.
- Postpone only canonical brand styling and visual polish until all domains work.

### Exit gate

- Tickets, Objectives, Inventory, Infrastructure, Settings, and offline communications work through the local web app.
- Every accepted cross-domain rule works through public application contracts rather than database shortcuts.
- Every completed capability has automated acceptance evidence.
- No critical Beta 1.0.0 domain workflow remains a placeholder, script, or developer-only command.
- All domains are complete before Overview implementation begins.

## Phase 6 — Overview and complete UI/UX system

### Purpose

Add cross-domain operational reporting only after its source domains are complete, then apply the accepted UI/UX Interaction Contract across every workflow and state.

### 6A. Overview and reporting

- Daily, Weekly, and Monthly Customer-scoped summaries with visible filter/scope.
- Period comparison, Contract Product Line/SLA context, communication coverage, Inventory lifecycle, and Objective/Maintenance Window context without reconstructing discarded `Resolved Status Date`.
- Operational narrative and scheduled Objective timeline.
- Needs Attention queues linking to preserved filtered views.
- A clean stable shell, context header, restrained modular summary cards, progressive detail, and collapsible recent-processing/review activity.
- Excel report snapshots with immutable calculation context and export golden fixtures.

### 6B. Complete visual and interaction system

- Final six-area navigation: Overview, Tickets, Objectives, Inventory, Infrastructure, Settings.
- Canonical SOMA mark, wordmark, lockup, application icon, favicon, tray identity, and one semantic design-token system.
- Accessible light, dark, high-contrast/forced-color, enlarged-text, and reduced-motion presentations.
- Global list/table navigation separating focus, active row, selection, multi-selection, and opening.
- Hovered/gesture-origin/focused scroll ownership across nested panes, lists, communication previews, tables, popups, dialogs, and activity surfaces.
- Bounded accessible autocomplete with stale-result suppression and explicit entity creation.
- Responsive split workbenches, horizontal table access, viewport-safe overlays, accessible icon actions, and complete empty/loading/error states.
- Allowlisted three-second deliberate confirmation with visible semantic progress, pointer/touch/keyboard equivalence, scroll-gesture safety, and mandatory Device Reference promotion coverage.
- Impact previews remain mandatory where domain consequences require them; holding never substitutes for understanding.
- Protected UI working copies, valid selective save/discard, recovery, stale-version conflict review, navigation warnings, and bounded safe Undo.
- Domain-derived Customer/communication/Inventory/Objective/SLA/main-view summaries.
- Lifecycle-contextual Inventory commands, compatible bulk preflight, per-target results, manual continuation, and export/transition separation.
- Overview and Infrastructure composition informed directionally by mature infrastructure-management hierarchy—including the reviewed vSphere reference—without third-party branding/assets/trade dress or wide-screen-only density.
- A versioned catalogue of directional references, sanitized visual acceptance fixtures, and export golden fixtures. Missing required fixtures block acceptance rather than authorize guessing.

### Usability and fixture validation

- Every available internal evaluator independently completes representative task scenarios before group discussion.
- Record observations, task outcomes, errors, and unresolved confusion.
- Verify wide/intermediate/narrow, themes, zoom/text, keyboard/pointer/touch, reduced motion, nested scrolling, deliberate holds, dialogs, drafts/conflicts, bulk actions, and complete lifecycle/error/recovery states.
- Validate screenshots only in deterministic approved contexts/tolerances; validate package exports structurally, semantically, and through rendered usability with explicit nondeterministic-field normalization.
- A baseline cannot be updated merely to make a regression pass.
- Resolve findings or disposition them under the accepted defect policy.

### Exit gate

- The final UI/UX pass is complete across **all workflows and states**, not only critical or visible screens.
- Every Beta 1.0 operator use case is completable through the web UI without database/developer tooling.
- Terminology, status, warnings, consequences, action availability, and summaries agree with owning domain contracts.
- Responsive, accessibility, input-method, hovered-scroll, recovery, conflict, fixture, export, and confirmation-tier scenarios pass.
- Canonical SOMA identity is consistent from browser tab to tray and packaged application.
- Every available internal evaluator completes the required usability validation.

## Phase 7 — Beta 1.0.0 hardening and acceptance

### Purpose

Prove that the integrated product is safe, recoverable, understandable, stable, and deployable for the internal team.

### Acceptance evidence

- Close the traceability chain:

  **Alpha source → BETA-REQ → use case → HLD owner → LLD design → implementation → automated/manual acceptance evidence**

- Run a deterministic synthetic suite covering requirements; identifiers and hierarchies; lifecycle changes and corrections; foreign-key/schema/migration integrity; versioned JSON; concurrent startup and local-instance attacks; append-only/minimal audit; diagnostic failure/redaction canaries; destructive impact; all imports/exports including Infrastructure Device workbook round trip; SLA; communications; security; recovery; hovered-pane/responsive/focus/reduced-motion/semantic/hold accessibility; and packaging.
- Require successful current-revision Windows CI on Python 3.13 and 3.14 and representative supported Windows desktop acceptance. Stale, cancelled, skipped, missing, flaky, or unexplained evidence does not pass.
- Run a controlled real-data pilot only after the Phase 4 security-and-recovery gate.
- Require representative workflow coverage **and** a minimum stable-operation soak; neither substitutes for the other.
- Require **four weeks** of stable operation.
- A Critical or High pilot defect invalidates the stability gate. The acceptance plan defines proportionate reset rules for lower-severity fixes.
- Complete fresh offline installation and upgrade validation on every supported platform combination.
- Demonstrate backup and recovery with operationally representative protected data.
- Complete license, proprietary notice, origin attribution, dependency attribution, asset provenance, privacy, setup, support, backup, recovery, and troubleshooting documentation.
- Produce versioned release artifacts and rollback/recovery instructions.

### Defect policy

- No known Critical or High defect may remain at acceptance.
- A Medium defect requires a formal exception recording impact, risk, safe workaround, owner, planned correction, and project-owner approval.
- Low defects remain documented and prioritized normally.
- No unexplained data-integrity failure may remain.

### Exit gate and authority

- Every Beta 1.0.0 requirement has passing evidence or a formally approved scope removal reflected through Phase 0 traceability.
- The deterministic synthetic suite passes.
- The representative real-data workflow matrix and four-week stability gate pass.
- Security, backup, and recovery are demonstrated.
- Every available internal evaluator has completed task-based usability validation.
- All permitted Medium exceptions are recorded.
- A fresh offline operator can install, understand, use, stop, restart, update, and recover SOMA.
- The **project owner** has sole final authority to accept SOMA Beta 1.0.0, but only after every objective gate above has passed.

## Phase 8 — Beta 1.x.0 evolution

Candidates include:

- SSH and reviewed Network Element operations;
- Infrastructure connectivity and topology;
- language switching; and
- refinements justified by Beta 1.0.0 field evidence.

Every candidate begins with a Product Contract and traceability change. Alpha implementation does not grant automatic acceptance or reuse.

## Cross-cutting traceability rules

Every deliverable uses stable references:

| Artifact | Example purpose |
|---|---|
| Alpha disposition | Historical source and Beta decision |
| BETA-REQ-0001 | Immutable normative product outcome |
| Use case | Meaningful operator goal or system-triggered behavior |
| HLD/ADR | Ownership, boundary, trust, and technical direction |
| LLD module | Exact implementable behavior |
| Test/acceptance scenario | Verifiable evidence |
| UI route/state | Operator-facing realization |

A feature is complete only when:

1. its product rule is accepted;
2. its meaningful operator and system-triggered use cases are accepted;
3. its HLD owner, boundaries, and failure outcomes are known;
4. its LLD covers persistence, transactions, security, adapters, and every UI state;
5. automated and manual acceptance evidence exists;
6. user-facing documentation is current; and
7. the traceability chain reaches the final UI without an unexplained gap.

## Explicit non-goals for Beta 1.0.0

- Shared multi-user or cloud deployment.
- Direct email send/receive.
- Arbitrary dashboard/report builders.
- Zeus/Alpha historical database migration.
- SSH or automated device connectivity.
- Infrastructure topology/connectivity.
- Language switching.
- Wholesale reuse of Alpha code, schema, migrations, fixtures, or tests.
