# SOMA Beta Normalization CP-007 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0153`–`BETA-REQ-0177`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0153` | RFC archival/restoration use cases and local-vs-provider lifecycle invariant | RFC Lifecycle + Workbenches | archive command, reviewed branch scope, operation-scoped restore | subordinate/master archive + pre-existing archive + source reappearance + active-evidence review scenarios |
| `BETA-REQ-0154` | SR↔RFC relationship lifecycle independence and historical reconciliation | Tickets Relationships + Audit | master-target link/unlink service, relationship history | terminal-SR late link + no reopen/SLA restart + idempotent link/unlink scenarios |
| `BETA-REQ-0155` | Manual WFM registration/adoption/history | WFM + RFC Lifecycle | registration/adoption service, parent correction, status-history mapper | exact TK+NC + Local fallback + exact adoption + Complete/Plan-Cancel history scenarios |
| `BETA-REQ-0156` | WFM source-plan temporal contract | WFM Import + Temporal | source interval parser, UTC normalization, schedule-conflict proposal | blank pair + half-pair reject + explicit offset + Guayaquil offsetless + retry-new-TK scenarios |
| `BETA-REQ-0157` | Global temporal Objective grouping invariant | Objectives + Scheduling | interval graph/component builder, work-package partitions | transitive overlap + exact touch + bridge consolidation + multi/unresolved-Customer scenarios |
| `BETA-REQ-0158` | Reviewed Objective regrouping | Objectives + Review/Audit | revisioned regroup diff, rejection fingerprint, atomic commit | Planned/In-Progress/terminal + reject-equivalent + changed-input + stale-revalidation scenarios |
| `BETA-REQ-0159` | RFC/WFM header-registry import contract | Tickets Import | versioned header registry, alias resolver, duplicate-semantic detector | required identity + optional missing + unresolved Customer + alias collision scenarios |
| `BETA-REQ-0160` | WFM logical-matrix identity/conflict and scalable preview | Tickets Import + UI | Task-No matrix parser, conflict partition, pagination/virtualization | repeated RFC + exact duplicate + conflicting identity + identityless row + exact totals scenarios |
| `BETA-REQ-0161` | Terminal RFC cascade | RFC/WFM Lifecycle + Objectives + Communications | captured cascade proposal, deliberate hold, atomic mutation, provenance | subordinate/master exact scope + rollback + surviving work + zero-executable + stale evidence scenarios |
| `BETA-REQ-0162` | Objective execution-lock/history-retention invariant | Objectives/Task Lifecycle | executable-set reducer, incomplete-review transition, deletion guard | surviving work + zero executable + clock-only no-lock + no hard-delete scenarios |
| `BETA-REQ-0163` | WFM RFC-derived hierarchy context | RFC/WFM Projection | hierarchy-context resolver | unscheduled context + no WFM hierarchy + reparent projection + history preservation scenarios |
| `BETA-REQ-0164` | Action-scoped Undo and correction boundary | UI Action Framework + domain correction owners | inverse registry, safety revalidator, invalidation explanation | unrelated-later action + related invalidation + warning ack + immutable-evidence no-undo scenarios |
| `BETA-REQ-0165` | RFC Customer reconciliation/hierarchy consistency | RFC + Customer Reconciliation | account-key matcher, proposal review, unresolved partition | account-number precedence + name-only reject + SR/WFM proposal + infra non-authority scenarios |
| `BETA-REQ-0166` | First-class Local Task creation/planning | Task Lifecycle + Objectives | Local Task model, optional relation editor, schedule initializer | name-only + no fake TK + unscheduled + 0..1 Objective + independent plan scenarios |
| `BETA-REQ-0167` | Task plan/execution/outcome state machine | Objectives/Task Lifecycle + Reporting | Task execution state machine, outcome review, aggregate reducer | Objective-start-not-Task-start + cancel-unstarted + effective/recording time + mixed outcome scenarios |
| `BETA-REQ-0168` | Objective identity/ordinal/timezone presentation | Objectives + Settings + Reporting | tracking-ID allocator, ordinal projection, IANA schedule setting | reschedule identity + unscheduled no ordinal + cross-month + tie + Galapagos + frozen label scenarios |
| `BETA-REQ-0169` | Semantic bounds and scalable list/export contract | Validation + UI Platform + Import/Export | bound registry, grapheme/byte validators, cursor/virtualization | no 400/100/500 + no truncation + smallest-safe import overflow + full totals/export scenarios |
| `BETA-REQ-0170` | WFM activity-lineage/competing-attempt review | WFM + Objectives | lineage review model, conflict resolver | same-RFC distinct activity + overlapping competing lineage + retry/cancel/source-error/unresolved scenarios |
| `BETA-REQ-0171` | Historical Objective proposal and operational-count inclusion | Objectives History + Reporting | historical proposal, inclusion classifier, aggregate population disclosure | Complete+plan proposal + no fabricated execution + unassigned history + partial/all exclusion scenarios |
| `BETA-REQ-0172` | Source-plan vs operational-plan reconciliation | WFM Scheduling + Objectives | schedule conflict review, plan lock, source-plan projection | source adopt + manual retain reason + third-plan correction + unresolved + execution/terminal lock scenarios |
| `BETA-REQ-0173` | Product Line/Contract/CPL SLA classification | SLA + Reference Data + Batch Review | classification resolver, batch partitions, audit result | same PL/different Customer SLA + cross-Customer incompatible + stale/unresolved/individual scenarios |
| `BETA-REQ-0174` | Exact SLA elapsed calculation | SLA Engine + Temporal + Reporting | endpoint resolver, cumulative suspension reducer, exact arithmetic | active/terminal endpoint + missing Report Date + regression + fractional/boundary + immutable snapshot scenarios |
| `BETA-REQ-0175` | Canonical SLA monthly cohorts/live states/snapshots | SLA Reporting | monthly cohort key, lower/best bounds, state matrix, snapshot builder | Guayaquil month + Objective TZ isolation + dimension partition + open-month non-final + daily/weekly/range scenarios |
| `BETA-REQ-0176` | Exact-source staged RFC/WFM review | Tickets Import + Review + RFC Lifecycle | staged observation ledger, disposition engine, low-risk auto-accept registry | presence-vs-acceptance + smallest-safe scope + excluded high-risk auto-accept + terminal/cascade separation scenarios |
| `BETA-REQ-0177` | Cross-domain temporal authority | Temporal Platform + Settings + adapters | temporal type model, schedule input conversion, source-profile conversion provenance | date/duration/unknown non-instants + display-vs-reschedule + ambiguous source + elapsed timer + frozen history scenarios |

