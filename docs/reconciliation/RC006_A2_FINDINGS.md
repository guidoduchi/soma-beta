# RC-006-A2 — Section-Level Assurance Findings

Status: **OPEN with F1–F2 corrected; F3–F4 open; F5 corrected in HEAD with bounded supersession pending; A2 section-destination map remains incomplete**  
Parent method: `RC006_A2_SECTION_DESTINATION_ASSURANCE.md`  
Phase-0 product authority: **accepted; F4 identifies a normalization-authority omission for already-accepted Workbench behavior; F5 corrects a destination contradiction without changing approved SLA policy**.

## Finding register

| ID | Severity | Finding | Authority | Disposition | Status |
|---|---|---|---|---|---|
| `RC006-A2-F1` | HIGH representation defect | `PRODUCT_CONTRACT.md` §7 stated that a Local Task may link to zero-many **Network Elements**, which conflicts with canonical Device Reference authority and the Workbench/Infrastructure representation. | `BETA-REQ-0049`, especially `DEVICE-REF-002`, `004`, `005`, `010..012`; Infrastructure Contract §§2–3; Workbench Contract §2.5 | Replace direct Network Element wording with zero-many **Device References**; state that a Device Reference may remain external or resolve to one Network Element and that regularization preserves the Task-to-Device-Reference relationship/history. | **CORRECTED** |
| `RC006-A2-F2` | HIGH representation defect | `ROADMAP.md` Phase 4 still required explicit application **lock/unlock** behavior and a “lock” acceptance action even though Phase-1A authority review found no accepted normalized/canonical authority for an application lock/unlock workflow. | `BETA-REQ-0035` (`AUTH-001..010`), `BETA-REQ-0078` login/auto-login/security families; UC-002 reverse-authority result; no canonical lock/unlock clause found | Remove explicit application lock/unlock from Phase 4 delivery/exit wording; retain password authentication, auto-login, protected local session/security mechanics, backup/recovery, and downstream session design without inventing product-visible locking. | **CORRECTED** |
| `RC006-A2-F3` | MEDIUM assurance-mechanics blocker | The unallocated RFC/WFM candidate corpus contains stored `fingerprint_sha256` values that do not consistently equal SHA-256 of the documented NFC/LF-normalized `exact_text`. Candidate text, locators, ordering, and semantic review remain intact, but the corpus cannot pass the frozen fingerprint contract as written. | `A2-EXTRACTION-SCHEMA-V1` fingerprint rule; `RC006_A2_SCHEMA_AMENDMENT_001.md`; B002 RFC/WFM blob `433ffbea4fe291e451b0fefc2b2c8a999c1b1894` | Regenerate only the pre-allocation candidate fingerprint fields from unchanged reviewed `exact_text`; verify all 171 records and source spans; refreeze before stable-ID allocation. Do not alter source text, boundaries, classification, semantic dispositions, or B002. | **OPEN — PRE-ALLOCATION BLOCKER** |
| `RC006-A2-F4` | HIGH reverse-authority gap | `WORKBENCH_CONTRACT.md` §3.2 allows an RFC with no linked SR to receive registered or unregistered Device References directly, and §3.3 states subordinate RFCs may have different involved devices; canonical `DEVICE-REF` authority directly enumerates SR and Task relationships but no RFC→Device Reference owner has been identified. | Workbench Contract §§3.2–3.3; `BETA-REQ-0049` `DEVICE-REF-001..014`; RFC hierarchy/relationship authority reviewed with no direct RFC→Device owner found | Preserve the accepted Workbench behavior; add controlled canonical authority for direct RFC→Device Reference context, including standalone/no-SR RFCs and subordinate RFCs, without converting it to direct RFC→Network Element identity and without changing SR→Master/root relationship rules. | **OPEN — NORMALIZATION AUTHORITY REQUIRED** |
| `RC006-A2-F5` | HIGH semantic contradiction | B002 `PRODUCT_LINE_SLA.md` §6 incorrectly listed `current compliance outcome` as a canonical SLA cohort partition dimension, contradicting `SLA-COHORT-049` and making percentage denominator identity self-referential. | `BETA-REQ-0175` `SLA-COHORT-001..120`; bounded amendment `RC006_A2_BOUNDED_AMENDMENT_001_PRODUCT_LINE_SLA.md` | Repository HEAD corrected the cohort key to calendar month + Customer + Contract + Contract Product Line + severity + policy tier, with outcome derived afterward. Preserve B002 unchanged; allocate the B002 assertion as failed/open, then supersede it through post-initial AMENDMENT allocation under the bounded-amendment protocol. | **HEAD CORRECTED / B002 SUPERSESSION PENDING** |

