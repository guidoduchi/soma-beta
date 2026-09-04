# RC-006-A2 — Execution Baseline Pin

Baseline ID: **`A2-BASELINE-002`**  
Status: **PINNED / VERIFIED — exact corpus manifest frozen; A2 assertion extraction/mass mapping authorized against this exact source snapshot; certification remains OPEN**  
Repository: `guidoduchi/soma-beta`  
Provenance branch: `foundation/product-contract-v0.1`  
Source commit: `61bbd665535e942ef3b05c5ed45661639d3a37a9`  
Source Git tree: `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`  
Supersedes for A2 execution: `A2-BASELINE-001` (historical preparation snapshot; not used for mass mapping after this rebaseline).

## Purpose

This record controls the exact immutable repository input corpus against which RC-006-A2 assertion extraction, forward clause placement, reverse normative authority, fingerprints, and validation results are computed. Branch names are provenance only; validation reads the immutable source commit/tree recorded above.

## Option-B pin model

A Git tree cannot contain a file that already knows the hash of that same tree. SOMA therefore uses a strict two-step baseline protocol:

1. finalize every included normative/synthesis input and every repository-facing status correction;
2. take that completed preparatory commit/tree as the source snapshot; then
3. create one follow-up control commit that modifies **only this baseline-control file** to insert the exact source commit/tree and mark the baseline PINNED / VERIFIED.

`RC006_A2_EXECUTION_BASELINE.md` is baseline-control metadata and is explicitly excluded from the normative A2 input corpus. Therefore pin/control commits that modify only excluded control evidence do not alter or invalidate the source snapshot they identify.

## Exact corpus-manifest freeze

The categories in this file explain the intended corpus, but **membership is governed only by the frozen exact manifest**:

- manifest artifact: `docs/reconciliation/RC006_A2_INPUT_MANIFEST.tsv`;
- manifest creation commit: `221bfdbbbb660387c407c44ac6e119a749c0dfbd`;
- manifest blob SHA: `05daa81310b8259ca8ff968bd1715244ecf0d5d5`;
- manifest payload SHA-256: `3bbe5c2f6c82b4ddaf4ecbc2825ace3b0edc3072e67fe09f6e68447e89fd1013`;
- source commit represented: `61bbd665535e942ef3b05c5ed45661639d3a37a9`;
- source tree represented: `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`;
- source-tree blob records: **92**;
- included records: **74**;
- excluded records: **18**;
- missing source-tree blobs from manifest: **0**;
- duplicate manifest paths: **0**.

`RC006_A2_INPUT_MANIFEST.tsv` is immutable A2 control evidence produced after the B002 source snapshot and is itself excluded from normative assertion extraction/destination interpretation. Its creation therefore does not invalidate `A2-BASELINE-002`.

### Deterministic manifest hash contract

The manifest is UTF-8 with LF line endings and a final LF. Its first line is the declared digest:

`manifest_sha256<TAB><64 lowercase hexadecimal characters><LF>`

The SHA-256 input is **every byte after that first LF through the final LF**, beginning exactly with `A2-CORPUS-MANIFEST-V1`. The payload contains source commit/tree and record counts followed by one record per source-tree blob. File records are sorted in ascending bytewise UTF-8 path order and contain exactly four tab-separated fields:

`INCLUDE|EXCLUDE<TAB>path<TAB>blob_sha<TAB>classification_or_exclusion_reason<LF>`

Paths, SHAs, classifications, and reasons may not contain TAB, CR, or LF. A validator shall reject the manifest if the recomputed payload digest differs, if the blob SHA differs from `05daa81310b8259ca8ff968bd1715244ecf0d5d5`, or if its membership/counts do not exactly match the pinned source tree.

### Assertion-allocation gate

No `A2-ASSERT-######` identity may be allocated, and no reverse-corpus-completeness claim may be made, unless all of the following first pass:

1. source commit/tree equals the B002 pin;
2. the exact manifest blob equals `05daa81310b8259ca8ff968bd1715244ecf0d5d5`;
3. the manifest payload SHA-256 equals `3bbe5c2f6c82b4ddaf4ecbc2825ace3b0edc3072e67fe09f6e68447e89fd1013`;
4. all 92 pinned source-tree blobs appear exactly once in the manifest;
5. every INCLUDE path resolves to the recorded pinned-tree blob SHA;
6. every EXCLUDE path resolves to the recorded pinned-tree blob SHA and carries a non-empty exclusion reason; and
7. included/excluded counts remain exactly **74 / 18**.

The frozen manifest satisfies these prerequisite membership controls. Assertion extraction must use its INCLUDE set; a validator may not infer a different subset from category prose.

## Included source corpus

The entire pinned Git tree is retained for reproducibility. The following categories explain the 74 exact INCLUDE entries frozen in `RC006_A2_INPUT_MANIFEST.tsv`; they do **not** independently add or remove files:

