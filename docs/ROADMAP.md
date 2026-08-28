# SOMA Beta Delivery Roadmap

Status: **Foundation and traceability in progress**

This roadmap takes SOMA Beta from historical requirement recovery to a complete, responsive local web application. It is contract-first, use-case-driven, and incrementally executable.

Dates are intentionally absent until the product foundation, use cases, HLD, and LLD make the remaining work estimable. Existing foundation documents are working baselines, not automatic acceptance of the phases below.

## Delivery chain

~~~mermaid
flowchart TD
    A["0. Alpha traceability"] --> B["1. Product stabilization"]
    B --> C["2. Use cases and HLD"]
    C --> D["3. Low-level design"]
    D --> E["4. Engineering foundation"]
    E --> F["5. Domain vertical slices"]
    F --> G["6. Integrated UI and UX"]
    G --> H["7. Beta 1.0.0 acceptance"]
~~~

A later phase may expose a missing product decision. When that happens, the decision returns to the Product Contract and traceability record before implementation continues. The LLD, schema, services, and UI must never silently invent business policy.

## Phase 0 — Historical traceability and foundation correction (current)

### Purpose

Turn SOMA Alpha into a controlled historical source instead of relying on memory or prose summaries.

### Deliverables

- 'ALPHA_TRACEABILITY.md' covering:
  - every requirement and decision accepted on Alpha 'main';
  - every additional rule from paused or unmerged Alpha work;
  - the authority and merge status of each source;
  - a Beta disposition of **Retain**, **Replace**, **Defer**, **Reject**, or **Open**;
  - the Beta document and requirement ID that owns every retained or replaced outcome; and
  - a rationale for every replacement, deferral, or rejection.
- A selective reuse inventory for Alpha code, tests, fixtures, canonical brand assets, and operational contracts.
- A contradiction and omission register separating:
  - confirmed Beta contradictions;
  - missing Beta rules;
  - intentional replacements;
  - candidate-only Alpha proposals requiring owner confirmation; and
  - implementation details reserved for LLD.
- Stable Beta requirement identifiers suitable for later use-case, design, and test references.
- An explicit license, attribution, and asset-provenance decision before Alpha code or assets are copied.

### Exit gate

- Every accepted Alpha requirement and decision has a recorded disposition.
- No unmerged Alpha proposal is treated as accepted merely because code or tests exist.
- Every retained or replaced rule has one authoritative Beta destination.
- All product-shaping gaps discovered by the audits are either resolved or explicitly open with a required decision phase.

## Phase 1 — Product contract stabilization

### Purpose

Complete the business truth that SOMA Beta 1.0.0 must implement.

### Deliverables

- Stabilized Product Contract, glossary, decision ledger, and release boundary.
- Focused product contracts where the main contract would become ambiguous or excessively dense:
  - Service Request identity, notes, source population, lifecycle, episodes, finalization, and retention;
  - RFC hierarchy, WFM ownership, adoption, correction, attempts, archive, tracking, and terminal cascade behavior;
  - Objective and Task composition, scheduling, execution, review, correction, cloning, and retry;
  - Inventory lifecycle covering Spare Needs, request lines and quantities, C10 positions, physical units, allocation, installation, return, and Fault Tags;
  - Infrastructure identity, placement, component compatibility, installation, replacement, and operational scope;
  - registered people, Customer Organizations, Local User Profile, Product Lines, Sites, and Dispatch Locations;
  - source-specific import and population behavior;
  - offline communications evidence and MSG draft behavior; and
  - Product Line/SLA classification, calculations, cohorts, warnings, and Overview presentation.
- Explicit resolution of current product gaps, including:
  - Customer Contact versus Requester versus Local User Profile;
  - Spare Request multi-BOM/request-line cardinality;
  - RFC/WFM hierarchy correction and terminal consequences;
  - SR same-number reappearance and manually created SR adoption;
  - minimum Network Element facts and direct operational scope;
  - Fault Tag item eligibility and evidence;
  - Overview treatment of SLA and Infrastructure; and
  - retention outcomes for each operational family.
- Product-level deletion, correction, archive, replacement, and historical-evidence rules.
- Confirmed Beta 1.0.0 acceptance scope and explicit 1.x deferrals.

### Exit gate

