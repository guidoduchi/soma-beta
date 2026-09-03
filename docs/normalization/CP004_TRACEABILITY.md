# SOMA Beta Normalization CP-004 — Traceability and Audit

Status: **Accepted**  
Scope: `BETA-REQ-0078`–`BETA-REQ-0102`.

## Design-traceability seeds

These are truthful destinations, not fabricated final use-case/HLD/LLD identifiers. Stable downstream IDs are assigned when those artefacts are created.

| Beta ID | Use case or invariant destination | HLD owner seed | Future LLD destination | Acceptance evidence seed |
|---|---|---|---|---|
| `BETA-REQ-0078` | Use cases: first-run bootstrap / login / progressive readiness / backup recovery; invariants: one Local Administrator, authentication keys separate from data/backup keys | Identity & Settings + Security + Foundation Runtime | admin bootstrap, password verifier, auto-login protection, live-data key lifecycle, portable recovery, managed backup rotation | one-admin + password-only + no-username + progressive-setup + encryption-separation + verified-prune scenarios |
| `BETA-REQ-0079` | Invariant/use case: one SR-level Spare Need aggregate with preserved Device Part Unit contributors | Inventory + Tickets | Spare Need aggregate, contributor relation, planned-vs-derived quantity projection | same-SR multi-device + cross-SR separation + request-does-not-consume scenarios |
| `BETA-REQ-0080` | Use cases: record faulty Device Part Unit / suggest Stock / choose local, external, or mixed fulfillment | Inventory + Tickets | Device Part Unit, Need contribution, compatibility suggestion, fulfillment-choice service | fault-record + stock-suggestion + mixed-quantity + external-despite-stock + no-auto-reserve scenarios |
| `BETA-REQ-0081` | Business invariant/use cases: reuse Spare Need / resolve / cancel / reactivate / remove safely | Inventory | Need lifecycle, allocation history, deletion eligibility, destructive preview | repeated-request + repeated-local + nonterminal-block + all-cancelled/rejected + untouched-hard-delete scenarios |
| `BETA-REQ-0082` | Invariant/use cases: create Spare Request / derive SR and customer / select receiver and logistics / reconcile correspondence | Inventory + Identity & Settings + Offline Communications | Spare Request aggregate, Need allocation relation, derived context, receiver/logistics selector, temporary-ID reconciliation | same-SR + cross-SR rejection + receiver-suggestion + logistics-required + missing-temp-ID reconciliation scenarios |
| `BETA-REQ-0083` | Invariant/use cases: edit request / compare quantities / accept submission / preserve submitted snapshot | Inventory + Offline Communications | request allocations, submission boundary, immutable submission snapshot, response-timer trigger | positive-whole + discrepancy + draft-not-submitted + sent/manual-submit + later-substitution-no-rewrite scenarios |
| `BETA-REQ-0084` | Invariant/use cases: create RMA / preassign target / receive inbound unit / select return / correct C10 | Inventory | RMA obligation bridge, deterministic target assignment, direct inbound link, return-unit selector, alias registry | partial-batch + redistribution + no-placeholder + C10-correction + new-authorization scenarios |
| `BETA-REQ-0085` | Structural invariant: Device Part Units and Spare Part Units remain separate physical identities with role-specific BOM/serial evidence | Inventory | physical-unit model, receipt/dismantling lineage, installation/removal relationships, provenance projection | dismantle-parent + extracted-child + requested-vs-inbound + installed-vs-returned scenarios |
| `BETA-REQ-0086` | Use cases: manually register local/legacy/installed/removed/extracted/scrapped unit; invariant: Stock is lifecycle eligibility projection | Inventory | LSU allocator, manual registration, provenance adoption, state/disposition model, Stock eligibility query | no-SR7/C10/serial + duplicate-candidate + later-RMA-provenance + unavailable-not-stock scenarios |
| `BETA-REQ-0087` | Invariant/use cases: Task-to-unit allocation / record maintenance physical outcome / derive RMA return unit | Objectives/Tasks + Inventory | Task allocation, physical consequence consumer, return-unit derivation, correction relationship | one-active-allocation + successful-replacement + unused/faulty/incompatible + parent-return + Task-authority-boundary scenarios |
| `BETA-REQ-0088` | Structural invariant: append-oriented independently addressable Inventory lifecycle with reproducible projections | Inventory + Audit/History | event journal, correction/supersession, projection reducer, cross-request Fault Tag and warehouse loop | event-metadata + correction + rejection/resend + projection-rebuild + atomic-event/projection scenarios |
| `BETA-REQ-0089` | Use cases: index communication / review lifecycle proposal / manual equivalent; invariant: hidden optional evidence boundary | Offline Communications + Inventory | PST/OST index adapter, proposal model, idempotent reindex, optional evidence reference, manual lifecycle commands | read-only-source + incremental-RMA + missing-ID + dispatch-vs-ack + no-upload-UI scenarios |
| `BETA-REQ-0090` | Use cases: manual transition / proposal review / bulk transition / correct one target; invariant: one event per target | Inventory + Offline Communications + Audit/History | transition matrix, bulk preview, batch identifier, per-target event transaction, correction service | manual-parity + bulk-conflict + per-target-events + single-member-correction + genuine-later-event scenarios |
| `BETA-REQ-0091` | Use cases: save request / generate `.msg` / confirm submission / register external request / reconcile duplicate | Inventory + Offline Communications | request-origin, MSG generation, submission snapshot, external registration, missing-Need reconstruction, duplicate reconciliation | msg-not-submission + external-prepared + external-submitted + later-email + duplicate-candidate scenarios |
| `BETA-REQ-0092` | Structural invariant/use cases: immutable Inventory identity / correct identifier / supersede relationship / correct bulk member | Inventory + Audit/History | identity map, alias registry, relationship supersession, projection rebuild, duplicate resolver | SR7/C10 correction + relationship correction + no-silent-merge + isolated-batch-correction + no-hard-delete scenarios |
| `BETA-REQ-0093` | Invariant/use cases: freeze submitted logistics intent / record actual dispatch-pickup-delivery-receipt / partial logistics / dismantling provenance | Inventory + Dispatch Location + Contacts | logistics snapshots, multi-target logistics event, partial fulfillment, historical-address materialization, parent/child provenance | intent-vs-actual + partial-receipt + multi-RMA-event + address-change + no-fabricated-local-delivery scenarios |
| `BETA-REQ-0094` | Mandatory capability/release invariant: full Fault Tag return lifecycle is first-class Beta 1.0 Inventory scope | Inventory + Offline Communications + Objectives/Tasks outcome consumer | Fault Tag aggregate, return transition matrix, proposal/manual handlers, full responsive state contract | creation-to-history matrix + cross-request grouping + manual parity + no-upload + release-coverage gate scenarios |
| `BETA-REQ-0095` | Structural invariant/use cases: create Fault Tag / choose return method / set pickup origin / accept first submission / correct event | Inventory + Dispatch Location + Offline Communications | Fault Tag identities, visible tracking ID, event-derived state, pickup-origin snapshot, first-submission event | identity + origin-vs-destination + non-pickup + draft-not-submission + immutable-first-submission scenarios |
| `BETA-REQ-0096` | Business invariant/use cases: select exact RMA return unit / validate membership / approve substitute / resend after rejection | Inventory + Objectives/Tasks outcome consumer | membership eligibility predicate, substitute authority, active exclusivity, resend membership creation | removed-target + inbound-return + different-BOM provider substitute + manual-safe-substitute + conflicting-active-return scenarios |
| `BETA-REQ-0097` | Structural invariant: Fault Tag membership is an identity-based relationship graph with derived current context and historical submitted snapshot | Inventory + Infrastructure consumer | membership FK graph, derived SR/Device resolver, snapshot allowlist, substitute relation, relationship correction | derived-SR + provisional-device + no-copy-current-truth + substitute-BOM + C10 historical/current scenarios |
| `BETA-REQ-0098` | Structural invariant/use cases: edit draft / correct false submission / replace real submitted membership / resend separately | Inventory + Audit/History | submission lock, suppression/correction, replacement transaction, linear typed lineage, membership revalidation | false-submission + material-change + linear-chain + alias-no-replacement + resend-vs-replacement scenarios |
| `BETA-REQ-0099` | Business invariant/use cases: warehouse receive / explicitly accept or reject / partial processing / correct warehouse event / resend | Inventory + Offline Communications | warehouse-stage reducer, explicit final-decision command, RMA close/open consequences, timestamp provenance | received-not-closed + accepted-close + rejected-open + partial + unknown-effective-time + resend scenarios |
| `BETA-REQ-0100` | Business invariant/use cases: delete untouched draft / cancel / replace / archive / resend / preview destructive effect | Inventory + Audit/History | deletion eligibility, dependency scanner, impact preview, lifecycle command dispatch, transaction/audit, exported-artifact boundary | untouched-delete + protected-block + no-cascade + preview + archival + exported-msg-survival scenarios |
| `BETA-REQ-0101` | Business invariant/use cases: choose Fault Tag return method / select pickup origin / actual pickup / logistics correction / resend | Inventory + Dispatch Location + Contacts | return-method validator, pickup-origin FK/snapshot, actual pickup event, discrepancy review, replacement/resend defaults | origin-required + origin-not-destination + non-pickup + actual-divergence + logistics-only-replacement + resend-new-snapshot scenarios |
| `BETA-REQ-0102` | Structural invariant/use cases: reference unregistered device / deliberately promote / reconcile legacy terminology / relocate Network Element | Infrastructure + Tickets/Inventory Device Reference consumers | Device Reference↔Network Element relation, promotion/reconciliation, duplicate candidate resolution, legacy mapping | unregistered-device + promotion-no-duplication + one-NE-resolution + relocation-preserves-ID + legacy-label scenarios |

