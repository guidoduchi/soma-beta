# RC-006-A2 — Execution Baseline Pin

Baseline ID: **`A2-BASELINE-002`**  
Status: **PREPARATION — source snapshot not yet pinned; A2 mass mapping prohibited until the follow-up control commit records PINNED / VERIFIED**  
Repository: `guidoduchi/soma-beta`  
Provenance branch: `foundation/product-contract-v0.1`  
Source commit: **TO_BE_PINNED_AFTER_PREPARATORY_STATE**  
Source Git tree: **TO_BE_PINNED_AFTER_PREPARATORY_STATE**  
Supersedes for A2 execution: `A2-BASELINE-001` (historical preparation snapshot; not used for mass mapping after this rebaseline).

## Purpose

This record controls the exact immutable repository input corpus against which RC-006-A2 assertion extraction, forward clause placement, reverse normative authority, fingerprints, and validation results are computed. Branch names are provenance only; validation reads the immutable source commit/tree recorded here once this baseline is PINNED / VERIFIED.

## Option-B pin model

A Git tree cannot contain a file that already knows the hash of that same tree. SOMA therefore uses a strict two-step baseline protocol:

1. finalize every included normative/synthesis input and every repository-facing status correction;
2. take that completed preparatory commit/tree as the source snapshot; then
3. create one follow-up control commit that modifies **only this baseline-control file** to insert the exact source commit/tree and mark the baseline PINNED / VERIFIED.

`RC006_A2_EXECUTION_BASELINE.md` is baseline-control metadata and is explicitly excluded from the normative A2 input corpus. Therefore the follow-up pin-only commit does not alter or invalidate the source snapshot it identifies.

## Included source corpus

The entire pinned Git tree is retained for reproducibility, but A2 assertion extraction and destination interpretation use only the normative-input subset below:

- accepted normalized catalogues, canonical clauses, clause-authority records, and checkpoint traceability under `docs/normalization/`;
- the accepted Product, Import, RFC/WFM, Workbench, Product Line/SLA, Inventory, Infrastructure, Communications, UI/UX, and Foundation Runtime contracts;
- accepted synthesis/authority documents needed to interpret destinations: Architecture, Glossary, Decisions, Branding, Roadmap, Foundation Gaps, Requirement Normalization, and reconciliation artifacts through RC-006-A2 preparation;
- `RC006_CLAUSE_DESTINATIONS.md` as the A1 forward owner/destination source; and
- the corrected representation findings recorded by `RC006_A2_FINDINGS.md`.

Explicitly excluded from normative assertion extraction/destination interpretation:

- this file, `RC006_A2_EXECUTION_BASELINE.md`, because it is baseline-control metadata;
- generated A2 maps, expanded ledgers, reverse ledgers, validator outputs, and validation summaries;
- repository-facing status-only metadata that contains no independent product obligation; and
- Phase 1A use cases, the pre-normalization `docs/BETA_REQUIREMENTS.md`, and Alpha source material as substitutes for normalized Phase-0 authority.

A file being present in the pinned Git tree does not automatically make every sentence in it a normative A2 assertion. Normative extraction follows `RC006_A2_SECTION_DESTINATION_ASSURANCE.md` and the role classification recorded by A2.

## Expected source invariants

- canonical clause IDs: **11,524**;
- owning requirements: exactly `BETA-REQ-0001..0177` (**177 / 177**);
- canonical-ID collisions: **0**;
- A1 missing/extra/duplicate/owner mismatches: **0 / 0 / 0 / 0**;
- first normative assertion ID: `A2-ASSERT-000001`;
- assertion IDs: opaque, monotonic, non-reused, and non-path-derived.

## Validation rules

1. Resolve every included source file/blob from the pinned Git tree, never from branch HEAD.
2. Verify the resolved tree equals the recorded tree before extraction or validation.
3. Extract normative assertions using `RC006_A2_SECTION_DESTINATION_ASSURANCE.md` §4.1 and allocate stable IDs from `A2-ASSERT-000001`.
4. Fingerprint exact assertion text using the method's defined UTF-8/Unicode-NFC/LF normalization.
5. Reject a run if source commit/tree, canonical counts, owner set, or included blob identities differ.
6. Record tool/script version and output hashes in the immutable validation summary.
7. Reject mass mapping while this record is not `PINNED / VERIFIED`.

## Invalidation and rebaseline

After pinning, any change to an included canonical clause, clause owner, normalized catalogue, normative contract assertion, or synthesis assertion used for destination interpretation invalidates the affected A2 evidence. The change must be handled through controlled correction and either:

- a complete rebaseline with a new never-reused baseline ID; or
- an explicitly bounded amendment proving unaffected assertion and clause evidence remains valid.

Changes confined to excluded generated/control artifacts do not invalidate the source baseline. A repository-facing status edit is exempt only when it contains no independent normative product assertion and its exclusion is explicit/reviewable; otherwise it is treated as an included-source change.

`A2-BASELINE-001` and `A2-BASELINE-002` are never reassigned to different source snapshots.

## Gate effect while preparation is open

- P1A-002 prerequisite assurance: **PASS**;
- A2 methodology readiness: **PASS**;
- A2 source baseline: **NOT YET PINNED**;
- A2 mass mapping: **PROHIBITED until the follow-up pin-only commit marks `A2-BASELINE-002` PINNED / VERIFIED**;
- A2 closure certification: **OPEN**;
- Phase 1A owner review after UC-001: **PAUSED until A2 PASS**.
