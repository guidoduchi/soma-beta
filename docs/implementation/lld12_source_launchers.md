# LLD-12 Source Launcher / Trusted Runtime Control — partial enabling slice

This intentionally early source-development scaffold supports the active LLD-10
campaign. LLD-10 remains `in_progress_not_certified`. LLD-12 is neither implemented
nor certified. **LLD12-P008: PARTIAL / dependency-pending.** These launchers cannot
yet start, open, or stop a host; they do not satisfy the trusted-control protocol.

## Captured baseline and isolation

- Implementation base: `1b28fc1da375723ae1e41fba0c473a08df55eb4f` on
  `feat/beta-1.0-implementation`; initially clean, no untracked files.
- Fetched design HEAD and accepted pin:
  `9a0e891127a771251afccca1a281b7ef7dde9e5f` (not advanced).
- Current-head CI at preflight: continuation run `37069650002` succeeded;
  implementation run `37069650018` was in progress. No new-slice CI inherited.
- Isolated branch: `feat/lld12-source-launchers`, based on that implementation
  HEAD. Active checkout is untouched, including subsequent untracked LLD-10 work.
- Planned changes: four root BAT adapters, `tools/source_launcher.py`, private
  `src/soma/security/runtime/source_control.py` and package initializers,
  `tests/test_source_launchers.py`, this document and continuation state only.

`implementation_state.py check` was executed against refreshed design and HEAD:
historical provider/shared changes require review; working tree was initially
clean. Unchanged scope does not renew certification. No overall completion
percentage or P001–P017 certification is assigned here.

## Authority read and concrete dependencies

All paths below were inspected at the accepted design pin:

- `spec/lld/security-packaging/_index.json`
- `spec/lld/security-packaging/implementation/module-map.json`
- `spec/lld/security-packaging/algorithms/trusted-instance.json`
- `spec/lld/security-packaging/types/runtime-control.json`
- `spec/lld/security-packaging/interfaces.json`
- `spec/lld/security-packaging/interfaces/cross-packet-v2.json`
- `spec/lld/security-packaging/algorithms/package-lifecycle.json`
- `spec/lld/security-packaging/tests/packaging.json`
- `spec/lld/foundation-runtime/algorithms/runtime-host.json`
- `spec/lld/foundation-runtime/implementation/module-map.json`

The safe boundary has three named dependencies:

1. **LLD12-SOURCE-REGISTRY-RECONCILIATION**: Foundation runtime-host specifies
   `SOMA-RUNTIME-REGISTRY-V1` and eight fields. Existing `registry.py` requires
   `registry_version=1`, `origin='SOMA'` and an absolute HTTP readiness locator.
   LLD-12 specifies version 2, canonical HTTP origin, a relative DPAPI file locator
   and an additional publication timestamp. Foundation `RuntimeHealth` lacks
   PID/birth and uses `host_state`; LLD-12 `RuntimeHealthV1` requires PID/birth
   and `status`. No accepted reconciliation or V1 compatibility rule was found
   in the pinned reconciliation/cross-packet layer. Resolve this with owning
   authority before changing certified Foundation contracts. Do not invent V1.5,
   rewrite the registry after HostRuntime publishes it, or use parallel registries.
2. **LLD12-SOURCE-WINDOWS-TRUST**: owner-only ACL/reparse validation, CurrentUser
   purpose/run-bound DPAPI secret capture, Windows process FILETIME and accepted
   source-child image identity, direct no-proxy/no-redirect authenticated health,
   exact run/data/process matching, server Host/forwarded-header guards and fresh
   shutdown verification are absent. Do not substitute PID/port heuristics or
   test credentials. The source child identity must be explicitly governed.
3. **LLD12-SOURCE-APPLICATION-COMPOSITION**: current `composition.py` provides
   owner/startup helpers, not a runnable application factory. Runtime host/server
   and Foundation routes are injection seams. Authoritative `ConnectionFactory`
   requires SQLCipher and a real live-key security provider and deliberately has
   no plaintext fallback. Existing tests inject plaintext/test security explicitly;
   those are not source-runtime authority. Completing SQLCipher/live-key/browser
   security is outside this mission, and the source launcher cannot bypass it.

No Foundation host, registry, lock, socket, routes, persistence or health contract
was changed. Future implementation must reuse HostRuntime and FoundationRoutes,
retaining their migrations, readiness, UoW, replay, audit and graceful drain.
`source_control.py` is a private fail-closed adapter, **not** `RunControlProvider`,
`GetRuntimeTrustStatus`, `trust.py` or `control.py` implementation authority.

## Use from the isolated Windows checkout

Run these files from any working directory; paths are anchored to the BAT file.
Install Python 3.13 or 3.14 with the Windows `py` launcher first.

```text
soma_setup.bat
soma_run_console.bat
soma_run.bat
soma_stop.bat
```

Setup chooses 3.14, then 3.13, creates or reuses checkout-local `.venv`, checks
its supported version and exact environment prefix, and runs the accepted
`python -m pip install -e ".[test]"` workflow. Setup can require dependency
network access. It never initializes, migrates, reads or erases an instance.
Incomplete/unsupported environments fail without automatic deletion/replacement.
Rerunning setup may reinstall editable package metadata; idempotence means reuse
of the environment and preservation of authoritative data, not byte-identical pip
metadata. Pip failures remain visible and actionable. This is not an installer.

All three runtime adapters use `.venv` and return **20 (`dependency_pending`)**
after prerequisite checks. Console keeps execution attached and propagates status.
They do not inspect runtime.json, contact a port, spawn a host, open a browser or
terminate a process. Missing/unsupported prerequisites return **10**; environment
operation or pip failure returns **11**. No successful stopped/already-stopping/
no-valid-instance result is claimed before real instance verification exists.

The intended future UX is console for visible debugging, run for verified reuse
or background start/open, stop for fresh authenticated graceful shutdown. Those
operations are currently unavailable. Do not manually delete runtime.json or kill
Python processes as a workaround. LLD-10 can continue independently using its
existing tests and fixture harness; this scaffold does not yet enable live source
application testing.

## Evidence and untouched work

Focused tests prove setup reuse/data preservation, explicit prerequisite and pip
failure, runtime fail-closed behavior without external authority, exit propagation
and platform-neutral imports. They **do not** prove real-host start/reuse,
127.0.0.1 ephemeral binding, interrupt cleanup, graceful stop, hostile/reused PID,
birth/run/data/authentication rejection, proxy/redirect rejection or verified open.
Those requested operational scenarios remain dependency-pending with P008.

Untouched: Local Admin/password/session/CSRF/deliberate action, SQLCipher migration
and live DEK, backups/restore, diagnostics, installer/tray/PyInstaller, signing,
production uninstall and release smoke matrix. No other LLD-12 acceptance case
is claimed. Existing migration bytes and LLD-10 owner/UI semantics are preserved.
