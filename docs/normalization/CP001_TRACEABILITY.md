# SOMA Beta Normalization CP-001 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0001`–`BETA-REQ-0027`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0001` | Structural invariant: Independent Product Lineage | Foundation Runtime / Product Boundary | Repository, migration, packaging and provenance specifications | Repository + migration-lineage verification |
| `BETA-REQ-0002` | Use-case family: Launch and operate SOMA locally | Local UI + Application Boundary | Runtime, API, frontend/backend integration | Local launch and functional operator-flow verification |
| `BETA-REQ-0003` | Structural invariant: Application-managed local persistence | Foundation Runtime / Persistence Boundary | Datastore connection, lifecycle, migration, backup/recovery specifications | Clean-install + offline persistence + restart verification |
| `BETA-REQ-0004` | Structural/quality invariant: Supported platform matrix | Deployment & Runtime Boundary | Packaging ADR / CI matrix / browser support | Hosted CI + representative Windows desktop verification |
| `BETA-REQ-0005` | Structural invariant: Proprietary/internal distribution boundary | Product / Trust Boundary | Repository, release, packaging, access-control policy | Repository/release governance inspection |
| `BETA-REQ-0006` | Structural invariant: Licensing and provenance isolation | Product Boundary / Release Governance | Repository notices, release metadata, asset provenance records | Licensing/provenance audit |
| `BETA-REQ-0007` | Structural invariant: Repository operational-data isolation | Product Boundary / Security Boundary | Repository policy, ignore rules, fixture governance, secret scanning | Repository-content and secret-scan verification |
| `BETA-REQ-0008` | Structural invariant: Bidirectional specification traceability | Cross-cutting Design Governance | Traceability index/schema and validation tooling | Forward + reverse coverage audit |
| `BETA-REQ-0009` | Use-case family: Install / Start / Stop SOMA | Foundation Runtime / Local Deployment | Setup, launcher, process lifecycle, shutdown, packaging | Clean-install + start/stop/restart verification |
| `BETA-REQ-0010` | Structural invariant: Identity independence | Shared Domain Identity / Persistence Boundary | ID generation, entity keys, uniqueness constraints, reconciliation mechanics | Schema + domain identity/reconciliation tests |
| `BETA-REQ-0011` | Structural invariant: Service Request identity lifecycle; use case: manually register/reconcile SR | Tickets / Shared Identity | SR identifier validation, local sequence allocation, reconciliation transaction | Identity canonicalization + reconciliation tests |
| `BETA-REQ-0012` | Structural invariant: Exact RFC business identity; use case: import/register/reconcile RFC | Tickets + Import/Reconciliation | RFC identifier parser, branch-artifact classification, staged-result taxonomy | RFC identity/import golden vectors |
| `BETA-REQ-0013` | Structural invariant: WFM business identity; use-case family: register/import/reconcile WFM | Objectives / Tickets relationship + Import/Reconciliation | WFM identifier validation and source parsing | WFM identity golden vectors |
| `BETA-REQ-0014` | Structural invariant: Spare Request identity continuity; use case: create/register/reconcile Spare Request | Inventory | Temporary ID generation, official-ID validation, reconciliation transaction | Identity continuity + duplicate-prevention tests |
| `BETA-REQ-0015` | Structural invariant: RMA obligation bridge; use cases: authorize/receive/review/return | Inventory | RMA lifecycle, cardinalities, target/inbound/return relationships, validation | RMA lifecycle and identity/cardinality scenarios |
| `BETA-REQ-0016` | Structural invariant: Physical spare identity survives incomplete provenance; use cases: register/enrich/receive/extract | Inventory | Local unit ID allocation, provenance relationships, enrichment/reconciliation rules | Unit identity/provenance/cardinality scenarios |
| `BETA-REQ-0017` | Structural invariant: Canonical scheduling-time integrity; use cases: schedule/reschedule Task or Objective | Objectives + Import/Reconciliation + cross-cutting Temporal Authority | Temporal types, timezone conversion, validation, persistence representation | Temporal golden vectors + timezone/rescheduling scenarios |
| `BETA-REQ-0018` | Structural invariant: Uniform transactional integrity | Foundation Runtime + all domain application boundaries | Validation order, DB constraints, unit-of-work, error taxonomy | Invariant + rollback + cross-entry-point tests |
| `BETA-REQ-0019` | Structural invariant: History preservation / exceptional deletion; use cases: archive/cancel/correct/supersede/delete eligible manual record | Cross-domain lifecycle + Audit | Deletion eligibility, impact preview, atomic cascade, audit/correction contracts | Lifecycle-preservation and destructive-action scenarios |
| `BETA-REQ-0020` | Structural invariant: Historical logistics evidence independence; use cases: submit/record/inspect logistics | Inventory + Reference Data boundary | Snapshot capture, immutable representation, historical projection rules | Mutable-master vs frozen-history scenarios |
| `BETA-REQ-0021` | Use-case family: Maintain operational reference data | Identity & Settings / shared reference boundary | Customer Organization and Contact commands, queries, validation and lifecycle | Reference-data creation, maintenance, reuse and history scenarios |
| `BETA-REQ-0022` | Structural invariant: Authentication/person-domain separation; use cases: setup/login + maintain Contacts + assign roles | Identity & Settings / Authentication Boundary | Local User Profile singleton, Contact role relationships, authentication model | Singleton-authentication + reusable-role scenarios |
| `BETA-REQ-0023` | Structural invariant: Operation-neutral Dispatch Location identity; use cases: configure/select logistics location | Identity & Settings + Inventory relationship boundary | Dispatch Location relationships, role typing, logistics validation | Role-reuse and pickup-origin semantics scenarios |
| `BETA-REQ-0024` | Structural invariant: Site ↔ dedicated Dispatch Location relationship; use case: register/maintain Site | Infrastructure + Identity/Settings + Inventory reference boundary | Creation transaction, cardinality constraints, address derivation and snapshot interaction | Site creation/linkage/address/history scenarios |
| `BETA-REQ-0025` | Use-case family: Archive / reactivate reference data | Identity & Settings + cross-domain dependency boundary | Archival eligibility, selectors, dependency checks, lifecycle evidence | Archive/reactivate/history-preservation scenarios |
| `BETA-REQ-0026` | Structural invariant: Customer-neutral logistics-location identity; use cases: maintain/select Dispatch Location | Identity & Settings + Inventory relationship boundary | Relationship constraints, derived-context queries, selector validation | Ownership-neutrality and cross-context logistics scenarios |
| `BETA-REQ-0027` | Structural invariant: Site-rooted Infrastructure ownership; use cases: register Site / regularize Device Reference / assign Cloud Deployment | Infrastructure + Customer reference boundary | Site ownership/cardinality, Cloud relationships, regularization, duplicate review | Ownership, placement, progressive-registration, duplicate-site scenarios |

