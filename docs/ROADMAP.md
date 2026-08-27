# SOMA Beta Roadmap

The roadmap is contract-first. Dates are intentionally absent until foundation review closes and work can be estimated from accepted low-level designs.

## Phase 0 — Product foundation (current)

Deliverables:

- product contract and canonical terminology;
- Product Line/SLA contract;
- high-level architecture and module boundaries;
- brand/UX contract;
- decision ledger and explicit release boundary; and
- review against representative SR, RFC, WFM, inventory, and mail artifacts.

Exit criteria: confirmed rules are internally consistent, open decisions have owners/order, and no unresolved ambiguity blocks schema design.

## Phase 1 — Low-level design

Deliverables:

- clean relational/domain schema and migration-free initialization;
- state machines and invariants for Tickets, Tasks/Objectives, Inventory, and Infrastructure;
- import mapping contracts for each official Excel source;
- SLA calculation specification and golden test vectors;
- encryption, key lifecycle, backup, recovery, and export threat model;
- offline PST/OST and MSG feasibility ADR;
- API/application boundary and local process lifecycle;
- packaging/support matrix and Windows tray behavior;
- responsive information architecture and primary workflow prototypes; and
- selective Alpha asset/reuse inventory, including canonical brand files.

Exit criteria: every 1.0.0 acceptance rule maps to a design, test strategy, and owned module.

## Phase 2 — Beta 1.0.0 implementation

Minimum integrated scope:

1. secure local bootstrap, login, optional auto-login, settings, backup/recovery;
2. Tickets with manual registration, population, relationships, Product Line, and SLA;
3. Objectives with Task/WFM scheduling, conflicts, outcomes, and review;
4. Inventory with BOM counts, Spare Needs, Spare Requests, RMAs, serialized units, and dispatch history;
5. Infrastructure with customer/cloud/site placement, device models/instances, components, and replacement history;
6. Overview with configurable period summaries, timeline, attention queues, filters, and Excel output;
7. read-only PST/OST evidence indexing and MSG draft generation;
8. responsive English light/dark UI using canonical branding; and
9. Windows packaging and tray lifecycle.

Quality gates include invariant tests, import golden files, SLA golden calculations, encryption/recovery tests, destructive-impact tests, accessibility checks, and an offline installation acceptance run.

## Phase 3 — Beta 1.x.0

Planned candidates:

- SSH/device operations within Infrastructure;
- device connectivity and topology;
- language switching; and
- refinements driven by 1.0.0 field use.

Candidates enter a release only after their own product and architecture contracts are accepted.

## Explicit non-goals for 1.0.0

- shared multi-user or cloud deployment;
- direct email send/receive;
- arbitrary report builders;
- Zeus/Alpha historical database migration;
- SSH or automated device connectivity; and
- wholesale reuse of Alpha code or schema.
