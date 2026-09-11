# SOMA Beta Normalization CP-003 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0053`–`BETA-REQ-0077`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0053` | Use cases: create manual SR / attach official identity / reconcile Advanced Search; invariant: one surviving SR identity | Tickets + Import/Reconciliation | manual SR creation, identity adoption, exact-source merge guard | known-ID + LSR + later-import + duplicate-ID + no-fuzzy-link scenarios |
| `BETA-REQ-0054` | Use cases: configure inbox / manual select / automatic discover; invariant: discovery is staging-only | Import/Reconciliation + Settings | candidate enumeration, stability checks, chronology selection, staging handoff | manual + newest-file + traversal/link + stale-candidate + no-mutation scenarios |
| `BETA-REQ-0055` | Use case: parse/stage Advanced Search; invariant: complete validation before mutation | Import/Reconciliation | safe parser, header resolver, row validator, duplicate/conflict detector | bad-file + reordered-columns + missing-header + duplicate/conflict scenarios |
| `BETA-REQ-0056` | Invariant: deterministic replay-safe official workbook imports | Import/Reconciliation shared boundary | canonical serialization, SHA-256 fingerprint, replay key, no-op detection | package-rewrite + row-order + replay + newer-identical-content scenarios |
| `BETA-REQ-0057` | Invariant: source reconciliation is nondestructive to SOMA-owned SR history | Tickets + Import/Reconciliation + Historical view | source-disappearance state, terminal projection, protected-field boundary | disappearance + reappearance + terminal + unknown-status + no-purge scenarios |
| `BETA-REQ-0058` | Use case: reconcile customer/contact references during SR import | Import/Reconciliation + Identity & Settings | account-code resolver, candidate matching, minimal-record proposal | unknown + ambiguous + conflicting-code + equal-name scenarios |
| `BETA-REQ-0059` | Security invariant: bounded offline XLSX processing | Import/Reconciliation + Security boundary | filesystem guards, archive limits, parser limits, active-content suppression | zip-bomb + link + external-reference + macro + partial-parse scenarios |
| `BETA-REQ-0060` | Invariant: explicit Advanced Search field authority allowlist | Import/Reconciliation | staging schema, field registry, discarded-field guard | allowlist + reordered + unknown-column nonauthority scenarios |
| `BETA-REQ-0061` | Invariant: versioned source semantics and distinct timezone authorities | Import/Reconciliation + Temporal authority | source profile, timezone parser, vocabulary registry, unknown-value projection | offset + no-offset + filename-TZ + unknown-vocabulary scenarios |
| `BETA-REQ-0062` | Invariant: Product discarded; Current Handler source-owned | Import/Reconciliation + Tickets + Identity & Settings | discarded-field guard, source assignment projection, Contact reconciliation proposal | Product-nonauthority + blank-handler + no-local-override scenarios |
| `BETA-REQ-0063` | Business invariant: future Resolve fields non-operational; suspension source-governed | Tickets + Import/Reconciliation + SLA | suspension state evaluator, cumulative source duration, contradiction review | future-field + active-suspend + blank-after-nonzero scenarios |
| `BETA-REQ-0064` | Business invariant/use cases: manage customer-specific SLA policy / evaluate cohorts / revise policy / report compliance | SLA Policy + Contracts + Overview/Reporting | tier model, template application, Non-fault derivation, revision recalculation, report evidence | template + custom-tier + revision + cancelled-exclusion + weekly/monthly-report scenarios |
| `BETA-REQ-0065` | Business invariant: at most one customer-compatible SR SLA classification | Tickets + SLA Policy + Import/Reconciliation | classification mapping, review, org correction, recalculation | unique-map + ambiguity + cross-customer + reclass + snapshot-immutability scenarios |
| `BETA-REQ-0066` | Invariant: field-level current projection + compact source deltas | Tickets + Import/Reconciliation + Audit/History | field observation selection, delta persistence, history projection | mixed-current + unchanged-import + summary-revision + terminal-history scenarios |
| `BETA-REQ-0067` | Use cases: generate communication / resolve recipient / inspect historical recipient | Identity & Settings + Offline Communications + Inventory | channel model, validator, alternate recipient, artifact snapshot | missing-address + alternate-contact + retry + historical-address scenarios |
| `BETA-REQ-0068` | Use cases: configure daily check / catch-up / Check now | Application shell + Settings + Import/Reconciliation | scheduler, boundary persistence, catch-up, fingerprint handoff | default-time + timezone + multi-day-miss + replay scenarios |
| `BETA-REQ-0069` | Business invariant: terminal lifecycle suppresses live alerting without erasing cohort evidence | Tickets + SLA + Overview/Needs Attention | terminal projection, notification dedupe, reversal warning | terminal-suppression + cohort + restart-throttle + reversal scenarios |
| `BETA-REQ-0070` | UI/business invariant: time-related warning semantics remain distinct | Tickets + SLA + Overview/Needs Attention | warning-state model, threshold evaluator, accessibility presentation | suspension-threshold + cohort-vs-individual + grayscale scenarios |
| `BETA-REQ-0071` | Invariant/use cases: immutable reproducible report snapshot / generate Daily Weekly Monthly reports | Overview & Reporting + SLA Policy + Audit/History | consistent-read snapshot, membership, artifact verification, immutable evidence | concurrent-change + policy revision + artifact-failure + no-cleanup scenarios |
| `BETA-REQ-0072` | Structural invariant: operational history survives presentation/report/source/age transitions | Cross-domain lifecycle + Audit/History + Foundation Runtime | retention authority matrix, historical projections, deletion eligibility | report + terminal + disappearance + housekeeping-isolation scenarios |
| `BETA-REQ-0073` | Structural invariant: protected independent Beta migration lineage | Foundation Runtime + Persistence | migration manifest, checksum verification, atomic apply, recovery compatibility | candidate-edit + accepted-tamper + atomic-failure + Alpha-db rejection scenarios |
| `BETA-REQ-0074` | Business invariant/use cases: exact import-impact review / confirm high-risk source population | Import/Reconciliation + all official source adapters | impact classifier, authoritative scope, confirmation binding, safe-auto-accept registry | partial-export + empty-population + high-risk-exclusion + anomaly scenarios |
| `BETA-REQ-0075` | Business/structural invariant: canonical SR identity survives incomplete source coverage | Tickets + Import/Reconciliation + SLA + Reporting | incomplete state, field usability, Report Date guard, point-of-use validation | identity-only + missing-date + later-enrichment + incomplete-report scenarios |
| `BETA-REQ-0076` | Structural invariant/use cases: one continuous SR identity / review terminal reversal | Tickets + Import/Reconciliation + SLA + Reporting | identity guard, reversal proposal, consequence preview, trust language | terminal-update + reappearance + accept/reject + unsigned-workbook scenarios |
| `BETA-REQ-0077` | Structural invariant: presentation aging and technical housekeeping never imply retention authority | Historical view + Settings + Foundation Runtime + Communications | presentation-window evaluator, retention authority boundary, housekeeping policies | no-clock + historical-transition + settings-absence + housekeeping-isolation scenarios |

