# RC-006-A2 — Execution Baseline Pin

Baseline ID: **`A2-BASELINE-001`**  
Status: **PINNED / VERIFIED — A2 methodology ready for execution; certification remains OPEN**  
Repository: `guidoduchi/soma-beta`  
Provenance branch: `foundation/product-contract-v0.1`  
Source commit: `8282d321d0ab318ef141695b2500c8247ccd26b4`  
Source Git tree: `3ee7140a3005d8538e6e350efac1de070c9c60be`  
Control record: created in the follow-up pin commit; intentionally not part of the source tree it identifies.

## Purpose

This record freezes the exact repository input corpus against which RC-006-A2 assertion extraction, forward clause placement, reverse normative authority, fingerprints, and validation results must be computed. Branch names are informational only; validation must read the immutable tree above.

## Why the pin is in a follow-up commit

A Git tree cannot contain a file that already knows the hash of that same tree. The preparatory commit therefore completed every input correction first. This control record then pins that completed tree without altering it. A2 output/control artifacts may be committed later while continuing to validate the immutable source tree.

## Included source corpus

The entire repository tree is frozen for reproducibility. The A2 normative-input subset is:

- accepted normalized catalogues, canonical clauses, clause-authority records, and checkpoint traceability under `docs/normalization/`;
- the accepted Product, Import, RFC/WFM, Workbench, Product Line/SLA, Inventory, Infrastructure, Communications, UI/UX, and Foundation Runtime contracts;
- accepted synthesis/authority documents needed to interpret destinations: Architecture, Glossary, Decisions, Branding, Roadmap, Foundation Gaps, Requirement Normalization, and reconciliation artifacts through RC-006-A2 preparation;
- `RC006_CLAUSE_DESTINATIONS.md` as the A1 forward owner/destination source; and
- the corrected Product Contract representation recorded by `RC006_A2_FINDINGS.md`.

The pre-normalization `docs/BETA_REQUIREMENTS.md`, Alpha source material, and Phase 1A use cases are preserved in the tree for provenance but are not substitutes for normalized Phase-0 authority and are not normative A2 destination sources.

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
4. Fingerprint exact assertion text using the method’s defined UTF-8/Unicode-NFC/LF normalization.
5. Reject a run if source commit/tree, canonical counts, owner set, or included blob identities differ.
6. Record tool/script version and output hashes in the immutable validation summary.

## Invalidation and rebaseline

Any change after this pin to a canonical clause, clause owner, normalized catalogue, normative contract, synthesis document used for destination interpretation, or other included normative source invalidates the affected A2 evidence. The change must be handled through controlled correction and either:

- a complete rebaseline with a new never-reused baseline ID; or
- an explicitly bounded amendment proving unaffected assertion and clause evidence remains valid.

Changes only to generated A2 maps, ledgers, validators, findings, or control metadata do not change this source baseline unless they also modify an included normative source. `A2-BASELINE-001` is never reassigned to another commit or tree.

## Gate effect

- P1A-002 prerequisite assurance: **PASS**;
- A2 methodology readiness: **PASS**;
- A2 mass-mapping authorization against this pinned tree: **AUTHORIZED**;
- A2 closure certification: **OPEN**;
- Phase 1A owner review after UC-001: **PAUSED until A2 PASS**.
