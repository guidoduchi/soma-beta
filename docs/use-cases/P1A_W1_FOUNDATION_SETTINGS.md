# P1A-W1 — Foundation & Settings Use Cases

Status: **P1A-002 Rework complete — UC-001 accepted; UC-002 Proposed after Specification Gate; remaining entries Goal Seeds**

These entries do not select schema, APIs, frontend technology, libraries, algorithms, packaging, or other HLD/LLD mechanics. Except for `UC-001` and the explicitly `Proposed` `UC-002`, Goal Seeds are not acceptance-ready until expanded to the full `USE_CASE_METHOD.md` template and validated for authority.

## UC-001 — Initialize a new SOMA installation

Status: **Accepted — repository representation expanded non-semantically by P1A-002**

- **Primary actor:** Local Administrator.
- **Supporting actor/source:** System, for local environment/timezone detection and first-run state.
- **Goal:** Complete the mandatory first-run bootstrap so a fresh installation can enter normal use while optional business readiness remains progressive.
- **Trigger:** Launch of a fresh installation with no accepted administrator bootstrap.
- **Preconditions:** Authoritative local data instance is new/uninitialized for bootstrap; no accepted Local Administrator bootstrap exists.
- **Main success flow:** establish the one stable Local Administrator identity; set password/confirmation without requiring username; accept Light/Dark/System plus one built-in skin; confirm Objective/Task scheduling timezone using detected supported IANA value or `America/Guayaquil` fallback; present skippable/reopenable readiness for Customer, Contract, Contract Product Line, Contact, Dispatch Location, and Infrastructure; complete bootstrap and enter normal use.
- **Alternate / warning / conflict / stale / correction / cancellation / retry / failure flows:** password mismatch or invalid mandatory choice leaves bootstrap incomplete; unavailable/invalid timezone detection uses the accepted fallback; skipped/partial business readiness never becomes a global application-use gate; missing business setup blocks only actions that require it; no fallback SLA classification is fabricated; interruption before completion leaves bootstrap incomplete and safely resumable; post-bootstrap preference/profile changes occur through their own UCs rather than rewriting bootstrap history.
- **Postconditions / accepted-state effects:** exactly one Local Administrator identity and completed bootstrap state exist; authentication is initialized; appearance/skin and Objective scheduling timezone are accepted; optional business readiness may remain incomplete.
- **Preserved evidence/history:** bootstrap completion state, accepted administrator identity, accepted appearance/skin/timezone choices, and audit/security evidence required by the owning contracts; later changes preserve their own history rather than rewriting the initial event.
- **Owning domain:** Foundation / Settings.
- **Affected workspaces:** first-run bootstrap and Settings; readiness links may navigate to reference/Infrastructure setup without transferring ownership.
- **Governing requirements:** `BETA-REQ-0078` plus applicable authentication/presentation/temporal structural authority.
- **Canonical authority:** `ADMIN-SETUP-001..067`, limited here to the first-run behavioral subset; security/key/backup/password-change/auto-login families remain covered by later UCs and/or SI.
- **Related focused contracts:** Product Contract; `UI_UX_CONTRACT.md`; `FOUNDATION_RUNTIME_CONTRACT.md`; Objective-timezone boundaries in the owning Workbench/temporal authority.
- **Downstream HLD boundaries:** exact first-run routing/state-machine decomposition, secure password-verifier mechanics, OS timezone detection adapter, persistence transaction boundaries, and UI component composition remain HLD/LLD decisions; no frontend framework is selected here.
- **Acceptance scenarios:** fresh install cannot reach accepted bootstrap with invalid mandatory authentication input; successful bootstrap creates exactly one Local Administrator without a username requirement; timezone detection failure selects `America/Guayaquil` rather than inventing another timezone; skipping optional Customer/CPL/Contact/Infrastructure readiness still allows unrelated application use; no skipped readiness item fabricates fallback SLA/customer truth.
- **Structural companions:** security/key/backup invariants within `BETA-REQ-0078` are not blanket-covered by this UC.

## UC-002 — Authenticate to an established SOMA installation

Status: **Proposed — Specification Gate PASS; pending project-owner review**