## Two-way coverage audit

### Forward check — source requirement → normalized authority

Every material assertion in `BETA-REQ-0053`–`BETA-REQ-0077` was checked against its accepted governing obligation and stable clauses. Dense import, source-history, SLA, reporting, retention, migration-lineage, warning, scheduling, incomplete-record, and terminal-reversal mechanics were decomposed rather than discarded.

Specific reconciliation notes:

- `BETA-REQ-0060` was checked against the exact source prohibition list. Discarded Advanced Search columns are explicitly prevented from influencing **identity, relationships, SLA, Infrastructure, Inventory, and UI behavior**; no substitute categories were used.
- `BETA-REQ-0064` includes the project-owner clarification that configurable Weekly/Monthly reports evaluate Contract Product Line SLA cohorts and expose actual compliance against every configured tier. Those report clauses are recorded as explicit normalization-time owner authority rather than inferred design behavior.
- `BETA-REQ-0074` preserves the boundary that safe auto-accept may only cover accepted low-risk classes and may never bypass the enumerated high-risk classes.
- `BETA-REQ-0076` keeps logical fingerprinting and structural validation separate from cryptographic publisher-authenticity claims.

**Result: 25/25 PASS.**

### Reverse check — clause → product authority

Every CP-003 clause records one owning immutable `BETA-REQ-####`. Where a clause needs additional approved authority or a technical design-resolution boundary, that support is explicit in `CP003_CLAUSE_AUTHORITY.md`.

