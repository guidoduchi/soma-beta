# SOMA — Agent Instructions

## Purpose

SOMA Beta is a local-first operations platform implemented from an accepted, machine-addressable HLD/LLD design.

Work as an implementation engineer under existing product and architecture authority. Do not invent product behavior when authority exists. This file defines how to work in the repository; it does not replace the normative specification.

## Start every task

For implementation continuation, first read `docs/implementation/current-state.json`
and `docs/implementation/continuation-workflow.md`. They index checkpoint evidence
and bounded tasks; they are not normative product authority. Refresh branch heads
and CI, then use `tools/implementation_state.py check` to target changed scopes.
Unchanged declared scope is continuity only, never automatic certification. Follow
the current user's task, not a stale generated prompt's selected task. Generate
copy-ready handovers with the tool instead of maintaining competing roadmap files.

Before changing code:

1. Inspect the branch and working tree with `git status --short --branch`.
2. Determine the exact requested scope.
3. Locate the relevant implementation modules, tests, implementation ledger, and normative packet.
4. Resolve the exact design revision pinned by the implementation checkpoint/CI before relying on design files.
5. Read the applicable packet index and the exact normative leaves needed for the task: commands, queries, schema, algorithms, transitions, bounds, errors, interfaces, audit, jobs, migrations, tests, and implementation module map as applicable.
6. Search for existing shared infrastructure and cross-packet interfaces before introducing new abstractions.
7. Preserve unrelated user/local changes. Never discard, reset, clean, or overwrite work outside the task.

Do not implement merely because expected behavior seems obvious.

## Authority and traceability

The accepted normalized requirements and canonical clauses are product authority. Accepted owner clarifications and focused normative contracts refine that authority within their owning scope. Derived synthesis documents cannot override their owners.

For implementation work, the pinned machine-readable design under `spec/` is the detailed implementation contract, subject to the authority order above.

Important design locations on `design/beta-1.0-hld-lld` include:

- `spec/requirements/`
- `spec/authority/`
- `spec/hld/`
- `spec/lld/`
- `docs/reconciliation/`
- focused normative contracts under `docs/`

Important implementation evidence includes:

- `docs/implementation/`
- `src/`
- `tests/`
- `tools/`
- `.github/workflows/`

Read design without switching away from the active implementation branch when possible. Prefer read-only commands such as:

```powershell
git fetch origin design/beta-1.0-hld-lld
git show <pinned-design-sha>:spec/lld/<packet>/<file>
```

Do not silently advance from the pinned design revision to a newer design revision.

If authoritative sources conflict, identify the exact conflict and use the reconciliation process. Do not choose new behavior for convenience and do not "fix the specification in code."

Code and passing tests are evidence of current behavior; they do not override normative authority.

## LLD implementation discipline

Start from the relevant packet `_index.json`.

Only paths listed as normative by the packet are implementation authority. Treat explicitly identified legacy synthesis files as nonnormative when the packet says so.

Use the packet's `implementation/module-map.json` for ownership and dependency direction. Do not manufacture empty wrappers solely for filename parity when existing accepted implementation ownership differs; preserve traceability and document any genuine layout divergence.

Cross-packet interfaces have exactly one provider. Consumers must use declared interfaces rather than reading or writing another packet's private tables.

Do not duplicate lifecycle or mutation authority owned by another packet.

## Correctness standard

Passing tests is necessary but not sufficient.

For substantive changes, reason about:

- normative semantics and identity;
- lifecycle/state transitions;
- bounds and edge cases;
- stale revisions and fingerprints;
- failure behavior and rollback;
- transaction and Unit-of-Work ownership;
- replay/idempotency behavior;
- audit evidence;
- recovery and crash safety;
- pagination, deterministic ordering, and cursor identity;
- schema constraints, indexes, and integrity verification;
- cross-packet ownership;
- security/trust boundaries;
- migration compatibility;
- packaging/resources;
- algorithmic complexity and measured database/file work.

When fixing a defect, add or strengthen a regression test that would have detected it when practical.

Never claim full compliance solely because tests pass.

## Commands, transactions, replay, and audit

Authoritative mutations use one outer LLD-01 UnitOfWork unless an accepted contract explicitly says otherwise.

Do not create nested authoritative command boundaries or nested receipts.

Cross-domain participants in an atomic command reuse the caller's UnitOfWork and command receipt.

Pure or expensive preparation may occur outside the writer transaction when safe, but eligibility, freshness, and mutable-state invariants required for correctness must be revalidated inside the authoritative writer UnitOfWork.

Required mutation, lifecycle evidence, replay result, cross-packet participant changes, and action-specific audit must obey the packet's atomicity contract.

Mutating commands use the canonical command envelope and exact request-hash semantics defined by Foundation. An eligible replay returns the exact immutable committed result. Do not re-execute a committed command because a replay result is inconvenient or unavailable.

