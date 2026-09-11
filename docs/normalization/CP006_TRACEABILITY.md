# SOMA Beta Normalization CP-006 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0128`–`BETA-REQ-0152`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0128` | Projection invariant/use cases: filter SR/main views by Customer / show Communication, Inventory, Objective, SLA, chronology and Historical context without dashboard-owned truth | Overview + Workbenches + domain projection owners | projection/query services, Customer scope, summary reducers, chronology/status renderers | all/specific/unassigned + canonical-Communication + mixed-Inventory + Task-derived-Objective + cohort-SLA + no-Resolved-Status-Date scenarios |
| `BETA-REQ-0129` | Use cases: derive contextual Inventory actions / execute material command / preflight bulk action / expose blockers/manual paths | Inventory + Application Services + UI action framework | action registry, eligibility resolver, impact preview, batch preflight/result model | stale-target + incompatible/missing-input/individual-review partitions + manual-path + export-not-progress + non-stranding scenarios |
| `BETA-REQ-0130` | Design/acceptance invariant: classify references / use directional inspiration / govern fixtures and export goldens | UI Design System + Branding + Acceptance | reference catalogue, fixture/golden metadata, visual-comparison tolerance contract | directional-not-normative + sanitized-fixture + reproducible-baseline + missing-fixture-block scenarios |
| `BETA-REQ-0131` | Persistence invariant: every authoritative SQLite connection proves FK enforcement and effective child-side indexing | Foundation Runtime + Persistence | connection factory, FK pragma verification, schema/index analyser, rebuild exception | every-access-path + disabled-FK-fail + leading-prefix-index + rebuild/foreign_key_check scenarios |
| `BETA-REQ-0132` | Migration invariant/use cases: serialize migration / atomically change schema+ledger / recover interruption / gate readiness | Foundation Runtime + Persistence | migration owner lock, transaction coordinator, ledger validator, readiness gate | dual-start + failure injection + safe cancellation + retry + ledger/schema/FK/audit validation scenarios |
| `BETA-REQ-0133` | Repository/runtime invariant: freeze accepted migration lineage and detect drift/future state | Foundation Runtime + Repository Policy | migration manifest, checksum canonicalization, startup drift classifier | candidate-rewrite + accepted-byte-drift + missing/misordered/ledger-mismatch/future + forward-fix scenarios |
| `BETA-REQ-0134` | Use case/invariant: inspect migration status without side effects | Foundation Runtime + Persistence | read-only status inspector, authenticated live-instance status client | missing-target-no-files + read-only-existing + live-writer-limited + filesystem-before/after scenarios |
| `BETA-REQ-0135` | Structural invariant: lifecycle evidence, audit, proposal/job history and diagnostics remain separate authorities | Application Services + Audit/History + domain owners | domain-event store, audit service, history projection/classifier | occurrence-vs-recording-time + atomic mutation/event/audit + rejected-attempt + correction + minimized-delete scenarios |
| `BETA-REQ-0136` | Structural invariant/use cases: persist typed versioned JSON documents without making JSON domain authority | Foundation Runtime + Settings + Editors + Background Jobs | JSON contract registry, strict parser/validator, upgrade runner, atomic setting writer | duplicate-key/nonfinite/unknown-version + missing/null/empty + read-purity + atomic-upgrade + secret/body exclusion scenarios |
| `BETA-REQ-0137` | Acceptance invariant: deterministic requirement/clause/migration/use-case verification with governed fixtures | Test Architecture + all domain owners | traceability matrix, deterministic dependency harness, fixture registry | positive+negative invariant vectors + every migration origin + import/export matrix + regression + no-required-skip scenarios |
| `BETA-REQ-0138` | CI/release invariant: current-commit Windows evidence on every supported Python runtime | CI/Release Engineering + Acceptance | Windows Python matrix, draft/full workflow gates, branch protection/release evidence | 3.13+3.14 independent + draft-reduced + current-head-full + stale/cancelled-not-pass + desktop-acceptance scenarios |
| `BETA-REQ-0139` | Acceptance use cases: governed manual accessibility/interaction inspection / deliberate Device promotion hold / non-authoritative review surfaces | UI/UX + Accessibility + Acceptance | acceptance checklist/harness, focus/modal tests, deliberate-hold primitive, defect gate | keyboard/pointer + zoom/reduced-motion + hovered-scroll + cancel/one-shot-hold + proposal-no-mutation + Critical/High-block scenarios |
| `BETA-REQ-0140` | Security/runtime invariant: trust/control only the exact authenticated local SOMA run and canonical data owner | Foundation Runtime + Security | loopback binder, data-instance owner lock, runtime registry, health/shutdown protocol | wildcard-bind-reject + PID/port reuse + stale/forged registry + redirect/proxy poisoning + repeated launch/shutdown scenarios |
| `BETA-REQ-0141` | Platform invariant/use cases: emit bounded external diagnostics / rotate / fail open only for logging | Diagnostics + Foundation Runtime | structured diagnostic schema, writer/queue/rotation, support-export builder | concurrent-complete-write + bounded-queue/rotation + recursion failure + audit/migration failure-stays-failure + no-upload scenarios |
| `BETA-REQ-0142` | Security invariant: prohibited sensitive data never reaches diagnostic/console/CI/crash/support sinks | Security + Diagnostics + CI | semantic field classifier, sanitizers, safe exception wrappers, canary scanner | password/token/header/body + nested/encoded/truncated canaries + sanitizer-failure-no-raw-fallback + useful-context scenarios |
| `BETA-REQ-0143` | Audit invariant: accepted `audit_events` rows are append-only and duplicate identities fail explicitly | Audit + Persistence | dedicated audit insert, schema/connection mutation guards, backup/restore validation | update/delete reject + duplicate error + idempotency-before-insert + atomic rollback + correction-append scenarios |
| `BETA-REQ-0144` | Audit-payload invariant: every action uses a bounded named/versioned closed schema | Audit + Security | action payload registry, strict JSON parser/validator, historical renderer | unknown/duplicate/nonfinite/excessive reject + mutation rollback + no whole-object fallback + historical-v1-read + canary scenarios |
| `BETA-REQ-0145` | Use cases: auto-discover Enhanced RFC/WFM workbook / rank candidate / report malformed newest / manual select | Tickets Import + Settings | source-family filename matcher, direct-file inspector, chronology/tie selector | configurable-root + WFM embedded-time + RFC mtime-only-ranking + collision-suffix-not-time + no-fallback scenarios |
| `BETA-REQ-0146` | Import invariant/use cases: stage RFC/WFM observations / fingerprint+diff / replay / conflict / recovery | Tickets Import + Application Services | source checkpoints, logical fingerprinting, diff/review model, recovery workflow | exact-replay + newer-identical + equal-time-different-content + older-recovery + omission-no-lifecycle scenarios |
| `BETA-REQ-0147` | Business/presentation invariant: recognized status, not workbook presence, controls active/historical RFC/WFM presentation | Tickets + Views/Filters | status projection, local historical filters, coverage-warning model | full/filtered omission + historical-retention + no-stop-tracking + source-level-warning + reappearance-same-ID scenarios |
| `BETA-REQ-0148` | Reconciliation use case: adopt exact manual RFC/WFM identity in place when official source arrives | Tickets Import + Identity/Reconciliation | adoption command, immutable provenance, source-owned-field diff, chronology conflict review | exact-ID-adopt + preserve-links/history + no-ever_imported-authority + missing-external-time + fuzzy-no-adopt scenarios |
| `BETA-REQ-0149` | RFC lifecycle use cases: normalize status / review regression correction / accept terminal evidence / confirm cascade | RFC Lifecycle + Audit + UI Review | closed status vocabulary, projection correction, terminal/cascade proposal transaction, deliberate confirmation | case-insensitive-closed-vocab + Closed-vs-Cancelled + Post-Implement-cancel-review + pending-cascade-atomicity scenarios |
| `BETA-REQ-0150` | RFC/WFM invariant/use cases: enforce Implement eligibility / bootstrap provisional RFC / reconcile stronger RFC evidence | RFC Lifecycle + WFM Import | eligibility resolver, provisional RFC/adoption flow, conflict review | active-WFM-bootstrap + pre-Implement-conflict + Complete/Plan-Cancel-history + no-SR-fabrication scenarios |
| `BETA-REQ-0151` | Use case: extract bounded SR-link candidates from RFC/WFM text and review master-RFC linkage | Tickets Import + Relationship Review | candidate parser/ranker, existing-SR resolver, master-target resolver | labelled-strong + isolated-low-confidence + date/substring exclusion + multiple-candidate + subordinate-to-master scenarios |
| `BETA-REQ-0152` | Structural invariant/use cases: manage two-level RFC forest / reparent / scale / narrowly hard-delete draft | RFC Relationships + Audit/History | hierarchy relation, cycle/depth/parent/customer validator, virtualized branch UI, deletion eligibility | self/indirect-cycle + second-parent + Customer mismatch/unknown + post-WFM reparent + >20 children + untouched-draft-delete scenarios |

