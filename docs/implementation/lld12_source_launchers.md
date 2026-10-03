# Trusted source launchers: local development handoff

Date: 2026-10-02. Local working-tree work only; no commit, push, branch, PR,
merge, tag or publication. Development evidence, not release certification.

## Authority and original diagnosis

Design pin: 9a0e891127a771251afccca1a281b7ef7dde9e5f.
Implementation HEAD: c633fe564069b04f7d384929c16da67001e538a6.
The original source-control adapter returned dependency_pending unconditionally
for console, run and stop. Accepted owner clarifications superseded its blockers.

Internal implementation order: inspect current/reference launchers and accepted
interfaces; implement native security providers; preserve Foundation host/lock/
socket/lifecycle; compose encrypted application; prove console authenticated READY;
complete trusted stop; detached start/reuse/browser; native adversarial checks.

Applied session clarifications:
- Foundation publishes RuntimeRegistryV2, owns the sole health endpoint with PID/
  birth and host_state authority, and owns exact-run shutdown HTTP 202, receipts,
  exact replay and audit when the authoritative DB is current.
- Global migration allocation: immutable UI 17, explicit Overview no-op 18,
  complete accepted Security schema 19. No migration 1-17 bytes/hashes changed.
- Approved local sqlcipher3 0.6.2 wheel uses official SQLCipher 4.17.0 and
  OpenSSL 3.6.0; the public 4.12.0-core wheel is not authoritative.
- Setup provisions independent raw 32-byte admin reset credential, SQLite SHA-256
  verifier in its owning setup UoW, CurrentUser DPAPI purpose admin_password_reset,
  installation binding, and owner-only security/admin-reset.dpapi before commit.
  Failed setup removes exact-owned new envelope best-effort; validated orphans
  confer no authority and may be replaced. Reset transport remains uncomposed.

## Launcher behavior

soma_setup.bat creates/reuses .venv, installs editable project/test dependencies,
hash-checks/installs the approved local native wheel, verifies keyed cipher
profile, frozen assets and existing canonical directory safety. No fake runtime
state, database creation or plaintext fallback.

soma_run_console.bat verifies environment, starts the real Foundation host in the
foreground, migrates/opens the encrypted DB, prints READY origin/schema, and serves
the actual frozen LLD-10 app after first setup/login. Ctrl+C performs graceful
owned shutdown. cmd.exe can then show its standard batch termination prompt.

soma_run.bat freshly verifies an existing instance and opens its origin, or starts
a detached real host with an owner-only startup log and waits up to 30 seconds
for authenticated READY before opening the verified origin. Concurrent invocations
use Foundation's existing lock; the losing launcher waits for the winning host.

soma_stop.bat freshly verifies the complete trusted instance, posts exact-run
authenticated Foundation shutdown, retains/revalidates a native process handle,
and waits within the 10-second graceful budget. Missing registry is successful/
idempotent. Timeout performs no forced termination. Unknown artifacts are preserved.

Canonical root: Windows KnownFolder LocalAppData + SOMA/Beta/instance-v1.
Directories/files enforce owner-only current-user/SYSTEM ACLs and reject reparse
points. Persistent installation identity, independent fresh run UUID/32-byte
credential, CurrentUser DPAPI purpose/install binding; runtime.json contains only
the nine V2 fields, never raw credentials. Atomic publication refuses concurrent
destination creation. Native cleanup compares captured bytes and deletes a
retained file object, preserving replacements.

Trust requires expected canonical path, safe ACL/path, strict V2 shape, literal
numeric IPv4 loopback origin, live PID, exact Windows process creation FILETIME,
expected source interpreter image (native Windows venv reports base interpreter),
DPAPI credential, authenticated direct no-proxy/no-redirect health, exact run/
data/PID/birth/protocol identity and Foundation READY. Browser session/CSRF and
launcher run control remain separate. HTTP parsing and absolute deadlines are bounded.

## Native build evidence

docs/implementation/lld12_sqlcipher_development.json records exact source commits,
source/generated/wheel hashes, OpenSSL archive/Conan recipe/package identity,
compiler and SDK, library hashes and scratch-only build adjustment.

Wheel: dist/source-development/sqlcipher3-0.6.2-cp314-cp314-win_amd64.whl
SHA256: ae151e020ce45b60aac8be3fc8628ae4a7894b2c543fbfb5bc1f4047db22618f
MSVC v143 19.44.35229, Windows SDK 10.0.26100.0. Installed only checkout .venv.
Build/source evidence remains under tmp/lld12-native-build, never production imports.
Official PRAGMA text is "4.17.0 community": provider verifies exact core 4.17.0
with recognized edition plus all cipher-profile invariants. Native checks cover
encrypted file header, wrong-key rejection, integrity, FK/memory security, all
19 migrations and schema guards.

