# SOMA Beta Requirement Normalization

Status: **Active — checkpoint 127/177 accepted; CP-001 amendment A1, CP-004 substitute clarification, and CP-005 Device Reference clarification applied**  
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
12. Each checkpoint audit shall cross-check the new range against all prior accepted checkpoints for semantic conflict, duplicated authority, terminology drift, ownership drift, and weakened invariants.
13. Each checkpoint commit shall be isolated to its normalization artefacts and normalization index unless a separately approved correction is explicitly included.

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
| CP-002 | `BETA-REQ-0028`–`0052` | 25 | 25 | 0 | 275 | Forward PASS; reverse-authority PASS; prior-checkpoint cross-check PASS; commit-isolation PASS |
| CP-003 | `BETA-REQ-0053`–`0077` | 25 | 25 | 0 | 666 | Forward PASS; reverse-authority PASS; CP-001/CP-002 cross-check PASS; commit-isolation PASS |
| CP-004 | `BETA-REQ-0078`–`0102` | 25 | 25 | 0 | 1383 | Two-pass preservation PASS; reverse-authority PASS; CP-001/CP-002/CP-003 cross-check PASS; commit-isolation PASS |
| CP-005 | `BETA-REQ-0103`–`0127` | 25 | 25 | 0 | 2669 | Two-pass preservation PASS; reverse-authority PASS; CP-001/CP-002/CP-003/CP-004 cross-check PASS; commit-isolation PASS |

Cumulative accepted normalization through CP-005: **127 / 177 requirements reviewed; 126 Replace; 1 Retain; 5176 stable clauses.**

CP-001 artefacts:
- [`normalization/CP001_CATALOGUE.md`](normalization/CP001_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP001_CLAUSES.md`](normalization/CP001_CLAUSES.md) — stable normative clause decomposition.
- [`normalization/CP001_CLAUSE_AUTHORITY.md`](normalization/CP001_CLAUSE_AUTHORITY.md) — explicit owner/supporting-authority evidence for all 183 clauses.
- [`normalization/CP001_TRACEABILITY.md`](normalization/CP001_TRACEABILITY.md) — design seeds and two-way audit.

CP-002 artefacts:
- [`normalization/CP002_CATALOGUE.md`](normalization/CP002_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP002_CLAUSES.md`](normalization/CP002_CLAUSES.md) — stable normative clause decomposition.
- [`normalization/CP002_CLAUSE_AUTHORITY.md`](normalization/CP002_CLAUSE_AUTHORITY.md) — explicit owner/supporting-authority evidence for all 275 clauses.
- [`normalization/CP002_TRACEABILITY.md`](normalization/CP002_TRACEABILITY.md) — design seeds and two-way audit.