- No unresolved business ambiguity blocks a use case, lifecycle, identity, or relationship.
- Every open item is genuinely an implementation choice assigned to HLD or LLD—not an undecided product behavior.
- Terminology and cardinalities agree across all foundation documents.

## Phase 2 — Business use cases and high-level design

### Purpose

Prove that the Product Contract supports complete operator workflows and give every workflow an architectural owner.

### 2A. Use-case catalogue

Each use case records:

- stable ID and goal;
- primary actor, trigger, and preconditions;
- main success flow;
- alternative, warning, conflict, correction, and cancellation flows;
- postconditions and preserved historical evidence;
- affected workspaces and domain owners;
- Product Contract and traceability references; and
- acceptance scenarios without prescribing tables, classes, or libraries.

The initial catalogue covers at least:

- local setup, login, automatic login, locking, backup, and recovery;
- Settings and registered-reference maintenance;
- manual SR creation, official-ID reconciliation, Advanced Search population, notes, and lifecycle;
- RFC creation, hierarchy, linking, import adoption, correction, archive, and termination;
- WFM registration/import, RFC ownership, planning, attempts, and Objective participation;
- Objective creation, Task composition, collision discovery, execution, review, correction, and retry;
- Spare Need creation and repeated procurement attempts;
- Spare Request creation, request lines, C10 outcomes, receipt, dispatch, installation, return, and completion;
- Fault Tag creation, first send, evidence, replacement, warehouse confirmation, and closure;
- Network Element registration, placement, component installation/replacement, and history;
- PST/OST scanning, evidence matching, backfill, and MSG draft generation;
- Overview filtering, attention queues, SLA progress, and Excel reporting; and
- archive, retention, restoration, destructive preview, and recovery workflows.

### 2B. High-level architecture

- Conceptual domain model spanning all six workspaces.
- Aggregate ownership and cross-module relationship rules.
- Lifecycle and state diagrams expressed in business vocabulary.
- Trust boundaries for local UI, application API, persistence, files, Windows protection, imports, exports, backups, and diagnostics.
- Source-staging, review, safe-auto-accept, and provenance flows.
- Audit, business evidence, source history, and technical diagnostics as separate authorities.
- Atomic mutation and failure-recovery requirements.
- Local process, single-instance, loopback, tray, startup, shutdown, and offline behavior.
- Encryption coverage and recovery objectives without prematurely selecting algorithms.
- Information architecture, route hierarchy, navigation, primary task flows, and low-fidelity responsive prototypes.
- Mapping from each use case to its owning module and architectural boundary.

### Exit gate

- Every product requirement is exercised by at least one use case or identified as a structural invariant.
- Every use case has a domain owner, state effects, trust boundary, and failure outcome.
- Cross-workspace dependencies are explicit and acyclic where required.
- Low-fidelity workflow validation finds no unresolved navigation or domain dead end.
- The HLD contains no hidden schema, library, or framework decision masquerading as product truth.

## Phase 3 — Low-level design

### Purpose

Translate the accepted product behavior and HLD into an implementable, testable technical design.

### Deliverables

- Clean relational schema, constraints, indexes, immutable evidence, and migration strategy.
- Exact state-transition tables and correction/supersession mechanisms.
- Application command/query contracts, validation order, transaction boundaries, concurrency behavior, stable errors, and idempotency/no-op rules.
- Local API routes and request/response contracts.
- Source-specific mapping contracts for:
  - Advanced Search Service Requests;
  - Enhanced Excel RFC data; and
  - Service Provider WFM plans.
- File discovery, stabilization, logical fingerprint, replay/high-water, absence, validation, resource-limit, preview, and acceptance rules.
- Sanitized golden import fixtures and expected normalized observations.
- Exact SLA calculations and golden vectors, including fractional suspension and immutable export snapshots.
- Threat model and ADRs for:
  - database and file encryption;
  - password KDF and data-key wrapping;
  - Windows automatic-login protection;
  - key recovery and rotation;
  - WAL-safe backup, verification, pruning, and restore;
  - PST/OST read and MSG generation; and
  - packaging and supported Windows/Python/browser versions.
- Concrete audit allowlists, append-only behavior, atomic rollback, retention, and housekeeping.
- Frontend architecture:
  - routing and workspace composition;
  - design tokens and canonical branding;
  - shared lists, details, forms, dialogs, timelines, and review surfaces;
  - draft protection and conflict recovery;
  - responsive breakpoints;
  - keyboard/pointer operation;
  - accessibility and reduced motion; and
  - loading, empty, error, warning, stale, and destructive-confirmation states.