## Two-pass checkpoint audit

### Pass 1 — source requirement → normalized authority

Every material assertion in `BETA-REQ-0153`–`BETA-REQ-0177` was checked against its accepted governing obligation and stable clause range.

Preservation findings:

- `0153` keeps archival SOMA-local/reversible, branch-exact, non-cascading and source-reconcilable.
- `0154` keeps SR and RFC lifecycle independent and makes relationship correction historical/idempotent.
- `0155`–`0156` preserve exact provider WFM identity, Local Task separation, terminal history, provider source interval semantics, `America/Guayaquil` offsetless conversion and new-TK retry identity.
- `0157`–`0158` preserve global transitive strict-overlap grouping and separately reviewed lifecycle-safe regrouping. Customer/Master context remains explanatory partitioning, never authority to create overlapping Objectives.
- `0159`–`0160` preserve deterministic header/matrix semantics, required identity, explicit unresolved state, identity-scoped conflict, security inspection and measured technical scaling rather than arbitrary business caps.
- `0161`–`0162` preserve deliberate all-or-nothing terminal cascade, independent provider/local provenance, surviving executable work, `Incomplete — Awaiting Review`, lifecycle-derived plan locks and permanent no-hard-delete once accepted history exists.
- `0163` keeps WFM hierarchy context RFC-derived and prohibits a second WFM hierarchy authority.
- `0164` keeps Undo action-scoped/safe and prevents it from erasing immutable evidence.
- `0165` keeps RFC Customer ownership singular, account-number-led, reviewable, hierarchy-consistent and non-blocking for temporal grouping when unresolved.
- `0166`–`0167` keep Local Tasks first-class and Task execution/outcomes independently authoritative from Objectives and Inventory.
- `0168` keeps Objective identity/tracking stable, ordinal derived and timezone selection scoped to Objective/Task scheduling only.
- `0169` removes Alpha's universal 400/100/500 limits without leaving data unbounded; exact limits remain semantic/LLD-owned and overflow never silently truncates.
- `0170` preserves distinct WFM Task identities and narrows the one-WFM restriction to overlapping active attempts of the same reviewed activity lineage.
- `0171` permits historical structure from provider Complete + valid source plan without inventing execution/Inventory facts and separates counting exclusion from deletion/history mutation.
- `0172` keeps provider plan, operational plan, Objective envelope and execution distinct, with explicit conflict choices and history/plan locks.
- `0173` preserves Product Line reuse and customer-specific SLA authority at Contract Product Line, with reviewed per-target classification.
- `0174` preserves exact reproducible SLA duration arithmetic, accepted source suspension only, first effective Resolved/Closed endpoint and immutable reports.
- `0175` fixes canonical SLA cohorts to Report Date month in `America/Guayaquil`, separates individual and cohort state and treats daily/weekly/range outputs as snapshots of monthly contractual cohorts.
- `0176` separates exact source presence, mutation acceptance and downstream consequence; high-risk classes never auto-accept and whole-workbook rejection is exceptional.
- `0177` preserves temporal types, UTC instants, fixed operational/SLA timezone, Objective-only selectable scheduling timezone, source-profile conversion authority, no-guessing ambiguity and immutable historical timezone context.

**Pass-1 result: 25/25 PASS.**

### Pass 2 — clause → approved authority

`CP007_CLAUSE_AUTHORITY.md` records exactly one owner for every CP-007 clause and explicit support/design boundaries without transferring ownership.

