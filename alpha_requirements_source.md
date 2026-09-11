# SOMA 1 Requirements Baseline

**Baseline:** Foundation 1 + accepted Phase 1C
**Last reviewed:** 2026-08-22
**Status:** Foundation 1 and Phase 1C accepted; all planned Phase 1D slices implemented and Phase 1D promotion review active

This document is the self-contained product and engineering requirements baseline for SOMA 1. Accepted cross-cutting details may be expanded in focused contracts such as `ADVANCED_SEARCH_CONTRACT.md` and `MIGRATION_002_DESIGN.md`, but those focused documents may not weaken these requirements.

## Interpretation and precedence

When sources conflict, use this order:

1. The latest explicit SOMA 1 decision.
2. This requirements baseline and accepted focused contracts.
3. Earlier SOMA design discussion.
4. Zeus behavior, only as historical input.

SOMA is a clean product lineage. Zeus may establish useful operational vocabulary/evidence, but prototype mechanics are not automatically SOMA requirements.

Current focused authorities are deliberately non-overlapping:

- `ADVANCED_SEARCH_CONTRACT.md` owns detailed source and synchronization semantics;
- `PHASE1C_PROMOTED_REPORT_FINALIZATION_CONTRACT.md` owns report-confirmed immediate finalization/privacy cleanup;
- `RETENTION_AND_SECURITY_POLICY.md` owns the later due snapshot/deep-purge and key/backup policy;
- `APPLICATION_SERVICES.md` owns use-case and transaction boundaries; and
- `MIGRATION_002_DESIGN.md` explains the accepted/frozen `002` persistence boundary.

Phase contracts and review reports provide implementation/verification evidence; they do not silently supersede Requirements or the decision ledger. `001_initial.sql` and `002_phase1_application.sql` are frozen on `main`; future persistence changes are forward-only.

## Status vocabulary for requirement delivery

- **Foundation** — represented/protected by current schema, migration runner, runtime, or tests.
- **Application** — required behavior for service/API/UI layers.
- **Deferred** — intentionally postponed until its prerequisite exists.
- **Open** — needs a business/sample/engineering decision before implementation.

## Product and operating model

| ID | Requirement | Delivery |
|---|---|---|
| PROD-001 | SOMA shall be a clean Service Operations Management Application, not a rename/history continuation of Zeus. | Foundation |
| PROD-002 | The intended UX shall be a localhost web application backed by Python. | Application |
| PROD-003 | Operational data shall remain locally usable without a separately administered database server. | Foundation |
| PROD-004 | Supported product targets are 64-bit Windows 10/11 with Python 3.13 or 3.14. Other OSes are not support targets. | Foundation/CI |
| PROD-005 | Source shall remain distributable under Apache License 2.0 with applicable attribution retained. | Foundation |
| PROD-006 | Runtime/customer/mail/credential/log/database/backup/export data shall not be committed to source control. | Foundation/Application |
| PROD-007 | SOMA 1 stable shall meet or deliberately replace every approved user-facing Zeus capability through explicit parity disposition. | Application/Release |
| PROD-008 | SOMA shall provide repeatable local setup plus explicit run/stop commands; Windows source deployments include direct launchers. | Foundation |

## Identity and common data rules

| ID | Requirement | Delivery |
|---|---|---|
| DATA-001 | Internal SOMA IDs are independent strings; external business identifiers are not relational primary keys. | Foundation |
| DATA-002 | Service Request identity is exactly eight digits. `SR`/`TT` are display contexts only. | Foundation |
| DATA-003 | RFC identity is `NC` plus fourteen digits. | Foundation |
| DATA-004 | WFM identity is `TK` plus fourteen digits. | Foundation |
| DATA-005 | Permanent Spare Request identity is `SR` plus seven digits; pre-assignment tracking ID is twelve digits. | Foundation |
| DATA-006 | Requested physical spare identity is `C` plus ten digits. | Foundation |
| DATA-007 | Canonical scheduled timestamps use UTC `YYYY-MM-DDTHH:MM:SSZ`; MW boundaries fall on `:00`/`:30`. | Foundation |
| DATA-008 | Required text PK/FK/enumerated/JSON facts are validated at the DB boundary. | Foundation |
| DATA-009 | Referenced history is normally archived/cancelled/superseded/rolled back rather than silently deleted. | Foundation/Application |
| DATA-010 | Mutable logistics master data shall not rewrite historical delivery/pickup evidence; operations preserve immutable site snapshots where needed. | Foundation/Application |

