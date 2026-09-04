# RC-006-A2 allocator identity hardening

Status: **PASS — Product Contract allocation path hardened; first allocation remains unexecuted**

This record closes the allocator loophole discovered after the Product Contract candidate corpus had already been validly frozen. It changes no B002 source, no Product Contract candidate record, no A2 extraction schema, and no product semantics.

## 1. Trigger

The frozen repository corpus is valid, but the prior hardened allocator (`allocate_rc006_a2_assertions_v1_1.py`) accepted an arbitrary `--candidates` path. Its validation path checked pinned-source consistency but did not require the Product Contract frozen candidate identities:

- canonical repository path: `docs/reconciliation/candidates/RC006_A2_PRODUCT_CONTRACT_CANDIDATES.jsonl`
- Git blob: `3fdbad0c4b9484735020a1dec2698c0e7e14ef95`
- payload SHA-256: `97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7`
- candidate count: `431`
- section count/set: `27`, ordinals `1..27`

The prior wrapper also validated one read and then delegated allocation to allocator v1.0, which reopened the candidate path. That created a validate-then-reread substitution gap.

A stale externally supplied ZIP was confirmed to contain a prior 426-record generation. It is **rejected noncanonical evidence and must not be used for allocation**. The canonical candidate evidence remains the frozen repository blob above and successful GitHub artifact `9953459940` from candidate-review run `33916839311`.

No B002 rebaseline and no candidate refreeze are required.

## 2. Hardened allocator

New tool:

`tools/reconciliation/allocate_rc006_a2_assertions_v1_2.py`

Identity:

- version: `1.2.0`
- Git blob: `d479b0e8158b96487d696792f3077e56cf7cce0d`
- SHA-256: `6c59ba98d47af0ff2f9d233c3fd425b0c8b60d1e42938c514574c8423458ab56`
- introducing commit: `20c50bfcb7dfe5e0a61b49ea2fb2fee7474ec336`

The tool preserves the existing allocation-state and assertion-ledger schemas.

### 2.1 Fail-closed frozen identity binding

For INITIAL allocation of `docs/PRODUCT_CONTRACT.md`, v1.2.0 requires all of the following:

1. the canonical repository candidate path;
2. the candidate file committed at `HEAD` with Git blob `3fdbad0c4b9484735020a1dec2698c0e7e14ef95`;
3. the same working-tree bytes to compute to that Git blob;
4. raw payload SHA-256 `97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7`;
5. exactly `431` canonical JSONL candidate records;
6. exactly the complete contiguous Product Contract section set `1..27`;
7. all prior candidate schema/fingerprint/classification checks;
8. all v1.1 pinned B002 exact-span/heading/ordinal checks;
9. INITIAL source order to identify `docs/PRODUCT_CONTRACT.md` as the next source;
10. exact batch ID `A2-BATCH-0001-PRODUCT-CONTRACT`.

An INITIAL source without an explicitly registered frozen corpus identity fails closed. AMENDMENT allocation is also fail-closed in v1.2.0 until an explicit frozen amendment identity rule is registered.

### 2.2 Single-read allocation semantics

For `validate-frozen`, `preallocate`, and `allocate`, the canonical Product Contract candidate file is read once. The same in-memory byte stream is used to:

- compute Git-blob identity;
- compute raw SHA-256 identity;
- parse and canonicalize JSONL;
- validate candidate metadata/fingerprints;
- validate exact pinned-source spans and section ownership;
- derive the candidate count and section set; and
- build the would-be or actual assertion records.

The `allocate` path does **not** call the v1.0 `allocate()` function and does not reopen `--candidates` after validation.

## 3. Preallocation CI

Workflow:

`.github/workflows/rc006-a2-product-allocation-readiness.yml`

Introducing commit:

`396a4deee7950a5a724d14504827d4cb495be17c`

Successful execution:

- run: `33918303398`
- job: `101170497652`
- conclusion: `success`
- evidence artifact: `9953994821`
- evidence artifact archive SHA-256: `046bedcd9f63883eb0c15d8e4bfed546f653d1ac9a15d0e28582391c4327cebe`

Every workflow step completed successfully, including canonical validation, nonmutating preallocation, stale-corpus rejection, restoration/revalidation, mutation proof, and tool-identity capture.

## 4. Canonical preallocation result

The registered frozen Product Contract corpus produced:

- result: `PASS`
- mode: `INITIAL`
- batch: `A2-BATCH-0001-PRODUCT-CONTRACT`
- candidate count: `431`
- section count: `27`
- candidate Git blob: `3fdbad0c4b9484735020a1dec2698c0e7e14ef95`
- candidate payload SHA-256: `97dffb8a826747fc9bc12bdbb876147da591b2e1350bed9a319cb86b9bab1ba7`
- first would-be stable ID: `A2-ASSERT-000001`
- last would-be stable ID: `A2-ASSERT-000431`
- would-be allocated count: `431`
- mutation performed: `false`
- prior state SHA-256: `5dfac65c13c3bcd68d466422b0a732295954db0181659454cba37af6051d70f7`
- would-be ledger SHA-256: `bbb71e9d6b7e0b9cff67f1b979c86a3e72664ad93f5df6a6d1c8326e947f0155`
- would-be state SHA-256: `ffb863cca14f8b4e799c0554b6caae5cdbde1a7f7ae199481a4f1ec2ad412602`
- preallocation result payload SHA-256: `438fc4635080f763d05734706715d10798b7ec6ee78d6d1c609d2db6e6b468e8`

## 5. Negative substitution proof

Within the same ephemeral CI checkout, the workflow:

1. preserved the valid 431-record corpus;
2. replaced the canonical worktree path with a 426-record truncation;
3. invoked the exact Product Contract preallocation command;
4. required nonzero exit;
5. observed rejection because the working-tree candidate Git blob differed from the frozen blob;
6. verified that no failed-preallocation output file was produced;
7. restored the exact valid corpus; and
8. revalidated the restored corpus successfully.

Observed stale-test rejection:

`A2_FROZEN_ALLOCATOR_ERROR working-tree candidate Git blob mismatch: 703837fabfdbff40edcd976c8c5103169a936160 != 3fdbad0c4b9484735020a1dec2698c0e7e14ef95`

Therefore the previously identified 426-record stale generation cannot be used to mint only `A2-ASSERT-000001..000426` through v1.2.0.

## 6. Zero-allocation proof after preallocation CI

Before and after the successful CI run:

- allocated count: `0`
- ledger record count: `0`
- next assertion ID: `A2-ASSERT-000001`
- next INITIAL source: `docs/PRODUCT_CONTRACT.md`
- completed INITIAL source count: `0`
- allocation-state SHA-256: `5dfac65c13c3bcd68d466422b0a732295954db0181659454cba37af6051d70f7`
- authority ledger: absent

The workflow independently checked the allocation-state file hash, required the authority ledger to remain absent, restored the candidate corpus byte-for-byte, and required no Git diff in the state or candidate corpus.

## 7. Disposition and authorization boundary

Product Contract candidate preparation remains complete and frozen. The stale external ZIP is rejected and is not an allocation input. The allocator identity/substitution blocker is closed by v1.2.0 and the successful preallocation CI evidence above.

This record does **not** itself mint a stable assertion ID.

Subject to a final current-HEAD zero-allocation recheck after this evidence record is committed, the next authorized mutation is:

`A2-BATCH-0001-PRODUCT-CONTRACT`

allocating exactly:

`A2-ASSERT-000001` through `A2-ASSERT-000431`.
