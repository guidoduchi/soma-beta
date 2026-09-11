# RC-006-A2 — Product Contract Candidate Corpus Validation Summary

Status: **PASS — complete Product Contract pre-allocation candidate corpus frozen and repository-validated; stable assertion allocation remains zero at this summary boundary**  
Baseline: `A2-BASELINE-002`  
Extraction schema: `A2-EXTRACTION-SCHEMA-V1` plus `RC006_A2_SCHEMA_AMENDMENT_001.md`  
Source: `docs/PRODUCT_CONTRACT.md`

## Purpose

This immutable control summary records the first A2 destination-source candidate-extraction batch before any `A2-ASSERT-######` identity is allocated. It proves that the complete reviewed Product Contract candidate byte stream is reproducible from the pinned B002 source, passes the hardened exact-source validator, and is frozen in the repository as generated/control evidence.

This artifact, the frozen candidate JSONL, candidate-preparation tools, validators, and workflows are post-B002 control/generated evidence. They do not alter accepted product authority and are not additional B002 normative destination sources.

## Pinned source identity

- baseline: `A2-BASELINE-002`;
- source commit: `61bbd665535e942ef3b05c5ed45661639d3a37a9`;
- source tree: `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`;
- source path: `docs/PRODUCT_CONTRACT.md`;
- source Git blob: `6ba3ecb8eabd0845927aa4e6436ec09130a90263`;
- source role: `DESTINATION_ASSERTION_SOURCE` under `RC006_A2_SOURCE_ROLES.tsv`;
- source-role manifest Git blob: `d6ad8f0f40fe860315ea4b8952545987ee29ca9d`;
- source-role payload SHA-256: `cb04974e04e1c7428dc20145bd2781dc0d184b559cee419039e20c72e25c4810`.

## Extraction and review machinery

### Schema hardening

Before candidate freeze and before the first stable assertion identity, `RC006_A2_SCHEMA_AMENDMENT_001.md` clarified document-wide `section_ordinal`, deterministic heading anchors, and exact pinned-source verification. The amendment changes no accepted product behavior and was issued while allocation remained zero.

### Final candidate generator

- path: `tools/reconciliation/prepare_rc006_a2_product_candidates_v1_3.py`;
- version: **1.3.1**;
- final-review generator commit: `5cf7940bad6c1a752e47975134dc910f79e7ea2c`;
- Git blob at freeze: `0d4da1863fd0b40afafe67ffb13f6bc09579cc10`;
- pinned base generator v1.2 Git blob: `93a246b3babf5b9fa28a13c6c0190cd6bd09bca1`;
- review model: sentence granularity plus explicit human atomicity overrides.

The generator does not allocate stable assertion identities. Its output remains freely correctable until the candidate corpus is frozen and later consumed by the allocator.

### Hardened candidate validator / allocator wrapper

- path: `tools/reconciliation/allocate_rc006_a2_assertions_v1_1.py`;
- version: **1.1.0**;
- Git blob: `88345216426ed4e3bbd9ac52c4aaf1e507ce2dac`;
- SHA-256: `7e39a4a6c692373d1fd037b43fd47142d18ae776d9a34a652dea8584bff90f72`;
- pinned base allocator v1.0 Git blob: `216bf8b5dc77f05b257ad70dc4133aa37370828b`.

The validator proves each candidate against the exact B002 Product Contract blob, including claimed line range, verbatim occurrence, owning heading, document-wide section ordinal, normalized anchor, candidate ordering, fingerprint, source blob, and candidate schema.

## Human-review convergence

Candidate extraction was deliberately reviewed before identity allocation rather than accepting the first mechanically valid split:

1. the first draft was mechanically valid but too coarse;
2. an aggressive generic punctuation split was rejected because shared modality/subject could be changed semantically;
3. extraction moved to sentence-level default plus explicit reviewed sub-sentence overrides;
4. a fail-fast expected-count check exposed an override-table omission that had dropped untouched source sentences;
5. the omission was repaired by preserving every original sentence and splitting only the specifically reviewed compound clause; and
6. the final v1.3.1 corpus passed the semantic-review invariants and hardened exact-source validator.

No stable assertion identity existed during any of these revisions, so no identifier was renumbered, reused, or semantically reassigned.

## Final candidate corpus

Frozen artifact:

`docs/reconciliation/candidates/RC006_A2_PRODUCT_CONTRACT_CANDIDATES.jsonl`

Frozen identities and invariants:

