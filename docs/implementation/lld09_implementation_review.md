# LLD-09 implementation review

Authority: accepted design `9a0e891127a771251afccca1a281b7ef7dde9e5f`, the accepted
proposal/query/job refinements in `docs/reconciliation/LLD09_*`, and the native
release clarification dated 2026-10-01. This records locally certified ordinary implementation evidence
in the uncommitted working tree. The exact-byte certificate is
`lld09_implementation_certificate.json`; native and supported-matrix promotion
remain excluded.

## Implementation scope

Communications owns source scopes, canonical messages and content, identity
review/reconciliation, independent links and typed proposals, coverage, orphan
retention/purge, immutable MSG draft/export provenance and summary projections.
Static transport and runtime composition bind these owners to the registered
commands, queries, workers and provider interfaces. Host-invoked scheduling uses
current LLD-02 settings and the Foundation coordinator; it does not install another
timer or executor. Ordinary, targeted and Deep Scan readers serialize per source
under Foundation's writer-owned claim. Housekeeping is installation-wide and
independent of scheduled fetching.

Targeted and Deep Scan runs preserve ordinary high-water. Historical segments
and per-folder resume positions belong to the immutable accepted job scope. Known
bounded ranges become complete only after actual readable exhaustion. Unknown
chronology, partial stores, cancellation and crashes retain truthful coverage.
Selected backfill targets are revalidated through current owner authority before
parsing and committing, including when later messages would not match them.

Parsing, bounded matching preparation, attachment capture and content hashing
occur outside the writer lock. Each authoritative inspection revalidates the
claim, scope/configuration, exact current candidates, revisions, identity and
range in one outer Foundation receipt/UnitOfWork. Content, children/search,
links/proposals/holds, retention, action-specific audit, counters and checkpoint
commit together. Exact replay returns the immutable result before mutable state
or consumed streams are consulted. Ambiguous identity never becomes auto-safe.

Governed historical reconstruction reuses the exact provider-resolved canonical
identity, verifies unchanged content evidence, restores children/search and
requires new governed protection in the same receipt. It increments content
revision and records reconstruction history/audit. Ordinary overlap never
recreates purged content; historical reinspection does not auto-reopen closed
links. Changed evidence or audit failure rolls the entire reconstruction back.

Inventory, SR and RFC acceptance/terminal consumers reuse the owning command's
UnitOfWork and receipt. Communications does not write their lifecycle tables.
Frozen terminal summaries precede direct-link closure; sibling links and protected
holds survive. Purge revalidates protected dependencies immediately before
minimizing content/search; append-only evidence, source stores and exported MSG
artifacts remain. Reversal restores governed links during grace or queues bounded
reconstruction after purge without fabricating source availability/chronology.

Proposal creation accepts complete registered typed facts under the caller receipt;
owner commands freshly validate target/membership/source fingerprints before
mutation and disposition. The accepted clarification does not authorize arbitrary
natural-language lifecycle extraction. Exact SR7+C10 resolution remains
Inventory-owned and requires current selected physical membership. Optional RT
context and its missing-reference warning are typed review inputs; CLOSED cannot
provide an accepted/rejected decision. Workbench presentation remains LLD-10-owned.

## Schema, bounds and ownership

Runtime migration `beta_0016_communications` has SHA256
`8e467684b9de0c2842d389da72877619e1fc460ab67b4a9c87b79f2cfc78ea8e`.
Accepted migration bytes/hashes 1–15 are preserved. The normal migration runner
now installs Communications; tests no longer apply candidate SQL afterward.
Upgrade-from-15 and fresh-16 schemas agree, and prefix history, FK coverage,
integrity, immutable evidence guards and release schema manifest are verified.
The candidate generator refuses to rewrite an accepted runtime migration.

Queries retain complete deterministic continuation keys, bounds and null ordering.
Matching uses a sealed, encrypted, streamed owner-identifier index with current
candidate revalidation and bounded indexed ambiguity probes. Selected-target
freshness uses the job/target index, not a full owner-registry scan per message.
Schedule evaluation pages sources in groups of 64 and finds the latest ordinary
request through the source/kind/time index. The claim-policy extension preserves
Foundation ordering and default selection; policy evaluation scans metadata and
loads only the chosen immutable payload. Queue traversal can grow with due work;
it does not load all job payloads or message bodies into a Python collection.

Module-map layout differences are explicit in `lld09_traceability.json`: shared
scan request ownership remains in `services/processing.py`, typed setting commands
remain in `services/settings.py`, and owned SQLite triggers maintain FTS atomically.
No empty filename-parity wrappers or competing authorities were introduced.