## Reference data and people

| ID | Requirement | Delivery |
|---|---|---|
| REF-001 | SOMA shall manage Customer Organizations and Contacts. | Foundation/Application |
| REF-002 | SOMA shall manage reusable Requesters and one local user profile. | Foundation/Application |
| REF-003 | Dispatch Sites represent reusable logistics locations for Spare Request/Fault Tag workflows. | Foundation/Application |
| REF-004 | Datacenter Sites represent infrastructure locations and remain distinct from Dispatch Sites. | Foundation/Application |
| REF-005 | Reference records with operational history support archival. | Foundation/Application |
| REF-006 | Customer Organization↔Dispatch Site is many-to-many; at most one preferred site per customer. | Foundation |
| REF-007 | Every Datacenter Site belongs to exactly one Customer Organization; Managed Elements may derive customer ownership through the site. | Foundation/Application |
| REF-008 | Customer Contact relational identity uses internal SOMA ID. Names are descriptive/may collide. Normalized email is scoped matching data, not a global primary identity. | Application |
| REF-009 | Organization-bound Contact identity preserves the organization under which SOMA knew the person. Moving organization creates a new contact row. If an SR selects an organization-bound contact, SR organization must exist/match it. | Application/Frozen `002` + candidate `003` |
| REF-010 | Advanced Search reference matching uses deterministic exact keys produced by Unicode NFKC compatibility normalization, collapse of surrounding/internal Unicode whitespace, and Unicode case folding. It does not strip accents or punctuation and does not use fuzzy similarity. If normalization maps multiple active records in the same accepted scope to one key, the result is ambiguous and SOMA must not guess. | Application |
| REF-011 | New Contacts require one active Customer Organization. A Foundation-era unbound Contact may be bound once; a bound Contact cannot move or unbind. Archived master records cannot receive new active operational references, and archive/reactivation operations must not strand active dependents. | Phase 1D application/candidate `003` |
| REF-012 | Requesters are reusable descriptive records. Archived Requesters cannot remain pinned, and a Requester cannot be archived while a nonarchived nonterminal Spare Request uses it. Terminal history may retain the reference. | Phase 1D application/candidate `003` |
| REF-013 | Datacenter Site ownership is stable. Ordinary edits cannot transfer it; an explicitly reasoned correction may change an erroneous initial Customer Organization only before direct site or Managed Element operational use/evidence. Archival cannot strand active Managed Elements or unfinished active Maintenance Windows. | Phase 1D application/candidate `003` |
| REF-014 | Dispatch Site Customer associations express optional availability/convenience rather than ownership. Preference is at most one per Customer, new active work cannot select archived sites, and a preferred or live-operation site cannot be archived until the blocking state is resolved. | Phase 1D application/candidate `003` |
| REF-015 | Completing the singleton Local User Profile is one-way. Public profile/policy edits preserve protected-key metadata; username is never key material. Concrete DPAPI key creation/recovery and verified finite backup rotation remain adapter work. | Phase 1D application/candidate `003` + deferred adapter |

## Service Requests, RFCs, WFMs, and Maintenance Windows

