# SOMA Beta Phase 1A — Business Use-Case Method

Status: **Accepted working method — amended by P1A-002 controlled catalogue reconstruction**  
Phase authority: `docs/ROADMAP.md` Phase 1A and the accepted/frozen Phase-0 decision baseline recorded in `docs/reconciliation/PHASE0_ACCEPTANCE.md`; current closure-certification status is governed by `docs/reconciliation/RC006_A2_SECTION_DESTINATION_ASSURANCE.md` and `docs/reconciliation/RECONCILIATION_INDEX.md`.

## 1. Purpose

Phase 1A translates accepted product authority into the complete set of meaningful human and system goals SOMA Beta 1.0 must support. It does not redesign product policy and does not select implementation technology.

A use case is a **meaningful actor goal or system-triggered goal** with observable preconditions, flow, outcomes, preserved evidence, and failure/correction behavior. It is not a button, screen, field, database command, clause, implementation task, or test case.

The initial Phase-1A catalogue may contain **Goal Seeds** used for decomposition and coverage discovery. A Goal Seed is not an acceptance-ready use-case specification and shall not be presented for project-owner approval until it passes the Specification Gate in §4.1.

## 2. Authority order

Use-case work consumes, in order:

1. accepted normalized `BETA-REQ-####` governing obligations and canonical stable clauses;
2. accepted product-owner decisions;
3. reconciled focused product contracts;
4. Product Contract and Glossary synthesis;
5. Phase-0 Architecture/Roadmap only as derived boundary/delivery guidance.

If a use-case draft exposes a genuine product contradiction or missing policy, Phase 1A does not invent the answer. The issue returns through controlled Phase-0 reopening/gap handling before the use case is accepted.

## 3. Stable identifiers

- Business use cases use `UC-###`, beginning with `UC-001`.
- An **Accepted** `UC-*` identity is stable and is never reused for a different goal.
- A pre-acceptance Goal Seed or Draft may be split, merged, narrowed, or retired during controlled catalogue reconstruction. Its disposition remains recorded so traceability is never silently lost.
- Every such transformation records the original identity, retained principal goal, successor/derived IDs, `derived-from` relationship, governing authority, reason, and whether observable behavior changed. If no unambiguous principal goal survives, the original seed is retired rather than misleadingly repurposed.
- Extracted/new goals receive new identifiers from the next unused `UC-###`; accepted IDs are never renumbered to close gaps.
- Phase-1A governance/checkpoint records use `P1A-*`; `CP-*` and `RC-*` remain reserved for their completed Phase-0 lineages.
- Structural invariants are recorded in traceability as `SI` classifications rather than fabricated use cases.

## 4. Required use-case fields

Every **Proposed** or **Accepted** use case records:

- stable ID and concise goal;
- primary actor (`Local Administrator` or `System`), with supporting actors/sources where relevant;
- trigger;
- preconditions;
- main success flow;
- alternate, warning, conflict, stale, correction, cancellation, retry, and failure flows that materially apply;
- postconditions / accepted-state effects;
- preserved evidence/history;
- owning domain and affected workspace(s);
- governing `BETA-REQ` references;
- governing canonical clause-family/subrange references;
- related focused contracts with exact normative section targets where practical;
- downstream HLD questions/boundaries exposed by the flow, without resolving LLD mechanics; and
- acceptance scenarios stated behaviorally, without prescribing tables, classes, APIs, frameworks, libraries, or algorithms.

A field may state `Not applicable` only when the reason is evident from accepted authority.

### 4.1 Specification Gate — mandatory before owner review

A Goal Seed/Draft may move to `Proposed` only when all of the following pass:

1. **Goal atomicity** — one meaningful actor/system goal; split if actor objective, authority boundary, accepted end state, or material recovery contract differs.
2. **Authority validity** — every cited `BETA-REQ` exists and is semantically relevant to the stated behavior.
3. **Canonical-owner validity** — every cited clause family/subrange belongs to the cited requirement owner in the accepted normalization authority.
4. **Normative-destination validity** — the behavior resolves to the correct owning focused contract/section; cross-domain supporting references do not transfer primary ownership.
5. **No authority padding** — broad requirement ranges are not cited merely because they are nearby or cross-cutting.
6. **Full representation** — every field in §4 is present.
7. **Recovery completeness** — materially applicable warning/conflict/stale/correction/cancellation/retry/failure paths are represented.
8. **Evidence completeness** — current-state effects and preserved evidence/history are explicit and not conflated.
9. **No duplicate goal ownership** — overlapping UCs either describe genuinely distinct goals or are merged/narrowed with recorded disposition.
10. **No premature design** — unresolved HLD/LLD mechanics remain explicit boundaries rather than being silently selected.

Failure of this gate returns the item to `Rework`; it is not presented to the project owner for semantic acceptance.

### 4.2 Accepted-specification expansion gate

An Accepted UC may be expanded in repository form without reopening acceptance only when every added statement is mechanically traceable to already accepted authority and introduces no new observable product behavior.

The expansion record must prove that it adds no new actor decision, outcome, warning, exception, permission boundary, state transition, recovery obligation, or other observable behavior. If any such behavior is introduced or existing meaning becomes narrower/broader, the affected portion returns to project-owner review. Labeling an edit “non-semantic” is not evidence by itself.

## 5. Scope and granularity rules

Create one use case per meaningful goal. Split when the actor objective, authority boundary, accepted end state, or materially different failure/recovery contract changes. Keep one use case when multiple UI actions are merely steps toward the same goal.

Examples of **not** separate use cases by themselves: clicking Save, opening a tab, selecting an autocomplete row, individual validation messages, one SQL transaction, or one lifecycle command that exists only as a step inside a broader operator goal.

