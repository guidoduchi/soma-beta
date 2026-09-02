# SOMA Beta Foundation Runtime, Persistence, Audit, and Verification Contract

Status: **Foundation review v0.1**  
Target: **SOMA Beta 1.0.0**  
Authority: accepted `BETA-REQ-0131` through `BETA-REQ-0144` and decisions `D-105` through `D-118`.

## 1. Purpose and authority boundaries

This contract governs SQLite connection safety, migrations, read-only status, persisted JSON, application audit, technical diagnostics, local startup and shutdown, automated verification, Windows/Python CI, and application acceptance.

| Requirement | Owning section |
|---|---|
| `BETA-REQ-0131` | §2 SQLite connections and referential integrity |
| `BETA-REQ-0132` | §3 Atomic, serialized migrations |
| `BETA-REQ-0133` | §4 Accepted migration immutability and drift detection |
| `BETA-REQ-0134` | §5 Observational migration status |
| `BETA-REQ-0135` | §§1 and 6 authority separation and audit |
| `BETA-REQ-0136` | §7 Versioned persisted JSON |
| `BETA-REQ-0137` | §8 Automated invariant and contract tests |
| `BETA-REQ-0138` | §9 Windows and Python continuous integration |
| `BETA-REQ-0139` | §10 Application interaction acceptance |
| `BETA-REQ-0140` | §11 Local startup, instance identity, and shutdown |
| `BETA-REQ-0141` | §12 External technical diagnostics |
| `BETA-REQ-0142` | §13 Diagnostic redaction and sensitive-data prevention |
| `BETA-REQ-0143` | §14 Append-only application audit |
| `BETA-REQ-0144` | §15 Minimal action-specific audit JSON |

SOMA keeps four authorities distinct:

| Record class | Authority |
|---|---|
| Domain lifecycle evidence | An accepted operational occurrence and its independently supported chronology |
| Application audit | The accepted command, decision, configuration change, or relationship mutation performed through SOMA |
| Proposal/job history | What processing discovered, proposed, accepted, rejected, retried, or failed |
| Technical diagnostics | Non-authoritative engineering evidence about runtime behavior and failures |

One class may reference another by immutable identity. It never silently becomes, duplicates, or overwrites another class.

## 2. SQLite connections and referential integrity

Every authoritative SQLite connection is created through one SOMA-owned connection factory. It enables `PRAGMA foreign_keys = ON` before beginning a transaction, verifies enforcement on that connection, and fails safely when enforcement cannot be proved. The rule applies to startup, migrations, imports, jobs, tests, backup/restore validation, read/write application work, and maintenance commands.

Foreign-key actions are explicit and match the owning deletion/retention contract. Ordinary application connections never disable enforcement. A versioned migration may temporarily use a separately controlled rebuild connection only when SQLite requires it; the operation remains isolated, transactional where supported, recovery-tested, and followed by `foreign_key_check` before publication.

Every child-side foreign-key access path used by ordinary joins or parent update/deletion checks has an effective index. A composite index satisfies the rule only when the foreign-key columns form its usable leading prefix. Redundant indexes are not required. The persistence LLD owns a machine-verifiable map from each foreign key to its supporting index or justified exception.

Post-migration and post-restoration integrity checks include foreign-key validation and exact schema verification before authoritative service becomes ready.

## 3. Atomic, serialized migrations

Migration schema/data changes and their migration-ledger/version bookkeeping commit in the same transaction or roll back together. SOMA never publishes a schema change without its corresponding ledger fact or records a migration whose changes did not commit.

One exclusive migrator owns a data instance. After acquiring ownership it re-reads the ledger and schema before deciding what remains. Concurrent launch attempts use bounded wait/activation/exit behavior and never apply one migration twice.

Crash, cancellation, full disk, constraint failure, process termination, or ledger failure leaves the database at the last committed version. Retry begins from that committed state. Cancellation occurs only at safe boundaries and never divides an atomic migration.

The service does not report readiness or expose ordinary queries and mutations until migration plus ledger, schema, foreign-key, and applicable append-only checks pass. A migration step that cannot safely participate in the transaction model requires a separately accepted design before use; it is not silently exempted.