## Verification and release limits

`lld09_traceability.json` binds all 100 exact normative scenarios to implementation
owners and executable evidence. The binding checker is structural evidence, not
an assertion that a named test proves every clause or that native fixtures passed.
The full implementation suite, focused adversarial tests, compileall, schema/FK,
resource packaging and private sample exclusion are the local verification gates.
The final suite passed **1,953 tests** on Windows Python 3.14.7 in 567.74 seconds.
Compileall, the 1,309-object schema manifest, all 16 packaged migration resources,
all 100 structural scenario bindings, private sample exclusion and pip check pass.
All 433 packaged Python modules exactly match the verified source bytes. The
778-file source/test/tool verification snapshot SHA256 is
`ebb49813bc48378518f0f21ea06366b86546e706601e61609a06c36ccde2de7b`.
The final local validation wheel SHA256 is
`b9ee6e894c7ef7dcb7f8b960947824ab0a9632d5f0978a5c3bca3d16e52797fb`.
Builds used installed tools with --no-deps --no-build-isolation; dependencies pass
pip check. Windows Python 3.13 and Ubuntu were not executed locally. The
Infrastructure upgrade test now stages its own accepted prefix through 15; the
new Communications migration test covers the full 15-to-16 upgrade.
Final observed counts and artifact hash are also recorded in `current-state.json`.

The PFF adapter architecture uses a static injected read-only release bridge,
typed bounded transient evidence, opaque generation-scoped checkpoints, bounded
attachment facades and sanitized failures without raw exception context. It never
discovers COM/MAPI or arbitrarily chooses pypff. Without an installed bridge it is
explicitly UNSUPPORTED. The bridge must prove native property normalization,
pre-allocation bounds, read-only access and truthful discovery/exhaustion against
physical fixtures when the release dependency is selected.

Native certification remains blocked by **LLD09-PFF-RELEASE-PIN** and
**LLD09-GOLDEN-CORPUS-FREEZE**, as accepted by the owner. All C001–C012 physical
release proofs remain deferred; synthetic and independent MSG verification do
not certify Outlook or a libpff build. The checker with
`--require-native-certification` fails closed while these gates are unresolved.
Real HTTP authentication/CSRF, session/run-bound proof issuance, SQLCipher/key
composition and supported release packaging belong to LLD-12. LLD-09 consumes
their declared boundaries; this local test environment does not certify them.

No branch switch, design-pin advance, commit, push, merge or promotion is part of
this implementation continuation. Remote CI for these working-tree bytes has not
run. Historical CI/certificates remain historical evidence.

## Second review and local certificate — 2026-10-01

The user requested a second check and certification. Source review confirmed the
identity, ownership, transaction/replay/audit, freshness, historical coverage,
reconstruction, purge, bounded query and artifact contracts above. It found an
adapter privacy edge: failed native cleanup during inspection unwind could replace
the inspection failure and attach its exception context. Cleanup now preserves
the original inspection failure; native attachment read attribute lookup and call
are both sanitized. Two regression tests cover these paths. No ordinary
implementation blocker remains in the reviewed scope.

After that change, the complete suite passed **1,955 tests** in 567.61
seconds on Windows Python 3.14.7. Compileall, the 1,309-object schema manifest,
100 structural scenario bindings, all 16 packaged migration resources, private
sample exclusion, state validation and pip check pass. Migration entries/bytes
1–15 remain exact against the base commit. All 433 wheel modules match source.
The new wheel SHA256 is `d59e315bb44cef19a100e5b5d04ec9a01af14b9571fa56ca3a1a4865fb8f03ae`.

The certificate preserves the exact 778-file source/test/tool manifest plus
supplemental build, accepted clarification and binding hashes. Its canonical
snapshot SHA256 is `247e9d1d6808a76dbd36574aab856fb211738b51ffcf9e2c546f68136fb06d13`. The earlier verification above is
historical; this certificate supersedes it for the two changed adapter/test files.
Recompute the recorded hashes before reusing certification after changes.

**PASS: local ordinary implementation.** This is not a native release certificate,
a supported-matrix CI certificate or a certificate for base commit
`47947c5066b600694ef70a828a46269fb658ea7a`. No commit, push or merge occurred.
C001–C012 physical/native gates and real LLD-12 host composition remain excluded
exactly as stated above. Immutable Git evidence promotion remains a separate
checkpoint; the existing immutable state references are preserved.