## Two-way coverage audit

### Forward check — source requirement → normalized authority

Every material assertion in each source requirement was checked against its accepted governing obligation and stable clauses. Dense mechanics were decomposed rather than discarded. `BETA-REQ-0013` was retained because its source wording was already atomic.

**Result: 27/27 PASS.**

### Reverse check — clause → product authority

Every CP-001 clause is attached to an immutable approved `BETA-REQ-####` and was explicitly accepted by the project owner during normalization. Cross-cutting clarifications remain bounded by already accepted Beta product authority and do not grant HLD or LLD permission to invent product behavior.

**Result: 183/183 PASS.**

### Terminology and ownership check

- `Objective` remains the product concept; Maintenance Window is not introduced as a competing record identity.
- Objective/Task selectable timezone authority remains separate from SLA and source-adapter timezone authority.
- Dispatch Location identity remains separate from Customer Organization ownership, Datacenter Site identity, logistics role, and warehouse destination.
- RMA identity remains separate from target, inbound, and return physical-unit identity.
- Authentication identity remains separate from reusable operational Contact identity.
- Current mutable logistics master data remains separate from immutable historical logistics evidence.

**Result: PASS.**

## Conclusion

CP-001 introduces no requirement renumbering, no silent deletion of approved behavior, and no known product contradiction. Any future conflict discovered during later normalization must return to explicit product authority rather than being reconciled silently in design.