System-triggered behavior is first-class. Scheduled import checks, background Communications processing, grace expiry/revalidation, notification evaluation, backup/runtime lifecycle behavior, and similar autonomous goals receive explicit system use cases where they produce meaningful observable product behavior.

Cross-cutting UI obligations such as pointer/keyboard equivalence, focus restoration, hovered-pane scroll ownership, responsive reachability, reduced motion, non-color meaning, and confirmation-tier mechanics are normally acceptance obligations/SI applied to relevant UCs. They should be maintained in shared named acceptance profiles or SI records and explicitly referenced by each applicable UC, avoiding copied text that can drift. They become a standalone UC only when the operator/system goal itself is independently meaningful.

## 6. Structural invariants

A normalized requirement may be classified wholly or partly as a Structural Invariant when it constrains the product but does not independently describe an actor/system goal—for example identity syntax, cardinality, persistence authority, or a platform boundary.

Structural-invariant classification requires:

1. exact `BETA-REQ` and applicable canonical clause-family coverage;
2. rationale for why no independent goal is created;
3. at least one downstream HLD/LLD/test destination class; and
4. confirmation that any behavioral clauses inside the same requirement are still exercised by use cases.

A dense requirement may therefore map to both `UC-*` and `SI`; classification at requirement-header level may not hide uncovered behavioral clause families.

## 7. Traceability doctrine

`USE_CASE_TRACEABILITY.md` is the Phase-1A forward coverage ledger. The accepted Phase-0 `RC006_CLAUSE_DESTINATIONS.md` remains the canonical owner-range source; Phase 1A references it rather than duplicating 11,524 clause rows.

For every `BETA-REQ-0001` through `BETA-REQ-0177`, Phase 1A must eventually record:

`BETA-REQ → canonical owner range/subrange → UC(s) and/or SI → coverage result`

For dense requirements, the review must inspect the canonical clause families/range and split coverage notes by sub-range/family when different use cases exercise different behavior.

The final Phase-1A forward invariant is:

- requirements represented: `177 / 177`;
- requirements resolved to UC/SI coverage: `177 / 177`;
- known behavioral clause-family orphans: `0`;
- accepted/proposed use cases lacking product authority: `0`;
- accepted/proposed use cases with invalid owner/family references: `0`; and
- duplicate independently-governing use-case goals: `0`.

The reverse audit is:

`UC normative behavior → accepted BETA-REQ → canonical family/subrange → owning normative destination`.

## 8. Review states

Use cases move through:

`Goal Seed → Draft → Proposed → Accepted`

or

`Goal Seed/Draft/Proposed → Rework → Draft/Proposed`.

A pre-acceptance seed/draft may also be `Split`, `Merged`, `Retired as duplicate`, or `Classified SI`; the disposition and successor/reference must remain recorded.

Acceptance is explicit. A proposed use case does not become product authority and cannot modify Phase-0 authority. If accepted Phase-0 wording must change, controlled reopening occurs separately. Repository expansion of an already Accepted UC must pass §4.2; otherwise the affected behavior returns to owner review.

## 9. Planned Phase-1A waves

1. **P1A-W1 — Foundation & Settings**: first run, Local User Profile, authentication/auto-login, reference setup, runtime/start/stop, backup/recovery-facing goals. Explicit application lock/unlock is excluded unless later authorized through controlled product reopening.
2. **P1A-W2 — Tickets & Source Intake**: SR/RFC/WFM registration/import/review, Contacts/customer context, CPL classification/SLA-facing goals.
3. **P1A-W3 — Objectives & Operational Work**: Local/WFM Tasks, planning, grouping/regrouping, execution/review/correction/retry, RFC cascade.
4. **P1A-W4 — Inventory**: Spare Needs, Stock, Spare Requests, RMA/logistics, Task physical consequences, Fault Tags/warehouse/resend.
5. **P1A-W5 — Infrastructure**: Sites/Dispatch Locations, Cloud Deployments, Device References/Network Elements, placement/components/IP, workbook exchange.
6. **P1A-W6 — Communications**: PST/OST source scopes, processing/matching/review, coverage/backfill/Deep Scan, MSG drafts, terminal unlink/orphan grace.
7. **P1A-W7 — Overview & Cross-domain Operations**: reporting, Needs Attention, history/archive/correction/destructive previews, restoration and cross-workspace navigation.
8. **P1A-W8 — Global Audit**: system-triggered coverage, structural invariants, clause-family orphan audit, reverse-authority audit, duplicate-goal audit, and Phase-1A acceptance gate.

Wave order is for review discipline, not domain ownership transfer. Cross-domain use cases live with the goal's primary owner and reference all affected domains.

## 10. Phase-1A exit gate

Phase 1A may close only when:

- every meaningful Beta 1.0 operator/system goal is represented by an accepted use case;
- every `BETA-REQ` is exercised by accepted `UC-*` use cases or explicitly justified as structural invariant, with dense mixed requirements split as needed;
- every accepted use case traces backward to accepted product authority through canonical family/subrange and owning normative destination;
- every accepted use case passed the Specification Gate;
- warning/conflict/correction/cancellation/retry/failure paths are represented where materially applicable;
- preserved evidence and postconditions are explicit;
- duplicate-goal ownership is zero;
- no unresolved product ambiguity remains;
- HLD questions are identified without prematurely selecting LLD implementation detail; and
- the project owner explicitly accepts Phase 1A before final Phase 1B HLD acceptance work proceeds.

Production code/scaffolding remains prohibited until the complete Beta 1.0 LLD is accepted.