- accepted normalized catalogues, canonical clauses, clause-authority records, and checkpoint traceability under `docs/normalization/`;
- the accepted Product, Import, RFC/WFM, Workbench, Product Line/SLA, Inventory, Infrastructure, Communications, UI/UX, and Foundation Runtime contracts;
- accepted synthesis/authority documents needed to interpret destinations: Architecture, Glossary, Decisions, Branding, Roadmap, Foundation Gaps, Requirement Normalization, and reconciliation artifacts through RC-006-A2 preparation;
- `RC006_CLAUSE_DESTINATIONS.md` as the A1 forward owner/destination source; and
- the corrected representation findings recorded by `RC006_A2_FINDINGS.md`.

The following categories explain exclusions; the exact 18 paths and reasons are frozen in the manifest:

- this file, `RC006_A2_EXECUTION_BASELINE.md`, because it is baseline-control metadata;
- generated A2 maps, expanded ledgers, reverse ledgers, validators, validation summaries, and corpus-manifest/control evidence produced after the pinned source tree;
- repository-facing status-only material that contains no independent product obligation where the manifest explicitly excludes it; and
- Phase 1A use cases, the pre-normalization `docs/BETA_REQUIREMENTS.md`, Alpha source material, and historical traceability as substitutes for normalized Phase-0 authority.

A file being included does not automatically make every sentence in it a normative A2 assertion. Normative extraction follows `RC006_A2_SECTION_DESTINATION_ASSURANCE.md`, while the exact manifest governs which source blobs are eligible to be inspected.

## Expected source invariants

- canonical clause IDs: **11,524**;
- owning requirements: exactly `BETA-REQ-0001..0177` (**177 / 177**);
- canonical-ID collisions: **0**;
- A1 missing/extra/duplicate/owner mismatches: **0 / 0 / 0 / 0**;
- exact source-tree corpus manifest: **92 / 92 blobs classified; 74 INCLUDE; 18 EXCLUDE**;
- first normative assertion ID: `A2-ASSERT-000001`;
- assertion IDs: opaque, monotonic, non-reused, and non-path-derived.

## Validation rules

1. Resolve source files/blobs from source Git tree `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`, never from branch HEAD.
2. Verify the resolved source commit/tree equals `61bbd665535e942ef3b05c5ed45661639d3a37a9` / `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8` before extraction or validation.
3. Verify the frozen exact manifest under the deterministic hash contract above before allocating any assertion ID.
4. Inspect **only manifest INCLUDE records** for normative A2 extraction; EXCLUDE records cannot silently enter the reverse corpus.
5. Extract normative assertions using `RC006_A2_SECTION_DESTINATION_ASSURANCE.md` §4.1 and allocate stable IDs from `A2-ASSERT-000001`.
6. Fingerprint exact assertion text using the method's defined UTF-8/Unicode-NFC/LF normalization.
7. Reject a run if source commit/tree, manifest blob/hash, canonical counts, owner set, membership classification, or any included blob identity differs.
8. Record tool/script version and output hashes in the immutable validation summary.
9. Reject any run that substitutes branch HEAD or prose-based corpus selection for the pinned source tree and exact manifest.

## Invalidation and rebaseline

Any later change to an included canonical clause, clause owner, normalized catalogue, normative contract assertion, or synthesis assertion used for destination interpretation invalidates the affected A2 evidence. The change must be handled through controlled correction and either:

- a complete rebaseline with a new never-reused baseline ID and a new exact corpus manifest; or
- an explicitly bounded amendment proving unaffected assertion and clause evidence remains valid.

Changes confined to excluded generated/control artifacts do not invalidate the source baseline. A repository-facing status edit is exempt only when its source-snapshot path is explicitly EXCLUDE in the frozen manifest and it contains no independent normative product assertion; otherwise it is treated as an included-source change.

`A2-BASELINE-001` and `A2-BASELINE-002` are never reassigned to different source snapshots. The frozen manifest digest for B002 is likewise never reassigned.

## Gate effect

- P1A-002 prerequisite assurance: **PASS**;
- A2 methodology readiness: **PASS**;
- A2 source baseline: **PINNED / VERIFIED — `A2-BASELINE-002`**;
- exact A2 input/exclusion manifest: **PINNED / VERIFIED — 92/92 blobs, 74 INCLUDE, 18 EXCLUDE**;
- A2 assertion allocation: **AUTHORIZED only after validating the B002 source pin and frozen manifest; prerequisite currently satisfied**;
- A2 mass mapping: **AUTHORIZED only against the frozen 74-file INCLUDE corpus at source commit/tree `61bbd665535e942ef3b05c5ed45661639d3a37a9` / `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`**;
- A2 closure certification: **OPEN**;
- Phase 1A owner review after UC-001: **PAUSED until A2 PASS**.