## Two-pass checkpoint audit

### Pass 1 — source requirement → normalized authority

Every material assertion in `BETA-REQ-0128`–`BETA-REQ-0152` was checked against its accepted governing obligation and stable clause range. Main-view projection truth, Inventory contextual actions, reference/fixture authority, SQLite FK/migration/status guarantees, evidence/audit/JSON/test/CI/accessibility/runtime/diagnostic contracts, and the complete RFC/WFM discovery/reconciliation/status/hierarchy block were decomposed rather than discarded.

Specific reconciliation notes:

- `0128` keeps Overview/list/workbench/export state derived from owning-domain truth. Customer filters use immutable Customer Organization identity; Communication uses canonical links/coverage; Objective context remains SR→Task→Objective; SLA cohort facts remain separate from individual duration; `Resolved Status Date` remains permanently discarded.
- `0128` does **not** transfer Task execution/outcome/review/correction/retry ownership to Inventory. Objectives/Task lifecycle remains the owner; Inventory consumes reviewed outcomes for unit/physical consequences.
- `0129` preserves contextual and bulk action truth, complete per-target preflight classification, manual evidence-independent paths, proposal review, export-not-progress, and non-stranding next-action behavior without reintroducing editable status labels.
- `0130` classifies visual/artifact references by authority. vSphere, Wireshark, and terminal interfaces remain directional inspiration only; no third-party branding/assets/pixels/trade dress become SOMA acceptance authority.
- `0131`–`0134` establish one FK-enforcing SQLite connection policy, serialized crash-safe migrations, immutable accepted migration lineage, and a strictly side-effect-free status operation. Runtime/readiness rules do not weaken domain persistence invariants.
- `0135`–`0136` separate lifecycle occurrence evidence, application audit, proposal/job history, diagnostics, and typed JSON documents. JSON never becomes normalized-domain authority and recording time never substitutes for independently supported occurrence time.
- `0137`–`0139` make acceptance traceable, deterministic, Windows-matrix-backed, accessible, and interaction-complete. Required failures/skips/nondeterminism or unresolved Critical/High interaction defects block acceptance.
- The CP-005 Device Reference clarification remains owned by `0102`: promotion/creation of a genuinely new Network Element retains the exact three-second hold, while reconciliation to an already-existing Network Element remains a distinct correction path without creation-hold semantics.
- `0140` treats loopback as necessary but insufficient trust. Exact origin, process birth, run/data/protocol identities, ownership, and authenticated health/shutdown all participate; PID, port, or registry presence alone never proves identity.
- `0141`–`0142` keep diagnostics non-authoritative and prevention-first. Diagnostic emission may fail open only for otherwise valid work; sanitization fails closed for disclosure and never falls back to raw sensitive content.
- `0143`–`0144` preserve append-only audit rows and closed action-specific payloads. Command idempotency resolves before insertion; duplicate event identity is an error; correction appends; audit does not claim cryptographic immunity from privileged file replacement.
- `0145` distinguishes discovery chronology from business chronology. WFM embedded timestamp governs candidate ranking; RFC mtime may rank candidates but never becomes RFC business time; collision suffixes have no chronology authority; malformed newest does not silently fall back.
- `0146` distinguishes workbook observation, source-family chronology checkpoint, logical fingerprint, diff/review, and business lifecycle. Exact replay is a no-op; newer-identical content may update bounded check recency only; equal chronology/different content conflicts; older content requires recovery; omission is non-destructive.
- `0147` keeps recognized status—not workbook presence—as active/terminal/cancelled/historical authority. Beta 1.0 has no `Stop tracking` state; historical rows stay available and reappearance uses the same identity without a synthetic resume transition.
- `0148` adopts exact manually registered RFC/WFM identities in place, preserving internal identity/relationships/history and deriving permanent adoption provenance without a mutable `ever_imported` authority. SOMA creation time, source creation time, file chronology, and import chronology remain distinct.
- `0149` keeps `Closed` and `Cancelled` distinct terminal evidence, makes projection correction append-only/high-risk, allows reviewed Post-Implement cancellation, and commits terminal evidence with a pending—not executed—cascade proposal atomically.
- `0150` permits WFM evidence to bootstrap a provisional RFC/eligibility only when stronger Enhanced RFC evidence is absent; accepted pre-Implement RFC evidence cannot be silently overridden; `Complete`/`Plan Cancel` remain historical and WFM evidence never fabricates an SR.
- `0151` makes text parsing candidate-only: exact labelled `SR`/`TT` eight-digit forms are strong, isolated unlabelled eight digits are lower confidence, dates/longer-ID substrings are excluded, existing SRs only are matchable, and subordinate-origin evidence targets the master RFC.
- `0152` formalizes the RFC hierarchy as an acyclic two-level one-parent forest with relationship-derived roles, same-Customer validation for resolved branches, no provider inference, high-risk history-preserving reparenting after WFM history, no arbitrary subordinate cap, and hard deletion only for a provably untouched manual draft.