- Requirement-to-use-case-to-design-to-test traceability.
- Implementation plan divided into independently verifiable vertical slices.

### Exit gate

- Every 1.0.0 use case maps to commands/queries, persistence, adapters, UI states, and tests.
- Every invariant has an application owner and a database/backstop decision where appropriate.
- Security, recovery, import, and destructive-operation designs have explicit failure tests.
- No LLD decision changes product behavior without returning through Phase 1.
- Estimates may be assigned only after this gate.

## Phase 4 — Engineering foundation

### Purpose

Build the secure local platform on which domain slices can be delivered without repeatedly rebuilding infrastructure.

### Deliverables

- Python application boundary and React/TypeScript web shell.
- Dependency manifest with few, pinned, justified, adapter-isolated production libraries.
- Local setup, upgrade, run, console-run, stop, health, and single-instance lifecycle.
- Loopback-only service, authenticated local control, and stale-process protection.
- Schema initialization/migration runner and database integrity checks.
- Encryption envelope, login, lock/unlock, optional Windows-user automatic login, and protected working paths.
- Unit-of-work, audit, clock, identity, error, and transaction foundations.
- Privacy-aware diagnostics.
- WAL-safe encrypted backup and verified restore baseline.
- Import staging framework with no domain mutation during parsing.
- Frontend routing, design system seed, themes, responsive shell, error boundary, and canonical SOMA assets.
- Continuous integration for the supported platform matrix.
- Automated architecture-boundary, migration, security, and packaging checks.

### Exit gate

- A clean supported Windows installation can set up, launch, authenticate, stop, restart, back up, and restore entirely offline.
- Database, temporary persistence, logs, communication indexes, imports retained by SOMA, and backups follow the accepted protection boundary.
- The web shell and tray share one application lifecycle.
- CI and local verification are reproducible before business-domain implementation begins.

## Phase 5 — Domain vertical slices

### Purpose

Deliver complete business capabilities incrementally. Each slice includes domain rules, persistence, application services, API, a minimally usable web workflow, tests, documentation, and traceability—not backend-only implementation.

### Recommended dependency order

#### 5.1 Settings and reference identity

Local User Profile, registered people, Customer Organizations, Product Lines, Sites, Dispatch Locations, Clouds, BOM catalog, and installation policy.

#### 5.2 Tickets and SLA

Manual/imported Service Requests, notes, official-ID reconciliation, RFC hierarchy, source population, Product Line assignment, SLA calculations, warnings, and lifecycle evidence.

#### 5.3 Infrastructure

Rooms, racks, Network Element models and instances, placement, addresses/management facts, compound elements, components, compatibility, and installation/replacement history.

#### 5.4 Inventory

Stock, Spare Needs, request lines, quantity outcomes, Spare Requests, C10 positions, serialized units, reservation/allocation, dispatch, receipt, installation, return, Fault Tags, and warehouse confirmation.

#### 5.5 Objectives and Tasks

Local/WFM Tasks, WFM imports and attempts, time-window discovery, Objective composition, Task-derived context, spare suggestions, execution, review, correction, cloning, and retry.

#### 5.6 Offline communications

Read-only PST/OST indexing, identifier matching, evidence links, targeted backfill, progress/cancellation, and MSG draft generation.

#### 5.7 Overview and reporting

Daily/Weekly/Monthly metrics, period comparison, SLA progress, operational narrative, Needs Attention queues, preserved filtered navigation, and Excel snapshots.

### Exit gate

- All six workspaces function through the local web app.
- Cross-domain rules work through public application contracts rather than table-level shortcuts.
- Every completed slice has traceable automated acceptance evidence.
- No critical 1.0.0 workflow remains a placeholder, database script, or developer-only command.

## Phase 6 — Integrated UI and UX completion

### Purpose

Turn the functional vertical slices into one coherent SOMA experience.

### Deliverables

- Final six-area navigation:
  1. Overview
  2. Tickets
  3. Objectives
  4. Inventory
  5. Infrastructure
  6. Settings
