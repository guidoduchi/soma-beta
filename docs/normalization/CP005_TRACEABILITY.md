# SOMA Beta Normalization CP-005 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0103`–`BETA-REQ-0127`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0103` | Invariant/use cases: register Network Element / progressively complete model, serial, placement and Cloud / preserve Notes and credential boundaries | Infrastructure | Network Element aggregate, Site/Rack/Cloud relationships, derived-context resolver | minimum-registration + same-Site placement + optional-model/serial + no-credential-field scenarios |
| `BETA-REQ-0104` | Invariant/use cases: maintain zero-many descriptive IPs / choose at most one primary / preserve no-IP validity | Infrastructure | IP-address relation, primary-address constraint, matching evidence | zero-IP + multi-IP + one-primary + duplicate-value-not-identity + no-topology scenarios |
| `BETA-REQ-0105` | Structural invariant/use cases: create/correct containment / reject cycles / preserve one-parent forest | Infrastructure + Audit/History | containment relation, cycle detector, correction history | self-cycle + indirect-cycle + one-parent + placement-independence scenarios |
| `BETA-REQ-0106` | Invariant/use cases: define reusable Cloud Type / create Site Deployment / assign same-Site Network Element | Infrastructure | Cloud Type, Cloud Deployment, same-Site assignment validator | many-sites + many-deployments + cross-site-reject + unresolved-Device-Reference scenarios |
| `BETA-REQ-0107` | Structural invariant: containment, placement, Cloud, IP and connectivity remain separate; canonical topology deferred from 1.0 | Infrastructure | 1.0 capability gate; future connectivity relationship model/ADR | no-inference + no-interface/discovery/topology + future-relationship provenance/correction scenarios |
| `BETA-REQ-0108` | Security invariant: reusable device/authentication secrets never enter ordinary SOMA domain/evidence/log/workbook state | Infrastructure + Security | prohibited-field/log schema checks; future opaque credential-provider reference | secret-rejection + no-SSH-UI + opaque-ref + provider-unavailable-no-fallback scenarios |
| `BETA-REQ-0109` | Persistence invariant: SQLite is complete authoritative operational store; graph may only be derived projection | Foundation Runtime + Persistence | SQLite repositories/constraints/projections; future graph rebuild adapter | SQLite-only operation + projection-rebuild + stale/absent-graph + no-graph-write scenarios |
| `BETA-REQ-0110` | Use cases: create empty template / discovery export / round-trip update / stage and review Infrastructure import | Infrastructure + Import/Export | versioned xlsx adapter, staging model, installation-scope identity, transactional acceptance | version-gate + same-install-target + foreign-ID-evidence + blank-nondestructive + idempotent scenarios |
| `BETA-REQ-0111` | Security/use-case gate: communication scanning exists only while an accepted trackable entity exists | Offline Communications | trackable-target gate, source validation, idle state | no-target-no-read + validation-only + first-target-eligible + retained-history-after-pause scenarios |
| `BETA-REQ-0112` | Structural invariant: governed communication registry maps accepted trackable identities to one owning entity | Offline Communications + domain identity owners | tracking registry, alias resolver, terminal suppression registry | SR/SR7/C10/RFC/WFM/Objective/FT + Local-Task-exclusion + ambiguous-ID scenarios |
| `BETA-REQ-0113` | Use cases: establish initial coverage / advance forward high-water / change source / add older entity | Offline Communications | source-scoped coverage ledger, watermark, overlap replay, coverage warning | earliest-supported-time + missing-time-bound + durable-advance + failed-range + targeted-old-history scenarios |
| `BETA-REQ-0114` | Use cases: targeted historical backfill / explicit Deep Scan | Offline Communications | backfill planner, Deep Scan confirmation, range coverage reducer | identity-range-backfill + no-global-rewind + bounded-auto + always-confirm-Deep-Scan scenarios |
| `BETA-REQ-0115` | Security/structural invariant: unmatched content transient; retained Communication requires accepted link; one canonical message can link many targets | Offline Communications | canonical Communication, typed links, retention gate, link correction | unmatched-no-persistence + one-message-many-targets + one-link-correction + final-link-orphan scenarios |
| `BETA-REQ-0116` | Use cases: terminal unlink / orphan grace / purge revalidation / terminal correction recovery | Offline Communications + Tickets lifecycle consumer | orphan state, grace scheduler, purge transaction, suppression evidence, targeted recovery | terminal-one-link + seven-day-default + restored-dependency + revalidate-before-purge + post-purge-backfill scenarios |
| `BETA-REQ-0117` | Use cases: scheduled ordinary scan / Check now / startup catch-up / trigger coalescing | Offline Communications + Background Jobs | unified pipeline scheduler, coalescing/non-overlap gate | hourly-default + disable + manual-check + one-startup-catch-up + purge-independent scenarios |
| `BETA-REQ-0118` | Structural invariant: immutable Communication identity within one path-independent Source Scope; structured participants | Offline Communications + Contacts | source-scope model, participant schema/rows, Contact reconciliation | folder-move-no-duplicate + cross-scope-no-merge + role preservation + malformed-participant scenarios |
| `BETA-REQ-0119` | Structural invariant/use cases: provider identity / deterministic fallback / collision / stronger identity / MSG reconciliation | Offline Communications | adapter identity extractor, fallback-versioning, alias/collision reconciliation, MSG artifact relation | stable-provider + deterministic-fallback + collision-separate + later-stronger-ID + msg-not-sent scenarios |
| `BETA-REQ-0120` | Platform/use cases: inspect/cancel/retry/recover long communication jobs | Background Jobs + Offline Communications | job state machine, checkpoints, counters, retry/backoff, redacted diagnostics | unknown-total-no-percent + safe-cancel + crash-not-success + bounded-idempotent-retry + no-content-logs scenarios |
| `BETA-REQ-0121` | Structural invariant: adapters/workflows own their own invocation/source/staging/job/transaction/progress and cooperate explicitly | Application Services + workflow owners | workflow ownership matrix, commands/proposals, orchestration | first-import-eligibility-not-scan + msg-not-send + report-not-scan + separate-job/result/failure scenarios |
| `BETA-REQ-0122` | Use cases: show entity Communication summary / preserve terminal frozen summary | Workbenches + Offline Communications projections | summary projection, chronology/direction reducer, coverage/freshness state | one-canonical-count + multi-entity-count + msg-draft-excluded + unknown-vs-zero + terminal-no-body scenarios |
| `BETA-REQ-0123` | Shared interaction invariant: active row/selection/membership/focus/open are distinct; scroll ownership and return restoration are deterministic | UI Shell + Workbenches | shared list/grid navigator, scroll containment, restoration state | single-click-select + double-click/Enter-open + Space-membership + nested-scroll + stale-return scenarios |
| `BETA-REQ-0124` | Shared use case: bounded accessible autocomplete/relationship selector with explicit creation separation | UI Components + domain selectors | combobox/listbox, async supersession, bounded query/popup, create-action boundary | focus-no-enumeration + threshold + stale-response + popup-scroll + typed-text-not-create scenarios |
| `BETA-REQ-0125` | Responsive invariant/use cases: preserve capability under reflow / accessible icons / governed deliberate hold | Responsive Shell + Workbenches | responsive primitives, icon-action primitive, deliberate-confirmation registry | narrow-split-pane + zoom/text + 3s-hold + scroll-not-hold + existing-NE-reconciliation scenarios |
| `BETA-REQ-0126` | Design-system invariant: semantic tokens + governed skins + independent appearance preserve meaning/accessibility | UI Design System + Branding | token schema/versioning, skin registry, appearance adapter | skin-parity + light/dark/system + forced-color + reduced-motion + no-semantic-drift scenarios |
| `BETA-REQ-0127` | Structural/editor invariant: accepted revision, unsaved working copy, and persistent Draft state are separate | UI Editors + Application Services + Persistence | revision token, dirty tracker, recovery store, partial-save validator, conflict comparator, safe-inverse registry | Draft-vs-dirty + selective-save + failure-preserves-input + recovery-not-accept + conflict-no-LWW + unsaved-no-authority scenarios |