Failure-injection and concurrency tests prove rollback, restart, and exactly-once committed application from every supported starting schema and from an uninitialized state.

## 4. Accepted migration immutability and drift detection

Before its acceptance into the protected Beta lineage, an individual migration candidate may be corrected, reordered, renamed, or consolidated. At that migration's acceptance its identity, filename, sequence, content, canonical bytes, checksum, and manifest entry freeze. Candidates do not collectively refreeze merely because they coexist on one branch.

Canonical migration bytes use governed UTF-8, line-ending, and normalization rules so Windows checkout behavior cannot create false drift or hide real drift. The accepted manifest and database ledger retain the applicable digest.

Startup and status comparison distinguish an unknown migration, missing migration, content drift, ledger mismatch, ordering error, and unsupported future version. Drift blocks authoritative startup. SOMA never alters a ledger checksum, accepted file, or manifest entry to make unexpected content appear valid.

Only an explicitly disposable development database affected by a pre-acceptance rewrite may be rebuilt or reset. A non-disposable instance requires an accepted forward migration or recovery path. Abandoned candidate checksums have no compatibility guarantee unless the origin is explicitly supported. An accepted migration is corrected only through a new forward migration. Checksums detect drift; they do not prove authorship, authenticity, or privileged-file tamper resistance.

## 5. Observational migration status

Migration status is read-only and side-effect free. Against a missing target it reports **Not initialized** and creates no database, directory, journal, WAL/SHM sidecar, temporary file, lock, configuration, default setting, or diagnostic merely because status was requested.

Against an existing target it opens with explicit read-only/query-only semantics and performs no migration, repair, checkpoint, vacuum, pragma mutation, schema write, ledger write, or timestamp-touching application operation. An invalid or non-database file is reported and never overwritten.

Live status should be requested through the authenticated running instance when that instance owns the database. Offline inspection refuses or reports limited/unavailable when a safe consistent view cannot be established; it does not disturb the writer.

Results distinguish at least not initialized, current, migrations pending, drift, unsupported future version, invalid database, integrity failure, locked/live-instance limitation, and inspection failure. Filesystem snapshot tests prove observational behavior.

## 6. Lifecycle evidence, audit, proposals, and diagnostics

Domain lifecycle evidence records an accepted operational occurrence with immutable identity, target, event type/schema version, recording time, independently supported effective time when known, actor or accepted source, and applicable evidence references. Unknown external time remains unknown.

Application audit records a meaningful accepted command, decision, configuration change, relationship change, correction, deletion, import acceptance, proposal decision, or other governed mutation. It preserves immutable audit identity, action type/version, target identity, actor/source, UTC recording time, reason category when applicable, command/correlation/job/import/proposal/batch identities, minimal changed-field or relationship summary, and references to resulting domain events.

The accepted authoritative mutation, required domain event, and required audit event commit atomically. Failure to create required audit rolls back the mutation. Failed or rejected attempts may create proposal, security, job, or diagnostic history but never false accepted-state evidence.

Projection recomputation, caching, querying, sorting, and rendering do not fabricate lifecycle evidence. Official-identifier and relationship corrections target exact immutable identities and preserve aliases and earlier evidence.

Eligible hard deletion retains only the minimized non-reconstructable audit evidence required by its deletion contract. Combined History views label each record class and preserve their independent authority.

## 7. Versioned persisted JSON

Every persisted JSON document belongs to an explicitly named and versioned contract. UI working copies, persistent domain Draft entities, typed local settings, import/export job configuration, and other approved document classes remain distinct. JSON is not a generic substitute for normalized entities, relationships, events, or independently queryable operational facts.

SOMA parses and validates before persistence: top-level shape, field names, types, required/optional members, enumerations, semantic constraints, encoded-size, depth, collection limits, and version compatibility. Database `json_valid` may be a backstop but never replaces application validation.

Persisted JSON uses UTF-8 and finite standards-compliant values. Malformed Unicode, truncated input, duplicate object keys, `NaN`, and infinities are rejected. Missing, explicit `null`, empty string, empty object, and empty array remain distinct where the contract assigns different meanings.

