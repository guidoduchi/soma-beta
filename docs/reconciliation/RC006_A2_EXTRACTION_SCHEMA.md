# RC-006-A2 — Assertion Extraction and Allocation Schema

Status: **FROZEN V1 — extraction machinery defined; no `A2-ASSERT` identity allocated at schema freeze**  
Schema ID: `A2-EXTRACTION-SCHEMA-V1`  
Baseline: `A2-BASELINE-002`  
Source commit/tree: `61bbd665535e942ef3b05c5ed45661639d3a37a9` / `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`  
Preflight summary: `RC006_A2_MANIFEST_VALIDATION.md` — PASS.

## 1. Purpose

This control artifact freezes the machine and review contracts that govern normative destination-assertion extraction, stable `A2-ASSERT-######` allocation, reverse authority, compact forward mapping, and later generated clause evidence. It is generated/control evidence outside the B002 normative source corpus and does not change accepted product authority.

No `A2-ASSERT-######` identity may be allocated except under this schema or a later explicitly versioned controlled amendment.

## 2. Exact included-source roles

The 74 B002 INCLUDE blobs are further classified by the frozen role manifest:

- artifact: `docs/reconciliation/RC006_A2_SOURCE_ROLES.tsv`;
- creation commit: `52622e2f2546693d361505c243746931038d2319`;
- Git blob SHA: `d6ad8f0f40fe860315ea4b8952545987ee29ca9d`;
- deterministic payload SHA-256: `cb04974e04e1c7428dc20145bd2781dc0d184b559cee419039e20c72e25c4810`;
- classified INCLUDE blobs: **74 / 74**;
- `DESTINATION_ASSERTION_SOURCE`: **16**;
- `CANONICAL_AUTHORITY_SOURCE`: **33**;
- `ASSURANCE_CONTEXT_SOURCE`: **25**.

Only `DESTINATION_ASSERTION_SOURCE` files may receive `A2-ASSERT-######` identities. Canonical-authority and assurance-context files remain required A2 inputs but do not themselves receive destination-assertion identities under V1.

A source-role change requires an explicit schema amendment before further allocation. Existing allocated IDs are never renumbered or reused.

## 3. Fixed initial extraction order

Initial extraction proceeds one complete source file at a time in exactly this order:

1. `docs/PRODUCT_CONTRACT.md`
2. `docs/IMPORT_CONTRACT.md`
3. `docs/RFC_WFM_CONTRACT.md`
4. `docs/WORKBENCH_CONTRACT.md`
5. `docs/PRODUCT_LINE_SLA.md`
6. `docs/INVENTORY_LIFECYCLE.md`
7. `docs/INFRASTRUCTURE_CONTRACT.md`
8. `docs/COMMUNICATIONS_CONTRACT.md`
9. `docs/UI_UX_CONTRACT.md`
10. `docs/FOUNDATION_RUNTIME_CONTRACT.md`
11. `docs/ARCHITECTURE.md`
12. `docs/GLOSSARY.md`
13. `docs/DECISIONS.md`
14. `docs/BRANDING.md`
15. `docs/ROADMAP.md`
16. `docs/FOUNDATION_GAPS.md`

For the initial pass, one allocation batch equals one complete source file. A file's candidate set must be human-reviewed for completeness before IDs are allocated for that file. Partial-file initial allocation is prohibited.

If a genuinely missed assertion is discovered after its file's initial batch is committed, the assertion receives the next never-used ID through a later `AMENDMENT` batch; prior IDs are not renumbered to restore textual order.

## 4. Normative assertion boundary

An assertion is one independently reviewable accepted-product obligation, prohibition, permission, or explicit design boundary represented in an eligible destination source.

Rules:

1. Compound source text containing independent rules is split into separate assertion candidates.
2. A candidate's `exact_text` is the minimal verbatim source span needed to express that assertion. It is not paraphrased.
3. Markdown characters occurring inside the selected verbatim span remain part of `exact_text`; leading/trailing source whitespace outside the selected span is excluded.
4. `fingerprint_sha256` is SHA-256 of `exact_text` after Unicode NFC and LF line-ending normalization, encoded UTF-8. Internal whitespace, punctuation, and Markdown are preserved.
5. Informative text receives no assertion identity.
6. Identical wording at different normative locations receives different IDs.
7. Allocation establishes identity only. It does **not** itself prove canonical authority or semantic PASS.
8. Every allocated assertion remains `PENDING_AUTHORITY` until reverse authority and contradiction review pass.

## 5. Candidate JSONL schema

Pre-allocation candidate batches use UTF-8 JSON Lines, one canonical JSON object per LF-terminated line. Each candidate has exactly these required fields:

- `schema`: literal `RC006-A2-ASSERTION-CANDIDATE-V1`;
- `source_path`: exact B002 repository path;
- `source_blob_sha`: exact B002 Git blob SHA from the source-role manifest;
- `section_heading`: exact visible Markdown heading text owning the assertion;
- `section_anchor`: explicit normalized section anchor used by A2 mapping;
- `section_ordinal`: 1-based occurrence of that heading/section in the source document;
- `assertion_ordinal`: 1-based normative-assertion order within that section;
- `source_start_line`: 1-based source line containing the start of the verbatim span;
- `source_end_line`: 1-based source line containing the end of the verbatim span;
- `exact_text`: minimal verbatim normative source span;
- `fingerprint_sha256`: V1 fingerprint defined in §4;
- `normative_kind`: one of `OBLIGATION`, `PROHIBITION`, `PERMISSION`, `DESIGN_BOUNDARY`;
- `classification_review`: literal `PASS` before allocation;
- `review_note`: concise human review note; may be empty only when the assertion is self-explanatory.