**Pass-1 result: 25/25 PASS.**

### Pass 2 — clause → approved authority

Every CP-006 clause has one immutable owner recorded in `CP006_CLAUSE_AUTHORITY.md`. Supporting authority records prior/same-checkpoint requirements or a named unresolved design boundary without transferring ownership.

- Clauses: **3444**
- Owner ranges: **25**
- Clauses with explicit supporting-authority/design-boundary evidence: **3444**
- Missing clause owners: **0**
- Overlapping owner ranges: **0**
- Unexplained normative clauses: **0**

**Pass-2 result: 3444/3444 PASS.**

## Canonical clause-ID correction

The active canonical clause range for `BETA-REQ-0152` is literally `RFC-FOREST-001..124` in both `CP006_CLAUSES.md` and `CP006_CLAUSE_AUTHORITY.md`. The original CP-006 checkpoint commit preserves the earlier `RFC-HIER` spelling in Git history, while `CP006_CLAUSE_ID_AMENDMENT.md` records why the prefix was corrected. Canonical consumers require **no overlay or runtime transformation** to obtain the current IDs.

This correction changes no clause wording, suffix, order, owner, supporting authority, requirement disposition, or clause count.

## Terminology, ownership, and invariant cross-check

- `Infrastructure` remains the canonical workspace name; Network Element remains the registered infrastructure instance; Device Reference remains the provisional/operational reference.
- Terminal ticket history does **not** freeze Device Reference correction to an existing Network Element.
- Creation/promotion of a genuinely new Network Element remains distinct from existing-NE reconciliation.
- `Objective` remains Maintenance Window; Task remains the scheduling/execution unit; Task outcome ownership remains in Objectives/Task lifecycle.
- Inventory consumes reviewed Task physical consequences and does not gain execution/outcome/review/correction/retry ownership.
- SQLite remains the sole authoritative Beta 1.0 operational datastore.
- Migration/status/runtime registries and diagnostics remain infrastructure coordination/observability state rather than domain authority.
- `audit_events` is application-enforced append-only; no unsupported cryptographic-tamper-proof claim is introduced.
- Diagnostics, console, CI, crash, startup fallback, and support-output paths share the sensitive-data minimization boundary.
- RFC/WFM workbooks remain untrusted observations. Discovery, source chronology, entity chronology, and business lifecycle chronology remain separate.
- Exact canonical RFC/WFM/SR identifiers remain identity authority; descriptive similarity never silently adopts, links, or infers hierarchy.
- Workbook omission has no lifecycle, unlinking, archival, deletion, or stop-tracking authority.
- `Closed` and `Cancelled` remain distinct RFC terminal evidence.
- WFM evidence may bootstrap a provisional RFC but never fabricates an SR and cannot silently override stronger Enhanced RFC pre-Implement evidence.
- SR relation evidence from a subordinate RFC/WFM targets the governing master RFC while preserving subordinate provenance.
- RFC hierarchy remains two levels: root/master + direct subordinate; subordinates cannot themselves parent RFCs.
- Customer Organization consistency uses canonical identity; unresolved ownership warns and known mismatch is not downgraded to uncertainty.
- No arbitrary twenty-subordinate business cap is introduced.
- Hard deletion remains narrowly constrained and history-preserving alternatives remain required once operational evidence exists.