Audit is append-only. Do not fabricate mutation or `NO_CHANGE` evidence. A no-change path must follow the exact owning contract and must not increment revisions unless explicitly specified.

## Persistence and migrations

SQLite is the authoritative operational datastore for Beta 1.0; production encryption/security composition follows its owning LLD authority.

Use the owned connection/Unit-of-Work abstractions. Repositories do not commit independently.

Schema guards, foreign keys, supporting indexes, append-only protections, manifests, migration hashes, and verification logic are correctness mechanisms.

Accepted runtime migrations in `src/soma/migrations/manifest.json` are immutable historical facts: never renumber, rewrite, reorder, or change their accepted bytes/hashes.

For a new migration:

1. inspect the accepted runtime manifest;
2. inspect the pinned design `spec/lld/migrations.json` and packet migration allocation;
3. distinguish accepted runtime history from provisional future design allocation;
4. never choose a migration sequence ad hoc;
5. if the runtime manifest and a packet-local historical filename differ, do not infer authority from the filename alone.

Future allocation changes require explicit design authority. Forward-only repair is preferred over rewriting accepted history.

## Queries and performance

Queries must honor exact bounds, deterministic total ordering, pagination, null ordering, cursor schemas, and required indexes.

Do not truncate a composite ordering key in a continuation token.

Do not materialize unbounded operator-controlled collections.

Do not raise global JSON/response limits merely to hide a paging or representation defect.

Evaluate both asymptotic complexity and actual work. Watch for:

- N+1 queries;
- repeated reads of stable/immutable inputs;
- full scans inside loops;
- unnecessary temporary sorts;
- complete blocker enumeration when an indexed existence probe suffices;
- global recomputation under a writer lock;
- process-wide caches for snapshot-specific mutable state;
- repeated serialization/deserialization;
- long writer transactions.

Prefer bounded indexed lookups, keyset paging, batching, prefetching, read snapshots, and safe reuse of already validated immutable inputs.

Optimization must not weaken authority, atomicity, replay, auditability, or freshness revalidation.

## Imports and generated artifacts

Treat imported files as untrusted.

Honor the owning packet's file, archive, worksheet, cell, formula, path, request-size, and parsing bounds.

When preflight and parsing are governed by one immutable-input contract, both operate on the same captured bytes. Do not reopen a mutable path and silently consume different content.

Generated artifacts must follow their versioned artifact contract, including naming, ordering, atomic publication, collision handling, and verification.

## Domain identity

Do not merge, replace, normalize, or reuse identity based on descriptive similarity unless the owning contract explicitly makes that field authoritative.

Examples of governed identities include official SR identities, Spare Request identifiers, RMA identifiers, Fault Tags, Local Spare Units, Device References, and Infrastructure Network Elements. Their exact validation, correction, lifecycle, and reuse rules belong to their owning packets.

A warning or duplicate descriptive value is not identity authority.

## Scope and Git safety

Implement the requested scope completely without opportunistically starting later LLDs or unrelated product work.

A necessary cross-cutting fix is acceptable only when required for correctness; keep it minimal and explain the dependency.

Avoid broad refactors during narrow fixes unless structure prevents a correct implementation.

Never force-push, rewrite published history, delete branches, destructively reset, or merge unless explicitly requested.

Do not amend existing commits unless requested.

Before finishing, inspect:

```powershell
git status --short
git diff --check
git diff
```

Do not claim a branch, commit, CI, or test state that was not actually verified.

## Verification

Use focused tests during development.

Before declaring a substantial implementation task complete, run the relevant focused suite and, when practical, the complete implementation verification expected by CI:

```powershell
python -m pip install -e ".[test]"
python -m compileall -q src tests
python -m pytest
python -m pip wheel --no-deps . --wheel-dir dist
python tools/verify_wheel_resources.py dist
```

Also run applicable repository integrity, schema-manifest, acceptance-marker, artifact, traceability, failure-injection, or packet-specific checks.

Do not edit a failing test merely to make the suite green. First determine whether implementation, test, or design authority is wrong.

For current campaign state, incomplete slices, audit debt, and exact checkpoints, inspect `docs/implementation/` rather than encoding transient status in this file.

## Completion standard

Before reporting completion, verify that:

- requested behavior is actually implemented;
- implementation agrees with the pinned normative authority;
- applicable acceptance/failure/security cases are covered;
- cross-packet ownership and module-map direction are preserved;
- transaction, replay, revision, and audit semantics are correct;
- schema/index/migration authority is preserved;
- access patterns are bounded and avoid obvious repeated work;
- focused tests pass;
- broader CI-equivalent checks pass when required and practical;
- the final diff contains only intended changes;
- unresolved authority conflicts, skipped checks, environment limitations, and known remaining gaps are stated explicitly.

Prefer evidence over assumption.
Prefer owning authority over accidental current behavior.
Prefer the smallest correct architecture-preserving change over a shortcut.
Prefer explicit reconciliation over invented requirements.
Correctness first; then clarity; then measured optimization.