## Reference work used

Inspected and retained intact under tmp/lld12-source-launchers:
- soma_setup.bat, soma_run_console.bat, soma_run.bat, soma_stop.bat
- tools/source_launcher.py
- src/soma/security/runtime/source_control.py
- tests/test_source_launchers.py
- docs/implementation/lld12_source_launchers.md

Used as scaffold/previous-investigation evidence, not canonical authority. No
implementation fragment was migrated or imported from that directory.

## Remaining limitations and exclusions

The canonical composition serves actual LLD-10 assets and assembles existing
Foundation, Reference, Infrastructure, Inventory, SLA, Objective/Task,
Communications and working-copy provider seams. It does not certify every owner
transport or workflow. Some concurrent UI/owner routes remain unassembled or need
owner reconciliation (Inventory needs transport, objective-timezone key, full
working-copy provider coverage). Missing owner functionality fails closed; no DTO
aliases or owner behavior were invented. Native PFF workflows require their owning
backend prerequisite. No src/web or src/soma/ui files were edited.

The small server-owned setup/login page issues the session then serves existing
assets. Full settings/password change/reset/auto-login UX and browser mutation UX
integration remain outside scope. Password reset invocation is disabled pending
LLD12_RUN_CONTROL_RESET_V1 closure. Python cannot promise native-quality secret
memory zeroization; raw secrets are never intentionally persisted/logged.

Malformed, stale, PID-reused, foreign or unauthentic runtime state fails closed
and is preserved for manual review. No automatic stale-registry recovery or
forced kill. Hard startup crashes can leave protected non-authoritative orphans;
unpublished credentials confer no control authority. Owner-only logs have no
automatic pruning in this slice.

Bootstrap targets this approved CPython 3.14 Windows x64 build. A new checkout
needs the locally evidenced wheel at the recorded path. Setup does not substitute
a public wheel or silently rebuild unknown dependencies. Frozen web output must
verify; setup does not rebuild concurrent UI source.

Backups, restore, pruning, support bundles, diagnostics UI, installer, signing,
tray/WebView2 packaging, release certification and full LLD-12 workflows remain
out of scope. Migration 19 includes their complete accepted schema because a
reduced launcher schema was not authorized.

## Manual first live test

From a normal Windows terminal:
    cd /d D:\DEV\soma-beta
    soma_setup.bat
    soma_run_console.bat

Open printed READY origin; first use asks for a local administrator password of
at least 12 characters, then serves the real app. Stop with Ctrl+C. Then:
    soma_run.bat
    soma_run.bat
    soma_stop.bat
    soma_stop.bat
    soma_run.bat
    soma_stop.bat

This BAT sequence was executed natively against the canonical user root: repeat
run reused the host, repeated stop succeeded, and restart created a new run.
Canonical encrypted DB is schema 19, administrator remains unconfigured there,
and no host was intentionally left running.

## Verification

CurrentUser DPAPI tests use the actual logged-in Windows token, outside the
restricted sandbox token which cannot decrypt those credentials. Test roots are
isolated in checkout tmp and do not replace canonical user data. These tests do
not imply release certification.

- Native publication/trust/process/application/launcher focused run: 58 passed
  in 26.32 seconds; final credential no-clobber fix followed and is covered by
  the final complete suite.
- Earlier complete suite: all passed, exit 0.
- Final complete suite after source freeze: 2152 passed in 676.86 seconds, exit 0.
- compileall -q src tests tools: passed.
- pip check: no broken requirements.
- schema manifest check: 1321 authoritative objects verified.
- git diff --check: passed; ordinary Git LF/CRLF notices only.
- Fresh isolated SOMA wheel build passed, avoiding stale existing build/lib.
- implementation_state.py check reports review_required for changed scopes,
  expected for dirty implementation. This is not semantic certification.

Native tests cover malformed/missing/stale registry, PID/birth/image mismatch,
PID reuse, DPAPI failure/binding, wrong run/data/protocol health, port reuse,
redirects, Host/proxy rejection, startup crash before READY/after bind before
publication/after publication, simultaneous starts, repeat run/stop, Foundation
exact shutdown replay, and foreign artifact preservation. Actual BAT setup,
foreground console, detached browser opening, reuse and stop were exercised.

## Exact local files and Git status

Tracked files changed:
- pyproject.toml
- src/soma/foundation/contracts/foundation.py
- src/soma/foundation/runtime/host.py
- src/soma/foundation/runtime/registry.py
- src/soma/migrations/manifest.json
- src/soma/schema_manifest.json
- tests/test_foundation_runtime_host.py
- tests/test_foundation_runtime_primitives.py
- tests/test_foundation_runtime_routes.py
- tests/test_foundation_runtime_status.py
- tests/test_foundation_starlette_smoke.py
- tests/test_ui_migration.py