## Two-pass checkpoint audit

### Pass 1 — source requirement → normalized authority

Every material assertion in `BETA-REQ-0078`–`BETA-REQ-0102` was checked against its accepted governing obligation and stable clauses. The dense administration/security bootstrap, Spare Need/Request/RMA/unit model, append-oriented Inventory lifecycle, offline communication proposal boundary, Fault Tag lifecycle, warehouse processing, destructive actions, logistics snapshots, and Infrastructure terminology were decomposed rather than discarded.

Specific reconciliation notes:

- `BETA-REQ-0078` keeps authentication credentials, live-data encryption, portable-backup recovery, and managed-backup rotation as separate authorities. Exact cryptographic algorithms and operational recovery mechanics remain under technical design item `O-005`; the normalization does not invent them.
- `BETA-REQ-0087` explicitly preserves the product authority boundary: Objectives/Task lifecycle owns Task execution, outcome, review, correction, and retry. Inventory consumes reviewed physical consequences and owns Task-to-unit allocation, physical-unit state effects, and RMA return-unit derivation.
- `BETA-REQ-0089`–`0091` preserve the approved hidden-evidence decision: persistence/application services can accept optional evidence references, indexed communications can provide evidence, manual actions remain valid without uploads, and Beta 1.0 exposes no manual attachment or upload control.
- `BETA-REQ-0096` includes the project-owner clarification accepted during normalization: exact BOM equality is neither necessary nor sufficient for compatibility. A different-BOM inbound unit may carry provider-approved substitute authority when the request/Need/target context consistently requested the original BOM and the provider dispatches the different BOM under the accepted RMA; the operator may also explicitly approve a warned different-BOM substitute. No substitute decision rewrites historical or physical BOM facts.
- `BETA-REQ-0097` and `0098` propagate that substitute authority only as relationship/provenance evidence and revalidate it when replacement membership depends on the substitute; they do not create competing mutable BOM truth.
- `BETA-REQ-0095` and `0101` preserve Dispatch Location directionality for Fault Tag pickup: it is the origin **from which** return units are dispatched or collected, never the warehouse destination.
- `BETA-REQ-0098` preserves the distinction among false submission correction, material correction through `corrects/replaces`, and genuine warehouse retry through `resend of`.
- `BETA-REQ-0099` preserves two-stage warehouse truth: receipt acknowledges possession only; explicit acceptance closes the RMA return obligation; rejection keeps it unresolved and may lead to a later resend attempt.
- `BETA-REQ-0102` preserves Device Reference continuity before and after deliberate Infrastructure regularization and prevents legacy `Managed Element` terminology from becoming a Beta domain type.