| ID | Requirement | Delivery |
|---|---|---|
| OPS-001 | Service Requests are pivotal when present, but RFCs/MWs/Spare Requests/other operational records may exist independently. | Foundation |
| OPS-002 | SR↔RFC is many-to-many; a direct SR link may target only a master RFC. | Foundation |
| OPS-003 | RFC hierarchy is exactly master/subordinate; subordinate cannot own subordinates. | Foundation |
| OPS-004 | Each WFM belongs to exactly one RFC and zero/one MW. | Foundation |
| OPS-005 | Within one MW, an RFC has at most one WFM; retry uses a new WFM ticket. | Foundation |
| OPS-006 | MW is first-class and may exist without SR/RFC/WFM/Spare Request/Managed Element. | Foundation |
| OPS-007 | Explicit SR/MW association is stored only when deliberately created; reachable SR context through WFM/RFC is derived. | Foundation/Application |
| OPS-008 | One SR may have unlimited terminal MW history but at most one unfinished MW. | Foundation |
| OPS-009 | MW retry is a new MW superseding one prior attempt; one attempt has at most one direct successor. | Foundation/Application |
| OPS-010 | Scheduled MW start is canonical half-hour UTC; end is later than start. | Foundation |
| OPS-011 | MW selection begins from the master-RFC WFM, resolves subordinate RFCs, and surfaces missing same-window subordinate WFMs as warnings. | Application |
| OPS-012 | SRs/WFMs/MWs link directly to affected/intervened Managed Elements without requiring a spare. | Foundation |
| OPS-013 | Due completed/incomplete MW attempts are surfaced for operator review; incomplete attempts count as awaiting review. | Application |
| OPS-014 | Users create/edit/link/regroup/cancel/archive/retry MWs from MW management, including initially standalone MWs. Hard deletion is not the historical correction mechanism. | Application |
| OPS-015 | An SR supports multiple independent operational notes with author/time/archive metadata. | Foundation/Application |
| OPS-016 | SOMA shall not offer manual Service Request creation. New canonical SRs enter SOMA only through Advanced Search synchronization. | Application |
| OPS-017 | The Advanced Search source is a user-configurable directory. A check automatically chooses the newest stable direct regular `Advanced Search(Service Request)YYYYMMDDHHMMSS.xlsx` by embedded export timestamp and rejects an export older than accepted history. | Application |
| OPS-018 | Source discovery/stabilization/XLSX parsing/header+row validation complete before mutation. Unreadable/malformed/unsafe input or omission of any contract-v4 minimum header (`SRNo`, `Problem Summary`, `Report Date`, `Customer Contact`, `Customer Severity`) rejects that synchronization with an actionable message and no fallback to older data. The remaining eight recognized headers are optional enrichment; provider-only headers are ignored without warning and excluded from logical identity. Duplicate/invalid SR rows reject the whole snapshot. | Application |
| OPS-019 | Advanced Search synchronization uses SHA-256 of deterministic validated logical content, not raw XLSX bytes/filesystem metadata. The same contract/export-time/fingerprint is a no-op. A newer export with identical content records accepted-run/check recency without duplicate per-SR observations or change audit. | Application/Frozen `002` + application |
| OPS-020 | SQLite remains authoritative for accumulated SOMA-owned state/history. First disappearance from the newest accepted Advanced Search marks the SR `Removed / Pending removal`; no second source absence is required. A terminal source Status also makes the SR pending report finalization. Row reappearance before finalization clears pending removal. Terminal-pending state clears only when `Status` is actually observed with a recognized nonterminal value; omitted/blank/unknown Status cannot erase terminal evidence. Synchronization itself never finalizes/purges the SR and cannot overwrite SOMA-owned relationships/evidence/local operational state. | Application |
| OPS-021 | Advanced Search Customer Organization/Contact labels are matching/reconciliation data, not durable IDs. Unknown/ambiguous references never block an otherwise valid SR import and never cause display-name identity invention. | Application |
| OPS-022 | The Advanced Search adapter enumerates direct regular files only, rejects link/reparse traversal and unsupported content, enforces reviewed archive/file/row/column/shared-string/text limits, executes no formulas, fetches no external workbook resources, and fails safely on limits. | Application/Security |
| OPS-023 | The Phase 1C Advanced Search logical source shape recognizes `SRNo`, `Problem Summary`, `Report Date`, `Customer Contact`, `Customer Severity`, `Product`, `Current Handler`, `Status`, `ResolveBy`, `Resolve By Suspend`, `Suspend Planned End Date`, `Suspension Duration`, and `Customer Org.`. Contract v4 requires the first five headers in every legitimate export and records all recognized coverage in accepted-run `observed_fields`. `SRNo` is the only universally required usable row value; the other four required-column cells remain non-destructive when blank/malformed/unknown. | Application |
| OPS-024 | Advanced Search timestamps without explicit offset are interpreted in `America/Guayaquil` (UTC-05:00) and normalized to aware UTC. Recognized Status/Severity vocabularies are exactly those versioned in `ADVANCED_SEARCH_CONTRACT.md`; unknown nonblank values warn and cannot overwrite the last recognized canonical value. | Application |
| OPS-025 | Product is latest-source-controlled product/device-family guidance and Current Handler is latest-source-controlled assignment guidance. Product does not itself create a Managed Element relationship; SOMA does not maintain a conflicting local handler authority. | Application |
| OPS-026 | `ResolveBy` is the original expiration date. A valid `Resolve By Suspend` is the revised expiration after suspension/save and prevails for effective expiration. `Suspend Planned End Date` and decimal-day cumulative `Suspension Duration` remain distinct optional source facts. Duration converts to signed-64-bit integer microseconds using Decimal/half-even rounding, has no business maximum, and is never inferred between exports. Tickets with no valid expiration remain trackable without synthetic expiration. | Application/Frozen `002` |
| OPS-027 | Configurable ticket age-risk defaults are Critical 5, Major 10, Minor 30, and Non-fault inquiry 45 calendar days from effective Report Date. Separate configurable suspension-KPI defaults are Critical 3, Major 10, Minor 15, and Non-fault inquiry 30 cumulative source-reported days. Neither schedule is a duration, retention, or extension limit. | Application |
| OPS-028 | The newest accepted Advanced Search observation prevails for current source-controlled facts. Retained historical observations are deliberately compact rather than full workbook copies, but preserve progression/KPI facts needed for useful history: report date, severity, Product, Current Handler, recognized status, deadline/suspension values, and allowlisted warnings. Problem Summary is not repeated per observation; its final accepted value is retained once in the terminated SR snapshot. Customer Org/Contact source labels and contact channels are not copied into every observation. | Application/Frozen `002` |
| OPS-029 | Unknown source Customer Organizations/Contacts may produce user-reviewed minimal-reference creation proposals after import. Contact matching is scoped by Customer Organization and follows REF-010. A usable/resolved Contact reference and contact email/phone are not required for ordinary SR/MW handling, even though the contract-v4 `Customer Contact` header is required; a later Spare Request operation may require/collect missing contact details when it actually needs them. | Application |
| OPS-030 | A pure invocation policy defaults Advanced Search automatic synchronization to 10:00 `America/Guayaquil` daily and accepts a configurable whole-minute local time. It identifies a due scheduled/startup check, catches up when the application was offline past the boundary, treats explicit **Sync now** as always runnable, and avoids rerunning an already satisfied daily boundary. The Phase 2 application shell owns timers, persistence of the last successful check, and runtime invocation; no trigger asks the operator to select a workbook. | Application/Phase 2 wiring |
| OPS-031 | `Closed`, `Resolved`, and `Cancelled` suppress active expiration/risk reminder notifications immediately while preserving historical KPI/source evidence. Dashboard risk state remains the primary continuous warning surface; supplemental notification for the same ticket/active condition occurs at most once per calendar day. | Application |
| OPS-032 | Approaching `Suspend Planned End Date` produces a distinct suspension-ending-soon alert in addition to age-risk/expiration state. Risk presentation supports no deadline, healthy, at-risk/old, expiring, overdue, suspended/extended, suspension ending soon, source warning, pending source removal, and terminal semantics using icon/text plus color rather than color alone. | Application/UX |
| OPS-033 | Export captures durable membership/lifecycle evidence, the matching compact source observation, report-time Customer Contact, report-time organization assignment/scope, and an immutable report-data snapshot for one Customer Organization or all organizations before writing the artifact. Artifact success enables a second explicit cleanup prompt; it does not finalize automatically. Later Customer Contact drift, captured compact-fact drift, or organization reassignment makes the member stale for both organization-scoped and all-organization reports. Problem Summary-only drift is the explicit exception and a newer identical provenance-only check is not stale. The operator may confirm or opt individual eligible tickets out and may return later through a manual cleanup action. Failed/cancelled generation performs no cleanup. | Application/Export |
| OPS-034 | Immediate cleanup finalizes only explicitly confirmed report members whose pending/report/source/scope evidence still matches. In the same rollback-by-default UoW, it archives/minimizes current SR state, removes resolved customer/contact links and SR communication associations, deletes only communications with no surviving ownership/evidence, appends minimized audit, and commits once. Separately, at the configurable 180-day default due instant, retention housekeeping creates one 27-field allowlisted final snapshot excluding Customer Contact and deep-purges remaining SR-episode source/report/note/history/link/cache data while preserving independent operational records, global contacts, append-only minimized audit, and legitimately shared evidence. | Application/Privacy/Frozen `002` |
| OPS-035 | Accepted/frozen migration `002_phase1_application.sql` separates accepted import runs, purgeable latest source state, compact observations, durable report runs/items/decisions, lifecycle, retention authorization, final snapshots, and purge tombstones. Finalization references the generated report whose confirmed snapshot member authorizes it. Future persistent corrections use `003+`. | Frozen `002` |
| OPS-036 | Before mutation, synchronization returns a compact inserted/changed/unchanged/missing/customer-shift/warning summary. A valid empty authoritative population affecting existing nonterminated SRs requires explicit confirmation bound to the exact source identity. Exact nonempty population/customer-distribution thresholds remain deferred until representative operational volumes establish reviewed defaults; the current result still exposes the counts needed by that later policy. | Application/Safety |
| OPS-037 | Every legitimate export contains the five contract-v4 minimum headers, and every source row requires a canonical nonblank SRNo. Other recognized values are merged only when usable; omission of optional fields or invalidity preserves prior valid state, while a new SR may begin incomplete. Missing/unusable Report Date records the captured import instant at canonical UTC whole-second persistence precision as `system_assigned`, and a later real value replaces that fallback. Before irreversible report-confirmed finalization, the accumulated projection must contain nonblank Problem Summary, recognized Severity, and effective Report Date. Product and Current Handler remain optional enrichment. | Application/Frozen `002` |
| OPS-038 | A finalized SR episode never reactivates. Terminal reappearance is ignored with bounded provenance. If a finalized or purged/tombstoned SRNo reappears nonterminally, Phase 1C fails closed and returns a bounded new-episode proposal; it cannot create a new anchor or mutate old history. Actual authorization/creation of a same-number new episode requires a future explicitly reviewed forward migration/application service. Unsigned XLSX validation detects structural/lineage anomalies but is not represented as proof that a person did not edit the file. | Application/Future forward migration |
| OPS-039 | Deep retention is per local user, defaults to 180 exact elapsed UTC days from effective Report Date, uses the accepted daily Guayaquil due policy when later housekeeping is wired, and exempts active tickets until finalization. Policy changes apply to terminated episodes that have not entered authorized purge; there is no per-ticket postponement/legal hold. | Application/Privacy |
| OPS-040 | First-run profile requires editable name, username, email, and phone. Username is never cryptographic key material. A random data key must be protected by Windows DPAPI or an equivalently reviewed provider and referenced by non-secret key metadata. SOMA retains a configurable positive finite backup count, default five, and prunes only after verifying the replacement backup. | Application/Security |