- Owner alone sufficient: **567**
- Explicit additional supporting authority/design boundary: **99**
- Missing clause owners: **0**
- Unexplained normative clauses: **0**

**Result: 666/666 PASS.**

### Terminology, ownership, and cross-contract check

- Service Request identity remains continuous across manual creation, official-ID adoption, terminal state, source disappearance, reappearance, and reviewed terminal reversal.
- Advanced Search `Product` remains discarded and cannot become Contract/Product Line/SLA/Infrastructure/Inventory authority.
- `Current Handler` remains source-owned current assignment; SOMA-owned local operational context remains in relationships, Tasks, Working Notes, and audit.
- Source-family timezone, fixed ordinary/SLA operational timezone, and Objective scheduling timezone remain distinct authorities.
- Contract Product Line remains customer-specific and distinct from the reusable Product Line.
- SLA policy remains owned by the customer-specific Contract Product Line; percentage tiers are cohort rules rather than per-ticket pass/fail labels.
- Weekly/Monthly reporting evaluates configured cohort tiers and completed report snapshots remain immutable evidence.
- Cancelled SRs remain excluded from SLA cohorts while Resolved/Closed SRs may remain eligible according to cohort rules.
- Historical view remains a presentation state over surviving operational records, not a retention/purge transition.
- Technical housekeeping remains separate from authoritative operational-history retention.
- Migration lineage remains independent from Alpha and accepted migrations are corrected only by forward migration.
- Import staging/review remains nondestructive and source disappearance does not authorize deletion.
- XLSX parsing remains offline, bounded, and non-executing.
- Contact communication channels remain optional until a communication-dependent action actually requires one.

**Result: PASS.**

### Cross-check against CP-001 and CP-002

CP-003 was cross-checked against all previously accepted normalized authority through `BETA-REQ-0052`.

- No CP-003 clause renumbers, weakens, or reassigns an existing CP-001/CP-002 clause.
- CP-003 preserves CP-001 identity, history, temporal, persistence, and lineage boundaries.
- CP-003 preserves CP-002 Contact identity/lifecycle, authentication/encryption separation, SR↔RFC, WFM/Task/Objective ownership, Device continuity, Task outcome authority, and Working Note history.
- `BETA-REQ-0060` was corrected during checkpoint reconciliation so its discarded-field clauses match the exact source categories rather than broader substitute wording.
- The known preliminary HLD wording defect assigning “Task outcomes” to Inventory remains a **design-reconciliation issue**, not a product-authority contradiction: accepted normalized authority continues to place Task execution/outcome/review facts with Objectives/Task lifecycle while Inventory consumes governed effects.

**Result: PASS.**

### Normalization anomaly check

No requirement in CP-003 required a new `BETA-REQ-####`, suffix ID, or silent split. No unresolved product contradiction was discovered.

**Result: PASS.**

### Commit-isolation check

The intended checkpoint commit changes only the normalization index plus the four CP-003 normalization artefacts:

- `docs/REQUIREMENT_NORMALIZATION.md`
- `docs/normalization/CP003_CATALOGUE.md`
- `docs/normalization/CP003_CLAUSES.md`
- `docs/normalization/CP003_CLAUSE_AUTHORITY.md`
- `docs/normalization/CP003_TRACEABILITY.md`

No implementation, HLD, LLD, baseline-requirement, or unrelated file is part of CP-003.

**Result: PASS.**

## Conclusion

CP-003 introduces no requirement renumbering, no silent deletion of approved behavior, and no design-added product authority. It extends accepted normalization coverage through `BETA-REQ-0077`.

**Overall CP-003: unconditional PASS.**
