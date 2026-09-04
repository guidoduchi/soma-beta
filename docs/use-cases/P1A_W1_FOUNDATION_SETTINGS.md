# P1A-W1 — Foundation & Settings Use Cases

Status: **Draft catalogue; UC-001 accepted, UC-002..UC-012 pending owner review**

These use cases are product-behavior drafts only. They do not select schema, APIs, frontend technology, libraries, algorithms, packaging, or other HLD/LLD mechanics.

## UC-001 — Initialize a new SOMA installation

Status: **Accepted**

- **Primary actor:** Local Administrator.
- **Goal:** Complete the mandatory first-run bootstrap so a fresh installation can enter normal use while optional business readiness remains progressive.
- **Trigger / preconditions:** Fresh installation; no accepted administrator bootstrap exists.
- **Main flow:** establish the one stable Local Administrator identity; set password/confirmation without requiring username; accept Light/Dark/System plus one built-in skin; confirm Objective/Task scheduling timezone using detected supported IANA value or `America/Guayaquil` fallback; present skippable/reopenable readiness for Customer, Contract, CPL, Contact, Dispatch Location, and Infrastructure; complete bootstrap.
- **Alternates/failures:** password mismatch or invalid mandatory choice leaves bootstrap incomplete; unavailable timezone detection uses fallback; skipped/partial readiness never becomes a global application-use gate; missing business setup blocks only the action that needs it; no fallback SLA classification is fabricated.
- **Postconditions/evidence:** administrator identity and bootstrap state exist; authentication initialized; appearance/skin/timezone accepted; readiness state preserved.
- **Authority:** `BETA-REQ-0078` (`ADMIN-SETUP` behavioral subset), Product Contract, UI/UX and Runtime contracts.
- **Structural companions:** security/key/backup invariants within `0078` remain SI and/or later UCs rather than being blanket-covered here.

## UC-002 — Authenticate, lock, and unlock the installation

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Enter an established SOMA installation, lock it when appropriate, and regain access without creating additional login identities.
- **Trigger / preconditions:** Bootstrap complete; Local Administrator authentication exists.
- **Main flow:** present password-only authentication unless eligible automatic login is active; verify the Local Administrator; establish the local authenticated session; allow explicit lock; require valid authentication to unlock.
- **Alternates/failures:** wrong password reveals no protected data; unavailable/invalid automatic-login material falls back safely to password authentication; lock/unlock failure never fabricates an authenticated state.
- **Postconditions/evidence:** exactly one authenticated local actor/session state; security/audit evidence where required.
- **Authority:** `BETA-REQ-0035`, `0078`; Product Contract; Foundation Runtime.

## UC-003 — Maintain the Local Administrator profile and password

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Change editable administrator presentation metadata and authentication password without changing stable actor identity or encryption authority.
- **Trigger / preconditions:** Authenticated installation.
- **Main flow:** review profile; edit permitted display metadata; optionally change password through governed verification; save valid changes; record independent audit evidence.
- **Alternates/failures:** username-like metadata never becomes login identity; email/phone remain Contact data; password change never rekeys or derives live/backup encryption material; failed validation preserves prior accepted state.
- **Postconditions/evidence:** stable actor identity preserved; accepted profile/password change recorded separately.
- **Authority:** `BETA-REQ-0021`, `0022`, `0035`, `0078`.

## UC-004 — Configure automatic login

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Enable or disable optional Windows-protected automatic login without storing the password or weakening the normal authentication boundary.
- **Trigger / preconditions:** Authenticated installation; bootstrap complete.
- **Main flow:** review current auto-login setting; deliberately enable or disable it; when enabling, establish only approved Windows-protected authentication material; confirm resulting state.
- **Alternates/failures:** unsupported/failed protection leaves auto-login disabled; stale/invalid protected material falls back to password login; password itself is never stored for this purpose.
- **Postconditions/evidence:** auto-login preference and protected-material state accepted/audited independently.
- **Authority:** `BETA-REQ-0035`, `0078` (`ADMIN-SETUP-043..045`).

## UC-005 — Change appearance, skin, and Objective scheduling timezone

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Change local presentation preferences and the Objective/Task scheduling timezone after onboarding.
- **Trigger / preconditions:** Authenticated installation.
- **Main flow:** choose Light/Dark/System; choose governed built-in skin; preview/apply presentation; select supported IANA Objective timezone; review scheduling impact; accept changes.
- **Alternates/failures:** presentation preview is reversible; invalid timezone is rejected; timezone change does not reinterpret source timestamps, ordinary operational time, SLA time, or accepted historical instants.
- **Postconditions/evidence:** local preferences updated; future Objective/Task scheduling/grouping/presentation follows selected timezone; history remains intact.
- **Authority:** `BETA-REQ-0078`, `0123..0130`, `0168`, `0177`; UI/UX Contract.

## UC-006 — Manage Contacts

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Create, edit, archive/reactivate, and use reusable operational Contacts independently from the Local Administrator login identity.
- **Trigger / preconditions:** Authenticated installation.
- **Main flow:** create or select Contact; maintain name and optional communication channels/Customer affiliation; save governed changes; use eligible Contact in operational workflows; archive/reactivate when allowed.
- **Alternates/failures:** communication channels are optional until an action specifically requires one; archival cannot strand active dependencies; historical Contact references survive archival; duplicate-looking Contacts do not silently merge.
- **Postconditions/evidence:** stable Contact identity and history preserved.
- **Authority:** `BETA-REQ-0021`, `0025`, `0028..0032`, `0067`.

