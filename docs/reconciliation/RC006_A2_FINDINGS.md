# RC-006-A2 — Section-Level Assurance Findings

Status: **OPEN with F1–F2 and F7 corrected in HEAD; F3–F4 and F6 open; F5 corrected in HEAD with bounded supersession pending; affected B002 F1/F7 assertions remain for explicit disposition; A2 section-destination map remains incomplete**  
Parent method: `RC006_A2_SECTION_DESTINATION_ASSURANCE.md`  
Phase-0 product authority: **accepted; F4 and F6 identify normalization-authority omissions for already-accepted Workbench/Infrastructure behavior; F5 corrects a destination contradiction without changing approved SLA policy; F7 corrects stale assurance-state prose without changing product authority**.

## Finding register

| ID | Severity | Finding | Authority | Disposition | Status |
|---|---|---|---|---|---|
| `RC006-A2-F1` | HIGH representation defect | The same root Task-device representation defect appeared across normative destinations: an earlier `PRODUCT_CONTRACT.md` §7 representation and the pinned B002 `GLOSSARY.md` Local Task definition / `DECISIONS.md` D-024 represented Local Task device relationships as direct **Network Elements**, conflicting with canonical Device Reference authority. | `BETA-REQ-0049`, especially `DEVICE-REF-002`, `004`, `005`, `010..012`; Infrastructure Contract §§2–3; Workbench Contract §2.5 | Use zero-many **Device References** as the Task relationship; state that a Device Reference may remain external or resolve to one Network Element and that regularization preserves the Task-to-Device-Reference relationship/history. Preserve pinned B002 text for explicit failed/superseded assertion treatment rather than rewriting the baseline. | **HEAD CORRECTED — B002 GLOSSARY/DECISION SUPERSESSION PENDING** |
| `RC006-A2-F2` | HIGH representation defect | `ROADMAP.md` Phase 4 still required explicit application **lock/unlock** behavior and a “lock” acceptance action even though Phase-1A authority review found no accepted normalized/canonical authority for an application lock/unlock workflow. | `BETA-REQ-0035` (`AUTH-001..010`), `BETA-REQ-0078` login/auto-login/security families; UC-002 reverse-authority result; no canonical lock/unlock clause found | Remove explicit application lock/unlock from Phase 4 delivery/exit wording; retain password authentication, auto-login, protected local session/security mechanics, backup/recovery, and downstream session design without inventing product-visible locking. | **CORRECTED** |
| `RC006-A2-F3` | MEDIUM assurance-mechanics blocker | The unallocated RFC/WFM candidate corpus contains stored `fingerprint_sha256` values that do not consistently equal SHA-256 of the documented NFC/LF-normalized `exact_text`. Candidate text, locators, ordering, and semantic review remain intact, but the corpus cannot pass the frozen fingerprint contract as written. | `A2-EXTRACTION-SCHEMA-V1` fingerprint rule; `RC006_A2_SCHEMA_AMENDMENT_001.md`; B002 RFC/WFM blob `433ffbea4fe291e451b0fefc2b2c8a999c1b1894` | Regenerate only the pre-allocation candidate fingerprint fields from unchanged reviewed `exact_text`; verify all 171 records and source spans; refreeze before stable-ID allocation. Do not alter source text, boundaries, classification, semantic dispositions, or B002. | **OPEN — PRE-ALLOCATION BLOCKER** |
| `RC006-A2-F4` | HIGH reverse-authority gap | `WORKBENCH_CONTRACT.md` §3.2 allows an RFC with no linked SR to receive registered or unregistered Device References directly, and §3.3 states subordinate RFCs may have different involved devices; canonical `DEVICE-REF` authority directly enumerates SR and Task relationships but no RFC→Device Reference owner has been identified. | Workbench Contract §§3.2–3.3; `BETA-REQ-0049` `DEVICE-REF-001..014`; RFC hierarchy/relationship authority reviewed with no direct RFC→Device owner found | Preserve the accepted Workbench behavior; close only through controlled existing-authority identification or controlled normalization reopening. Do not convert it to direct RFC→Network Element identity and do not change SR→Master/root relationship rules. | **OPEN — NORMALIZATION AUTHORITY REQUIRED** |
| `RC006-A2-F5` | HIGH semantic contradiction | B002 `PRODUCT_LINE_SLA.md` §6 incorrectly listed `current compliance outcome` as a canonical SLA cohort partition dimension, contradicting `SLA-COHORT-049` and making percentage denominator identity self-referential. | `BETA-REQ-0175` `SLA-COHORT-001..120`; bounded amendment `RC006_A2_BOUNDED_AMENDMENT_001_PRODUCT_LINE_SLA.md` | Repository HEAD corrected the cohort key to calendar month + Customer + Contract + Contract Product Line + severity + policy tier, with outcome derived afterward. Preserve B002 unchanged; allocate the B002 assertion as failed/open, then supersede it through post-initial AMENDMENT allocation under the bounded-amendment protocol. | **HEAD CORRECTED / B002 SUPERSESSION PENDING** |
| `RC006-A2-F6` | HIGH reverse-authority gap | `INFRASTRUCTURE_CONTRACT.md` §4 and its workspace/placement model require a richer physical submodel than the stable canonical clauses fully own: Site→Room→Rack structure, Rack row/column/placement semantics, and the distinction between reusable Model/BOM compatibility and per-instance Component installation history are represented in the accepted focused contract but are only partially established by `NE-CORE`, `STORE-AUTH`, `INFRA-XLSX`, and related Infrastructure clauses. | Infrastructure Contract §§3.1–4, 11–17; `BETA-REQ-0027` `INFRA-OWN-*`; `BETA-REQ-0103` `NE-CORE-*`; `BETA-REQ-0109` `STORE-AUTH-009..017`; `BETA-REQ-0110` `INFRA-XLSX-023..035`; Product §9 A2 reverse-authority opens | Preserve the accepted Infrastructure physical model; close only through controlled existing-authority identification or controlled normalization reopening for Room/Rack hierarchy/lifecycle/cardinality, applicable Rack row/column/position semantics, and reusable Model/component-compatibility versus per-instance installed-Component history. Do not collapse Device Reference, Network Element, Model, Component, placement, containment, or Inventory physical-unit identities. | **OPEN — NORMALIZATION AUTHORITY REQUIRED** |
| `RC006-A2-F7` | MEDIUM assurance-state representation defect | Pinned B002/current pre-correction `ROADMAP.md` reported the reverse normative-assertion audit as `PASS — 0 known unsupported assertions` while also declaring A2 certification open, and `FOUNDATION_GAPS.md` said Phase 0 closure remained pending only project-owner acceptance even though the historical acceptance action was already preserved and A2 was the current closure gate. | `RC006_A2_SECTION_DESTINATION_ASSURANCE.md` §8 and its current-status rule; `PHASE0_ACCEPTANCE.md`; current A2 findings F1–F6 | Preserve the historical pre-A2 pass as history, but correct current HEAD status prose so reverse authority is OPEN under A2 and closure certification is pending A2. Keep `FND-GAP-001..016` resolved; do not convert A2 authority omissions into new product-gap IDs unless controlled reopening determines an actual product contradiction/omission. Preserve B002 for explicit supersession/disposition. | **HEAD CORRECTED — B002 SUPERSESSION PENDING** |

