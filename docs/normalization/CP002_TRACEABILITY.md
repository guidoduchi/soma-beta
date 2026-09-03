# SOMA Beta Normalization CP-002 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0028`–`BETA-REQ-0052`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0028` | Structural invariant: Contact identity independence; use cases: reconcile/select Contact | Identity & Settings + Import/Reconciliation | Contact identity, scoped matching, ambiguity resolution | Duplicate-name/email-scope + ambiguous-match scenarios |
| `BETA-REQ-0029` | Structural invariant: Contact affiliation history; use cases: affiliate/reassign/reconcile Contact | Identity & Settings + Tickets + Import/Reconciliation | Affiliation history, mismatch warning, reviewed correction | Affiliation-change + mismatch + historical-context scenarios |
| `BETA-REQ-0030` | Business rule: deterministic candidate reconciliation | Import/Reconciliation + Identity & Settings | Normalization function, scope keys, ambiguity state | Unicode normalization + ambiguity golden vectors |
| `BETA-REQ-0031` | Use-case family: create/archive/reactivate Contact; structural invariant: affiliation-aware lifecycle | Identity & Settings + cross-domain dependency boundary | Contact lifecycle, dependency checks, reactivation | Archive-block + reactivation + historical-visibility scenarios |
| `BETA-REQ-0032` | Use cases: select requester / archive Contact / inspect terminal Spare Request | Inventory + Identity & Settings | Requester relation, eligibility, archival dependency, historical projection | Requester-selection + archive-block + terminal-history scenarios |
| `BETA-REQ-0033` | Use cases: correct Site ownership / archive Site; structural invariant: ownership stability | Infrastructure + cross-domain dependency boundary | Ownership correction eligibility, dependency validation, archival transaction | Pre-history correction + dependency-block + preservation scenarios |
| `BETA-REQ-0034` | Use cases: archive/reactivate Dispatch Location / resolve logistics dependency | Identity & Settings + Infrastructure + Inventory | Archival eligibility, active selectors, Site coupling, reactivation | Archived-selector + Site/logistics-block + reactivation scenarios |
| `BETA-REQ-0035` | Structural/security invariant: authentication-encryption separation; use cases: setup/login/auto-login | Authentication + Security + Windows trust boundary | Verifier, credential lifecycle, Windows-protected auto-login | Login/verifier + password-change + auto-login scenarios |
| `BETA-REQ-0036` | Security invariant: authentication-independent live-data encryption | Persistence + Security + Windows trust boundary | AEAD, DEK generation/protection, key lifecycle | Encryption-at-rest + key-independence + password-change scenarios |
| `BETA-REQ-0037` | Security invariant/use-case family: create/export/restore portable backup set | Backup & Recovery + Persistence + Security | Backup envelope, key/recovery lifecycle, detached verification artifacts, atomic restore | Portability + wrong-secret/tamper + missing-sidecar + non-mutating-failure scenarios |
| `BETA-REQ-0038` | Structural invariant: domain-owned relationships with SR-centered correlation | Tickets + Objectives + Inventory + Infrastructure boundaries | Cardinality/FK model, relationship derivation, consistency validation | Standalone-existence + mandatory-owner + derived-context scenarios |
| `BETA-REQ-0039` | Structural invariant: master-boundary SR↔RFC relationship | Tickets relationship boundary | Master-only join model, inherited-context query, workbench projection | Many-to-many + subordinate-inheritance + no-direct-link scenarios |
| `BETA-REQ-0040` | Structural invariant: two-level acyclic RFC forest; use cases: create/reparent subordinate | Tickets hierarchy boundary | Hierarchy constraints, cycle detection, reparenting transaction | Cardinality + depth + cycle + history-preservation scenarios |
| `BETA-REQ-0041` | Structural invariant: singular WFM RFC ownership and Objective membership | Tickets + Objectives relationship boundary | WFM owner relation, nullable Objective membership, regroup transaction | Mandatory-owner + unscheduled + move-without-duplication scenarios |
| `BETA-REQ-0042` | Structural invariant: WFM attempt independence and activity-lineage conflict | Tickets + Objectives + Import/Reconciliation | Attempt identity, lineage/conflict state, grouping guardrails | Distinct-attempt + conflict-review + no-overlap-workaround scenarios |
| `BETA-REQ-0043` | Structural invariant: first-class nonempty Objective; use case: create Objective | Objectives domain | Objective aggregate, persistence gate, draft boundary | Standalone Objective + empty-draft + nonempty-persistence scenarios |
| `BETA-REQ-0044` | Structural invariant/use case: Task-mediated Objective SR context and provenance | Objectives consumer + Tickets/Task fact authority | Derived SR query, RFC path resolution, provenance projection | Local/WFM derivation + mutation + provenance scenarios |
| `BETA-REQ-0045` | Business rule: optional Task-mediated SR work participation | Tickets + Objectives scheduling boundary | Derived Objective context, overlap/grouping evaluator | Zero-work + multi-Objective + overlap-grouping scenarios |
| `BETA-REQ-0046` | Structural invariant: immutable Task-attempt retry lineage; use cases: retry Local/WFM Task | Tasks lifecycle + Objectives derived-context boundary | Predecessor/successor model, cloning review, scheduling handoff | Identity + chain cardinality + regrouping + multi-Objective ancestry scenarios |
| `BETA-REQ-0047` | Structural invariant: valid Objective interval and timeframe-gated Task membership | Objectives + cross-cutting Temporal Authority | Temporal value objects, interval validation, membership eligibility | Positive-duration + arbitrary-minute + no-rounding + unscheduled scenarios |
| `BETA-REQ-0048` | Use cases: Task-driven Objective grouping / RFC collision review | Objectives grouping + Tickets/RFC context consumer | Eligibility evaluator, overlap engine, RFC context resolver, warnings | Local/WFM parity + hierarchy-context + nonblocking-warning scenarios |
| `BETA-REQ-0049` | Structural invariant: provisional-to-regularized Device continuity; use cases: attach/promote Device | Tickets/Tasks fact authority + Objectives consumer + Infrastructure | Device Reference resolution, promotion transaction, relationship preservation | Provisional-use + promotion-continuity + derived-Objective scenarios |
| `BETA-REQ-0050` | Use cases: review Objective/Task outcome / correct outcome / initiate retry | Objectives owns execution/review facts; Inventory consumes governed effects | Review queue, reviewed_at semantics, correction history, retry handoff | Review-timestamp + mixed-outcome + no-spare-inference + correction-vs-retry scenarios |
| `BETA-REQ-0051` | Use-case family: create/schedule/regroup/execute/review/cancel/archive Objective; retry Task | Objectives workspace + Task lifecycle + cross-domain projections | Objective commands, guards, Task membership editor, derived-context UI | Complete lifecycle + relationship-authority + history-protection scenarios |
| `BETA-REQ-0052` | Use cases: add/edit/delete/inspect Working Note; invariant: SOMA-owned note history | Tickets + Audit/History cross-cutting boundary | Working Note entity, version/audit model, active-view deletion, import guards | Multi-note + immutable-creation + edit/delete-history + import-preservation scenarios |