## UC-007 — Manage Customers, Product Lines, Contracts, and Contract Product Lines

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Maintain the reusable commercial/reference structure needed for ticket classification and customer-specific SLA policy.
- **Trigger / preconditions:** Authenticated installation.
- **Main flow:** create/review Customer Organization; create reusable Product Line; create Contract owned by one Customer; create Contract Product Line joining that Contract and Product Line; maintain customer/contract-specific SLA policy; archive/reactivate eligible references.
- **Alternates/failures:** same Product Line may be reused by different customers/contracts with different policy; archived/inactive CPL is not eligible for new active classification unless its lifecycle permits; archival cannot strand active dependencies.
- **Postconditions/evidence:** reference identities/history preserved; current CPL policy becomes classification/SLA authority for compatible SRs.
- **Authority:** `BETA-REQ-0021`, `0025`, `0064..0065`, `0173..0175`; Product Line/SLA Contract.

## UC-008 — Manage Dispatch Locations

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Create and maintain customer-neutral logistics locations, including site-bound dedicated locations where applicable.
- **Trigger / preconditions:** Authenticated installation.
- **Main flow:** create independent Dispatch Location or manage one produced with a Site; maintain address according to owning rules; select it in eligible logistics workflows; archive/reactivate when safe.
- **Alternates/failures:** a Site-linked location derives current address from the Site; a Dispatch Location never acquires Customer ownership merely through use; archival is blocked by active Site/logistics dependencies; historical logistics snapshots remain frozen.
- **Postconditions/evidence:** stable location identity/history and valid active/archive state.
- **Authority:** `BETA-REQ-0023..0026`, `0034`, `0097`, Infrastructure/Inventory contracts.

## UC-009 — Create and manage verified backups

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Create a protected managed or portable backup and retain a verified recoverable set without unsafe pruning.
- **Trigger / preconditions:** Authenticated installation; backup capability available.
- **Main flow:** request backup; produce protected backup under the accepted security envelope; authenticate/integrity/structurally verify it; record success; for managed rotation, prune only after verified replacement and keep configured retention (default five).
- **Alternates/failures:** failed verification prevents pruning; last verified restorable copy is never automatically deleted; operator-exported portable backups are outside managed pruning; recovery secret remains independent from login password/live key.
- **Postconditions/evidence:** verified backup plus immutable backup/verification history.
- **Authority:** `BETA-REQ-0037`, `0078`; Foundation Runtime; Roadmap security boundary.

## UC-010 — Restore or recover an installation from protected backup

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Recover authoritative SOMA data from an eligible protected backup without silently accepting damaged, wrong, or incompatible material.
- **Trigger / preconditions:** Restore/recovery action; candidate backup and required recovery authority available.
- **Main flow:** select candidate; authenticate/decrypt/validate according to accepted security contract; verify structure/integrity and compatibility; preview material consequence where required; restore atomically; verify restored authoritative state before normal use.
- **Alternates/failures:** wrong secret, damaged/incompatible backup, interruption, or failed integrity leaves prior/last valid state safe; exact recovery mechanics remain `O-005`/LLD.
- **Postconditions/evidence:** restored verified data instance and recovery audit/history.
- **Authority:** `BETA-REQ-0037`, `0078`, `0131..0144`; Foundation Runtime.

## UC-011 — Start, reuse, and stop the local SOMA instance

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator / System.
- **Goal:** Reach one verified ready local SOMA instance, reuse it on repeated launch, and shut it down safely.
- **Trigger / preconditions:** Application launch, repeated launch, tray/exit/shutdown action.
- **Main flow:** acquire/verify ownership of intended data instance; complete required startup/migration/integrity readiness; expose only loopback service; open/activate verified instance; on repeated launch activate exact existing instance rather than competing; on shutdown stop new mutations and close/release safely.
- **Alternates/failures:** stale registry/PID/port never proves identity; conflicting or unhealthy instance yields bounded failure; forced shutdown revalidates exact target; tray/background exact mechanics remain `O-010`.
- **Postconditions/evidence:** at most one authoritative local instance per data instance; clean ready/stopped state and technical/audit evidence as applicable.
- **Authority:** `BETA-REQ-0002..0004`, `0140`; Foundation Runtime.

## UC-012 — Inspect runtime, migration, and diagnostic status

Status: **Draft — pending owner review**

- **Primary actor:** Local Administrator.
- **Goal:** Determine installation/runtime health and migration state without causing hidden mutation, and access safe technical diagnostics when troubleshooting is needed.
- **Trigger / preconditions:** Operator requests status/diagnostic information.
- **Main flow:** inspect observational migration/runtime status; distinguish not initialized/current/pending/drift/future/invalid/integrity/locked/inspection failure; view allowlisted redacted diagnostics where applicable.
- **Alternates/failures:** status inspection does not initialize/migrate/repair/touch a missing or existing database; diagnostics remain non-authoritative and redact/minimize sensitive data; live-instance limitations are reported rather than disturbed.
- **Postconditions/evidence:** no business mutation; operator receives truthful bounded status/diagnostic information.
- **Authority:** `BETA-REQ-0133..0144`; Foundation Runtime.