## RC006-A2-F1 — Task device relationship synthesis

### Defective representation

The root representation defect first appeared in Product synthesis as direct Local Task→Network Element wording. Although `PRODUCT_CONTRACT.md` §7 was corrected before the currently pinned Product B002 blob, the same semantic error survived in other pinned B002 normative destinations:

> `GLOSSARY.md` — Local Task: “It may link to zero or many SRs, master or subordinate RFCs, Spare Part Units, and Network Elements.”

> `DECISIONS.md` D-024: “Local Tasks may link to zero or many SRs, master or subordinate RFCs, Spare Part Units, and Network Elements...”

### Accepted authority

Canonical `BETA-REQ-0049` states:

- `DEVICE-REF-001` — Service Requests may relate directly to affected Device References.
- `DEVICE-REF-002` — Local Tasks and WFM Tasks may relate directly to zero or more affected Device References.
- `DEVICE-REF-004` — Device References may remain valid external/unregistered operational references.
- `DEVICE-REF-005` — a Device Reference may resolve to a registered Network Element.
- `DEVICE-REF-010..014` — regularization preserves Device Reference operational identity and existing SR/Task/Objective/Spare relationships/history.

The Infrastructure Contract likewise defines Device Reference as the operational identity used across Tickets, Tasks, Objectives, and Inventory, while Network Element is the registered Infrastructure device instance. The Workbench Task flow selects participating Device References.