## Two-way coverage audit

### Forward check — source requirement → normalized authority

Every material assertion in `BETA-REQ-0028`–`BETA-REQ-0052` was checked against its accepted governing obligation and stable clauses. Dense relationship, lifecycle, security, scheduling, review, retry, and UI mechanics were decomposed rather than discarded.

`BETA-REQ-0037` also includes the explicit project-owner normalization amendment requiring a complete portable-backup set with detached MDA-style digest/manifest and PKCS#7/CMS-style authenticity artifacts, or governed equivalents.

**Result: 25/25 PASS.**

### Reverse check — clause → product authority

Every CP-002 clause records one owning immutable `BETA-REQ-####`. Where a clause needs additional approved authority, that support is explicit in `CP002_CLAUSE_AUTHORITY.md`.

- Owner alone sufficient: **152**
- Explicit additional supporting authority: **123**
- Missing clause owners: **0**
- Unexplained normative clauses: **0**

During this audit, the exact digest algorithm for the `BETA-REQ-0037` detached manifest was deliberately left as a Security LLD decision rather than promoted into new product authority. The approved product requirement is the detached integrity/authenticity artifact set and its validation; algorithm selection remains under technical design item `O-005`.

**Result: 275/275 PASS.**

### Terminology and ownership check

- Service Request remains pivotal operational context without becoming a universal aggregate parent.
- Direct SR↔RFC authority terminates at master RFCs; subordinate context remains inherited.
- WFM identity, RFC ownership, Objective membership, attempt lineage, and retry identity remain distinct concerns.
- Objective owns Objective lifecycle state; Service Request, RFC, Device, and Inventory context remains Task- or domain-derived.
- Objective review acceptance remains separate from execution chronology.
- Objective success does not create Inventory-use facts.
- Device References remain usable before Infrastructure regularization and preserve operational continuity when promoted.
- Contact identity remains independent from descriptive matching data and Customer Organization affiliation.
- Dispatch Location remains Customer-Organization-neutral and distinct from Site identity and logistics operation history.
- Authentication credentials, live-data encryption keys, and portable-backup protection remain separate security boundaries.
- Working Notes remain SOMA-owned operational history and are not source-owned import fields.

**Result: PASS.**

### Normalization anomaly check

No requirement in this checkpoint required a new `BETA-REQ-####`, suffix ID, or silent split. No unresolved product contradiction was discovered.

**Result: PASS.**

## Conclusion

CP-002 introduces no requirement renumbering, no silent deletion of approved behavior, and no design-added product authority. The checkpoint extends accepted normalization coverage through `BETA-REQ-0052`.
