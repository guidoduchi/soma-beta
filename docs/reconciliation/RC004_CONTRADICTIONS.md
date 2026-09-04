# SOMA Beta Reconciliation RC-004 — Contradiction Report

Status: **Accepted**

## Resolved in RC-004

| ID | Finding | Resolution |
|---|---|---|
| `RC004-C01` | Inventory's `Replacement outcome` wording could make Inventory appear authoritative for what occurred during a Task. | Reframed as Inventory-owned reviewed physical consequence consuming an Objectives/Task-owned reviewed outcome. |
| `RC004-C02` | Inventory section 10 said the operator confirms the outcome inside Inventory. | Task outcome review/correction is explicitly owned by Objectives/Task lifecycle; Inventory records/reviews resulting physical facts. |
| `RC004-C03` | Spare Need reuse was represented but normalized Resolve/Cancel/Reactivate/removal/hard-delete mechanics were incomplete. | Added complete history-preserving Need lifecycle boundary. |
| `RC004-C04` | Spare Request Contact suggestion did not fully express requester Contact archival/history rules. | Added reusable Contact relationship and active-dependency archival boundary. |
| `RC004-C05` | Infrastructure omitted the normalized dedicated Site↔Dispatch Location contract. | Added exact Site one-location / Dispatch zero-or-one-Site relation and Site-creation behavior. |
| `RC004-C06` | Infrastructure did not state that a Site-linked Dispatch Location's current address derives from Site. | Added derived-address and historical-snapshot non-rewrite rules. |
| `RC004-C07` | Infrastructure did not state Dispatch Location customer neutrality/lifecycle strongly enough. | Added no direct Customer ownership/preference plus archive/reactivate dependencies. |
| `RC004-C08` | Site stable ownership, archival blockers, and duplicate-location review were absent from the focused Infrastructure contract. | Added normalized Site lifecycle and review boundaries. |
| `RC004-C09` | Device Reference promotion wording used `repoints`, which could be read as rewriting historical operational relationships. | Clarified exact regularization to existing/new Network Element while preserving Device Reference identity, valid relationships, and historical evidence. |
| `RC004-C10` | Infrastructure Component history could be read as owning Task execution/outcome. | Clarified that Infrastructure consumes reviewed physical consequences and owns only physical installation/removal history. |

## Not contradictions

- A Spare Need remaining reusable after prior fulfillment is intentional.
- A Spare Request may receive fewer RMAs than requested and remain partially authorized.
- Actual inbound BOM/serial may differ from promised or requested facts; compatibility remains reviewed.
- Fault Tag warehouse receipt and final acceptance are deliberately distinct.
- Genuine warehouse rejection/resend is new history, not correction rollback.
- Unregistered Device References are valid throughout supported workflows.
- A registered Network Element requires exactly one Site while an unregistered Device Reference may have none.
- Dispatch Location may exist without a Site and is not Customer-owned.
- Cloud Type is reusable while Cloud Deployment is Site-scoped.
- SQLite remains authoritative; any future graph is disposable derived projection.

## Downstream queue

1. `ARCHITECTURE.md` still contains the known stale Task-outcomes-under-Inventory ownership sentence. RC-004 strengthens the canonical evidence needed to patch it in RC-006.
2. Communications, UI/UX, Foundation Runtime, and Branding remain scheduled for RC-005.
3. Roadmap/Architecture/global bidirectional closeout remains scheduled for RC-006.

Unresolved product contradiction after RC-004: **0**.