Unknown versions are never interpreted as current. Unknown fields follow an explicit reject, preserve, or quarantine policy; SOMA never silently discards them and overwrites the source. Version upgrades validate source and target and commit atomically. Failure preserves the last valid document rather than resetting defaults.

Local settings are typed and application-owned. Reading them does not create defaults. Writes use atomic replacement or equivalent safe commit. UI working-copy discard/recovery never deletes, submits, or approves a domain Draft.

JSON follows the security envelope and excludes ordinary storage of credentials, secrets, unrestricted communication bodies, uncontrolled provider payloads, and whole-object copies. Canonical serialization is defined only where checksum, fingerprint, equality, or deterministic export requires it; otherwise property order has no business meaning.

## 8. Automated invariant and contract tests

Deterministic automated tests trace to every accepted requirement, domain-contract clause, migration version, and use case. The governed suite includes focused unit tests, persistence/migration integration tests, domain transition tests, structured import/export contract tests, and cross-layer acceptance scenarios.

Required coverage proves:

- identifier syntax, normalization, uniqueness, correction, aliasing, provisional/official identity, and prevention of identity substitution;
- hierarchy/cardinality, ownership, cycle prevention, derived relationships, organization boundaries, Infrastructure ancestry, RFC hierarchy, and Dispatch Location direction;
- immutability of submitted snapshots, lifecycle evidence, official-identifier history, accepted migrations, audit events, corrections, replacement and resend lineages;
- every permitted and prohibited lifecycle transition, manual/proposal paths, partial processing, terminal projection, interruption, correction, cancellation, replacement, rejection, resend, and recovery;
- foreign keys, indexes, restrictions, cascades, eligible deletion, protected dependencies, rollback, and orphan detection on enforcement-enabled connections;
- migration from every supported schema and clean state, concurrency, interruption, retry, checksums, JSON upgrades, exact schema, and safe drift/corruption failure; and
- exact required tables, columns, affinities, constraints, indexes, foreign keys, triggers, ledger entries, append-only protection, and absence of obsolete duplicates.

Every supported import/export format has governed fixtures. Infrastructure Device workbook tests cover template, discovery export, round-trip update, version recognition, matching/foreign-installation identity, duplicates, ambiguity, malformed/modified files, partial failure, and authoritative hierarchy preservation.

Time, locale, filesystem paths, ordering, concurrency, and external artifacts are controlled. Tests do not depend on local timezone, regional spreadsheet formatting, directory enumeration order, prior residue, customer data, Outlook profiles, or uncontrolled network availability.

Accepted reproducible defects receive regression tests. Required failures, unexplained skips, and nondeterminism block release. Raw line coverage informs gaps but never substitutes for behavioral evidence.

## 9. Windows and Python continuous integration

CI runs the governed suite on Windows for every supported runtime, initially Python 3.13 and 3.14. Each matrix entry reports its exact interpreter, runner image, dependency resolution, selection, and result. Changing support requires an explicit decision and synchronized documentation.

Draft pull requests may omit the expensive full matrix but retain bounded validation for workflow/project syntax, imports, migration-manifest consistency, and directly affected deterministic tests. Marking a pull request ready triggers the full current-head matrix. Every later non-draft revision invalidates older results.

Every protected-primary-branch push and release candidate runs the complete required matrix. A passing older commit, cancelled run, missing discovery, infrastructure failure, timeout, or allowed-failure entry is not acceptance evidence. Superseded PR runs may cancel; the current merge candidate, primary-branch push, and release candidate may not be replaced by cancellation.

Dependencies resolve from governed reproducible metadata. Jobs use isolated temporary workspaces and exercise relevant Windows paths, Unicode, line endings, locking, registry handling, atomic replacement, process shutdown, spreadsheet behavior, and SQLite sidecars.

CI uses synthetic data and no production credentials, customer content, Outlook profile, or operator-specific location. Logs/artifacts follow redaction and minimization. Hosted CI is supplemented before release by representative Windows desktop acceptance across Python 3.13 and 3.14 for startup, browser, registry, imports/exports, filesystem permissions, and responsive interaction.

