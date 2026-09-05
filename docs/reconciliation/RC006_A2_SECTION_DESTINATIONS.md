# RC-006-A2 — Accumulated Section Destination Map

Status: **WORKING — semantic authority mapping in progress; not certification evidence**  
Baseline: `A2-BASELINE-002`  
Assertion ledger: `docs/reconciliation/RC006_A2_ASSERTION_AUTHORITY.jsonl`  
Canonical clause authority: accepted CP-001..CP-007 clause catalogues and clause-authority matrices.

## Operating rule

This is the single maintained human-reviewed forward map for RC-006-A2. Contract batches update this file and the assertion authority ledger. Local accumulated validation may be run after a batch for feedback, but intermediate runs do not create committed reports, workflow artifacts, hash narratives, or approval gates. Only the final full-corpus validation becomes A2 certification evidence.

A mapping row records canonical authority already accepted elsewhere; it does not create new product authority. Rows marked `PASS` have completed semantic review for the represented clause range and listed normative destination assertions. Unsupported, partial, duplicated, or contradictory representations remain outside a PASS row until explicitly disposed.

## Mapping rows

| Map row | Canonical clause range | Owner | Primary destination | Supporting destinations | Normative assertions | Representation note | Semantic review |
|---|---|---|---|---|---|---|---|
| `A2-MAP-000001` | `LINEAGE-001`..`LINEAGE-001` | `BETA-REQ-0001` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000005`, `A2-ASSERT-000010` | Product §2 represents the independent Beta repository/schema/migration lineage through the clean `soma-beta` repository boundary and independent schema/migration lineage. | `PASS` |
| `A2-MAP-000002` | `LINEAGE-002`..`LINEAGE-002` | `BETA-REQ-0001` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000006`, `A2-ASSERT-000009`, `A2-ASSERT-000011` | Product §2 represents Zeus/Alpha as historical rather than executable or migration ancestors; the no-Alpha-migration and no-auto-upgrade statements are representations of that boundary. | `PASS` |
| `A2-MAP-000003` | `LINEAGE-003`..`LINEAGE-003` | `BETA-REQ-0001` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000007`, `A2-ASSERT-000008` | Product §2 requires explicit Beta evaluation before historical Alpha work is reused and rejects wholesale Alpha PR reuse. | `PASS` |
| `A2-MAP-000004` | `LINEAGE-004`..`LINEAGE-004` | `BETA-REQ-0001` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000008`, `A2-ASSERT-000009`, `A2-ASSERT-000011` | Product §2 preserves the no-continuity consequence of historical reuse: wholesale merge, inherited migration requirement, and continuation/upgrade of Alpha persistence are excluded. | `PASS` |
| `A2-MAP-000005` | `PROVENANCE-001`..`PROVENANCE-001` | `BETA-REQ-0006` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000013` | Product §2 preserves Alpha-origin provenance for the canonical SOMA brand assets. | `PASS` |
| `A2-MAP-000006` | `PROVENANCE-002`..`PROVENANCE-002` | `BETA-REQ-0006` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000014` | The proprietary/internal-use rights statement is supported by the accepted owner-rights/relicensing authority. The additional statement that these assets contain no surviving third-party material remains separately pending semantic disposition and is not certified by this row. | `PASS — PARTIAL ASSERTION COVERAGE` |
| `A2-MAP-000007` | `PROVENANCE-003`..`PROVENANCE-004` | `BETA-REQ-0006` | `docs/PRODUCT_CONTRACT.md#2-lineage-and-migration-boundary` | — | `A2-ASSERT-000015` | Product §2 preserves Alpha's Apache-2.0 license as an Alpha-repository property and prevents historical derivation from imposing that license on unrelated Beta material or independently owned assets. | `PASS` |

## Open semantic dispositions from Product §§1–2

These are deliberately **not forced into PASS mappings** yet:

- `A2-ASSERT-000001` — high-level local/offline product-intent synthesis; likely multi-owner representation and requires exact clause decomposition.
- `A2-ASSERT-000002` — cross-domain product-intent synthesis (service obligations, work, spare logistics, Infrastructure history); requires multi-domain authority review.
- `A2-ASSERT-000003` and `A2-ASSERT-000004` — game/terminal-inspired presentation direction; likely `BETA-REQ-0126` (`UI-THEME`) authority, to be mapped when the Product-intent section is reviewed as one cross-cutting slice.
- `A2-ASSERT-000012` — the requirement for a *separately accepted contract* before any later Alpha-data importer is stronger/more specific than `LINEAGE-003`'s explicit-Beta-evaluation wording; exact canonical authority must be established or the representation narrowed/superseded.
- `A2-ASSERT-000014` — proprietary/internal-use rights are mapped, but the factual statement that the assets contain no third-party material requiring a surviving license is not independently established by `PROVENANCE-002`; this portion requires disposition before the assertion may become `PASS`.
- `A2-ASSERT-000016` and `A2-ASSERT-000017` — HLD → LLD → implementation sequencing is a project-governance gate and requires exact canonical authority identification before semantic PASS.

## Progress accounting

- Allocated destination assertions: **653**.
- Semantically mapped in this file so far: **9 assertion identities with at least one reviewed forward edge** (`000005`–`000011`, `000013`–`000015`; `000014` remains only partially covered).
- Fully authority-ready assertions in this slice: **8** (`000005`–`000011`, `000013`, `000015`).
- Assertions deliberately left open in Product §§1–2: **7** (`000001`–`000004`, `000012`, `000016`, `000017`) plus the unresolved third-party-material portion of `000014`.
- Reverse-ledger fields remain to be updated from these reviewed rows before this slice is considered end-to-end complete.
- Overall RC-006-A2 certification remains **OPEN**.
