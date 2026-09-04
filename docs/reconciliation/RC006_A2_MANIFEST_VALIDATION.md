# RC-006-A2 — Manifest Preflight Validation Summary

Status: **PASS — repository-executed B002 corpus validation complete; A2 assertion allocation may begin only after this summary commit is verified**  
Baseline: `A2-BASELINE-002`  
Validation schema: `RC006-A2-MANIFEST-VALIDATION-RESULT-V1`

## Purpose

This immutable summary records the repository-executed preflight proving that the frozen RC-006-A2 input manifest exactly represents the pinned `A2-BASELINE-002` source tree. It is control/generated evidence and is excluded from normative assertion extraction and destination interpretation.

No `A2-ASSERT-######` identity had been allocated when this validation was executed or when this summary was prepared.

## Pinned inputs

- source commit: `61bbd665535e942ef3b05c5ed45661639d3a37a9`;
- source Git tree: `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`;
- manifest path: `docs/reconciliation/RC006_A2_INPUT_MANIFEST.tsv`;
- manifest creation commit: `221bfdbbbb660387c407c44ac6e119a749c0dfbd`;
- manifest Git blob SHA: `05daa81310b8259ca8ff968bd1715244ecf0d5d5`;
- manifest payload SHA-256: `3bbe5c2f6c82b4ddaf4ecbc2825ace3b0edc3072e67fe09f6e68447e89fd1013`;
- expected source-tree blob records: **92**;
- expected INCLUDE records: **74**;
- expected EXCLUDE records: **18**.

## Validator identity

- validator path: `tools/reconciliation/validate_rc006_a2_manifest.py`;
- validator version: **`1.0.0`**;
- validator creation commit: `9a05bf0a7c0ad0009a660a6dd90eaaa599133db1`;
- validator Git blob SHA: `69bc453816d8dce0e20b6eace9bd16cc24cf1fee`;
- validator source SHA-256: `5f08d07e871e62dc1a621a060185129d72e575766ee52ea454497045bcefa5a3`;
- implementation dependencies: Python standard library plus local Git executable;
- baseline behavior: B002 identities and expected counts are hard-pinned and cannot be replaced by command-line overrides.

## Repository execution evidence

- workflow: `.github/workflows/rc006-a2-preflight.yml`;
- workflow commit/head SHA: `2a643c900c4031854934bc32f50ae75ccb2d47b8`;
- GitHub Actions workflow run ID: **`33913171111`**;
- job ID: **`101154192896`**;
- job name: `preflight`;
- runner OS: Ubuntu 24.04.4 LTS;
- Git version: `2.55.0`;
- Python runtime: CPython `3.13.15`;
- checkout mode: full repository history (`fetch-depth: 0`);
- execution conclusion: **success**;
- validator process result: **PASS**.

The workflow executed:

`python tools/reconciliation/validate_rc006_a2_manifest.py --repo . --output rc006_a2_manifest_validation.txt`

against a full clone containing the pinned historical objects.

## Deterministic result identity

- result SHA-256 emitted by validator: **`06f398f26405ac092a15544911d8b161ee7c680d4eb5991ce5885755fccaeb44`**;
- uploaded artifact name: `rc006-a2-manifest-validation`;
- GitHub Actions artifact ID: **`9952130473`**;
- uploaded artifact size: **1049 bytes**;
- uploaded artifact archive SHA-256: **`5faf866855a39f44a67da56be5b23080ae3497abcccb68f0b01c119dc84b066a`**;
- artifact retention at execution: 90 days.

The transient Actions artifact is supplementary execution evidence. This committed summary and the deterministic result hash are the durable repository evidence; A2 certification shall not depend on artifact retention.

## Validation results

| Invariant | Result |
|---|---:|
| Source commit resolves to pinned B002 tree | PASS |
| Resolved source tree equals `b6f7fcdd…` | PASS |
| Manifest Git blob equals `05daa813…` | PASS |
| Declared payload SHA-256 equals expected | PASS |
| Recomputed payload SHA-256 equals expected | PASS |
| Final LF present | PASS |
| CR count | **0** |
| Manifest format errors | **0** |
| Malformed file records | **0** |
| Empty classification/reason evidence | **0** |
| Invalid blob SHA records | **0** |
| Invalid INCLUDE/EXCLUDE classifications | **0** |
| Duplicate manifest paths | **0** |
| Bytewise UTF-8 path-order mismatches | **0** |
| Manifest metadata/source-identity mismatches | **0** |
| Source-tree blob records | **92** |
| Source-tree non-blob leaf records | **0** |
| Manifest file records | **92** |
| Manifest unique paths | **92** |
| INCLUDE records | **74** |
| EXCLUDE records | **18** |
| Missing source-tree paths | **0** |
| Extra manifest paths | **0** |
| Blob-SHA mismatches | **0** |
| Overall validator result | **PASS** |

All boolean checks emitted by `RC006-A2-MANIFEST-VALIDATION-RESULT-V1` were `true`; all error/mismatch counts were zero.

## Gate effect

This summary closes the RC-006-A2 manifest preflight gate:

- exact corpus manifest: **PASS**;
- deterministic validator specification: **PASS**;
- repository-native validator execution: **PASS**;
- immutable validation summary: **RECORDED by this artifact**;
- `A2-ASSERT` allocation: **AUTHORIZED only after the Git commit/blob identity of this summary is verified**;
- A2 section-level/reverse-authority certification: **still OPEN**;
- Phase 1A owner review after `UC-001`: **still PAUSED until A2 PASS**.

This result authorizes only the next controlled A2 step. It does not itself claim section-destination completeness, reverse-authority completeness, or final RC-006-A2 PASS.