- **Primary actor:** Local Administrator.
- **Supporting actor/source:** System, which verifies the local authentication credential and establishes the authenticated application context.
- **Goal:** Authenticate the installation's one Local Administrator through the governed password-login path without requiring or creating a username identity.
- **Trigger:** The established installation requires Local Administrator authentication and the password-login path is used.
- **Preconditions:** First-run bootstrap is complete; exactly one authenticating Local User Profile exists; its password verifier was established; the installation has not obtained equivalent access through a separately eligible automatic-login flow.
- **Main success flow:** present the password authentication control without a required username; accept the password attempt through the local authentication boundary; verify it against the stored approved verifier; on success establish authenticated Local Administrator access to the installation; preserve the same stable Local Administrator identity rather than creating another login profile.
- **Alternate / warning / conflict / stale / correction / cancellation / retry / failure flows:** an incorrect or unverifiable password leaves the installation unauthenticated and changes no business/domain state; cancelling or abandoning authentication grants no access; repeated attempts remain attempts against the same singleton profile rather than creating identities; automatic login is not performed or configured by this UC and remains governed by `UC-004`; password change/reset/recovery is not silently performed by failed login and remains governed by its own accepted workflow/design boundary.
- **Postconditions / accepted-state effects:** on success, the existing singleton Local Administrator is authenticated for application use; on failure/cancellation, no authenticated application state is established and no operational record is mutated.
- **Preserved evidence/history:** no plaintext/recoverable password is persisted by authentication; security/audit evidence, if required by the downstream security/audit design, must be minimized and must not contain the password or authentication secret. This UC does not invent a business lifecycle event for login.
- **Owning domain:** Foundation authentication.
- **Affected workspaces:** global application entry/authentication surface; authenticated access subsequently permits normal workspace use according to each owning domain.
- **Governing requirements:** `BETA-REQ-0035`, with the login-specific subset of `BETA-REQ-0078`.
- **Canonical authority:** `AUTH-001..004`, `AUTH-010`; `ADMIN-SETUP-007`, `ADMIN-SETUP-038..042` as applicable separation/security constraints. `AUTH-007..009` / `ADMIN-SETUP-043..045` belong primarily to `UC-004` automatic-login behavior and are supporting boundaries only here.
- **Related focused contracts:** `PRODUCT_CONTRACT.md` §3 Deployment and operator model; authentication/security persistence mechanics remain downstream design constrained by the normalized `AUTH`/`ADMIN-SETUP` clauses. `FOUNDATION_RUNTIME_CONTRACT.md` supplies audit/diagnostic and runtime security constraints only where applicable; it does not own password-login policy.
- **Downstream HLD boundaries:** exact authenticated-session representation and lifetime; authentication endpoint/service decomposition; verifier library and parameters within the accepted salted memory-hard requirement; failed-attempt throttling/telemetry policy if adopted without inventing product-visible lockout behavior; secure handling/zeroization of transient password material; CSRF/session-cookie mechanics for the localhost browser boundary; and exact audit/security-event treatment. No account-lockout, explicit application lock/unlock workflow, username login, second user, remote authentication, or password-reset behavior is authorized by this UC.
- **Acceptance scenarios:**
  1. Given a bootstrapped installation, the Local Administrator can authenticate with the valid password without entering a username.
  2. An invalid password does not establish authenticated access and does not mutate operational/domain state.
  3. Authentication always resolves to the one existing Local User Profile; retrying login never creates another profile or actor identity.
  4. The persisted authentication credential is a salted memory-hard verifier rather than a recoverable password, and the login password is not used as operational-data or portable-backup encryption authority.
  5. Automatic-login configuration/execution is not silently changed by ordinary password authentication and remains a separately governed capability.
  6. No explicit lock/unlock or account-lockout behavior is required or implied by this UC; such behavior would require accepted product authority before introduction.
- **Specification Gate result:** **PASS** — one actor goal; accepted authority verified; canonical owners verified; Product Contract destination verified; unsupported lock/unlock behavior removed; recovery/failure/evidence/design boundaries explicit; no duplicate with `UC-004`.

### UC-002 correction note

The original Goal Seed was titled **Authenticate, lock, and unlock the installation**. P1A Specification Gate review found no accepted normalized requirement or canonical clause authorizing an explicit application lock/unlock workflow. The seed was therefore narrowed before acceptance to the supported authentication goal. This is a removal of unsupported seed behavior, not a Phase-0 product-policy change.

## UC-003 — Maintain the Local Administrator profile and password

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Change editable administrator presentation metadata and authentication password without changing stable actor identity or encryption authority.
- **Trigger/preconditions:** Authenticated installation.
- **Main flow:** review profile; edit permitted display metadata; optionally change password through governed verification; save valid changes; record independent audit evidence.
- **Alternates/failures:** username-like metadata never becomes login identity; email/phone remain Contact data; password change never rekeys or derives live/backup encryption material; failed validation preserves prior accepted state.
- **Postconditions/evidence:** stable actor identity preserved; accepted profile/password change recorded separately.
- **Candidate authority:** `BETA-REQ-0021`, `0022`, `0035`, `0078`.

