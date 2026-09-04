# RC-006-A2 — Section-Level Assurance Findings

Status: **OPEN with F1–F2 corrected; A2 section-destination map remains incomplete**  
Parent method: `RC006_A2_SECTION_DESTINATION_ASSURANCE.md`  
Phase-0 product authority: **accepted and unchanged**.

## Finding register

| ID | Severity | Finding | Authority | Disposition | Status |
|---|---|---|---|---|---|
| `RC006-A2-F1` | HIGH representation defect | `PRODUCT_CONTRACT.md` §7 stated that a Local Task may link to zero-many **Network Elements**, which conflicts with canonical Device Reference authority and the Workbench/Infrastructure representation. | `BETA-REQ-0049`, especially `DEVICE-REF-002`, `004`, `005`, `010..012`; Infrastructure Contract §§2–3; Workbench Contract §2.5 | Replace direct Network Element wording with zero-many **Device References**; state that a Device Reference may remain external or resolve to one Network Element and that regularization preserves the Task-to-Device-Reference relationship/history. | **CORRECTED** |
| `RC006-A2-F2` | HIGH representation defect | `ROADMAP.md` Phase 4 still required explicit application **lock/unlock** behavior and a “lock” acceptance action even though Phase-1A authority review found no accepted normalized/canonical authority for an application lock/unlock workflow. | `BETA-REQ-0035` (`AUTH-001..010`), `BETA-REQ-0078` login/auto-login/security families; UC-002 reverse-authority result; no canonical lock/unlock clause found | Remove explicit application lock/unlock from Phase 4 delivery/exit wording; retain password authentication, auto-login, protected local session/security mechanics, backup/recovery, and downstream session design without inventing product-visible locking. | **CORRECTED** |

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

## Current A2 status

F1–F2 demonstrate why section-level forward/reverse assurance is useful, but they do not complete A2. `RC006_A2_SECTION_DESTINATIONS.md` must still be produced and mechanically/semantically validated against all 11,524 canonical clauses before RC-006-A2 can become PASS or receive a Phase-0 assurance addendum.