- Canonical SOMA mark, wordmark, lockup, application icon, favicon, and tray treatment.
- Unified responsive desktop and narrow-layout behavior.
- Complete light and dark themes using shared accessible design tokens.
- Consistent lists, filters, selection, details, editors, autocomplete, dialogs, lifecycle timelines, import review, conflict resolution, and destructive previews.
- Operationally useful empty, loading, error, stale, locked, unsupported-file, and recovery states.
- Draft protection, selective save/discard, navigation/reload warnings, and meaningful undo where the business operation is reversible.
- Keyboard and pointer parity for primary workflows.
- Screen-reader labels, visible focus, non-color status indicators, and reduced-motion support.
- Overview links that preserve filter and period context.
- End-to-end usability reviews using sanitized representative SR, RFC, WFM, Inventory, Infrastructure, Fault Tag, and PST/OST scenarios.
- Visual regression coverage for core responsive states.

### Exit gate

- Every primary use case can be completed through the web UI without database access or developer tooling.
- UX terminology, status, warnings, and consequences agree with the Product Contract.
- Responsive, keyboard, pointer, focus, contrast, reduced-motion, and destructive-confirmation acceptance scenarios pass.
- The canonical SOMA identity is used from browser tab through tray and packaged application.

## Phase 7 — Beta 1.0.0 hardening and acceptance

### Purpose

Prove that the integrated product is safe, recoverable, understandable, and deployable for the internal Beta team.

### Deliverables

- Final closed traceability chain:

  'Alpha source → Beta requirement → use case → HLD owner → LLD design → implementation → automated/manual acceptance evidence'

- Full invariant, lifecycle, correction, concurrency, audit, and destructive-impact suites.
- Golden-file verification for all official Excel imports and Excel report exports.
- PST/OST tests covering locked, changing, corrupted, unsupported, duplicate, received, sent, unrelated, older/backfill, and multi-entity evidence.
- SLA golden calculations and immutable report-snapshot verification.
- Encryption, wrong-password, automatic-login, key-recovery, backup-corruption, restore, and last-recoverable-copy tests.
- Fresh offline installation and upgrade tests on every supported Windows/Python/browser combination.
- Performance and bounded-resource tests using representative operating volumes.
- Accessibility and representative operator-task acceptance.
- License, NOTICE, dependency attribution, asset provenance, privacy, support, setup, backup, recovery, and troubleshooting documentation.
- Small-team field pilot, defect triage, and release-candidate evidence.
- Versioned Beta 1.0.0 release artifacts and rollback/recovery instructions.

### Exit gate

- Every 1.0.0 requirement has passing acceptance evidence or an explicitly approved removal from scope.
- No unresolved critical/high-severity defect or unexplained data-integrity failure remains.
- Backup and recovery have been demonstrated, not merely documented.
- A fresh offline operator can install, understand, use, stop, restart, update, and recover SOMA.
- Product, architecture, security, UX, and release acceptance are explicitly recorded.

## Phase 8 — Beta 1.x.0 evolution

Candidates include:

- SSH and reviewed Network Element operations;
- Infrastructure connectivity and topology;
- language switching; and
- refinements justified by 1.0.0 field evidence.

Every candidate starts with a Product Contract and traceability change. A feature is not added merely because Alpha contained related code.

## Cross-cutting traceability rules

Every deliverable uses stable references:

| Artifact | Example purpose |
|---|---|
| Alpha disposition | Historical source and Beta decision |
| Beta requirement | Normative product outcome |
| Use case | Operator goal and business flow |
| Architecture/ADR | Ownership, boundary, and technical choice |
| LLD contract | Concrete implementation behavior |
| Test/acceptance scenario | Verifiable evidence |

A feature is complete only when:

1. its product rule is accepted;
2. its use cases include success, warning, correction, cancellation, and failure paths where applicable;
3. its HLD owner and trust boundaries are known;
4. its LLD covers persistence, transactions, security, adapters, and UI states;
5. automated and manual acceptance evidence exists;
6. user-facing documentation is current; and
7. the traceability chain contains no unexplained gap.

## Explicit non-goals for Beta 1.0.0

- Shared multi-user or cloud deployment.
- Direct email send/receive.
- Arbitrary dashboard/report builders.
- Zeus/Alpha historical database migration.
- SSH or automated device connectivity.
- Infrastructure topology/connectivity.
- Language switching.
- Wholesale reuse of Alpha code or schema.