- candidate records: **431**;
- Product Contract eligible sections represented: **27 / 27**;
- candidate payload SHA-256: **`97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7`**;
- frozen candidate Git blob: **`3fdbad0c4b9484735020a1dec2698c0e7e14ef95`**;
- candidate schema: `RC006-A2-ASSERTION-CANDIDATE-V1`;
- every candidate `classification_review`: `PASS`;
- candidate source blob mismatch: **0**;
- candidate source-path mismatch: **0**;
- candidate exact-text/claimed-range mismatch: **0**;
- section-heading/ordinal/anchor mismatch: **0**;
- fingerprint mismatch: **0**;
- noncontiguous per-section assertion ordinals: **0**.

The only semicolon-bearing candidate retained intentionally is source line **52**, because its semicolon-separated actions share one governing modal/subject (`The operator can ...`) and therefore form one permission assertion. Splitting that sentence would change normative force.

## Repository-native candidate validation

Final candidate-review workflow execution:

- run: **`33916839311`**;
- job: **`101165839020`**;
- workflow head commit: `5cf7940bad6c1a752e47975134dc910f79e7ea2c`;
- Python: `3.13.15`;
- Git: `2.55.0`;
- preparation result: **PASS**;
- hardened exact-source validation result: **PASS**;
- explicit final-review invariant result: **PASS**;
- candidate count: **431**;
- represented sections: **27**;
- intentional semicolon source rows: exactly **line 52**.

Preserved CI artifact:

- artifact name: `rc006-a2-product-contract-candidates-final`;
- artifact ID: **`9953459940`**;
- archive SHA-256: **`63757c7727a0f43b647a0d907d5648f575afcf81e3a4299b8812a0b3f5eb57f2`**;
- artifact size: **45,560 bytes**.

The hardened validator output independently recorded:

- result: `PASS`;
- candidate count: **431**;
- candidate payload SHA-256: `97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7`;
- section count with candidates: **27**;
- source blob: `6ba3ecb8eabd0845927aa4e6436ec09130a90263`;
- validator version/blob/SHA-256: `1.1.0` / `88345216426ed4e3bbd9ac52c4aaf1e507ce2dac` / `7e39a4a6c692373d1fd037b43fd47142d18ae776d9a34a652dea8584bff90f72`.

## Immutable freeze execution

Freeze workflow definition commit:

**`e01677bd6f17b038ac5e96c57832598d7c419bb1`** — `Freeze validated Product Contract A2 candidates`

The workflow regenerated v1.3.1 output from the pinned source, reran hardened validation, enforced the exact payload hash/count/section/semicolon invariants, and only then staged the generated candidate JSONL.

Freeze execution:

- workflow run: **`33916935911`**;
- job: **`101166146688`**;
- result: **PASS**;
- generated candidate freeze commit: **`887fef8a6ee53b943727671f7be7a27912118950`**;
- freeze commit parent: `e01677bd6f17b038ac5e96c57832598d7c419bb1`;
- freeze commit tree: `d49ae82ef8b01f467aa5dc73e8255ec3ea243420`.

Mechanical compare from the workflow-definition parent to the freeze commit is exactly **one commit / one changed file**:

`docs/reconciliation/candidates/RC006_A2_PRODUCT_CONTRACT_CANDIDATES.jsonl`

No included B002 source file changed.

## Stable-ID allocation boundary

At the candidate-freeze boundary, `RC006_A2_ASSERTION_ALLOCATION_STATE.json` remains:

- allocated count: **0**;
- highest allocated assertion ID: `null`;
- next assertion number: **1**;
- next permitted identity: **`A2-ASSERT-000001`**;
- batches: **0**;
- completed initial sources: **0**.

`docs/reconciliation/RC006_A2_ASSERTION_AUTHORITY.jsonl` has not yet been created by an allocation batch.

Therefore this summary does **not** claim reverse authority or A2 certification. It certifies only that the complete Product Contract candidate corpus is frozen and ready to be consumed atomically by the deterministic initial allocator.

## Gate result

- B002 Product Contract source identity: **PASS**;
- Product Contract source-role eligibility: **PASS**;
- schema/amendment readiness: **PASS**;
- human atomicity/classification review: **PASS**;
- exact pinned-source candidate validation: **PASS**;
- candidate records: **431**;
- eligible Product Contract sections covered: **27 / 27**;
- frozen payload/blob identity: **PASS**;
- freeze commit isolation: **PASS — one generated candidate file only**;
- accepted product authority changed: **0**;
- stable assertion IDs allocated: **0**.

**RC-006-A2 PRODUCT CONTRACT CANDIDATE FREEZE: PASS.**

The next authorized operation is the first deterministic `INITIAL` allocation batch against this exact frozen candidate payload. It shall allocate `A2-ASSERT-000001` onward without changing the candidate corpus or B002 source.