## Spare Need, Spare Request, and physical spare lifecycle

| ID | Requirement | Delivery |
|---|---|---|
| SPR-001 | A Spare Need represents a persistent operational requirement, not a consumed request attempt. | Foundation/Application |
| SPR-002 | A Spare Need may carry BOM/model/quantity/notes/positions/faulty serial evidence and links to SR/WFM/Managed Elements. | Foundation |
| SPR-003 | A Spare Need remains requestable multiple times until explicitly resolved/cancelled; each request attempt retains its Need link. | Foundation/Application |
| SPR-004 | A Spare Request is an independent request/tracking container and may optionally link SR, Dispatch Site, and Requester. | Foundation |
| SPR-005 | A Spare Request may contain multiple BOM lines with positive quantity; submitted lines and Need membership lock after draft. | Foundation |
| SPR-006 | RMA is a normalized first-class return authorization; correcting canonical number preserves old number as immutable alias. One Spare Request may have multiple canonical RMAs. | Foundation |
| SPR-007 | Physical units are separate from request lines; requested units require matching request item/BOM and C10 identity. | Foundation |
| SPR-008 | Scrapped/on-site unit has no request item/C10 and is identified by BOM plus serial. | Foundation |
| SPR-009 | A physical unit may be manually allocated to an MW; released/unused unit may be reused, used unit may not be used twice without explicit rollback. | Foundation/Application |
| SPR-010 | Spare lifecycle evidence is append-oriented with source/time/target/optional communication evidence/supersession-suppression. | Foundation/Application |
| SPR-011 | Email-derived lifecycle events reference the stored relevant communication supporting them. | Foundation |
| SPR-012 | Lifecycle transitions are available manually and through reviewed email-derived proposals; compatible bulk actions support explicit rollback/correction. | Application |
| SPR-013 | SOMA supports Create and Export & Create plus recording a request created/sent outside SOMA; export is not proof of email send. | Application |
| SPR-014 | Lifecycle correction/supersession targets the exact same Spare Request/item/unit; target identity is immutable. | Foundation |
| SPR-015 | Submitted Spare Requests may preserve requested/default delivery snapshot; each physical unit may separately preserve actual delivery snapshot/site. | Foundation/Application |