## RC006-A2-F1 — Task device relationship synthesis

### Defective representation

`PRODUCT_CONTRACT.md` §7 previously stated:

> A Local Task requires only a Task Name from the operator. It may link independently to zero or many SRs, zero or many RFCs—including subordinate RFCs—zero or many Spare Part Units, and zero or many Network Elements.

### Accepted authority

Canonical `BETA-REQ-0049` states:

- `DEVICE-REF-001` — Service Requests may relate directly to affected Device References.
- `DEVICE-REF-002` — Local Tasks and WFM Tasks may relate directly to zero or more affected Device References.
- `DEVICE-REF-004` — Device References may remain valid external/unregistered operational references.
- `DEVICE-REF-005` — a Device Reference may resolve to a registered Network Element.
- `DEVICE-REF-010..014` — regularization preserves Device Reference operational identity and existing SR/Task/Objective/Spare relationships/history.

The Infrastructure Contract likewise defines Device Reference as the operational identity used across Tickets, Tasks, Objectives, and Inventory, while Network Element is the registered Infrastructure device instance. The Workbench Task flow selects participating Device References.

### Correction

`PRODUCT_CONTRACT.md` §7 now states that the Local Task may link to zero-many **Device References**, and explicitly preserves the distinction:

- Device Reference = operational Task relationship identity;
- Network Element = optional registered Infrastructure resolution target;
- regularization does not replace/repoint the Task relationship as a direct Network Element relationship.

### Product-authority effect

- requirement identity changed: **0**;
- canonical clause changed: **0**;
- clause owner changed: **0**;
- accepted behavior changed: **0**;
- synthesis representation corrected: **1**.

This is a Phase-0 representation correction discovered by post-closure assurance hardening. It does not invalidate the historical Phase-0 acceptance action and does not introduce a new product decision.

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

The corrective direction is therefore **authority completion**, not removal of the Workbench behavior: add a controlled normalized owner that preserves Device Reference as the operational identity, permits no-SR and subordinate RFC device context, and does not create a competing direct SR→subordinate relationship.

## RC006-A2-F5 — SLA cohort identity contradiction

The exact defect, canonical authority, repository correction, B002 preservation boundary, and post-initial assertion-supersession protocol are recorded in `RC006_A2_BOUNDED_AMENDMENT_001_PRODUCT_LINE_SLA.md`.

Repository correction commit: `3465d229dd48f43005fc556fd079eb9eb9d91caa`.  
Bounded-amendment record commit: `c60cff898907929d9e166ca6135cecbc8e8888a6`.

No approved SLA percentage, duration, eligibility rule, cohort calendar rule, requirement identity, stable clause identity, or clause owner changed.

## Current A2 status

F1–F5 demonstrate why section-level forward/reverse assurance is useful, but they do not complete A2. Product and Import are semantically reviewed; RFC/WFM semantic review is complete but allocation is blocked by F3; Workbench and Product Line/SLA have completed semantic pre-passes with F4/F5 requiring controlled treatment. `RC006_A2_SECTION_DESTINATIONS.md` and the maintained assertion ledger still require accumulated reconciliation against all 11,524 canonical clauses before RC-006-A2 can become PASS or receive a Phase-0 assurance addendum.