### Correction

Current HEAD now aligns all three affected normative destinations with the canonical distinction:

- `PRODUCT_CONTRACT.md` §7 — Task relationships use **Device References**; Network Element is only an optional resolution target.
- `GLOSSARY.md` Local Task — corrected in commit `b98af736e8b1560ca615821bd327c10dce599e7f`.
- `DECISIONS.md` D-024 — corrected in commit `4cccd1d97ea9176b3bfa45f113826f4607d6d765`.

The pinned B002 Glossary/Decision text remains unchanged and shall be dispositioned explicitly during assertion allocation/supersession.

### Product-authority effect

- requirement identity changed: **0**;
- canonical clause changed: **0**;
- clause owner changed: **0**;
- accepted behavior changed: **0**;
- normative destination occurrences corrected: **3**;
- root semantic defect families added: **0** beyond F1.

This is one Phase-0 representation defect with multiple destination occurrences discovered by post-closure assurance hardening. It does not invalidate the historical Phase-0 acceptance action and does not introduce a new product decision.

## RC006-A2-F2 — Unsupported application lock/unlock synthesis

### Defective representation

`ROADMAP.md` Phase 4 previously required:

> Local-admin password authentication and lock/unlock behavior.

and its exit gate required a clean offline installation to:

> launch, authenticate, lock, back up, restore, restart, and recover.

### Accepted authority

The normalized authentication authority establishes one local authenticating profile, password authentication, verifier/security separation, and optional Windows-protected automatic login. Phase-1A reverse-authority review of the original `UC-002` seed found **no accepted `BETA-REQ` or canonical clause authorizing an explicit application lock/unlock workflow**.

The accepted authority therefore supports authentication and downstream secure session mechanics, but not a product-visible lock/unlock lifecycle unless future controlled product authority explicitly adds it.

### Correction

`ROADMAP.md` Phase 4 now requires local-admin password authentication and governed authenticated-session/security behavior without naming an unsupported lock/unlock product action. The exit gate validates launch, authentication, backup, restore, restart, and recovery without requiring “lock.”

### Product-authority effect

- requirement identity changed: **0**;
- canonical clause changed: **0**;
- clause owner changed: **0**;
- accepted behavior changed: **0**;
- unsupported synthesis behavior removed: **1**.

This is a representation correction, not a product-policy change. Explicit application lock/unlock remains excluded unless accepted authority is later added through controlled reopening.

## RC006-A2-F3 — RFC/WFM candidate fingerprint integrity

The frozen-but-unallocated RFC/WFM candidate file contains 171 reviewed records in eight sections. Direct recomputation against the schema formula confirms that at least multiple stored fingerprints differ from SHA-256 of normalized `exact_text`; for example, the first candidate reproduces correctly while subsequent simple candidates such as `Each adapter owns its filename pattern, stabilization, source chronology, fingerprint, and accepted checkpoint.` and `Only stable direct regular files are discovered.` do not.

This finding does **not** reopen the RFC/WFM semantic review. The pinned source blob, exact text, source locators, section ordering, atomic boundaries, and reverse-authority dispositions remain independently reviewable. Because no RFC/WFM assertion ID has yet been allocated, the candidate fingerprints shall be repaired before allocation rather than normalized after stable identity creation.

## RC006-A2-F4 — Missing RFC-to-Device-Reference canonical owner

Workbench B002 states that an RFC without an SR may still carry directly involved registered or unregistered Device References, and that subordinate RFCs may have different involved devices. This is consistent with the accepted SOMA workflow in which RFC work may exist independently of an SR and subordinate RFCs retain their own operational context.

The current canonical Device Reference family directly authorizes SR→Device Reference and Task→Device Reference relationships, plus later regularization to a Network Element, but A2 review has not identified a stable canonical clause authorizing direct RFC→Device Reference context. RFC hierarchy and SR-link authority do not fill that gap.

