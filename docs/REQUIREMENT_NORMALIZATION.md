# SOMA Beta Requirement Normalization

Status: **Complete — 177/177 accepted; final two-way audit passed; CP-006 clause-ID amendment and CP-007 final checkpoint applied**  
Authority: project-owner-approved normalization decisions.  
Source baseline: `docs/BETA_REQUIREMENTS.md` preserves the pre-normalization approved wording and immutable `BETA-REQ-####` identities.

## Purpose

This layer makes the approved Beta catalogue consistently atomic, readable, traceable, and testable without discarding the pre-normalization product record.

For every reviewed requirement:

- the `BETA-REQ-####` identity remains immutable;
- **Replace** means the normalized governing obligation in this layer supersedes the earlier wording while all approved detail survives in stable clauses;
- **Retain** means the earlier wording remains the governing obligation because it was already atomic;
- clause IDs are stable normative references and must continue to point back to approved Beta authority;
- every clause records one owning `BETA-REQ-####`; supporting authority is explicit where required and never transfers ownership;
- genuinely new product behavior must be explicitly approved rather than introduced by design;
- every requirement must eventually map to a business use case or structural invariant, HLD ownership, LLD destination, and acceptance evidence.

## Normalization doctrine

1. No `BETA-REQ-####` renumbering or identity reuse.
2. One governing obligation per requirement.
3. Detailed lifecycle, cardinality, exception, correction, transaction, UI-state, and acceptance mechanics belong in stable normative clauses.
4. Early vague requirements are strengthened only from already approved product authority or explicit owner clarification.
5. Terminology follows the accepted glossary and later approved product decisions.
6. Classification uses one primary category with optional secondary categories. The first listed classification is primary; later semicolon-separated classifications are secondary.
7. Forward coverage: every material assertion in the source requirement must survive in its governing obligation or linked clauses.
8. Reverse coverage: every normative clause must record its owning approved requirement and any additional approved supporting authority needed to establish the rule.
9. Supporting authority strengthens provenance only; it does not transfer ownership or authorize new product behavior.
10. Design may choose implementation mechanics but may not weaken, replace, or silently invent product behavior.
11. A compound requirement that cannot be normalized under one coherent obligation is flagged to the project owner rather than split silently.
12. Each checkpoint audit cross-checks the new range against all prior accepted checkpoints for semantic conflict, duplicated authority, terminology drift, ownership drift, weakened invariants, and globally duplicated clause IDs.
13. Each checkpoint commit is isolated to normalization artefacts and the normalization index unless a separately recorded normalization amendment is explicitly included.

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
| CP-004 | `BETA-REQ-0078`–`0102` | 25 | 25 | 0 | 1383 | Two-pass preservation PASS; reverse-authority PASS; CP-001–CP-003 cross-check PASS; commit-isolation PASS |
| CP-005 | `BETA-REQ-0103`–`0127` | 25 | 25 | 0 | 2669 | Two-pass preservation PASS; reverse-authority PASS; CP-001–CP-004 cross-check PASS; commit-isolation PASS |
| CP-006 | `BETA-REQ-0128`–`0152` | 25 | 25 | 0 | 3444 | Two-pass preservation PASS; reverse-authority PASS; CP-001–CP-005 semantic cross-check PASS; clause-ID prefix corrected by final amendment A1 |
| CP-007 | `BETA-REQ-0153`–`0177` | 25 | 25 | 0 | 2904 | Two-pass preservation PASS; reverse-authority PASS; CP-001–CP-006 cross-check PASS after CP-006 clause-ID amendment; global clause-ID PASS; classification-vocabulary PASS |

Cumulative accepted normalization: **177 / 177 requirements reviewed; 176 Replace; 1 Retain; 11524 stable clauses.**

## Checkpoint artefacts

CP-001 through CP-006 retain their accepted catalogue, clauses, clause-authority, and traceability artefacts under `docs/normalization/`.

CP-006 additionally has:
- [`normalization/CP006_CLAUSE_ID_AMENDMENT.md`](normalization/CP006_CLAUSE_ID_AMENDMENT.md) — canonical prefix correction for `BETA-REQ-0152`: legacy CP-006 `RFC-HIER-001..124` becomes `RFC-FOREST-001..124` without semantic, owner, order, support, or count change.