Canonical JSON means UTF-8, `sort_keys=true`, separators `,` and `:`, `ensure_ascii=false`, and one final LF per object. Candidate files contain no assertion IDs.

Within an initial file batch candidates are ordered by `(section_ordinal, assertion_ordinal)` ascending. Duplicate locator pairs are prohibited. Source line numbers are locators/evidence only and never form stable identity.

## 6. Stable assertion ledger JSONL schema

The maintained reverse ledger is `docs/reconciliation/RC006_A2_ASSERTION_AUTHORITY.jsonl`. Each allocated record has exactly these required fields:

- `schema`: literal `RC006-A2-ASSERTION-RECORD-V1`;
- `assertion_id`: `A2-ASSERT-######`;
- `allocation_batch_id`;
- all source/location/text/fingerprint/kind fields from the candidate;
- `canonical_clause_ids`: ordered unique canonical clause IDs; may be empty only while `semantic_review` is `PENDING_AUTHORITY`;
- `requirement_owners`: ordered unique `BETA-REQ-####` owners derived from `canonical_clause_ids`; may be empty only while pending;
- `destination_edges`: array of `{map_row_id, role}` objects, where role is `PRIMARY_NORMATIVE` or `SUPPORTING_NORMATIVE`; may be empty while forward mapping is pending;
- `semantic_review`: `PENDING_AUTHORITY`, `PASS`, or `FAIL`;
- `contradiction_status`: `NONE`, `OPEN_FINDING`, or `RESOLVED_FINDING`;
- `supersedes`: ordered assertion-ID array;
- `superseded_by`: ordered assertion-ID array;
- `status`: `ACTIVE` or `SUPERSEDED`;
- `review_note`.

The ledger is ordered by numeric `assertion_id`. Existing committed records may gain authority/review/supersession evidence, but an existing assertion ID may never be reassigned to different semantic source text. A semantic split/replacement allocates new IDs and supersedes the old ID.

## 7. Allocation-state schema

`docs/reconciliation/RC006_A2_ASSERTION_ALLOCATION_STATE.json` is the machine allocation state. V1 fields are:

- `schema`: `RC006-A2-ASSERTION-ALLOCATION-STATE-V1`;
- `baseline_id`: `A2-BASELINE-002`;
- `extraction_schema`: `A2-EXTRACTION-SCHEMA-V1`;
- `source_roles_blob_sha`;
- `source_roles_payload_sha256`;
- `next_assertion_number`;
- `allocated_count`;
- `highest_allocated_assertion_id` (`null` before first allocation);
- `completed_initial_sources`: ordered source-path array;
- `batches`: ordered batch records.

A batch record contains `batch_id`, `mode` (`INITIAL` or `AMENDMENT`), `source_path`, `first_assertion_id`, `last_assertion_id`, `assertion_count`, `candidate_payload_sha256`, `result_payload_sha256`, and `reason` (`null` for an initial batch).

Initial frozen state is allocation count **0**, next assertion number **1**, no completed sources, and no batches.

## 8. Deterministic allocation rules

1. Preflight summary must be PASS before allocation.
2. Source-role manifest digest/blob/counts must verify before every allocation.
3. Only a `DESTINATION_ASSERTION_SOURCE` may be allocated.
4. `INITIAL` mode must use the next exact source from §3 and must represent the complete human-reviewed candidate set for that file.
5. Candidate order is preserved exactly after validation of `(section_ordinal, assertion_ordinal)` ascending.
6. `A2-ASSERT-{next_assertion_number:06d}` is assigned sequentially to the validated candidate sequence.
7. The next number advances by candidate count; allocated count advances by the same amount.
8. No gap is intentionally created; once an ID is committed, deletion/supersession never returns the number to the pool.
9. `AMENDMENT` mode is prohibited until all 16 initial source batches are complete. An amendment records a non-empty reason and allocates only new IDs.
10. Allocation writes deterministic canonical JSONL records and a deterministic batch result. A failed validation writes no new allocation state or ledger records.
11. The first valid allocated identity under V1 is exactly `A2-ASSERT-000001`.

## 9. Compact forward-map contract

The human-maintained compact map remains `RC006_A2_SECTION_DESTINATIONS.md` as required by the governing A2 method. Each mapping row must carry:

- stable `A2-MAP-######` row ID;
- inclusive canonical clause start/end IDs;
- exact `BETA-REQ-####` owner;
- one primary destination `path#section-anchor`;
- zero or more supporting destinations with role `SUPPORTING_NORMATIVE` or `INFORMATIVE_REFERENCE`;
- referenced `A2-ASSERT-######` IDs for normative destination edges;
- representation note;
- semantic-review result.

`A2-MAP` IDs are assurance identities only. Once a committed map row has been used to generate downstream evidence, its ID is not reused for a different semantic range.

## 10. Generated expanded-clause ledger contract

The generated 11,524-record ledger is machine-readable JSONL. Each record contains:

- canonical `clause_id`;
- `owner`;
- `map_row_id`;
- exact primary destination path/section;
- supporting destination edges;
- normative `assertion_ids` supporting those edges;
- `semantic_review`.

The expanded ledger is generated from the compact reviewed map plus canonical authority; it is never hand-maintained.

## 11. A2-1 gate

A2-1 is PASS only when:

- the 74/74 source-role manifest is frozen and self-hash-verifiable;
- the schema in this file is committed;
- the initial zero-allocation state is committed;
- a deterministic allocator implementing §8 is committed and repository-checked without allocating an assertion;
- source-role counts are 16 / 33 / 25 with no duplicate/missing included path;
- allocated assertion count remains **0** during A2-1 verification.

Only after A2-1 PASS may the complete `docs/PRODUCT_CONTRACT.md` candidate batch be prepared for the first allocation.