**Result: PASS.**

## Cross-check against CP-001 through CP-005

CP-006 was cross-checked against all accepted normalized authority through `BETA-REQ-0127`.

- No CP-006 requirement renumbers, weakens, or reassigns a stable clause owned by CP-001–CP-005.
- Immutable internal identity remains independent from business identifiers, source labels, IPs, filenames, PIDs, ports, and descriptive similarity.
- Canonical UTC/source-time provenance and non-fabrication rules remain intact; RFC file mtime, workbook chronology, import time, and SOMA creation time do not substitute for missing source business time.
- Source-family workflows remain isolated and cooperate through explicit commands/proposals; Communications coverage does not become RFC/WFM import chronology and vice versa.
- The no-upload-control Beta 1.0 boundary remains unchanged; imports are file discovery/selection, not arbitrary evidence attachment capability.
- Local/offline operation remains intact; no automatic telemetry, diagnostic upload, cloud database, or external account dependency is introduced.
- The single Local User versus reusable operational Contacts distinction remains intact; per-run runtime authentication is technical launcher/service coordination, not a second user account.
- CP-004 Inventory/RMA/Fault Tag and approved-substitute authority is not altered by CP-006 action-surface normalization.
- CP-005 Communication retention/orphan rules are not broadened into general audit/diagnostic purge authority.
- CP-005 UI navigation/autocomplete/responsive/theme/draft contracts remain the shared primitives consumed by CP-006 acceptance requirements.
- The CP-005 Device Reference clarification remains supporting authority only and does not transfer Infrastructure correction ownership into UI acceptance.
- The known preliminary-HLD defect assigning “Task outcomes” to Inventory remains a later design-reconciliation item and is not silently fixed inside normalization.

