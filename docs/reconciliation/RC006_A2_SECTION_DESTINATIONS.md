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
| `A2-MAP-000008` | `RUNTIME-001`..`RUNTIME-001` | `BETA-REQ-0002` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | `docs/FOUNDATION_RUNTIME_CONTRACT.md` | `A2-ASSERT-000018` | Product §3's locally running installation represents the locally served operator-experience boundary. | `PASS` |
| `A2-MAP-000009` | `PERSIST-004`..`PERSIST-004` | `BETA-REQ-0003` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | `docs/FOUNDATION_RUNTIME_CONTRACT.md` | `A2-ASSERT-000018` | Product §3 explicitly preserves local authoritative operation during loss/absence of external connectivity. | `PASS` |
| `A2-MAP-000010` | `AUTH-001`..`AUTH-002` | `BETA-REQ-0035` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000019` | Product §3 preserves exactly one installation authentication profile/local administrator rather than a user-account population. | `PASS` |
| `A2-MAP-000011` | `ADMIN-SETUP-001`..`ADMIN-SETUP-003` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000019`, `A2-ASSERT-000020` | Product §3 represents the singleton Local Administrator and its generated stable internal identity. | `PASS` |
| `A2-MAP-000012` | `ADMIN-SETUP-004`..`ADMIN-SETUP-005` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000021` | Initial authentication setup requires password and confirmation. | `PASS` |
| `A2-MAP-000013` | `ADMIN-SETUP-007`..`ADMIN-SETUP-007` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000022` | Product §3 preserves password-only login without username identity. | `PASS` |
| `A2-MAP-000014` | `ADMIN-SETUP-008`..`ADMIN-SETUP-010` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000023`, `A2-ASSERT-000024` | Product §3 represents the default display name and optional non-authenticating username-like display metadata. | `PASS` |
| `A2-MAP-000015` | `ADMIN-SETUP-011`..`ADMIN-SETUP-013` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000025`, `A2-ASSERT-000026` | Product §3 keeps Local Administrator email/phone optional and places operational channels on reusable Contacts. | `PASS` |
| `A2-MAP-000016` | `ACTOR-003`..`ACTOR-003` | `BETA-REQ-0022` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000027` | Registered operational people remain reusable Contacts and do not receive authentication profiles merely by participating in workflows. | `PASS` |
| `A2-MAP-000017` | `CONTACT-AFF-002`..`CONTACT-AFF-002` | `BETA-REQ-0029` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000028`, `A2-ASSERT-000029` | Product §3 preserves the valid unbound-Contact state and therefore does not require Customer Organization affiliation merely to register a person. | `PASS` |
| `A2-MAP-000018` | `CONTACT-LIFE-001`..`CONTACT-LIFE-001` | `BETA-REQ-0031` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000028`, `A2-ASSERT-000029` | Contact creation permits no affiliation or exactly one active Customer Organization affiliation. | `PASS` |
| `A2-MAP-000019` | `CONTACT-COMM-001`..`CONTACT-COMM-007` | `BETA-REQ-0067` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000030` | Product §3 summarizes the accepted rule that missing communication channels do not block ordinary Ticket/Task/Objective creation, review, scheduling, execution, or historical viewing. | `PASS` |
| `A2-MAP-000020` | `CONTACT-COMM-008`..`CONTACT-COMM-008` | `BETA-REQ-0067` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000031` | Communication channels are validated just in time when an action actually requires a recipient. | `PASS` |
| `A2-MAP-000021` | `CONTACT-COMM-012`..`CONTACT-COMM-017` | `BETA-REQ-0067` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000032` | Failure to resolve a required recipient blocks only the communication-dependent action and not the underlying operational records. | `PASS` |
| `A2-MAP-000022` | `AUTH-007`..`AUTH-009` | `BETA-REQ-0035` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000034` | Product §3's explicit automatic-login option is optional, Windows-protected, and non-password-storing under the authentication contract. | `PASS` |
| `A2-MAP-000023` | `ADMIN-SETUP-043`..`ADMIN-SETUP-045` | `BETA-REQ-0078` | `docs/PRODUCT_CONTRACT.md#3-deployment-and-operator-model` | — | `A2-ASSERT-000034` | The later normalized administrator setup authority independently confirms the optional Windows-protected automatic-login boundary. | `PASS` |

## Open semantic dispositions from Product §§1–3

These are deliberately **not forced into PASS mappings** yet:

- `A2-ASSERT-000001` — high-level local/offline product-intent synthesis; likely multi-owner representation and requires exact clause decomposition.
- `A2-ASSERT-000002` — cross-domain product-intent synthesis (service obligations, work, spare logistics, Infrastructure history); requires multi-domain authority review.
- `A2-ASSERT-000003` and `A2-ASSERT-000004` — game/terminal-inspired presentation direction; likely `BETA-REQ-0126` (`UI-THEME`) authority, to be mapped when the Product-intent section is reviewed as one cross-cutting slice.
- `A2-ASSERT-000012` — the requirement for a *separately accepted contract* before any later Alpha-data importer is stronger/more specific than `LINEAGE-003`'s explicit-Beta-evaluation wording; exact canonical authority must be established or the representation narrowed/superseded.
- `A2-ASSERT-000014` — proprietary/internal-use rights are mapped, but the factual statement that the assets contain no third-party material requiring a surviving license is not independently established by `PROVENANCE-002`; this portion requires disposition before the assertion may become `PASS`.
- `A2-ASSERT-000016` and `A2-ASSERT-000017` — HLD → LLD → implementation sequencing is a project-governance gate and requires exact canonical authority identification before semantic PASS.
- `A2-ASSERT-000033` — “Password login is required” is directionally consistent with password authentication, but the reviewed clauses explicitly require a password at setup and constrain password authentication without yet establishing this exact always-password-login wording as a standalone Product assertion. Exact authority/disposition remains open.
- `A2-ASSERT-000035` and `A2-ASSERT-000036` — separate installations for multiple evaluators / no shared multi-user database are consistent with singleton-per-installation authority but need an exact product-authority clause before semantic PASS; singleton identity alone must not be stretched into an unrelated deployment restriction.

## Progress accounting

- Allocated destination assertions: **653**.
- Semantically mapped in this file so far: **26 assertion identities with at least one reviewed forward edge** (`000005`–`000011`, `000013`–`000015`, `000018`–`000032`, `000034`; `000014` remains only partially covered).
- Fully authority-ready assertions so far: **25** (all mapped identities above except the unresolved portion of `000014`).
- Assertions deliberately left open in Product §§1–3: **10** (`000001`–`000004`, `000012`, `000016`, `000017`, `000033`, `000035`, `000036`) plus the unresolved third-party-material portion of `000014`.
- Reverse-ledger fields remain to be updated from these reviewed rows before these slices are considered end-to-end complete.
- Overall RC-006-A2 certification remains **OPEN**.