CP-007 artefacts:
- [`normalization/CP007_CATALOGUE.md`](normalization/CP007_CATALOGUE.md) — accepted governing obligations and approved-vocabulary classifications for `BETA-REQ-0153`–`0177`.
- [`normalization/CP007_CLAUSES.md`](normalization/CP007_CLAUSES.md) — normative clause manifest for all 2904 clauses.
- [`normalization/CP007_CLAUSES_0153_0161.md`](normalization/CP007_CLAUSES_0153_0161.md) — 1058 normative clauses for `0153`–`0161`.
- [`normalization/CP007_CLAUSES_0162_0169.md`](normalization/CP007_CLAUSES_0162_0169.md) — 894 normative clauses for `0162`–`0169`.
- [`normalization/CP007_CLAUSES_0170_0177.md`](normalization/CP007_CLAUSES_0170_0177.md) — 952 normative clauses for `0170`–`0177`.
- [`normalization/CP007_CLAUSE_AUTHORITY.md`](normalization/CP007_CLAUSE_AUTHORITY.md) — one-owner/supporting-authority evidence for all 2904 clauses using globally unambiguous prefixes.
- [`normalization/CP007_TRACEABILITY.md`](normalization/CP007_TRACEABILITY.md) — final two-pass audit, design seeds, CP-001–CP-006 cross-check, clause-ID collision correction evidence, classification-vocabulary audit, technical-design boundaries, and cumulative 177-requirement audit.

The three CP-007 clause shards are a physical-storage/readability split only. Their clause IDs and text are normative exactly as if stored in one file; `CP007_CLAUSES.md` is their authoritative manifest.

## Amendment log

### CP-001-A1 — clause authority evidence and classification syntax

Independent review accepted the CP-001 product content but identified that the original reverse-authority PASS was not yet evidenced at clause granularity. Amendment A1 changed no governing obligation or clause rule; it recorded clause ownership/supporting authority and clarified compact classification syntax.

### CP-003 owner clarification — configurable SLA cohort reports

During normalization of `BETA-REQ-0064`, the project owner confirmed that configurable Weekly/Monthly reports evaluate the applicable Contract Product Line cohort against configured SLA tiers, expose actual cohort compliance against each required percentage/duration, and preserve report-time policy/result evidence. Exact elapsed endpoint semantics remained separately governed and are finalized by `BETA-REQ-0174`.

### CP-004 owner clarification — approved spare substitutes

During normalization of `BETA-REQ-0096`, the project owner confirmed that exact BOM/Part Number equality is not required for a valid replacement or return relationship when an approved substitute is used. Original requested BOM and actual substitute BOM remain distinct and preserved; substitute approval does not bypass other identity, allocation, RMA, installation, condition, or return prerequisites.

### CP-005 owner clarification — post-terminal Device Reference regularization

During normalization of `BETA-REQ-0110`, the project owner confirmed that a provisional or temporary Device Reference may be reviewably resolved or reassigned to an already-existing Network Element even after related Service Requests become terminal. The correction preserves identities, original text, prior resolution evidence and history, never reopens the SR, and remains distinct from creation/promotion of a genuinely new Network Element, which retains the accepted three-second deliberate hold.

### CP-006-A1 — global clause-ID collision correction

The final global audit found that CP-006 reused `RFC-HIER` for `BETA-REQ-0152`, colliding with canonical CP-002 `RFC-HIER-001..009` owned by `BETA-REQ-0040`. Product content and owner mapping were correct; only the later prefix reuse was invalid.

The canonical CP-006 `0152` range is therefore `RFC-FOREST-001..124`. `CP006_CLAUSE_ID_AMENDMENT.md` is the authoritative overlay; as-landed CP-006 artefacts remain preserved for historical comparison. Clause text, order, owner, support, count and cumulative totals do not change.

The same final audit prevented two equivalent collisions before CP-007 persistence: proposed `OBJ-GROUP` for `0157` became `OBJ-TEMP-GROUP`, preserving CP-002 `OBJ-GROUP-*` ownership by `0048`; proposed `WFM-ATTEMPT` for `0170` became `WFM-LINEAGE`, preserving CP-002 `WFM-ATTEMPT-*` ownership by `0042`.

## Known design-reconciliation boundary

The preliminary HLD contains wording assigning “Task outcomes” to Inventory. Accepted product authority through the completed normalization does **not** support that ownership. Objectives/Task lifecycle owns Task execution, outcome, review, correction, and retry; Inventory consumes reviewed outcomes only to apply Task-to-unit allocation and physical lifecycle consequences. `BETA-REQ-0128`, `0162`, `0166`, and `0167` reinforce this boundary. It remains a design-reconciliation item for the later HLD audit and was not silently edited during normalization.

## Preserved open technical-design items

- `O-001` report snapshot persistence/on-demand mechanics.
- `O-003` exact Objective/Task outcome transition/correction reason model beyond approved outcomes.
- `O-004` exact PST/OST/MSG parser library/subset/adapters.
- `O-005` exact encryption/KDF/recovery/rotation/backup/export mechanics.
- `O-006` exact supported Windows editions/builds/browser/runtime/packaging matrix.
- `O-007` exact safe auto-accept field/change classes.
- `O-010` exact tray/background lifecycle.

## Final consolidation rule

`docs/BETA_REQUIREMENTS.md` remains the preserved pre-normalization baseline. The normalized governing obligations and stable clauses in this layer are now complete for all `BETA-REQ-0001`–`0177` and may be consolidated into downstream product/design catalogues without deleting source history. The normalization layer remains the authority for clause identity and before/after traceability, including recorded amendments.