## Two-pass checkpoint audit

### Pass 1 — source requirement → normalized authority

Every material assertion in `BETA-REQ-0103`–`BETA-REQ-0127` was checked against its accepted governing obligation and stable clauses. Infrastructure identity/placement/cloud/IP/containment, 1.0 connectivity deferral, credential exclusion, SQLite authority, versioned Infrastructure workbook exchange, the complete local PST/OST communication contract, shared navigation/autocomplete/responsive/theme behavior, and editor working-copy semantics were decomposed rather than discarded.

Specific reconciliation notes:

- `0103`–`0107` preserve Infrastructure separation: Network Element identity is not Model, serial, IP, containment, placement, Cloud, or connectivity identity. No 1.0 topology capability is smuggled in by descriptive IP or placement data.
- `0108` preserves the device-secret boundary without changing the separately governed Local Administrator authentication, live-data encryption, or portable-backup recovery contracts.
- `0109` makes SQLite sufficient for all Beta 1.0 authoritative operation; any future graph engine remains disposable projection only.
- `0110` preserves three macro-free workbook use cases, explicit discovery, staging/review, installation-scoped identity, non-destructive omission/blank semantics, idempotency, and read-only treatment of operator-managed source workbooks.
- The project owner's CP-005 Device Reference clarification is preserved as `0102` Infrastructure authority: typo/provisional references can be resolved or corrected to an existing Network Element from Infrastructure even after all related SRs are terminal. This correction preserves both identities and history and never reopens or rewrites the SR. `0110`, `0121`, `0125`, and `0127` consume only the workbook/workflow/UI/editor consequences of that authority.
- `0111`–`0114` distinguish scanning eligibility, tracking identity, forward coverage, targeted backfill, and explicitly confirmed Deep Scan. Infrastructure or first-target import may change eligibility but does not scan inside the import workflow.
- `0115`–`0116` preserve matched-only retention, one canonical Communication with independent links, terminal direct-link removal, seven-exact-day default orphan grace, transactional purge revalidation, non-reconstructable suppression evidence, and recovery by restored dependency or targeted source backfill.
- `0116` does not create generic ticket reopening authority. Communication processing consumes only an accepted owning-domain terminal correction/reversal; a later message alone never reopens a ticket.
- `0117`–`0120` preserve one ordinary local pipeline, hourly default cadence, Check now, at most one startup catch-up, coalescing/non-overlap, independent orphan housekeeping, source-scope/message identity, truthful background-job progress, cancellation, crash recovery, bounded retry, and redacted diagnostics.
- `0118`–`0119` keep Source Scope path-independent, provider/fallback identifiers typed, fallback canonicalization versioned/deterministic, collisions non-destructive, and `.msg` artifact identity distinct from observed sent Communication identity.
- `0121` prevents workflow impersonation or direct cross-owner state mutation. Explicit orchestration may coordinate several workflows but preserves separate jobs/results/failures and receiving-domain validation.
- `0122` keeps Communication summaries as projections of accepted canonical links and coverage; scan/discovery/proposal times never substitute for message chronology, drafts do not inflate counts, and terminal SR/RFC summaries are frozen/non-reconstructable without body navigation.
- `0123`–`0126` establish one interaction grammar, bounded selector behavior, responsive capability preservation, allowlisted three-second deliberate hold for new Device Reference promotion, semantic-token skins, independent Light/Dark/System appearance, and accessibility/non-color invariants.
- `0127` keeps persistent domain `Draft` distinct from unsaved/dirty UI state. Recoverable working copies are not accepted truth, stale conflicts are reviewed rather than last-write-wins, and unsaved values never affect authoritative projections, matching, SLA, availability, relationships, or reports.

