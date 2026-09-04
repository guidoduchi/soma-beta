# RC-006-A2 — Section-Level Clause Destination Assurance

Status: **OPEN — Phase-0 decision baseline accepted/frozen; closure certification suspended pending A2; Phase 1A owner review paused**  
Parent: `RC-006-A1`  
Baseline: accepted Phase-0 product authority and the 11,524-clause canonical set recorded in `PHASE0_ACCEPTANCE.md`.

## 1. Purpose

RC-006-A1 proves literal canonical-set equality, requirement ownership, unique destination-map membership, and at least one reconciled destination for every stable clause through 177 inclusive owner ranges.

A2 strengthens that proof. It adds an independently reviewable edge from each semantic canonical subrange to the **exact primary normative destination section** that represents the obligation.

This is assurance hardening, not product-policy reopening. A2 shall not change:

- any `BETA-REQ-####` identity;
- canonical clause ID/text/owner;
- accepted product behavior;
- focused-contract ownership;
- accepted Phase-0 history; or
- downstream `O-*` design boundaries.

If A2 discovers an actual semantic contradiction, that finding follows the existing controlled correction/reopening doctrine; A2 itself does not invent the correction.

## 2. Why A2 is additive

`RECONCILIATION_METHOD.md` originally required support for:

`stable clause → owning requirement → destination contracts → reconciliation result`.

A1 satisfies that literal contract-level edge. A2 deliberately adopts a stronger future assurance standard:

`stable clause/subrange → owning requirement → primary normative document §anchor → supporting §anchor(s) → reconciliation result`.

The stronger standard is prospective/additive. It must not be used to rewrite history by claiming the accepted A1 standard never passed its then-governing doctrine.

## 3. A2 row contract

Every A2 mapping row records:

| Field | Rule |
|---|---|
| Canonical clause subrange | Inclusive stable IDs; split only when semantic primary destination changes |
| Owner | Exact accepted `BETA-REQ-####` owner |
| Primary normative destination | Exactly one focused-contract/document section that owns the represented rule |
| Supporting destination(s) and role | Optional cross-domain/synthesis sections; each is classified `SUPPORTING_NORMATIVE` or `INFORMATIVE_REFERENCE` |
| Reverse-authority reference | Canonical clause(s) authorizing every primary or supporting normative assertion at the destination |
| Representation note | Concise explanation of what the primary section represents and why supporting roles are needed |
| Result | `PASS` only after section existence, semantic representation, role classification and reverse authority are verified |

A broad owner range must be split when different canonical clauses are primarily represented in different normative sections.

## 4. Primary-destination rules

1. Each canonical stable clause appears in **exactly one A2 primary-coverage row** after range expansion.
2. Every destination relationship is classified as `PRIMARY_NORMATIVE`, `SUPPORTING_NORMATIVE`, or `INFORMATIVE_REFERENCE`.
3. A `SUPPORTING_NORMATIVE` destination may overlap other coverage only when its obligation is independently source-authorized and semantically consistent with the primary destination. An `INFORMATIVE_REFERENCE` carries no independent obligation.
4. Architecture/Roadmap may be supporting/derived destinations but cannot become primary product authority where a focused contract owns the behavior.
5. A section reference must resolve to an existing heading/anchor in the target document.
6. A section is not accepted merely because the document is generally related; semantic representation of the mapped subrange must be inspected.
7. Cross-domain rules retain one primary traceability anchor and classify other required normative representations as supporting normative rather than demoting them to commentary.
8. The primary destination is a traceability anchor, not a claim that all other normative representations are non-authoritative.
9. A design-boundary clause may map primarily to the governing product/runtime contract section that explicitly leaves the mechanic downstream; A2 must not choose the mechanic.

## 5. Mechanical invariants

After expanding all primary A2 ranges, validation shall require:

- canonical stable IDs: **11,524**;
- machine-expanded clause-ledger records: **11,524**;
- primary-covered IDs: **11,524**;
- missing canonical IDs: **0**;
- extra/noncanonical IDs: **0**;
- duplicate primary memberships: **0**;
- owner mismatches: **0**;
- rows without exactly one primary destination: **0**;
- unclassified supporting destination relationships: **0**;
- broken/nonexistent destination document/section references: **0**;
- rows lacking semantic-review PASS: **0**;
- enumerated primary/supporting normative destination assertions without canonical authority: **0**;
- contradictory primary/supporting normative representations: **0**; and
- unreconciled reverse-authority entries: **0**.

Supporting-destination overlap is excluded from duplicate-primary checks, but overlap is never exempt from role classification, reverse authority, or contradiction review. The compact map is the maintained human-review source; a deterministic, reproducible 11,524-record expanded ledger is mandatory validation evidence and must never be hand-maintained as a competing catalogue.

## 6. Semantic verification procedure

For each canonical owner range from `RC006_CLAUSE_DESTINATIONS.md`:

1. inspect the canonical clauses in the accepted normalization artifacts;
2. identify semantic destination changes inside the owner range;
3. split into the minimal lossless subranges needed for distinct primary ownership;
4. resolve the exact primary contract heading/section;
5. record every supporting section and classify it as `SUPPORTING_NORMATIVE` or `INFORMATIVE_REFERENCE`;
6. verify that each normative destination preserves identity, cardinality, lifecycle, temporal, source-of-truth, release, correction and failure semantics applicable to the subrange;
7. enumerate the normative assertions in each primary/supporting destination and map them back to accepted canonical authority;
8. record and resolve any unsupported or contradictory destination assertion through controlled correction;
9. mark PASS only after section existence, meaning, destination role, and reverse authority all verify; and
10. expand the completed primary ranges and run the mechanical invariants in §5.

The reverse audit is mandatory:

`normative destination assertion → authorizing canonical clause(s) → owning BETA-REQ`

A2 fails if forward clause coverage passes while any normative destination assertion remains unauthorized, unclassified, or contradictory.

## 7. Deliverable

The final A2 evidence shall include:

1. `RC006_A2_SECTION_DESTINATIONS.md` — compact human-reviewed semantic subranges;
2. a generated machine-readable 11,524-record expanded clause ledger;
3. a reverse normative-destination authority ledger;
4. a reproducible validator and immutable validation summary; and
5. the A2 finding/correction register.

The compact map may use inclusive ranges substantially finer than the 177 owner ranges. The expanded ledger is generated evidence, not a second hand-authored normative catalogue. “Automated-equivalent” evidence is insufficient: expansion and invariant checks must be automated and reproducible.

## 8. Acceptance/addendum rule

A2 is **not PASS merely because this method exists**.

After the destination map is complete and all §5 invariants pass:

1. complete the compact forward map, generated 11,524-record ledger, reverse-authority ledger, reproducible validator, and validation summary;
2. prove every §5 invariant with zero unresolved exceptions;
3. mark A2 `PASS`;
4. record every finding/correction explicitly;
5. add a Phase-0 assurance addendum stating whether accepted product authority remained stable and that section-level evidence was added post-closure; and
6. do not rewrite the original `PHASE0_ACCEPTANCE.md` action or accepted pre-closure head.

Until then:

> **Phase-0 decision authority remains accepted and frozen. Historical acceptance remains preserved. Current closure certification is suspended/open until RC-006-A2 passes, and Phase 1A owner review remains paused after UC-001.**