**Pass-1 result: 25/25 PASS.**

### Pass 2 — clause → approved authority

Every CP-004 clause has one immutable `BETA-REQ-####` owner recorded in `CP004_CLAUSE_AUTHORITY.md`. Cross-cutting clauses additionally record prior or same-checkpoint supporting authority, explicit project-owner clarification, or a technical design-resolution boundary where necessary.

- Clauses: **1383**
- Owner ranges: **25**
- Owner alone sufficient: **288**
- Explicit additional supporting authority/design boundary: **1095**
- Missing clause owners: **0**
- Overlapping owner ranges: **0**
- Unexplained normative clauses: **0**

**Pass-2 result: 1383/1383 PASS.**

## Terminology, ownership, and invariant cross-check

- Local Administrator remains the sole authenticating local user; operational people remain reusable Contacts.
- Password authentication remains separate from operational and backup encryption secrets.
- Objective scheduling timezone remains separate from source-family and fixed ordinary/SLA timezone authority.
- Spare Need is SR-level planning demand, not a Device-owned or request-consumed record.
- Device Part Unit and Spare Part Unit remain distinct physical entities.
- Stock remains a projection of eligible physical Spare Part Units, not a second physical identity.
- Spare Request temporary tracking, SR7, C10, BOM, serial, names, labels, and communication subjects remain external/display evidence rather than relational identity.
- Requested, promised, inbound, installed, returned, and substitute part facts remain role-specific evidence rather than overwrite targets.
- Provider-approved and operator-approved substitutes remain distinguishable by provenance.
- Fault Tag membership always binds one open RMA return obligation to one reviewed physical return unit; cross-request grouping never weakens per-member eligibility.
- Fault Tag first submission freezes membership/logistics evidence; communication draft creation does not.
- False submission correction, replacement lineage, and resend lineage remain semantically distinct.
- Warehouse receipt remains separate from warehouse final disposition; rejected RMA return obligations remain open.
- Archival remains presentation/lifecycle state and never substitutes for retention or correction lineage.
- Dispatch Location remains customer-neutral and distinct from Infrastructure Site; in Fault Tag pickup it is the origin, not destination.
- Device Reference remains the operational device identity boundary and may stay provisional/external or deliberately resolve to exactly one registered Network Element.
- `Infrastructure`, `Device Reference`, and `Network Element` are canonical Beta terms; `Device Manager`/`Managed Element` are not canonical Beta domain terminology.