- Clauses: **2904**
- Owner ranges: **25**
- Missing owners: **0**
- Overlapping CP-007 owner ranges: **0**
- Unexplained normative clauses: **0**

**Pass-2 result: 2904/2904 PASS.**

## Global stable-clause-ID audit

The final audit found three later prefix reuses of identifiers already assigned in CP-002:

1. CP-006 `BETA-REQ-0152` had reused `RFC-HIER`, already canonical for `BETA-REQ-0040`.
2. Proposed CP-007 `BETA-REQ-0157` used `OBJ-GROUP`, already canonical for `BETA-REQ-0048`.
3. Proposed CP-007 `BETA-REQ-0170` used `WFM-ATTEMPT`, already canonical for `BETA-REQ-0042`.

Resolution is reference-only; no clause wording, order, owner, count or product semantics change:

- `0152`: canonical prefix becomes `RFC-FOREST`; recorded in `CP006_CLAUSE_ID_AMENDMENT.md` while preserving CP-006 as-landed artefacts.
- `0157`: persisted CP-007 prefix is `OBJ-TEMP-GROUP`.
- `0170`: persisted CP-007 prefix is `WFM-LINEAGE`.

After applying these corrections, CP-001–CP-007 clause identifiers are globally unambiguous under the normalization layer's amendment rules.

**Global clause-ID result: PASS after reference-ID correction.**

## Classification-vocabulary audit

All CP-007 catalogue classifications were normalized to the accepted six-term vocabulary only:

- Functional capability
- Business rule
- Structural invariant
- Security/privacy constraint
- UI/UX obligation
- Quality/platform requirement

Descriptive phrases used during interactive review (for example “data-retention/history constraint” or “temporal configuration constraint”) were treated as explanatory prose, not persisted classification values.

**Classification result: PASS.**

## Terminology, ownership and invariant cross-check

- `Objective` remains Maintenance Window; Task remains the scheduling/execution unit.
- Task execution/outcome/review/correction/retry ownership remains with Objectives/Task lifecycle. Inventory only consumes reviewed physical consequences.
- WFM Task identity remains `TK` + 14 digits; genuine retry uses a new Task No.
- RFC hierarchy remains a two-level one-parent forest and is the sole Master/subordinate authority for WFM context.
- Product Line remains reusable; customer-specific SLA authority remains Contract Product Line.
- Customer names remain descriptive; canonical Customer identity and supported external account key govern reconciliation.
- Workbook presence, accepted source mutation and local downstream consequence remain separate authorities.
- Workbook omission does not create lifecycle disappearance.
- Source planning, operational Task planning, Objective envelope and actual execution remain separate.
- Known instants remain canonical UTC whole seconds; unresolved chronology remains unresolved.
- `America/Guayaquil` remains fixed ordinary operational/SLA interpretation; selectable IANA timezone remains scoped to Objective/Task scheduling/calendar presentation.
- Completed report snapshots and accepted historical evidence remain immutable.
- No arbitrary 20-child, 400-character, 100-page-size or 500-row business limit is introduced.
- No terminal ticket state freezes correction of a provisional Device Reference to an already-existing Network Element.

**Result: PASS.**

## Cross-check against CP-001 through CP-006

CP-007 was cross-checked against accepted normalized authority through `BETA-REQ-0152`, including CP-001 amendment A1, CP-004 substitute clarification, CP-005 Device Reference clarification and the final CP-006 clause-ID amendment.

- No requirement identity is renumbered or reused.
- No owning requirement changes.
- No later clause transfers ownership from an earlier requirement.
- The three detected prefix collisions are resolved without semantic change.
- CP-002 keeps original canonical `RFC-HIER-*`, `OBJ-GROUP-*`, and `WFM-ATTEMPT-*` ownership.
- CP-007 uses only globally unambiguous new prefixes.
- Existing open technical-design items remain unresolved design boundaries rather than invented product behavior.

**Prior-checkpoint cross-check: PASS after CP-006 reference-ID amendment.**

## Preserved technical-design boundaries

Normalization does not decide unresolved implementation mechanics:

- `O-001` report snapshot persistence/on-demand mechanics;
- `O-003` exact Objective/Task outcome transition/correction reason model beyond approved outcomes;
- `O-004` exact PST/OST/MSG parser library/subset/adapters;
- `O-005` exact encryption/KDF/recovery/rotation/backup/export mechanics;
- `O-006` exact supported Windows editions/builds/browser/runtime/packaging matrix;
- `O-007` exact safe auto-accept field/change classes;
- `O-010` exact tray/background lifecycle.

## Cumulative audit

Checkpoint counts:

- CP-001: 183
- CP-002: 275
- CP-003: 666
- CP-004: 1383
- CP-005: 2669
- CP-006: 3444
- CP-007: 2904

Cumulative stable clauses: **11524**.

Cumulative requirements: **177 / 177**.

Dispositions: **176 Replace / 1 Retain**.

**Final normalization content audit: PASS.**

Commit-isolation evidence is completed after the final tree is committed and branch comparison is re-run.