## UC-004 — Configure automatic login

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Enable or disable optional Windows-protected automatic login without storing the password or weakening the normal authentication boundary.
- **Trigger/preconditions:** Authenticated installation; bootstrap complete.
- **Main flow:** review current auto-login setting; deliberately enable or disable it; when enabling, establish only approved Windows-protected authentication material; confirm resulting state.
- **Alternates/failures:** unsupported/failed protection leaves auto-login disabled; stale/invalid protected material falls back to password login; password itself is never stored for this purpose.
- **Postconditions/evidence:** auto-login preference and protected-material state accepted/audited independently.
- **Candidate authority:** `BETA-REQ-0035`, `0078` (`ADMIN-SETUP-043..045`).

## UC-005 — Change appearance, skin, and Objective scheduling timezone

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Change local presentation preferences and the Objective/Task scheduling timezone after onboarding.
- **Trigger/preconditions:** Authenticated installation.
- **Main flow:** choose Light/Dark/System; choose governed built-in skin; preview/apply presentation; select supported IANA Objective timezone; review scheduling impact; accept changes.
- **Alternates/failures:** presentation preview is reversible; invalid timezone is rejected; timezone change does not reinterpret source timestamps, ordinary operational time, SLA time, or accepted historical instants.
- **Postconditions/evidence:** local preferences updated; future Objective/Task scheduling/grouping/presentation follows selected timezone; history remains intact.
- **Candidate authority:** `BETA-REQ-0078`, `0123..0130`, `0168`, `0177`.

## UC-006 — Manage Contacts

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Create, edit, archive/reactivate, and use reusable operational Contacts independently from the Local Administrator login identity.
- **Trigger/preconditions:** Authenticated installation.
- **Main flow:** create or select Contact; maintain name and optional communication channels/Customer affiliation; save governed changes; use eligible Contact in operational workflows; archive/reactivate when allowed.
- **Alternates/failures:** communication channels are optional until an action specifically requires one; archival cannot strand active dependencies; historical Contact references survive archival; duplicate-looking Contacts do not silently merge.
- **Postconditions/evidence:** stable Contact identity and history preserved.
- **Candidate authority:** `BETA-REQ-0021`, `0025`, `0028..0032`, `0067`.

## UC-007 — Manage Customer Organizations

Status: **Goal Seed — narrowed by P1A-002; Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Create, maintain, archive/reactivate, and reuse Customer Organizations without conflating them with Product Lines, Contracts, or Contract Product Lines.
- **Trigger/preconditions:** Authenticated installation; customer reference context is needed.
- **Main flow:** create/select Customer Organization; maintain permitted current reference facts; use it as owner/context only where owning domain allows; archive/reactivate when dependency rules permit.
- **Alternates/failures:** duplicate-looking names never silently merge identity; archival cannot strand active dependencies; historical references remain interpretable.
- **Postconditions/evidence:** stable Customer Organization identity and reference history.
- **Candidate authority:** `BETA-REQ-0021`, `0025`, applicable reference/customer clauses.

## UC-008 — Manage Dispatch Locations

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Create and maintain customer-neutral logistics locations, including site-bound dedicated locations where applicable.
- **Trigger/preconditions:** Authenticated installation.
- **Main flow:** create independent Dispatch Location or manage one produced with a Site; maintain address according to owning rules; select it in eligible logistics workflows; archive/reactivate when safe.
- **Alternates/failures:** a Site-linked location derives current address from the Site; a Dispatch Location never acquires Customer ownership merely through use; archival is blocked by active Site/logistics dependencies; historical logistics snapshots remain frozen.
- **Postconditions/evidence:** stable location identity/history and valid active/archive state.
- **Candidate authority:** `BETA-REQ-0023..0026`, `0034`, applicable Fault Tag/Spare Request logistics families.

## UC-009 — Create and manage verified backups

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Create a protected managed or portable backup and retain a verified recoverable set without unsafe pruning.
- **Trigger/preconditions:** Authenticated installation; backup capability available.
- **Main flow:** request backup; produce protected backup under the accepted security envelope; authenticate/integrity/structurally verify it; record success; for managed rotation, prune only after verified replacement and keep configured retention (default five).
- **Alternates/failures:** failed verification prevents pruning; last verified restorable copy is never automatically deleted; operator-exported portable backups are outside managed pruning; recovery secret remains independent from login password/live key.
- **Postconditions/evidence:** verified backup plus immutable backup/verification history.
- **Candidate authority:** `BETA-REQ-0037`, `0078`; Foundation Runtime; Roadmap security boundary.

## UC-010 — Restore or recover an installation from protected backup

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Recover authoritative SOMA data from an eligible protected backup without silently accepting damaged, wrong, or incompatible material.
- **Trigger/preconditions:** Restore/recovery action; candidate backup and required recovery authority available.
- **Main flow:** select candidate; authenticate/decrypt/validate according to accepted security contract; verify structure/integrity and compatibility; preview material consequence where required; restore atomically; verify restored authoritative state before normal use.
- **Alternates/failures:** wrong secret, damaged/incompatible backup, interruption, or failed integrity leaves prior/last valid state safe; exact recovery mechanics remain `O-005`/LLD.
- **Postconditions/evidence:** restored verified data instance and recovery audit/history.
- **Candidate authority:** `BETA-REQ-0037`, `0078`, `0131..0144`; Foundation Runtime.

