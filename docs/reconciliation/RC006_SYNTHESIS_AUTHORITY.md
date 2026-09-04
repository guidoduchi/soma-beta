# SOMA Beta Reconciliation RC-006 — Synthesis Authority

Status: **Accepted reconciliation record**  
Baseline: `RC-005` commit `859645476df96ab0687adfb45e7ad66043ed00a9`  
Scope: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, repository-facing foundation status/index text, and final global reconciliation.

## Purpose

RC-006 reconciles the derived synthesis layer only after every owning focused contract has already passed its own forward/reverse audit. It cannot create product authority. It repairs Architecture, Roadmap, and repository-facing navigation/status so they accurately project the normalized requirements, `D-158`, and RC-001 through RC-005 contracts.

No requirement identity, governing obligation, canonical clause, clause owner, focused-contract product rule, or open technical-design item is changed by RC-006.

## Architecture reconciliation

RC-006 repairs the following synthesis defects:

1. **Task ownership** — Objectives/Task lifecycle explicitly owns Task operational planning, execution, outcome, review, correction, cancellation, and retry. Inventory owns Task-to-unit allocations and reviewed physical consequences only.
2. **Audit authority** — application audit records accepted SOMA commands/decisions/configuration/relationship mutations; it no longer claims ownership of accepted domain facts or lifecycle evidence.
3. **Planning separation** — WFM source plan, accepted operational Task plan, derived Objective envelope, and actual execution are represented as separate authorities.
4. **Report-storage design boundary** — Architecture no longer selects persisted completed-report snapshots. Immutable completed-report evidence remains required while persisted/on-demand/both stays `O-001`.
5. **Device Reference resolution** — regularization preserves Device Reference identity and existing relationships without generic historical “repointing.” Resolution to an existing Network Element remains distinct from creation/promotion of a new Network Element; new creation/promotion retains the three-second hold.
6. **Objective grouping input** — grouping consumes accepted operational Task intervals, not raw WFM source-plan authority.
7. **RFC Communication unlink** — provider terminal evidence/import acceptance cannot unlink RFC Communications; only the separately confirmed local terminal cascade can do so.
8. **Platform support** — Architecture states the fixed Windows 10/11 x64 + Python 3.13/3.14 product boundary while preserving exact build/browser/runner/packaging choices under `O-006`.
9. **Canonical vocabulary** — `Contact` replaces stale `registered people` terminology and module ownership wording is aligned to focused contracts.
10. **Release synthesis** — Beta 1.0 Task lifecycle and Inventory physical consequences are described without transferring ownership between modules.

## Roadmap reconciliation

RC-006 repairs roadmap status and release sequencing without changing accepted scope:

1. normalization is recorded complete at 177/177 and 11,524 clauses;
2. contract reconciliation is recorded complete through RC-006;
3. Phase 0 is at its closure gate rather than still waiting for normalization/use-case/LLD work;
4. stale Task `cloning` wording is replaced by new Task attempts with immutable predecessor lineage;
5. Inventory consumes reviewed Task physical consequences rather than owning Task outcomes;
6. `Contact` replaces `registered people` as canonical reference vocabulary;
7. brand provenance follows `D-158` rather than conditional Apache-2.0 inheritance language;
8. exact platform-design work cannot narrow the accepted Windows/Python product matrix;
9. Phase 5 RFC Communication unlink requires the confirmed local cascade; and
10. report deliverables preserve `O-001` rather than selecting an internal completed-report storage strategy.

## Repository-facing status reconciliation

RC-006 also repairs navigation/status text that could otherwise misdirect downstream work:

- README now identifies `docs/BETA_REQUIREMENTS.md` as the preserved pre-normalization baseline and points first to the normalization and reconciliation authorities.
- README uses canonical `Contact` terminology and Light/Dark/System appearance.
- `FOUNDATION_GAPS.md` records all sixteen existing gaps as resolved and reports no new RC-006 product gap.
- `REQUIREMENT_NORMALIZATION.md` records the Architecture Task-ownership defect as resolved by reconciliation while changing no normalization content.
- `RECONCILIATION_INDEX.md` records RC-001 through RC-006 complete and distinguishes reconciliation completion from the still-pending project-owner Phase 0 closure acceptance.

## Reverse authority

Every material RC-006 assertion resolves to one or more of:

- accepted normalized governing obligations/stable clauses;
- `D-158`;
- an already reconciled focused contract; or
- an explicit `O-*`/future-release boundary.

Architecture and Roadmap remain derived synthesis. They do not override focused contract meaning.

## Product-owner decisions

New product-owner decisions opened by RC-006: **0**.

Known unresolved Phase 0 product ambiguities: **0**.

## Result

- Architecture forward/reverse reconciliation: **PASS**
- Roadmap forward/reverse reconciliation: **PASS**
- Repository-facing authority navigation/status: **PASS**
- Requirement identities changed: **0**
- Canonical stable clause IDs changed: **0**
- Clause owners changed: **0**
- Product behavior invented: **0**
- Open design boundaries silently resolved: **0**
