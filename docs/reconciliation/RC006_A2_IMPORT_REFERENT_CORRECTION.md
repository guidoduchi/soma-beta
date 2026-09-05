# RC-006-A2 Import referent correction — v0.5.2 review

Status: **Correction implemented; Import semantic completeness/atomicity review OPEN; no freeze or allocation authorization.**

This is excluded reconciliation control evidence, not a change to B002 authority.
Starting branch checkpoint: `f0181078ea272d484cee6f609f0892af5996ec68`.
B002 source commit: `61bbd665535e942ef3b05c5ed45661639d3a37a9`.
Import source blob: `08dcf31d23748d4269538baa6ee1fcd7499585e8`.

## Disposition

The v0.5.1 experiment combines the permission at Import §9.2 line 256 with the
prohibitions at line 258, solely to bring the antecedent of “It” into the same
span. Extraction Schema V1 §4 requires independently reviewable rules and
minimal verbatim spans; §5 already provides `review_note` for contextual review.
Pronoun presence alone is not sufficient grounds to merge independent rules.

The active review workflow now uses the separately versioned v0.5.2 generator.
It retains the v0.5.0 186-record structure and adds the antecedent explanation to
one review note, at section ordinal 26 / assertion ordinal 2. The permission and
prohibition remain separate. v0.5.1 remains historical experimental evidence and
is not the active review generator. No canonical source, source span, kind,
ordinal, fingerprint or stable assertion identity is changed.

This narrow correction does **not** certify every v0.5.0 grouping as atomic.
In particular, its 23 earlier combination groups still need explicit semantic
disposition under §4, including the multiple prohibitions retained at line 258.
Inherited candidate `classification_review: PASS` values are previous review
metadata, not a new completeness certificate. The v0.5.2 summary explicitly
sets semantic review OPEN and both freeze/allocation authorization false.
186 is a regression expectation for this correction, not a mandatory final
count: any justified later split requires a separately versioned, reviewed corpus.

## Identity and local evidence

The prior CI artifact `9957374484` was downloaded and independently checked:

| Identity | Value |
|---|---|
| ZIP SHA-256 | `5bf5804d2f23274be9eb3796df793c1a852520a69859b0105e6c6cf20372359e` |
| v0.5.0 parent generator blob | `e77c1667f96c52337d0c50db71233ee1f664f971` |
| v0.5.0 candidate payload SHA-256 | `ce0a6102cc72ef6e0ef4a00a12f0bb7ae8f15db5c7c6d12ddb301192e1663dfc` |
| v0.5.2 generator blob | `3a5b6f9d779d78eabf5d3c6a4746a5c791cacf11` |
| v0.5.2 generator SHA-256 | `d2653b27c2760a015cb51d8c2304ff598824d1f5e77cb4dc74621e4d40e6b463` |
| v0.5.2 review payload SHA-256 | `4a0a1c6109fe581c6874e59559530c7a892b2e3588286610031aff9e6a6db981` |
| v0.5.2 review payload Git blob | `a8a023e9a4df02bd7b9867d9b98219e1d7f0b8e6` |

Local transformation of those exact artifact bytes produced 186 records, with
only candidate position 163's `review_note` changed. All other parsed fields and
record ordering were identical. The payload above is review evidence only,
not a frozen canonical candidate corpus.

Sixteen unit tests pass, including count/section/text/identity substitution,
stable-ID refusal, same-count payload substitution, input immutability and
repository-output/symlink/alias refusal. Synthetic fixtures are test-only.
The exact parent payload is hashed before parsing; the transformation consumes
that same byte stream. Review outputs must be outside the repository.

Local testing used a partial downloaded snapshot, not a full Git checkout.
Full pinned-source regeneration and hardened validation must therefore pass in
the updated review CI. This record does not claim that future CI result.
CI checks allocation-state/ledger byte identities before and after processing,
reruns allocator check-state, and rejects tracked or untracked repository changes.

## Remaining execution boundary

1. Obtain successful v0.5.2 CI evidence at its exact commit and verify payload identity.
2. Review every final candidate and source section for omissions, independent
   rules, authority and classification; explicitly resolve the 23 inherited groups.
3. Only then freeze the final Import corpus and record validation/freeze evidence.
4. Register that exact frozen identity in a separately versioned hardened allocator;
   test stale, same-count and altered-source inputs plus nonmutating preallocation.
5. Recheck unchanged Product allocation and exact commit boundary before Import allocation.

Until those gates pass, `A2-ASSERT-000432` is not allocated. Product IDs
`000001..000431` remain intact and pending reverse-authority certification.
UC owner review remains paused until full RC-006-A2 PASS. This correction does
not authorize HLD acceptance, LLD acceptance or production implementation.