## Fault Tags and returns

| ID | Requirement | Delivery |
|---|---|---|
| FTT-001 | Fault Tags/returns are SOMA 1 scope. | Foundation |
| FTT-002 | Fault Tag has tracking identity, optional pickup site, state, immutable first-send evidence. | Foundation |
| FTT-003 | Fault Tag items may be faulty removed hardware or new/unused replacement units. | Foundation |
| FTT-004 | Item may reference SR/Spare Request/Managed Element/physical unit/canonical RMA without duplicating RMA values. | Foundation |
| FTT-005 | Membership/item identity lock after first send; correction cancels/archives original and creates one explicit replacement. | Foundation/Application |
| FTT-006 | Warehouse confirmation/closure requires evidence communication for every item plus explicit user confirmation; confirmed evidence/timestamps lock and closed is terminal. | Foundation/Application |
| FTT-007 | Product “Delete Fault Tag” means archive/cancel/optional replace when history exists; hard delete only true unsent draft without dependent history. | Application |
| FTT-008 | Sent Fault Tag pickup selection/snapshot is immutable; snapshot cannot exist without selected pickup site. | Foundation/Application |

## Managed Elements and topology

| ID | Requirement | Delivery |
|---|---|---|
| DEV-001 | UI may use “Device Manager”; domain uses Managed Element for physical/logical infrastructure. | Foundation/Application |
| DEV-002 | Managed Element requires name/type and may store model/serial/rack/U/site/username/credential-reference/notes. | Foundation |
| DEV-003 | Managed Element has zero-many IPs and at most one primary; logical elements need not have IP. | Foundation |
| DEV-004 | Containment is an acyclic parent/child forest. | Foundation |
| DEV-005 | Cloud/Solution↔Datacenter Site and Managed Element↔Cloud/Solution are many-to-many. | Foundation |
| DEV-006 | Network/logical connectivity is stored separately from containment with provenance/confidence/times where applicable. | Foundation |
| DEV-007 | Passwords are never stored in ordinary SOMA tables; only opaque future credential-provider references may persist. | Foundation/Application |
| DEV-008 | SQLite remains authoritative; graph database may only be introduced later as a derived projection if measurements justify it. | Deferred |