CP-003 artefacts:
- [`normalization/CP003_CATALOGUE.md`](normalization/CP003_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP003_CLAUSES.md`](normalization/CP003_CLAUSES.md) — stable normative clause decomposition.
- [`normalization/CP003_CLAUSE_AUTHORITY.md`](normalization/CP003_CLAUSE_AUTHORITY.md) — explicit owner/supporting-authority evidence for all 666 clauses.
- [`normalization/CP003_TRACEABILITY.md`](normalization/CP003_TRACEABILITY.md) — design seeds, forward/reverse audit, prior-checkpoint cross-check, and commit-isolation evidence.

CP-004 artefacts:
- [`normalization/CP004_CATALOGUE.md`](normalization/CP004_CATALOGUE.md) — accepted governing obligations and classifications.
- [`normalization/CP004_CLAUSES.md`](normalization/CP004_CLAUSES.md) — stable normative clause decomposition, including the accepted `BETA-REQ-0096` substitute clarification.
- [`normalization/CP004_CLAUSE_AUTHORITY.md`](normalization/CP004_CLAUSE_AUTHORITY.md) — explicit owner/supporting-authority evidence for all 1383 clauses.
- [`normalization/CP004_TRACEABILITY.md`](normalization/CP004_TRACEABILITY.md) — two-pass audit, design seeds, substitute-authority reconciliation, prior-checkpoint cross-check, and commit-isolation evidence.

CP-005 artefacts:
- [`normalization/CP005_CATALOGUE.md`](normalization/CP005_CATALOGUE.md) — accepted governing obligations and classifications for `BETA-REQ-0103`–`0127`.
- [`normalization/CP005_CLAUSES.md`](normalization/CP005_CLAUSES.md) — 2669 stable normative clauses covering Infrastructure completion, offline Communications, shared UI behavior, and editor state.
- [`normalization/CP005_CLAUSE_AUTHORITY.md`](normalization/CP005_CLAUSE_AUTHORITY.md) — one-owner/supporting-authority evidence for all 2669 clauses, including the Device Reference regularization clarification as supporting authority only.
- [`normalization/CP005_TRACEABILITY.md`](normalization/CP005_TRACEABILITY.md) — two-pass audit, design seeds, owner clarification reconciliation, prior-checkpoint cross-check, open-design boundaries, and commit-isolation evidence.

## Amendment log

### CP-001-A1 — clause authority evidence and classification syntax

Independent review accepted the CP-001 product content but correctly identified that the original reverse-authority PASS was not yet evidenced at clause granularity. Amendment A1 changes no governing obligation or clause rule. It:

- records an owner for all **183/183** stable clauses;
- records explicit additional supporting authority for **54** cross-cutting clauses while **129** clauses are fully established by their owner alone;
- re-runs the reverse-authority audit from that recorded mapping with **183/183 PASS**;
- clarifies that the first classification listed in compact catalogue syntax is primary and later entries are secondary.

After A1: **Product preservation PASS; structural integrity PASS; forward traceability PASS; reverse authority PASS; overall CP-001 unconditional PASS.**

### CP-003 owner clarification — configurable SLA cohort reports

During normalization of `BETA-REQ-0064`, the project owner explicitly confirmed that configurable Weekly/Monthly reports must evaluate the applicable Contract Product Line cohort against its configured SLA tiers, expose the actual cohort compliance against each required percentage/duration, and preserve the report-time policy/result evidence. The clarification does not hard-code a terminal endpoint such as `Closed`; exact elapsed-duration endpoint semantics remain governed by the SLA/Temporal contracts.

### CP-004 owner clarification — approved spare substitutes

During normalization of `BETA-REQ-0096`, the project owner explicitly confirmed that exact BOM/Part Number equality is not required for a valid replacement or return relationship when a substitute is approved. When the faulty Device Part Unit, its Spare Need, and the submitted Spare Request consistently identify the original BOM but the provider fulfills the accepted RMA with a different actual BOM, SOMA may preserve that mismatch as provider-approved substitute evidence. The operator may also explicitly approve a different-BOM substitute after a material warning. Neither path rewrites the original requested BOM or the substitute physical unit's actual BOM, and substitute approval does not bypass other identity, allocation, open-RMA, installation, condition, or contradictory-return prerequisites.

The clarification is owned by `BETA-REQ-0096` and is propagated only as explicit supporting authority where later Fault Tag relationship or replacement clauses depend on it.

### CP-005 owner clarification — post-terminal Device Reference regularization

During normalization of `BETA-REQ-0110`, the project owner explicitly confirmed that typos and provisional operational references must remain correctable: a provisional or temporary Device Reference may be reviewably resolved or reassigned to an already-existing Network Element from the Infrastructure workspace even after every related Service Request reaches a terminal state. Ticket closure does not freeze Infrastructure regularization. The Device Reference identity, Network Element identity, original imported or ticket-time text, prior resolution evidence, and correction history remain preserved, and the Infrastructure correction neither reopens nor rewrites the terminal Service Request.

This clarification strengthens the already accepted Device Reference authority in `BETA-REQ-0102`; it is propagated into CP-005 only as explicit supporting authority for workbook, workflow-isolation, responsive-action, and editor consequences. Creation/promotion of a genuinely new Network Element remains distinct and retains the accepted three-second deliberate-hold behavior.

## Known design-reconciliation boundary

The preliminary HLD currently contains wording that assigns “Task outcomes” to Inventory. Accepted product authority through CP-005 does **not** support that ownership. Objectives/Task lifecycle owns Task execution, outcome, review, correction, and retry; Inventory consumes reviewed outcomes only to apply Task-to-unit allocation and physical lifecycle consequences. This remains a design-reconciliation item for the later HLD audit and is not silently edited during Phase 0A normalization.

## Final consolidation rule

`docs/BETA_REQUIREMENTS.md` remains the preserved pre-normalization baseline during the pass. After `BETA-REQ-0177` is normalized and the complete two-way audit passes, the accepted normalized obligations may be consolidated into the main catalogue without deleting the preserved source history. The normalization layer remains the authority for clause identity and before/after traceability.