**Pass-1 result: 25/25 PASS.**

### Pass 2 — clause → approved authority

Every CP-005 clause has one immutable owner recorded in `CP005_CLAUSE_AUTHORITY.md`. Supporting authority records prior/same-checkpoint requirements, the explicit Device Reference owner clarification, or a named unresolved technical design boundary without transferring ownership.

- Clauses: **2669**
- Owner ranges: **25**
- Clauses with explicit supporting-authority/design-boundary evidence: **2669**
- Missing clause owners: **0**
- Overlapping owner ranges: **0**
- Unexplained normative clauses: **0**

**Pass-2 result: 2669/2669 PASS.**

## Terminology, ownership, and invariant cross-check

- Infrastructure remains the workspace; Device Reference remains the operational device reference; Network Element remains the registered instance; legacy Managed Element remains non-canonical.
- Terminal ticket history does **not** freeze Infrastructure Device Reference reconciliation.
- Network Element identity remains distinct from Model, serial, IP, placement, containment, Cloud, and connectivity.
- Site remains the physical authority; Rack and Cloud Deployment assignments must remain same-Site.
- Dispatch Location directionality remains unchanged; no CP-005 Infrastructure rule turns it into a destination.
- No device/SSH credential store is introduced in Beta 1.0.
- SQLite remains authoritative; no graph/database dual truth is introduced.
- Import/export sources remain operator-managed and unmodified; imports stage before acceptance and do not silently clear omitted/blank optional data.
- Communication scanning remains read-only and target-gated; Customer, Contact, Infrastructure, and Local Task data do not become direct trackable identity.
- `.msg` generation remains artifact creation, not sending evidence or scan progress.
- Communication identity, source scope, aliases, links, and lifecycle proposals remain separate concerns.
- Orphan purge affects SOMA-held reconstructable content only; PST/OST sources, existing portable exports, and existing backups remain outside the purge mutation boundary.
- Terminal SR/RFC Communication links are removed only after accepted terminal decisions; other links survive, and frozen terminal summaries do not preserve hidden body copies.
- Objective/Task lifecycle continues to own Task execution, outcome, review, correction, and retry. CP-005 does not transfer that authority to Inventory or Communication Processing.
- Single-click selection, double-click/Enter opening, scroll ownership, autocomplete creation separation, responsive capability preservation, and accessible state semantics are consistent across shared UI primitives.
- Persistent Draft, unsaved working copy, and accepted revision remain separate; unsaved state is never authoritative.