## Communications and mailbox synchronization

| ID | Requirement | Delivery |
|---|---|---|
| MAIL-001 | Mail scanning does not run until at least one trackable operational entity exists; Managed Elements alone do not trigger scanning. | Application |
| MAIL-002 | Trackable entities include SR/TT context, Spare Requests, RFCs, WFMs, MWs, Fault Tags. | Foundation/Application |
| MAIL-003 | Initial scan begins no earlier than earliest relevant report/external creation date; later scans incremental from high-water mark. | Foundation/Application |
| MAIL-004 | Adding older object may trigger bounded targeted backfill; Deep Scan is explicit user action. | Application |
| MAIL-005 | Only matched communications persist; one communication may link multiple entities. | Foundation/Application |
| MAIL-006 | Relevant mail retained by default while its active/retained entity context requires it; report-confirmed SR termination applies OPS-034 minimization rather than an unconditional forever-retention rule. | Foundation/Application |
| MAIL-007 | Fetch/matching schedules default hourly/linked unless user explicitly separates them. | Foundation/Application |
| MAIL-008 | Message uniqueness is account-scoped; recipients are valid JSON. | Foundation |
| MAIL-009 | Microsoft adapter requests provider-stable message IDs; any fallback requires explicit identity/canonicalization/collision policy. | Application |
| MAIL-010 | Long provider work exposes progress/phase/count/cancellation/bounded retry/redacted diagnostics. | Application |
| MAIL-011 | Mail fetch/matching, Advanced Search synchronization, and local draft persistence remain independent workflows with no implicit cross-write. | Application |
| MAIL-012 | SR/Spare Request views distinguish received/sent counts/direction and last-interaction age without duplicating message bodies. | Application |

