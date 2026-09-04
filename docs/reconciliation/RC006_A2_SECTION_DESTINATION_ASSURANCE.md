# RC-006-A2 — Section-Level Clause Destination Assurance

Status: **OPEN — post-closure assurance hardening; does not reopen Phase-0 product authority**  
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
| Supporting destination(s) | Optional cross-domain/synthesis sections; may overlap freely |
| Representation note | Concise explanation of what the primary section represents |
| Result | `PASS` only after section exists and semantic representation is verified |

A broad owner range must be split when different canonical clauses are primarily represented in different normative sections.

## 4. Primary-destination rules

1. Each canonical stable clause appears in **exactly one A2 primary-coverage row** after range expansion.
2. Supporting references do not count as primary ownership and may overlap.
3. Architecture/Roadmap may be supporting/derived destinations but cannot become primary product authority where a focused contract owns the behavior.
4. A section reference must resolve to an existing heading/anchor in the target document.
5. A section is not accepted merely because the document is generally related; semantic representation of the mapped subrange must be inspected.
6. Cross-domain rules retain one primary normative owner and list the other domain representations as supporting destinations.
7. A design-boundary clause may map primarily to the governing product/runtime contract section that explicitly leaves the mechanic downstream; A2 must not choose the mechanic.

## 5. Mechanical invariants

After expanding all primary A2 ranges, validation shall require:

- canonical stable IDs: **11,524**;
- primary-covered IDs: **11,524**;
- missing canonical IDs: **0**;
- extra/noncanonical IDs: **0**;
- duplicate primary memberships: **0**;
- owner mismatches: **0**;
- rows without one primary destination: **0**;
- broken/nonexistent destination document/section references: **0**;
- rows lacking semantic-review PASS: **0**.

Supporting-destination overlap is permitted and is excluded from duplicate-primary checks.

## 6. Semantic verification procedure

For each canonical owner range from `RC006_CLAUSE_DESTINATIONS.md`:

1. inspect the canonical clauses in the accepted normalization artifacts;
2. identify semantic destination changes inside the owner range;
3. split into the minimal lossless subranges needed for distinct primary ownership;
4. resolve the exact primary contract heading/section;
5. record any supporting sections needed to understand cross-domain representation;
6. verify that the section preserves identity, cardinality, lifecycle, temporal, source-of-truth, release, correction and failure semantics applicable to the subrange;
7. mark PASS only after the section reference and meaning both verify; and
8. expand the completed primary ranges and run the mechanical invariants in §5.

## 7. Deliverable

The final A2 evidence shall be stored as a destination-specific map, preferably `RC006_A2_SECTION_DESTINATIONS.md` or a generated machine-readable companion plus a human-readable rendered map.

It shall avoid an unnecessary 11,524-row duplicate catalogue by using inclusive ranges, but those ranges may be substantially finer than the 177 owner ranges when semantic destination changes require it.

## 8. Acceptance/addendum rule

A2 is **not PASS merely because this method exists**.

After the destination map is complete and all §5 invariants pass:

1. mark A2 `PASS`;
2. record any findings/corrections explicitly;
3. add a Phase-0 assurance addendum stating that the accepted product authority remained stable and that section-level evidence was added post-closure; and
4. do not rewrite the original `PHASE0_ACCEPTANCE.md` action or accepted pre-closure head.

Until then:

> **Phase-0 product authority remains accepted and closed. RC-006-A2 assurance hardening remains open.**