Branch protection requires current results. Emergency bypass is attributable and reasoned and must be followed by complete validation; it never converts missing evidence into success.

## 10. Application interaction acceptance

Automated application acceptance plus governed manual accessibility inspection covers every release-critical workspace, workbench, dialog, proposal, import/export, protected action, and populated/empty/loading/partial/stale/warning/error/historical/recovery state.

Keyboard testing covers logical traversal, arrows, Enter/Space/Escape, menus, dialogs, lists, trees, workbenches, autocomplete, proposal review, confirmation, and focus restoration. Pointer testing covers primary/double activation, contextual actions, hover, cancellation, movement tolerance, disabled state, and duplicate-command prevention.

Wheel/trackpad input scrolls the eligible pane under the pointer: communication pane, Ticket list, Infrastructure tree, detail/history/activity pane, table, dialog, autocomplete, or other scroll container. It never unexpectedly moves an unrelated pane or shell at a nested boundary. Keyboard scrolling belongs to focus and touch to gesture origin.

Responsive tests prove all supported viewport compositions keep hierarchy, commands, data, warnings, dialogs, tables, and validation reachable without unintended clipping or loss of authority. Focus remains visible and programmatically determinable; modals contain it and restore it safely. Reduced motion removes nonessential movement without hiding state or progress.

Controls and structures expose semantic names, roles, states, relationships, and errors. Icon-only controls have accessible names. Color, placement, tooltip, or motion is never the sole meaning. Zoom and text enlargement preserve access.

Consequential actions follow their assigned tier. The three-second Device Reference promotion hold uses monotonic elapsed time, visible/semantic progress, and cancellation on early release, loss of activation, Escape, page hiding, invalidation, or movement classified as scrolling. It commits at most once after state revalidation. Keyboard/assistive operation is equivalently deliberate. A hold never replaces an impact preview where understanding requires targets and consequences, and ordinary reversible actions do not gain unnecessary holds.

Proposal/import review tests prove no authoritative mutation before acceptance, visible source/diff, partial decisions where supported, rejection/correction, stale detection, and equivalent input methods. Failures preserve recoverable work and never fabricate success.

## 11. Local startup, instance identity, and shutdown

The local service binds only to explicitly supported loopback addresses—never wildcard, LAN, public, VPN, or container-bridge interfaces by default. Remote access requires a separate future contract.

Startup canonicalizes owned paths and acquires exclusive ownership of the intended data instance before migration or service. Ownership scopes the data location/database, not just a TCP port. Concurrent launches activate the verified instance or exit safely; they do not start competing migrators/servers.

Configuration, diagnostics initialization, migration, and post-migration integrity complete before readiness and ordinary service. Browser launch follows an authenticated readiness verification. Failure produces a bounded unavailable state rather than partial operation.

Each run receives unpredictable instance identity/authentication material. Secrets are not durable reusable credentials, ordinary diagnostics, browser history, or proof derived merely from loopback reachability.

The atomic runtime registry contains only canonical loopback origin, PID, independently determined process-birth identity, run identity, protocol version, data-instance identity, and secure readiness-discovery material. Trust requires supported syntax/version, exact URL constraints, matching live process and birth, expected SOMA runtime/ownership, and an authenticated non-redirecting health handshake returning the run and data identities. PID, open port, page title, or unauthenticated response alone proves nothing.

Launcher health/shutdown bypass proxies, reject redirects and endpoint changes, use bounded timeouts, and do not forward credentials. The server validates `Host`, origin, forwarded-host substitution, cross-site commands, and DNS-rebinding patterns. Browser mutations retain local-session, origin, and anti-forgery protection.

Shutdown is an authenticated state-changing command targeting the exact run. It stops new mutations, commits or rolls back active transactions, closes connections, releases ownership, and reports graceful/forced/failed/no-valid-instance outcomes. Forced termination revalidates PID and birth. A stale or malicious registry is never opened or used for shutdown and is removed/replaced only after safe invalidity and ownership checks.