## Application interaction and Zeus parity

| ID | Requirement | Delivery |
|---|---|---|
| UX-001 | List navigation separates selection/opening: click selects, double-click/Enter opens, arrows move selection, wheel scrolls surface. | Application |
| UX-002 | Autocomplete is theme-consistent, input-triggered, bounded, internally scrollable. | Application |
| UX-003 | Narrow layouts reflow controls, preserve horizontal table access, center empty states, prevent overflow, and use icon/tool-tip actions when needed. | Application |
| UX-004 | Typography/status badges/semantic colors/focus/dialogs/motion use shared accessible tokens and never rely only on color/blinking. | Application |
| UX-005 | Editable workflows use consistent draft protection, selective save/discard, meaningful undo, reload/navigation confirmation. | Application |
| UX-006 | SR dashboards support customer filtering, mail summaries, spare lifecycle summaries, MW context, and expiration/KPI presentation without reintroducing removed `Resolved Status Date`. | Application |
| UX-007 | Spare Request/Fault Tag actions are stage-contextual, support compatible bulk transitions, manual/export flows, and never strand valid lifecycle. | Application |
| UX-008 | Pixel-accurate layouts/export artifacts require approved sanitized fixtures rather than guessed legacy screenshots. | Open prerequisite |

## Reliability, security, diagnostics, auditability

| ID | Requirement | Delivery |
|---|---|---|
| NFR-001 | Foreign keys enabled on every app connection; reverse FK indexes support normal joins/deletes. | Foundation |
| NFR-002 | Migration + ledger commit atomically or roll back together; concurrent startup does not apply a migration twice. | Foundation |
| NFR-003 | Migrations accepted into `main` are checksum-verified and immutable. Branch-only candidates may be corrected/consolidated until explicit merge approval, when names/order/content/checksums freeze. Never alter a ledger checksum to hide drift. | Foundation |
| NFR-004 | Migration status is read-only and does not create a missing DB/sidecars. | Foundation |
| NFR-005 | Meaningful state/identity/relationship changes go to application audit; business lifecycle evidence remains separate. | Foundation/Application |
| NFR-006 | Draft payloads/local settings are valid JSON. | Foundation |
| NFR-007 | Automated tests cover identifiers/hierarchy/immutability/lifecycle/referential integrity/migrations/schema integrity. | Foundation |
| NFR-008 | CI runs supported suite on Python 3.13/3.14 Windows; draft PR updates may skip, non-draft revisions and main pushes validate. | Foundation/CI |
| NFR-009 | Application acceptance tests cover keyboard/pointer/responsive/focus/reduced-motion/semantic labels/destructive confirmation. | Application |
| NFR-010 | Local startup migrates before serving, loopback-only, prevents duplicate instances, authenticates shutdown, validates exact registry URL/PID birth/health, bypasses proxies/redirects. | Foundation |
| NFR-011 | Technical diagnostics live outside SQLite with UTC/severity/component/event/run-id/context/traceback and fail-open behavior. | Foundation/Application |
| NFR-012 | Diagnostics redact credentials/tokens/password/body-like values; pattern redaction is defense in depth and does not permit deliberate sensitive logging. | Foundation/Application |
| NFR-013 | `audit_events` is append-only: update/delete/replace/conflict-skip existing rows are forbidden through normal SQL; duplicate event ID is error. | Foundation/Application |
| NFR-014 | Audit JSON is action-specific/minimal/allowlisted and excludes credentials, secrets, full mail/note bodies, uncontrolled provider payloads, arbitrary exceptions, whole-object copies. | Application |