Untracked files added/updated:
- docs/implementation/lld12_source_launchers.md
- docs/implementation/lld12_sqlcipher_development.json
- soma_run.bat
- soma_run_console.bat
- soma_setup.bat
- soma_stop.bat
- src/soma/application.py
- src/soma/migrations/0018_overview.sql
- src/soma/migrations/0019_security_packaging.sql
- src/soma/runtime_domains.py
- src/soma/security/__init__.py
- src/soma/security/auth/__init__.py
- src/soma/security/auth/passwords.py
- src/soma/security/auth/sessions.py
- src/soma/security/contracts/__init__.py
- src/soma/security/contracts/security.py
- src/soma/security/crypto/__init__.py
- src/soma/security/crypto/dpapi.py
- src/soma/security/crypto/live_key.py
- src/soma/security/crypto/sqlcipher_provider.py
- src/soma/security/runtime/__init__.py
- src/soma/security/runtime/control.py
- src/soma/security/runtime/installation.py
- src/soma/security/runtime/source_control.py
- src/soma/security/runtime/trust.py
- src/soma/security/runtime/windows.py
- src/soma/security/services/__init__.py
- src/soma/security/services/auth.py
- tests/test_security_control_http.py
- tests/test_security_migration.py
- tests/test_security_passwords.py
- tests/test_security_runtime_trust.py
- tests/test_security_sqlcipher_native.py
- tests/test_security_windows_native.py
- tests/test_source_application_native.py
- tests/test_source_control_native.py
- tests/test_source_launchers.py
- tools/source_launcher.py

git status --short:

```text
 M pyproject.toml
 M src/soma/foundation/contracts/foundation.py
 M src/soma/foundation/runtime/host.py
 M src/soma/foundation/runtime/registry.py
 M src/soma/migrations/manifest.json
 M src/soma/schema_manifest.json
 M tests/test_foundation_runtime_host.py
 M tests/test_foundation_runtime_primitives.py
 M tests/test_foundation_runtime_routes.py
 M tests/test_foundation_runtime_status.py
 M tests/test_foundation_starlette_smoke.py
 M tests/test_ui_migration.py
?? docs/implementation/lld12_source_launchers.md
?? docs/implementation/lld12_sqlcipher_development.json
?? soma_run.bat
?? soma_run_console.bat
?? soma_setup.bat
?? soma_stop.bat
?? src/soma/application.py
?? src/soma/migrations/0018_overview.sql
?? src/soma/migrations/0019_security_packaging.sql
?? src/soma/runtime_domains.py
?? src/soma/security/
?? tests/test_security_control_http.py
?? tests/test_security_migration.py
?? tests/test_security_passwords.py
?? tests/test_security_runtime_trust.py
?? tests/test_security_sqlcipher_native.py
?? tests/test_security_windows_native.py
?? tests/test_source_application_native.py
?? tests/test_source_control_native.py
?? tests/test_source_launchers.py
?? tools/source_launcher.py
```

## Exact final verification commands

Executed with checkout .venv:
```powershell
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-full-verification-m
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-publication-final tests/test_foundation_runtime_primitives.py tests/test_security_runtime_trust.py tests/test_security_windows_native.py tests/test_source_application_native.py tests/test_source_control_native.py
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-reset-final tests/test_source_application_native.py
.venv\Scripts\python.exe -m compileall -q src tests tools
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe tools/generate_schema_manifest.py --check src/soma/schema_manifest.json
.venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation tmp/lld12-wheel-source-final-v2 --wheel-dir dist/lld12-runtime-current
.venv\Scripts\python.exe tools/verify_wheel_resources.py dist/lld12-runtime-current
.venv\Scripts\python.exe tools/implementation_state.py check
git diff --check
git status --short
```

The isolated wheel source is a fresh copy of current src and pyproject.toml;
preexisting build/dist artifacts were preserved. SOMA wheel SHA256:
4ad2a334c334462ba8bc51f8c20d856df9a4dec5e54809acddb957654047cfef.
Resource verification passed: 19 migration files, manifests/schema/FK authority,
packet registries, Unicode and frozen UI assets.

Added reset failure/orphan regression after full-suite collection: separate native
run of both application tests passed, 2 tests in 8.34 seconds. It changes tests
only; the final source freeze already includes the orphan no-clobber fix.

Read-only CI refresh: implementation HEAD c633fe564069b04f7d384929c16da67001e538a6
has successful Beta implementation CI (37075236840) and Implementation continuation
integrity (37075236838). Those runs cover committed HEAD, not these dirty changes.
Migration bytes and manifest entries 1-17 were independently compared with HEAD
and are identical. Reference worktree has preexisting modified current-state and
launcher notes; this task did not edit them.

## Final observed result

