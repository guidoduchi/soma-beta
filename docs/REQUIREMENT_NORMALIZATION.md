# SOMA Beta Requirement Normalization

Status: **Active — checkpoint 27/177 accepted**  
Authority: project-owner-approved normalization decisions.  
Source baseline: `docs/BETA_REQUIREMENTS.md` preserves the pre-normalization approved wording and immutable `BETA-REQ-####` identities.

## Purpose

This layer makes the approved Beta catalogue consistently atomic, readable, traceable, and testable without discarding the pre-normalization product record.

For every reviewed requirement:

- the `BETA-REQ-####` identity remains immutable;
- **Replace** means the normalized governing obligation in this layer supersedes the earlier wording while all approved detail survives in stable clauses;
- **Retain** means the earlier wording remains the governing obligation because it was already atomic;
- clause IDs are stable normative references and must continue to point back to approved Beta authority;
- a requirement may own multiple clauses, and a clause may cite supporting approved requirements where needed;
- genuinely new product behavior must be explicitly approved rather than introduced by design;
- every requirement must eventually map to a business use case or structural invariant, HLD ownership, LLD destination, and acceptance evidence.

## Normalization doctrine

1. No `BETA-REQ-####` renumbering or identity reuse.
2. One governing obligation per requirement.
3. Detailed lifecycle, cardinality, exception, correction, transaction, UI-state, and acceptance mechanics belong in stable normative clauses.
4. Early vague requirements are strengthened only from already approved product authority or explicit owner clarification.
5. Terminology follows the accepted glossary and later product decisions.
6. Classification uses one primary category with optional secondary categories.
7. Forward coverage: every material assertion in the source requirement must survive in its governing obligation or linked clauses.
8. Reverse coverage: every normative clause must trace back to approved product authority.
9. Design may choose implementation mechanics but may not weaken, replace, or silently invent product behavior.
10. A compound requirement that cannot be normalized under one coherent obligation is flagged to the project owner rather than split silently.

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
| CP-001 | `BETA-REQ-0001`–`0027` | 27 | 26 | 1 | 183 | Forward/reverse semantic coverage passed |

CP-001 artefacts:
- [`normalization/CP001_CATALOGUE.md`](normalization/CP001_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP001_CLAUSES.md`](normalization/CP001_CLAUSES.md) — stable normative clause decomposition.
- [`normalization/CP001_TRACEABILITY.md`](normalization/CP001_TRACEABILITY.md) — design seeds and two-way audit.

## Final consolidation rule

`docs/BETA_REQUIREMENTS.md` remains the preserved pre-normalization baseline during the pass. After `BETA-REQ-0177` is normalized and the complete two-way audit passes, the accepted normalized obligations may be consolidated into the main catalogue without deleting the preserved source history. The normalization layer remains the authority for clause identity and before/after traceability.
