# SOMA Beta Requirement Normalization

Status: **Active — checkpoint 27/177 accepted; CP-001 amendment A1 applied**  
Authority: project-owner-approved normalization decisions.  
Source baseline: `docs/BETA_REQUIREMENTS.md` preserves the pre-normalization approved wording and immutable `BETA-REQ-####` identities.

## Purpose

This layer makes the approved Beta catalogue consistently atomic, readable, traceable, and testable without discarding the pre-normalization product record.

For every reviewed requirement:

- the `BETA-REQ-####` identity remains immutable;
- **Replace** means the normalized governing obligation in this layer supersedes the earlier wording while all approved detail survives in stable clauses;
- **Retain** means the earlier wording remains the governing obligation because it was already atomic;
- clause IDs are stable normative references and must continue to point back to approved Beta authority;
- every clause records one owning `BETA-REQ-####`; when a clause also depends on other approved authority, that supporting authority is recorded explicitly without transferring ownership;
- genuinely new product behavior must be explicitly approved rather than introduced by design;
- every requirement must eventually map to a business use case or structural invariant, HLD ownership, LLD destination, and acceptance evidence.

## Normalization doctrine

1. No `BETA-REQ-####` renumbering or identity reuse.
2. One governing obligation per requirement.
3. Detailed lifecycle, cardinality, exception, correction, transaction, UI-state, and acceptance mechanics belong in stable normative clauses.
4. Early vague requirements are strengthened only from already approved product authority or explicit owner clarification.
5. Terminology follows the accepted glossary and later product decisions.
6. Classification uses one primary category with optional secondary categories. In compact catalogue syntax, the **first listed classification is primary** and every subsequent semicolon-separated classification is **secondary**.
7. Forward coverage: every material assertion in the source requirement must survive in its governing obligation or linked clauses.
8. Reverse coverage: every normative clause must record its owning approved requirement and any additional approved supporting authority needed to establish the rule.
9. Supporting authority strengthens provenance only; it does not transfer clause ownership or authorize new product behavior.
10. Design may choose implementation mechanics but may not weaken, replace, or silently invent product behavior.
11. A compound requirement that cannot be normalized under one coherent obligation is flagged to the project owner rather than split silently.

## Classification vocabulary

- Functional capability
- Business rule
- Structural invariant
- Security/privacy constraint
- UI/UX obligation
- Quality/platform requirement

## Checkpoint cadence

- First checkpoint: `BETA-REQ-0001`–`0027`.
- Subsequent checkpoints: every 25 reviewed requirements — `0052`, `0077`, `0102`, `0127`, `0152`, then final `0177`.

## Accepted checkpoints

| Checkpoint | Scope | Reviewed | Replace | Retain | Clause count | Audit |
|---|---|---:|---:|---:|---:|---|
| CP-001 | `BETA-REQ-0001`–`0027` | 27 | 26 | 1 | 183 | Forward PASS; reverse-authority PASS after amendment A1 |

CP-001 artefacts:
- [`normalization/CP001_CATALOGUE.md`](normalization/CP001_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP001_CLAUSES.md`](normalization/CP001_CLAUSES.md) — stable normative clause decomposition.
- [`normalization/CP001_CLAUSE_AUTHORITY.md`](normalization/CP001_CLAUSE_AUTHORITY.md) — explicit owner/supporting-authority evidence for all 183 clauses.
- [`normalization/CP001_TRACEABILITY.md`](normalization/CP001_TRACEABILITY.md) — design seeds and two-way audit.

## Amendment log

### CP-001-A1 — clause authority evidence and classification syntax

Independent review accepted the CP-001 product content but correctly identified that the original reverse-authority PASS was not yet evidenced at clause granularity. Amendment A1 changes no governing obligation or clause rule. It:

- records an owner for all **183/183** stable clauses;
- records explicit additional supporting authority for **54** cross-cutting clauses while **129** clauses are fully established by their owner alone;
- re-runs the reverse-authority audit from that recorded mapping with **183/183 PASS**;
- clarifies that the first classification listed in compact catalogue syntax is primary and later entries are secondary.

After A1: **Product preservation PASS; structural integrity PASS; forward traceability PASS; reverse authority PASS; overall CP-001 unconditional PASS.**

## Final consolidation rule

`docs/BETA_REQUIREMENTS.md` remains the preserved pre-normalization baseline during the pass. After `BETA-REQ-0177` is normalized and the complete two-way audit passes, the accepted normalized obligations may be consolidated into the main catalogue without deleting the preserved source history. The normalization layer remains the authority for clause identity and before/after traceability.
