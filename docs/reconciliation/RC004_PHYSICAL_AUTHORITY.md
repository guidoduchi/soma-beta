# SOMA Beta Reconciliation RC-004 — Inventory and Infrastructure Physical Authority

Status: **Accepted reconciliation record**  
Baseline: `RC-003` commit `0c7ae9d8a3a799d0e7de6bb9c4d782668cc70bef`  
Scope: `docs/INVENTORY_LIFECYCLE.md` and `docs/INFRASTRUCTURE_CONTRACT.md`

## Purpose

RC-004 reconciles SOMA's physical-truth layer against the normalized catalogue and reconciled RC-001 through RC-003 authority. It repairs representation drift only. It introduces no new Inventory lifecycle state, Infrastructure topology capability, evidence requirement, identifier, or Task outcome.

Primary authority includes `BETA-REQ-0014`–`0016`, `0023`–`0027`, `0032`–`0034`, `0038`, `0049`–`0050`, `0079`–`0110`, and their stable clauses, plus the already reconciled Task/Objective and Workbench boundaries.

## Inventory reconciliation

RC-004 preserves the accepted Spare Need, Stock, Spare Request, RMA, physical-unit, logistics, Fault Tag, warehouse, manual/proposal, correction, and no-upload workflows.

It repairs these boundaries:

1. **Task outcome ownership** — Inventory no longer presents itself as the authority that records/decides a Task outcome. Objectives/Task lifecycle owns execution/outcome/review/correction/retry; Inventory owns Task-to-unit allocation and the reviewed physical consequences consumed from that outcome.
2. **Physical consequence representation** — the former generic `Replacement outcome` wording is clarified as an Inventory-owned reviewed maintenance physical consequence linked to an already reviewed Task outcome. This preserves installed/removed/unused/faulty/incompatible/dismantled physical truth without creating a second Task state machine.
3. **Return-unit derivation** — RMA return-unit selection remains deterministic/reviewable from the accepted reviewed Task outcome plus Inventory physical consequence and never overwrites inbound BOM/serial identity.
4. **Spare Need lifecycle** — reuse, Resolve/Cancel/Reactivate, removal blockers, history-preserving removal, and narrow untouched-draft hard deletion are now explicitly represented.
5. **Requester Contact lifecycle** — Spare Request requester/receiver remains a reusable Contact relationship; archived Contacts cannot be newly selected and active request dependencies block incompatible archival.
6. **Dispatch Location semantics** — logistics roles remain operation-specific and customer-neutral; Site/address changes cannot rewrite frozen submission or pickup evidence.
7. **Fault Tag provenance** — membership derives from reviewed Task outcome plus accepted Inventory physical consequence, while warehouse receipt, final acceptance/rejection, correction replacement, and resend remain independent history.

## Infrastructure reconciliation

RC-004 preserves Infrastructure as the canonical registered-device domain, Device Reference validity before registration, Network Element identity, placement, Models, Components, IP inventory, containment, Cloud Deployment, SQLite authority, workbook exchange, and Beta 1.0 connectivity/SSH exclusion.

It repairs these boundaries:

1. **Site/Dispatch Location coverage** — every Site has one dedicated Dispatch Location created during governed Site creation; a Dispatch Location may exist independently but links to at most one Site; the two remain distinct identities.
2. **Address authority** — a Site-linked Dispatch Location derives its current address from Site and cannot diverge through ordinary editing; historical logistics snapshots remain immutable.
3. **Customer neutrality** — Dispatch Location has no direct Customer ownership/preference. Any Customer context is derived from an optional linked Site and does not restrict unrelated valid logistics use.
4. **Site lifecycle** — Site Customer ownership is stable, with narrow pre-history correction; Site archival is blocked by active Infrastructure/operational dependencies and preserves the dedicated Dispatch Location unless a separate reviewed lifecycle action says otherwise.
5. **Dispatch lifecycle** — active-Site and unfinished-logistics dependencies block archival; archived locations remain historical and require explicit reactivation before new use.
6. **Duplicate Site review** — normalized-address similarity produces review candidates, never automatic merge.
7. **Device Reference regularization** — promotion/reconciliation can resolve to exactly one existing or new Network Element while preserving Device Reference identity and operational relationships; terminal SR history does not block later regularization or get rewritten by it.
8. **Derived ownership/context** — Network Element Customer derives through Site; Cloud Type derives through Cloud Deployment; containment, placement, Cloud, IP, Components, and connectivity remain independent authorities.
9. **Task/physical boundary** — Infrastructure Component installation/removal consumes reviewed physical consequences and preserves physical history without becoming Task-outcome authority.

## Reverse reconciliation

Every strengthened normative assertion above traces to accepted normalized requirements/stable clauses or reconciled upstream authority. RC-004 does not choose exact Rack/U occupancy mechanics, IP duplicate scopes, workbook limits, matching heuristics, topology design, SSH mechanics, or Task outcome transition tables.

## Product-owner decisions

New product-owner decisions opened by RC-004: **0**.

Known unresolved Phase-0 product ambiguities remain: **0**.

## Result

- Forward requirement coverage: **PASS**
- Reverse authority: **PASS**
- Task/Inventory ownership consistency: **PASS**
- Inventory/Infrastructure identity and relationship consistency: **PASS**
- Site/Dispatch Location cross-domain consistency: **PASS**
- Requirement identities changed: **0**
- Stable clause identities changed: **0**
- Product behavior invented: **0**
- Open design boundaries silently resolved: **0**