## Deliberately deferred or still open

| Item | Status | Why / entry condition |
|---|---|---|
| Web framework/API/final UI component system | Deferred | Choose/finish in the local application-shell phase after domain service/repository contracts. |
| Exact Spare Request/Fault Tag export layout | Open | Requires sanitized representative output fixtures and approved format/branding. |
| Outlook/Microsoft authentication/mailbox adapter | Deferred | Requires consent/account scope/token/credential/throttling/runtime decisions. |
| Fallback identity for mail without provider-stable ID | Deferred | Requires explicit canonicalization/collision fixtures. |
| Direct Spare Need↔MW planning | Deferred | Add only when unresolved demand must be reserved before a physical unit exists. |
| Explicit Spare Request grouping entity | Deferred | Add only when otherwise independent SR7 requests need user-controlled grouping beyond shared context. |
| Detailed warehouse-origin/physical-transfer tracking | Deferred | Add when operations require movement-chain provenance beyond delivery/pickup. |
| Ping/SSH/automated topology discovery | Deferred | Requires threat/permission/timeout/operator-control model. |
| Graph projection | Deferred | Add only after measured SQLite topology query limits. |
| Zeus data importer | Deferred | Requires real migration need/source inventory/mapping. |
| Same-number SR new-episode authorization | Deferred | Frozen `002` fails closed on tombstoned-number reuse. Define durable user confirmation and introduce the required forward migration before creation is allowed. |
| Broader Advanced Search anomaly thresholds | Deferred after Phase 1C | Empty-population confirmation is implemented. Choose practical nonempty population/customer-distribution thresholds from representative operating volumes before enabling broader automatic blocking. |
| Non-report administrative SR archival | Open | Mistaken import, duplicate correction, or privacy remediation outside report-confirmed source termination requires a reviewed exceptional workflow. |
| Suspension-end lead time and final design tokens | Open for Phase 1H/UI | The distinct suspension-ending-soon state is accepted; choose configurable lead time and accessible icons/colors with read-model/settings/design-token implementation. |
| Pixel-level page layouts/visual tokens | Open | Requires approved sanitized responsive wireframes/assets/accessibility scenarios. |

Deferral means “not yet,” not discarded. No deferred item may weaken the current durable schema/history/privacy contract.

## Durable baseline acceptance criteria

The accepted Foundation + Phase 1C baseline remains valid when:

1. fresh database applies packaged `001 → 002` migrations and integrity checks pass;
2. failed migration leaves neither schema changes nor ledger row;
3. modified/missing applied migrations are detected and accepted migration content is regression-pinned;
4. database protects requirements marked Foundation/Frozen `002`;
5. diagnostics rotate/carry context/redact representative sensitive values;
6. supported Windows Python matrix passes for review-ready changes;
7. requirements/decisions/migration/architecture/data/testing/roadmap remain versioned/aligned;
8. setup initializes current DB and runtime lifecycle remains loopback-safe; and
9. later phases use forward migrations rather than reopening `001` or `002`.