**Result: PASS.**

## Cross-check against CP-001, CP-002, CP-003, and CP-004

CP-005 was cross-checked against all accepted normalized authority through `BETA-REQ-0102`.

- No CP-005 requirement renumbers, weakens, or reassigns any stable clause in CP-001–CP-004.
- CP-005 preserves immutable internal identity, append/correction history, transactional persistence, temporal truth, external-evidence separation, and non-fabrication rules established in earlier checkpoints.
- CP-005 preserves the single Local Administrator / reusable Contact distinction and does not turn message participants into authentication identities.
- CP-005 preserves source-family chronology: import/discovery/index/current time cannot fabricate missing external business/message time.
- CP-005 preserves terminal-history semantics while adding only domain-compatible Communication unlink/orphan behavior; it does not authorize silent ticket reopen.
- CP-005 preserves CP-004 Inventory/Task authority: Inventory consumes reviewed Task physical consequences, while Objectives/Task lifecycle owns execution/outcome/review/correction/retry.
- CP-005 preserves the no-upload-UI Beta 1.0 boundary; communication evidence is indexed/read-only and manual paths remain available.
- CP-005 preserves the CP-004 substitute-BOM clarification without extending it into unrelated Infrastructure or communication identity logic.
- CP-005 preserves Dispatch Location as a separately governed location concept and does not infer Site/Cloud/Customer ownership from communication or workbook text.
- CP-005 introduces no generalized retention clock beyond the specifically approved Communication orphan grace in `0116`.
- CP-005 introduces no canonical topology, SSH, email-send, or external-account capability into Beta 1.0.
- The preliminary HLD defect assigning “Task outcomes” to Inventory remains a later design-reconciliation item and is not silently edited during normalization.

**Prior-checkpoint cross-check result: PASS.**

## Open technical-design boundaries preserved

Normalization does not close unresolved implementation decisions merely to make the clauses concrete:

- `O-004` — exact supported PST/OST/MSG parsing library/subset and adapter mechanics.
- `O-005` — exact database/encryption/KDF/recovery/rotation/backup/export protection mechanics, including protection of recoverable working-copy storage.
- `O-006` — exact supported Windows editions/builds, browser/runtime combinations, and packaging support.
- `O-007` — exact field/change classes eligible for safe automatic proposal/link acceptance.
- `O-010` — exact tray/background lifecycle where applicable.

These remain design questions; none is silently answered by CP-005.

## Normalization anomaly check

No CP-005 requirement required renumbering, a suffix requirement ID, or a silent split into multiple governing requirements. The Device Reference clarification is explicitly recorded as a project-owner strengthening of existing `BETA-REQ-0102` authority and is consumed only as supporting authority by dependent CP-005 clauses.

No unresolved product contradiction was discovered.

**Result: PASS.**

## Commit-isolation check

The intended checkpoint commit changes only the normalization index plus the four CP-005 normalization artefacts:

- `docs/REQUIREMENT_NORMALIZATION.md`
- `docs/normalization/CP005_CATALOGUE.md`
- `docs/normalization/CP005_CLAUSES.md`
- `docs/normalization/CP005_CLAUSE_AUTHORITY.md`
- `docs/normalization/CP005_TRACEABILITY.md`

No implementation, baseline requirement, HLD, LLD, architecture, data-model, migration, or unrelated file belongs to CP-005.

**Result: PASS.**

## Conclusion

CP-005 introduces no requirement renumbering, no silent deletion of approved behavior, no cross-workflow ownership collapse, no secret-store or topology scope creep, no silent ticket reopen, no transfer of Task-outcome authority to Inventory, and no design-added product authority. It extends accepted normalization coverage through `BETA-REQ-0127`.

**Overall CP-005: unconditional PASS.**