Port conflicts never establish identity; another permitted loopback port may be selected only before publishing verified readiness. Repeated launch/shutdown remains idempotent and cannot affect a later process reusing a port or PID.

## 12. External technical diagnostics

Technical diagnostics live outside SQLite so database/startup failures remain inspectable. Records use a versioned structured format with UTC recording time, severity, stable component, stable event code, run ID, summary, and minimal allowlisted context. Applicable correlation/request/job/import/migration identity, process/task context, monotonic duration, sanitized exception chain, and sanitized traceback may be included.

UTC time describes diagnostic emission; monotonic time governs durations/timeouts. Diagnostics never substitute for unknown external chronology. Severity and event codes have governed meanings.

Files use owned local-user paths and permissions, concurrency-safe complete records, bounded queues, and governed size/age/total-volume rotation. Cleanup deletes only proven managed diagnostic files. Error/critical records flush at practical failure/shutdown boundaries without recursive logging.

Diagnostic emission is fail-open for otherwise valid work: logging failure does not corrupt state, roll back a valid mutation, weaken security, or crash through a secondary exception. It never turns a failed migration, audit insertion, authorization, integrity check, or domain transaction into success. A bounded safe fallback is used without exposing raw content.

Diagnostics are never automatically transmitted. A future support bundle requires explicit previewed operator export and reapplied redaction and excludes authoritative data by default.

## 13. Diagnostic redaction and sensitive-data prevention

Credentials, passwords, recovery values, session/authentication secrets, tokens, private keys, authorization/cookie material, protected database values, and designated sensitive data never enter technical outputs.

Primary control is source minimization: components emit named allowlisted facts, not arbitrary request/response/settings/import/email/exception/environment/database/domain objects. Structured classification operates recursively with size/depth limits. Normalized sensitive-name recognition covers case and punctuation variants.

Full email/note/HTTP/provider/workbook bodies, clipboard content, generated MSG content, SQL parameters, and arbitrary objects are omitted. Allowlisted metadata such as opaque identity, row/field, size, type, and validation category may remain. URLs remove credentials, sensitive query/fragment/bootstrap/path content. Headers use a positive allowlist.

Exceptions are untrusted and sanitized across messages, causes, arguments, representations, and tracebacks. Pattern redaction provides defense in depth for recognizable accidental bearer/token/connection/password/private-key forms. Its existence never permits deliberate logging. Encoding, encryption, hashing, truncation, or partial display does not automatically make authentication material safe.

Redaction occurs before durable write, asynchronous queue, console, fallback, CI, or secondary formatter. Operational correlation uses purpose-created opaque identifiers rather than secret-derived hashes. Failure drops the disputed field/record and never emits the raw object.

Support-bundle export reapplies current inspection/redaction. Canary tests verify prohibited complete and reconstructable fragments never appear while event identity, component, severity, run correlation, opaque target, and actionable category remain useful.

## 14. Append-only application audit

`audit_events` is append-only. Accepted rows are never updated, deleted, replaced, overwritten, merged, conflict-skipped, reused, or silently ignored through ordinary application, import, cleanup, maintenance, recovery, or SQL workflows.

Each event has an immutable opaque identity independent of target, action, time, or content. The dedicated insert path expects exactly one new row. Duplicate identity is an explicit integrity error. `OR IGNORE`, `OR REPLACE`, upsert overwrite/do-nothing, and ambiguous affected-row handling are forbidden.

Command idempotency is resolved before audit insertion through command/proposal/import/job/request identity. Retry returns/reconstructs the prior result and never treats a duplicate audit insert as success.

The schema and owned connections reject direct/indirect `UPDATE`, `DELETE`, replacement, cascade, trigger, and conflict paths against accepted audit rows. Required mutation and audit commit together or roll back. Multi-record commands define one minimal set event or several events and never accept partial audit coverage.

Correction, reversal, cancellation, suppression, supersession, archival, restoration, and deletion append new events. Correction targets the exact prior event. Routine retention, communication purge, diagnostic rotation, cache/projection rebuild, JSON upgrade, and optimization never delete audit.

