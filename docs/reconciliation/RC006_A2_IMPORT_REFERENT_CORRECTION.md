# RC-006-A2 Import boundary review and process simplification

Status: **Human boundary review complete; canonical candidate freeze pending its one-file commit; reverse authority and A2 certification OPEN.**

This record is excluded reconciliation evidence. It changes no B002 source,
requirement, product decision, use-case state or allocated assertion.

## Corrected semantic result

The v0.5.1 experiment joined the Import §9.2 permission at line 256 to the
prohibitions at line 258 because “It” needed an antecedent. That merge was
incorrect under Extraction Schema V1: the rules can fail independently.
Context belongs in `review_note`; it does not require a larger normative span.

The subsequent v0.5.2 experiment demonstrated this correction while retaining
186 records, but also revealed a broader problem: v0.5.0 had joined several
independently testable rules under the label “context closure.” Its mechanical
PASS therefore did not establish complete or atomic semantic review.

The human review used the exact B002 Import source blob
`08dcf31d23748d4269538baa6ee1fcd7499585e8` and inspected the complete source
and all 186 v0.5.2 candidates. It directly split 27 compound candidates into 63
atomic candidates and retained 159 candidates. The resulting corpus has:

- **222 candidates** in **22 normative sections**;
- 222 unique `(section_ordinal, assertion_ordinal)` locators;
- 222 unique exact-text fingerprints;
- contiguous assertion ordinals within every represented section;
- exact verbatim spans within the pinned source lines;
- no stable `A2-ASSERT` identity;
- payload SHA-256 `418196ba0acc587797dedec05900d42fdc52f4b052c8f8ca44e15c8b01cc4ca4`;
- predicted Git blob `e9a66fe4b9343929f70c40cd0c7cf24320b16233`.

The count is a result of the boundary decisions, not a required target.
Informative sample-evidence sections remain unallocated; the Temporal Authority
section remains represented. Lists and table rows stay cohesive when the list or
row is the field/allowlist contract being reviewed. Distinct permissions,
prohibitions, consequences and authority statements were split when each can be
violated or mapped independently. Pronoun and clause context is recorded in the
candidate note.

This completes candidate completeness/atomicity review only. Canonical reverse
authority, contradiction review, forward mapping and clause coverage remain A2
work. `classification_review: PASS` means the candidate is normative and its
boundary is reviewed; it does not mean `semantic_review: PASS` in the assertion
authority ledger.

## Simplified A2 operating rule

Effective after this correction:

> No new per-contract extractor version, workflow, CI artifact, hash-evidence
> document or dedicated micro-validator may be added unless it detects a class
> of error that the accumulated A2 validator cannot reasonably detect.

Operational consequences:

1. Human reviewers edit the candidate set directly before allocation. Boundary
   corrections do not create another extractor program.
2. Each destination contract receives one reviewed canonical candidate file,
   frozen once before allocation. Existing stable IDs are never renumbered.
3. The maintained assertion authority ledger is the durable evidence. Per-step
   archives and narrative hash records do not become a second ledger.
4. One accumulated validator checks every processed source: corpus membership,
   source blobs/spans, candidate/ledger schema, fingerprints, stable-ID order and
   uniqueness, forward edges, reverse clause authority, owner derivation,
   contradictions, exact 11,524-clause completeness and orphan conditions.
5. Small local inspection scripts may be used ephemerally. They are not committed
   unless the accumulated validator needs the capability permanently.
6. A new tool is justified only by a documented error class, why human review
   plus the accumulated validator cannot catch it reasonably, and how the tool
   will be reused across the accumulated corpus.

Accordingly, the v0.5.2 generator and its dedicated tests, the P1A assessment
checker/tests, the Import-only review workflow, and the duplicate v0.5.2 CI
evidence record are removed. Their historical commits and successful run remain
available in Git history. The 95-UC readiness assessment and every substantive
semantic finding are retained.

## Next boundary

The next commit may add exactly the canonical Import candidate JSONL and no
other path. After its blob is verified, the general allocation path may register
that frozen identity, preallocate once, allocate `A2-ASSERT-000432` onward and
continue to the next destination source. The accumulated A2 validator remains
the final assurance gate.

Product allocation remains 431 records through `A2-ASSERT-000431`; Import is not
yet allocated. UC owner review remains paused until RC-006-A2 PASS. HLD, complete
LLD acceptance and production implementation remain downstream gates.