## UC-011 — Start, reuse, and stop the local SOMA instance

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator / System.
- **Goal:** Reach one verified ready local SOMA instance, reuse it on repeated launch, and shut it down safely.
- **Trigger/preconditions:** Application launch, repeated launch, tray/exit/shutdown action.
- **Main flow:** acquire/verify ownership of intended data instance; complete required startup/migration/integrity readiness; expose only loopback service; open/activate verified instance; on repeated launch activate exact existing instance rather than competing; on shutdown stop new mutations and close/release safely.
- **Alternates/failures:** stale registry/PID/port never proves identity; conflicting or unhealthy instance yields bounded failure; forced shutdown revalidates exact target; tray/background exact mechanics remain `O-010`.
- **Postconditions/evidence:** at most one authoritative local instance per data instance; clean ready/stopped state and technical/audit evidence as applicable.
- **Candidate authority:** `BETA-REQ-0002..0004`, `0140`; Foundation Runtime.

## UC-012 — Inspect runtime, migration, and diagnostic status

Status: **Goal Seed — Specification Gate pending**
- **Primary actor:** Local Administrator.
- **Goal:** Determine installation/runtime health and migration state without causing hidden mutation, and access safe technical diagnostics when troubleshooting is needed.
- **Trigger/preconditions:** Operator requests status/diagnostic information.
- **Main flow:** inspect observational migration/runtime status; distinguish not initialized/current/pending/drift/future/invalid/integrity/locked/inspection failure; view allowlisted redacted diagnostics where applicable.
- **Alternates/failures:** status inspection does not initialize/migrate/repair/touch a missing or existing database; diagnostics remain non-authoritative and redact/minimize sensitive data; live-instance limitations are reported rather than disturbed.
- **Postconditions/evidence:** no business mutation; operator receives truthful bounded status/diagnostic information.
- **Candidate authority:** `BETA-REQ-0133..0144`; Foundation Runtime.

## UC-078 — Manage reusable Product Lines

Status: **Goal Seed — extracted from former UC-007 by P1A-002**
- **Primary actor:** Local Administrator.
- **Goal:** Create and maintain reusable Product Lines independently from any one Customer or Contract.
- **Trigger/preconditions:** Authenticated installation; product classification reference is needed.
- **Main flow:** create/select Product Line; maintain permitted descriptive facts; reuse the same identity across eligible customer Contracts; archive/reactivate when allowed.
- **Alternates/failures:** equal-looking labels never silently merge; Product Line itself does not own customer-specific SLA policy.
- **Postconditions/evidence:** stable reusable Product Line identity/history.
- **Candidate authority:** `BETA-REQ-0064..0065`, `0173..0175`; Product Line/SLA Contract.

## UC-079 — Manage Contracts

Status: **Goal Seed — extracted from former UC-007 by P1A-002**
- **Primary actor:** Local Administrator.
- **Goal:** Create and maintain Contracts owned by one Customer Organization without collapsing Contract identity into Product Line or SLA policy.
- **Trigger/preconditions:** Customer Organization exists; contract context is required.
- **Main flow:** create/select Contract; bind it to its Customer owner; maintain allowed reference facts; archive/reactivate when dependencies permit.
- **Alternates/failures:** a Contract cannot silently transfer to another Customer; archival cannot strand active CPL/classification dependencies.
- **Postconditions/evidence:** stable Contract identity/Customer ownership/history.
- **Candidate authority:** `BETA-REQ-0064..0065`, `0173..0175`; Product Line/SLA Contract.

## UC-080 — Manage Contract Product Lines and customer-specific SLA policy

Status: **Goal Seed — extracted from former UC-007 by P1A-002**
- **Primary actor:** Local Administrator.
- **Goal:** Join one reusable Product Line to one Customer-owned Contract and maintain the customer/contract-specific SLA policy that governs compatible SR classifications.
- **Trigger/preconditions:** Contract and Product Line exist.
- **Main flow:** create/select Contract Product Line; validate Contract/Product Line relationship; maintain applicable SLA policy/tier/cohort rules; archive/reactivate according to dependencies.
- **Alternates/failures:** the same Product Line may participate in different CPLs with different policies; policy change affects current derived classification/SLA behavior as governed but never rewrites completed reports.
- **Postconditions/evidence:** stable CPL identity, current policy, and preserved policy/lifecycle history.
- **Candidate authority:** `BETA-REQ-0064..0065`, `0173..0175`; Product Line/SLA Contract.