**Prior-checkpoint cross-check result: PASS.**

## Open technical-design boundaries preserved

Normalization does not close unresolved implementation decisions merely to make the clauses concrete:

- `O-001` — exact report snapshot persistence strategy: persisted, on-demand, or both.
- `O-003` — exact Objective/Task outcome transition and correction-reason state machine where not already fixed by product authority.
- `O-004` — exact supported PST/OST/MSG parsing library/subset and adapter mechanics.
- `O-005` — exact database/encryption/KDF/recovery/rotation/backup/export protection mechanics, including secure working copies and runtime secret material.
- `O-006` — exact supported Windows editions/builds, browser/runtime combinations, packaging, process-birth representation, and representative desktop matrix.
- `O-007` — exact field/change classes eligible for safe automatic proposal/link acceptance.
- `O-010` — exact tray/background lifecycle where applicable.

CP-006 also deliberately leaves these implementation details to LLD unless later product authority narrows them: exact migration lock mechanism, checksum algorithm, migration-status read-only mechanics, diagnostic file path/rotation thresholds, sanitizer/redaction library, CSRF mechanism, runtime registry path/ACL/token transport, RFC/WFM filename-pattern literals, file-stability algorithm, logical fingerprint algorithm, deterministic candidate tie-break key, and measured hierarchy virtualization/scale thresholds.

These are design questions; none is silently answered by CP-006.

## Normalization anomaly check

No CP-006 requirement required renumbering, a suffix requirement ID, or a silent split into multiple governing requirements. No new product-owner clarification was required during CP-006. Previously accepted clarifications are consumed only as supporting authority in their appropriate boundaries.

No unresolved product contradiction was discovered.

**Result: PASS.**

## Commit-isolation plan

The CP-006 checkpoint commit is restricted to:

- `docs/REQUIREMENT_NORMALIZATION.md`
- `docs/normalization/CP006_CATALOGUE.md`
- `docs/normalization/CP006_CLAUSES.md`
- `docs/normalization/CP006_CLAUSE_AUTHORITY.md`
- `docs/normalization/CP006_TRACEABILITY.md`

No preserved baseline requirement, HLD/LLD, data-model, source-code, migration, configuration, or runtime file is modified by the checkpoint.

**Commit-isolation preflight: PASS.**

## Checkpoint result

- Requirements reviewed: **25/25**
- Replace: **25**
- Retain: **0**
- Stable clauses: **3444**
- Forward preservation: **PASS**
- Reverse authority: **PASS**
- Terminology/ownership/invariant cross-check: **PASS**
- CP-001–CP-005 cross-check: **PASS**
- Design-boundary preservation: **PASS**
- Normalization anomaly check: **PASS**
- Commit-isolation preflight: **PASS**

**Overall CP-006 result: unconditional PASS.**
