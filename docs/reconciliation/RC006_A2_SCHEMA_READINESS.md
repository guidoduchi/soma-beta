# RC-006-A2 — Extraction Schema Readiness Summary

Status: **PASS — A2-1 extraction/allocation machinery is frozen and repository-checked with zero allocated assertions**  
Baseline: `A2-BASELINE-002`  
Schema: `A2-EXTRACTION-SCHEMA-V1`

## Purpose

This immutable control summary records the repository-native A2-1 readiness check performed before the first stable normative assertion identity was allocated. It is generated/control evidence outside the B002 normative source corpus and does not change accepted product authority.

At the execution point summarized here:

- allocated `A2-ASSERT-######` identities: **0**;
- reverse-ledger records: **0**;
- next permitted identity: **`A2-ASSERT-000001`**;
- next required initial source: **`docs/PRODUCT_CONTRACT.md`**.

## Frozen source-role contract

- role manifest: `docs/reconciliation/RC006_A2_SOURCE_ROLES.tsv`;
- role-manifest creation commit: `52622e2f2546693d361505c243746931038d2319`;
- role-manifest Git blob SHA: `d6ad8f0f40fe860315ea4b8952545987ee29ca9d`;
- role-manifest whole-file SHA-256: `307e40d1910273bbd00333f52245798f0b7a530aea8bec7f1ea0a43f7d9c3982`;
- role-manifest deterministic payload SHA-256: `cb04974e04e1c7428dc20145bd2781dc0d184b559cee419039e20c72e25c4810`;
- classified B002 INCLUDE blobs: **74 / 74**;
- `DESTINATION_ASSERTION_SOURCE`: **16**;
- `CANONICAL_AUTHORITY_SOURCE`: **33**;
- `ASSURANCE_CONTEXT_SOURCE`: **25**.

Only the 16 destination-assertion sources are eligible for `A2-ASSERT` allocation under V1.

## Frozen schema and state

Extraction schema:

- artifact: `docs/reconciliation/RC006_A2_EXTRACTION_SCHEMA.md`;
- schema ID: `A2-EXTRACTION-SCHEMA-V1`;
- Git blob SHA: `17338d8caa37d85d01b6178dd585136d9ad9e67a`.

Initial allocation state:

- artifact: `docs/reconciliation/RC006_A2_ASSERTION_ALLOCATION_STATE.json`;
- Git blob SHA: `6917e2cd44b6fceb34a212e9643c65976bd0595b`;
- deterministic state SHA-256: `5dfac65c13c3bcd68d466422b0a732295954db0181659454cba37af6051d70f7`;
- `allocated_count`: **0**;
- `next_assertion_number`: **1**;
- `highest_allocated_assertion_id`: `null`;
- completed initial sources: **0**;
- allocation batches: **0**.

The absent reverse ledger is treated as the empty ledger at readiness time, whose SHA-256 is `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

## Deterministic allocator

- tool: `tools/reconciliation/allocate_rc006_a2_assertions.py`;
- version: **`1.0.0`**;
- Git blob SHA: `216bf8b5dc77f05b257ad70dc4133aa37370828b`;
- source SHA-256: `f69f4d08a0f30c86aa07606b298f26a98b3ce0c11d3b16a6441e3bdf389a5e52`.

The allocator verifies the frozen role-manifest identities/counts, canonical state serialization, ledger sequence/fingerprints, destination eligibility, fixed initial source order, candidate canonical JSONL, candidate fingerprint validity, locator uniqueness/order, and fail-closed batch/state rules. `check-state --expect-zero` performs no allocation and fails if any assertion has already been allocated.

## Repository-native execution evidence

Workflow commit: `6df24f845b26695a75c99db601dd11801a3ccc0b`  
Workflow: `.github/workflows/rc006-a2-schema-readiness.yml`  
GitHub Actions run: **`33914585321`**  
Job: **`101158682579` (`readiness`)**  
Runner: Ubuntu 24.04  
Python: **3.13.15**  
Git: **2.55.0**  
Job conclusion: **success**

Executed command:

```text
python tools/reconciliation/allocate_rc006_a2_assertions.py --repo . check-state --expect-zero --output rc006_a2_schema_readiness.json
```

The deterministic readiness JSON has SHA-256:

`d49ba0ab590637b0f0ea4e1fb04a1b83d0093e272102cc0de4b3bb4f982adf88`

The uploaded artifact is:

- name: `rc006-a2-schema-readiness`;
- artifact ID: **`9952642126`**;
- archive SHA-256: `ab9a04129dfcfab9dae77697b1de393b455c3f756ff0a5f96f2693eea970661d`.

## Readiness result vector

- baseline ID: `A2-BASELINE-002` — **PASS**;
- extraction schema: `A2-EXTRACTION-SCHEMA-V1` — **PASS**;
- source-role Git blob: exact — **PASS**;
- source-role payload hash: exact — **PASS**;
- source-role counts: **16 / 33 / 25** — **PASS**;
- allocation state canonical and internally consistent — **PASS**;
- allocated assertions: **0** — **PASS**;
- reverse-ledger records: **0** — **PASS**;
- next assertion: `A2-ASSERT-000001` — **PASS**;
- next initial source: `docs/PRODUCT_CONTRACT.md` — **PASS**;
- repository-native check result: **PASS**.

## Gate effect

**RC-006-A2 A2-1 EXTRACTION-SCHEMA READINESS: PASS.**

The first allocation is now authorized only after the complete human-reviewed normative candidate set for `docs/PRODUCT_CONTRACT.md` is prepared under `RC006_A2_EXTRACTION_SCHEMA.md`.

This summary does not itself allocate `A2-ASSERT-000001` and does not claim reverse-authority or A2 certification PASS.
