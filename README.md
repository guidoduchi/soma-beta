# SOMA Beta

**Service Operations Management Application**

SOMA Beta is a local, offline-first operations workspace for service tickets, maintenance work, spare-parts logistics, infrastructure history, and SLA control. It is a clean product and schema lineage: Zeus and SOMA Alpha are historical checkpoints and selective sources, not codebases or databases to migrate wholesale.

## Product status

Phase 0 requirement normalization and foundation contract reconciliation are complete through `RC-006`, with the `RC-006-A1` corrective assurance amendment applied. The foundation is **ready for project-owner Phase 0 closure acceptance**; business use cases and the complete HLD begin only after that acceptance, followed by the complete Beta 1.0.0 LLD.

No production code, final database schema, or Alpha data migration is approved by this foundation state. Production implementation remains blocked until the entire Beta 1.0.0 LLD is accepted.

## Canonical work areas

1. **Overview** — configurable Daily, Weekly, and Monthly progress summaries plus an operational narrative.
2. **Tickets** — Service Requests and Requests for Change.
3. **Objectives** — Maintenance Windows composed of Tasks, including WFM Tasks.
4. **Inventory** — Stock, Spare Requests, and Fault Tags, including Spare Need, RMA, and physical-unit lifecycles.
5. **Infrastructure** — customer-owned Datacenter Sites, Cloud Types and Deployments, racks, Network Elements, and component history.
6. **Settings** — the Local User Profile, Contacts, reusable reference data, and installation-wide configuration.

These names and this order are product language. `Settings` must not be renamed to `Administration`.

## Foundation authority and documents

The normalized governing obligations and canonical stable clauses are current product authority. `docs/BETA_REQUIREMENTS.md` remains the preserved **pre-normalization baseline** and must not be used as a substitute for the normalized catalogue/clauses.

- [Requirement normalization authority and doctrine](docs/REQUIREMENT_NORMALIZATION.md)
- [Normalized catalogue, canonical clauses, clause authority, and checkpoint audits](docs/normalization/)
- [Foundation reconciliation index](docs/reconciliation/RECONCILIATION_INDEX.md)
- [Foundation reconciliation doctrine](docs/reconciliation/RECONCILIATION_METHOD.md)
- [Literal canonical clause destination audit](docs/reconciliation/RC006_CLAUSE_DESTINATIONS.md)
- [Pre-normalization Beta requirement baseline](docs/BETA_REQUIREMENTS.md)
- [Alpha-to-Beta traceability register](docs/ALPHA_TRACEABILITY.md)
- [Foundation gaps register](docs/FOUNDATION_GAPS.md)
- [Product contract](docs/PRODUCT_CONTRACT.md)
- [Import contract](docs/IMPORT_CONTRACT.md)
- [RFC/WFM import, lifecycle, and grouping contract](docs/RFC_WFM_CONTRACT.md)
- [Ticket and Objective workbench contract](docs/WORKBENCH_CONTRACT.md)
- [Inventory lifecycle contract](docs/INVENTORY_LIFECYCLE.md)
- [UI/UX interaction contract](docs/UI_UX_CONTRACT.md)
- [Foundation runtime, persistence, audit, and verification contract](docs/FOUNDATION_RUNTIME_CONTRACT.md)
- [Infrastructure contract](docs/INFRASTRUCTURE_CONTRACT.md)
- [Communications contract](docs/COMMUNICATIONS_CONTRACT.md)
- [Domain glossary](docs/GLOSSARY.md)
- [Contract Product Line and SLA contract](docs/PRODUCT_LINE_SLA.md)
- [High-level architecture synthesis](docs/ARCHITECTURE.md)
- [Brand and UX contract](docs/BRANDING.md)
- [Decision ledger](docs/DECISIONS.md)
- [Release roadmap](docs/ROADMAP.md)

## Foundation principles

- Fully usable without internet, cloud services, or an email server.
- One authenticating Local User Profile per installation; Contacts recorded in the business domain are not login accounts.
- Source imports populate operational records without erasing local relationships, notes, history, or review state—the “soul of SOMA.”
- Contract Product Line classification and cohort SLA behavior remain a core purpose of SOMA.
- Dependencies are deliberately few, pinned, auditable, and isolated behind SOMA-owned adapters.
- Game-inspired information architecture makes work legible; the visual identity remains precise and restrained.

## Version intent

`1.0.0` delivers the six functional work areas, local security, supported imports and Infrastructure workbook exchange, status-driven RFC/WFM history with local filtering and reviewed Objective grouping, target-gated read-only PST/OST processing with terminal orphan grace/purge, MSG draft generation, Excel exports, Contract Product Line/SLA control, a responsive terminal-inspired interface with curated skins and Light/Dark/System appearance, vSphere/Wireshark-derived information patterns, deliberate confirmation and governed fixtures, an atomic SQLite/migration/audit runtime, Windows/Python verification, and Windows tray behavior. Device operations such as SSH, topology, and language switching belong to `1.x.0`.