Historical action-schema versions remain readable and are not rewritten by migration. Backup/restore preserves exact identities and values and detects conflicts rather than resolving them last-write-wins. Startup verifies append-only protections after migration/restoration.

Read-only audit presentation may sort/filter/group without mutation and labels audit separately from lifecycle/proposal/diagnostic records. SQLite/application protections guard ordinary use but do not claim cryptographic tamper evidence against a privileged operator replacing local files.

## 15. Minimal action-specific audit JSON

Every audit action has an explicitly named/versioned payload schema. There is no unrestricted generic details object. Core relational facts—event/action/version/target/actor/source/time/correlation/domain-event references—stay in owning columns/relationships rather than duplicated JSON.

Payload members have defined name, type, cardinality, size, sensitivity, nullability, and semantics. Closed allowlists reject unknown fields, unsupported versions, invalid/duplicate/non-finite/excessive values, and incompatible combinations before persistence. Failure rolls back the associated required mutation; SOMA never falls back to whole-command or whole-entity serialization.

Identity/relationship actions record immutable identities and the minimal difference. Changed-field summaries distinguish add/remove/replace/clear/relationship change and include only allowlisted fields. A sensitive value may be recorded only as the governed fact that its field changed; credentials and protected values never appear as old/new/hash/prefix/suffix/length/reversible content.

Payloads exclude secrets, full mail/note/comment/clipboard prose, complete MSG/PST/OST/workbook/HTTP/provider payloads, uncontrolled headers/attachments, arbitrary exceptions/tracebacks, environment/request/response/database/ORM objects, whole snapshots, and unbounded paths/registry/import/diagnostic content.

Provenance uses immutable references to governed communication, import, export, proposal, job, diagnostic run, or domain event identities without copying their content. Communication/import decisions record source/job/proposal identity, accepted targets, decision/reason category, and minimal diff. Bounded user explanation exists only when the action contract requires it.

Technical failures use governed result categories and diagnostic correlation, not exception bodies. Audit corrections append minimal target/difference. Eligible deletion retains a minimized action record, not a whole-object tombstone.

Payload action versions remain permanent and readable. Valid UTF-8 JSON and the persisted-JSON rules apply; canonicalization is explicit only where required. History distinguishes current labels, historical facts, and deliberately omitted values and never fabricates old state from current entities.

Per-action accepted/rejected fixtures and canaries prove exact fields, omissions, bounds, versions, deterministic behavior where applicable, rollback, correction, historical reading, and non-disclosure in database, UI, export, and combined History.

## 16. Required acceptance evidence

Before Beta 1.0 release, evidence includes:

1. connection-factory foreign-key enforcement and indexed-FK coverage;
2. clean/concurrent/interrupted/drifted migrations and observational status;
3. lifecycle/audit/proposal/diagnostic separation and atomic mutation/audit behavior;
4. JSON malformed/version/upgrade/concurrency/recovery cases;
5. identifier/hierarchy/lifecycle/immutability/schema/import-export invariant suites;
6. current-revision Windows Python 3.13/3.14 CI plus representative desktop acceptance;
7. keyboard/pointer/touch/responsive/focus/reduced-motion/semantic/hover-scroll/hold acceptance;
8. loopback binding, forged/stale registry, PID/port reuse, proxy/redirect, origin, shutdown, crash/restart cases;
9. diagnostic structure/rotation/failure and redaction canaries; and
10. direct/indirect audit mutation attempts plus per-action audit-payload fixtures.

Missing, skipped, nondeterministic, stale, cancelled, or unexplained required evidence does not pass.

## 17. LLD responsibilities

LLD defines the connection factory, pragma verification, FK-index map, migration/manifest/canonical-byte model, migrator lock, status protocol, JSON schema registry/upgraders, event/audit schemas and transactions, audit protections and idempotency store, diagnostic format/path/rotation/queue/fallback/redaction rules, canary corpus, local runtime registry/lock/process-birth/health/session/shutdown protocols, Windows/Python/browser matrix, CI workflows/branch protection, exact automated/manual test allocation, acceptance fixtures, stable errors, resource limits, and recovery procedures. No LLD choice may weaken this contract.