A2 itself cannot invent new canonical clauses. Closure therefore requires either identification of an already-existing stable owner or a controlled normalization reopening outside A2 that preserves Device Reference as the operational identity, permits no-SR and subordinate RFC device context, and does not create a competing direct SR→subordinate relationship.

## RC006-A2-F5 — SLA cohort identity contradiction

The exact defect, canonical authority, repository correction, B002 preservation boundary, and post-initial assertion-supersession protocol are recorded in `RC006_A2_BOUNDED_AMENDMENT_001_PRODUCT_LINE_SLA.md`.

Repository correction commit: `3465d229dd48f43005fc556fd079eb9eb9d91caa`.  
Bounded-amendment record commit: `c60cff898907929d9e166ca6135cecbc8e8888a6`.

No approved SLA percentage, duration, eligibility rule, cohort calendar rule, requirement identity, stable clause identity, or clause owner changed.

## RC006-A2-F6 — Infrastructure physical-model authority completeness

The accepted Infrastructure focused contract models Room/Rack physical structure and Component history more specifically than the stable canonical clauses currently establish. Existing canonical authority proves that a Network Element has one governing Site, may have Rack placement, derives Room through Rack, must use a same-Site Rack, persists Room/Rack placement in SQLite, and may represent Room/Rack in the Infrastructure workbook. It also proves that Component definitions/relationships are persistable and that Model/component concepts remain distinct from containment and connectivity.

What A2 has not identified is one stable owner for the complete focused-contract statements that a Site contains Rooms, a Room contains Racks, Rack row/column/position semantics belong to that hierarchy, devices of one Model may carry different installed Components, and reusable Model/BOM compatibility remains distinct from per-instance Component installation/removal history.

A2 itself cannot add authority to the frozen canonical set. Closure therefore requires either identification of already-existing stable authority or controlled normalization reopening outside A2. The accepted physical model should not be weakened merely to make the audit pass.

## RC006-A2-F7 — Stale Phase-0/A2 assurance-state representation

Pinned B002 Roadmap and Foundation Gaps retained two historical-status assertions that became false once A2 findings existed:

- Roadmap `Final Phase 0 gate state` claimed the reverse normative-assertion authority audit was already `PASS — 0 known unsupported assertions`, while the same Roadmap also stated current closure certification was suspended/open pending A2.
- Foundation Gaps stated Phase 0 closure remained pending only project-owner acceptance, even though the historical project-owner acceptance action already existed and the active closure gate was A2.

The A2 method explicitly preserves historical acceptance while stating that current closure certification remains suspended/open until A2 passes. The correction therefore changes only **current-status representation**, not historical acceptance or product policy.

Current HEAD corrections:

- `FOUNDATION_GAPS.md` — commit `1b695e7cd423034a777539da942de239ed21b3b9` now preserves `FND-GAP-001..016` as resolved while naming A2 as the current closure gate.
- `ROADMAP.md` — commit `9794bcfe58e642fb9a6ace81066e89f04c43e2e0` now distinguishes the historical pre-A2 reverse-audit result from the current OPEN A2 reverse-authority state.

Pinned B002 remains unchanged. Those baseline assertions shall receive explicit failed/superseded treatment rather than being silently reinterpreted.

## Current A2 status

Semantic pre-pass review is now complete for **all 16 destination sources**: Product, Import, RFC/WFM, Workbench, Product Line/SLA, Inventory Lifecycle, Infrastructure, Communications, UI/UX, Foundation Runtime, Architecture, Glossary, Decisions, Branding, Roadmap, and Foundation Gaps.

This does **not** make A2 PASS. Product and Import have the established stable-ID allocation/review frontier; RFC/WFM semantic review is complete but allocation remains blocked by F3; later destination sources have completed semantic pre-pass but still require formal extraction/allocation, forward-map edges, reverse-ledger disposition, and final validator reconciliation. F4/F6 remain unresolved authority gaps, F5 and affected F1/F7 B002 assertions require explicit supersession/disposition, and `RC006_A2_SECTION_DESTINATIONS.md` plus the maintained assertion ledger still require accumulated reconciliation against all 11,524 canonical clauses before RC-006-A2 can become PASS or receive a Phase-0 assurance addendum.
