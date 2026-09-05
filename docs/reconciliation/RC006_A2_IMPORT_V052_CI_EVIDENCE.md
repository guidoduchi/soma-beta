# Import v0.5.2 correction — executed CI evidence

Status: **Mechanical correction PASS; full Import semantic review OPEN.**

This excluded control record supplements, without rewriting,
`RC006_A2_IMPORT_REFERENT_CORRECTION.md` at correction commit
`9094bfe60e14e1105720f8a9fbc5bb37ff373d7e`.

## Verified execution

| Evidence | Verified value |
|---|---|
| Correction commit | `9094bfe60e14e1105720f8a9fbc5bb37ff373d7e` |
| Correction tree | `55620a266b5ffaf8668425ae5bd036ca3bda91fe` |
| Parent checkpoint | `f0181078ea272d484cee6f609f0892af5996ec68` |
| CI run | [33936265186](https://github.com/guidoduchi/soma-beta/actions/runs/33936265186) — success |
| Review job | `101224689664` — all stages success |
| Artifact | `9960264983`, `rc006-a2-import-candidate-review-v052` |
| Downloaded archive SHA-256 | `d4d022518efc2c8c39737fa20b88319ed344aa53b4baffdf17afe990f32baa5e` |
| Candidate count / sections | 186 / 22 |
| Candidate payload SHA-256 | `4a0a1c6109fe581c6874e59559530c7a892b2e3588286610031aff9e6a6db981` |
| Generator blob | `3a5b6f9d779d78eabf5d3c6a4746a5c791cacf11` |
| Hardened validator blob / version | `88345216426ed4e3bbd9ac52c4aaf1e507ce2dac` / v1.1.0 |
| Pinned Import source blob | `08dcf31d23748d4269538baa6ee1fcd7499585e8` |

The run's exact head SHA and job steps were read from GitHub. Its archive was
downloaded and its SHA-256 independently reproduced, matching the artifact API
digest. Generator identity, validator output and candidate payload match local
expectations. Comparing the old and new artifact records independently confirms
that only candidate position 163's `review_note` changed; all 186 assertion
boundaries, kinds, texts, fingerprints, locators and ordering are preserved.

CI ran all 16 Import regression tests, regenerated through pinned parent tools
from B002 with full Git history, and passed hardened source-span validation.
The explicit semantic-review state remained OPEN, with freeze and allocation
authorization both false. CI success is not semantic completeness certification.

## Nonmutation proof

Before/after allocation summaries are byte-identical. Their verified state is:

- allocated count and ledger records: **431**;
- next assertion: **A2-ASSERT-000432**;
- completed INITIAL sources: **1**, Product Contract;
- next INITIAL source: **docs/IMPORT_CONTRACT.md**;
- allocation state SHA-256: `ffb863cca14f8b4e799c0554b6caae5cdbde1a7f7ae199481a4f1ec2ad412602`;
- authority ledger SHA-256: `bbb71e9d6b7e0b9cff67f1b979c86a3e72664ad93f5df6a6d1c8326e947f0155`.

CI also verified these two file hashes after processing, reran check-state, and
confirmed no tracked changes or untracked files in its checkout.
The GitHub comparison from parent checkpoint to correction commit contains
exactly four files: the review workflow, v0.5.2 generator, its regression tests,
and the correction record. It changes no B002 included input or allocation file.

## Catalogue assessment evidence

`docs/use-cases/P1A_READINESS_ASSESSMENT_2026_09_05.md` supplies one specific
readiness observation for each UC-001..095 and preserves current statuses.
Its local accounting checker verifies exact numeric order, unique identity,
matching source-wave/status and a nonempty individual review focus.
Four local regression tests check valid accounting and refusal of missing,
duplicated and falsely promoted rows. This does not certify canonical semantics.

Reproduce the local checks from this evidence commit's complete checkout:

```sh
python -m unittest discover -s tools/reconciliation -p 'test_rc006_a2_import_v0_5_2.py' -v
python -m unittest discover -s tools/reconciliation -p 'test_p1a_readiness_assessment.py' -v
python tools/reconciliation/check_p1a_readiness_assessment.py --repo .
```

The accounting tests are explicitly checkpoint-specific; future accepted
catalogue evolution needs a new assessment/version rather than falsifying this
historical result. These four catalogue tests were run locally, not in the
earlier correction CI run cited above.

## Remaining gate

The broader Import completeness/atomicity review, final corpus freeze, hardened
Import identity registration and preallocation remain pending. Product's 431 IDs
are unchanged; no Import IDs are minted. RC-006-A2 certification remains OPEN,
UC owner review remains paused, and HLD/LLD acceptance and production implementation
remain downstream gates. See the per-UC assessment for the ordered completion route.