Complete suite: 2152 passed in 676.86s (0:11:16), exit 0.
Two additional regressions added after collection passed separately:
- reset provisioning rollback/validated orphan replacement (application suite:
  2 passed in 8.34s, including the existing application test)
- real reachable loopback port with foreign run health (1 passed in 0.65s)

Port-reuse command:
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-port-reuse-final tests/test_security_runtime_trust.py::test_reused_loopback_port_with_foreign_health_never_proves_trust

Final compileall and diff checks passed. check_local_only.py passed. Native
soma_stop.bat returned exit 0, nothing running; read-only Windows process inventory
found no detached source_launcher.py host. No commits or publication were made.
Ignored local artifacts include the native wheel at its recorded path, the SOMA
verification wheel under dist/lld12-runtime-current, build sources/evidence under
tmp/lld12-native-build, fresh wheel source under tmp/lld12-wheel-source-final-v2,
and verification logs/test roots under tmp/lld12-*. The source checkout .venv was
updated with approved dependencies. User canonical encrypted data is preserved.
## Live-test routing correction — 2026-10-03

The previous application composition stripped the leading slash from
/static/ui/assets/... and compared that string with manifest-relative assets/...
names. The mismatch fell through to index.html, serving JS/CSS as text/html.
Unauthenticated static requests could also fall through to the login shell.

Changes in this follow-up:
- src/soma/application.py delegates serving to the existing UiAssets.resolve().
  /api/... is dispatched first; exact packaged static assets are returned before
  browser authentication; only closed registered client routes can reach the
  login/SPA page path. Missing assets and unknown/untrusted paths return 404.
  Escaped ASGI raw_path is retained for the owning resolver's percent/path guard.
  Content-Type is exactly the owning UiAsset content_type; no filesystem mount.
- tests/test_source_application_native.py adds live-host unauthenticated and
  authenticated routing/hash/MIME/404/API separation coverage and a real native
  Edge login/module execution/React-mount regression.
- tests/source_runtime_browser.mjs uses the existing repository Node/Playwright
  tooling with native Edge, the actual encrypted SourceApplication, no fixture/
  Vite host, and no API mocks. Test credentials travel through bounded stdin.
- This handoff records the correction. No src/web or src/soma/ui edits.

Verified exact assets:
- /static/ui/assets/index-CC0C6mm0.js: text/javascript; charset=utf-8,
  SHA256 fc9e6cff525a356b3d4c895971596c10ab60526880346d28f922fcf0018de647
- /static/ui/assets/index-CoKe4wwi.css: text/css; charset=utf-8,
  SHA256 cc795d5fa7139f975ea7a89edfd850221613bf8f3ca7788ed2eaabc2de6e3c78

Current follow-up verification (historical 2152-test full run above preceded this
routing correction; no new complete-suite certification is claimed):
- Native focused source/application/assets/control/Foundation host/routes/
  Starlette scope: 31 passed in 48.30s.
- Final live-host/application/assets scope after escaped-path guard:
  6 passed in 14.89s, including real Edge password login, JS and CSS response
  verification, #root rendered children and visible #main-content, no page error.
- First focused routing run: 14 passed in 36.26s.
- Standalone real Edge login regression: 1 passed in 5.94s.
- compileall -q src tests tools and git diff --check: passed.
- Fresh wheel build and verification passed, 19 migrations and frozen assets.
  dist/lld12-runtime-ui-routing/soma_beta-1.0.0.dev0-py3-none-any.whl
  SHA256 c559ae62a27f9118efbd1dbf9a60a572e4efb9e1438a2579745244746a86e01b.
- Read-only branch/CI refresh: implementation HEAD unchanged, latest runs passed.
  implementation_state.py check remains review_required for local dirty scopes.
- Interactive browser connector inventory was empty and iab unavailable; the
  existing native Edge/Playwright test tooling successfully verified execution.

Commands:
```powershell
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-ui-routing-final tests/test_source_application_native.py tests/test_ui_assets.py tests/test_source_control_native.py tests/test_security_control_http.py tests/test_foundation_runtime_host.py tests/test_foundation_runtime_routes.py tests/test_foundation_starlette_smoke.py
.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider --basetemp=tmp/lld12-ui-routing-wire-final tests/test_source_application_native.py tests/test_ui_assets.py
.venv\Scripts\python.exe -m compileall -q src tests tools
.venv\Scripts\python.exe tools/verify_wheel_resources.py dist/lld12-runtime-ui-routing
git diff --check
```

Browser verification used an isolated encrypted test instance; the user's
administrator credential and canonical data were not changed. The additional
manual isolated host tmp/lld12-ui-browser-live was stopped through fresh trusted
run-control verification, exit 0, and its process exited normally. Existing
canonical hosts must be restarted to load the application routing correction:
soma_stop.bat, then soma_run.bat, then sign in again.
No commit, push, branch, PR or publication.