**Result: PASS.**

## Cross-check against CP-001, CP-002, and CP-003

CP-004 was cross-checked against all accepted normalized authority through `BETA-REQ-0077`.

- No CP-004 clause renumbers, weakens, or reassigns any stable clause in CP-001–CP-003.
- CP-004 preserves CP-001 immutable identity, audit/history, persistence, temporal, Dispatch Location, Site, and Infrastructure ownership rules.
- CP-004 preserves CP-002 single-admin authentication/encryption separation, Service Request/RFC/Task/Objective ownership, Device Reference continuity, Task outcome authority, and Working Note history.
- CP-004 preserves CP-003 source-time authority, incomplete-record behavior, reporting/retention boundaries, exact-source review, and terminal-history rules.
- The known preliminary HLD defect assigning “Task outcomes” to Inventory remains a design-reconciliation issue. CP-004 deliberately reinforces that Objectives/Task lifecycle owns execution/outcome/review/correction/retry, while Inventory consumes reviewed physical consequences.
- No generalized retention clock is introduced. Fault Tag hard deletion remains a narrow untouched-draft domain rule compatible with `BETA-REQ-0019`, `0072`, and `0077`.
- No upload UI is introduced despite internal optional evidence-reference support.
- No hidden destination semantics are assigned to Dispatch Location in the Fault Tag return flow.

**Prior-checkpoint cross-check result: PASS.**

## Normalization anomaly check

No CP-004 requirement required renumbering, a suffix requirement ID, or a silent split into multiple governing requirements. The project-owner substitute clarification was incorporated under the immutable owner `BETA-REQ-0096` and propagated only as explicit supporting authority where later clauses depend on it.

No unresolved product contradiction was discovered.

**Result: PASS.**

## Commit-isolation check

The intended checkpoint commit changes only the normalization index plus the four CP-004 normalization artefacts:

- `docs/REQUIREMENT_NORMALIZATION.md`
- `docs/normalization/CP004_CATALOGUE.md`
- `docs/normalization/CP004_CLAUSES.md`
- `docs/normalization/CP004_CLAUSE_AUTHORITY.md`
- `docs/normalization/CP004_TRACEABILITY.md`

No implementation, HLD, LLD, baseline-requirement, architecture, data-model, or unrelated file is part of CP-004.

**Result: PASS.**

## Conclusion

CP-004 introduces no requirement renumbering, no silent deletion of approved behavior, no transfer of Task-outcome authority to Inventory, and no design-added product authority. It extends accepted normalization coverage through `BETA-REQ-0102`.

**Overall CP-004: unconditional PASS.**
