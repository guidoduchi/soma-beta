# Repository-backed continuation

`current-state.json` is the compact entry point for ongoing work. Existing semantic
ledgers remain detailed evidence; accepted design remains authority. Historical
roadmaps and slice notes remain historical. A generated handover is a prompt for
another chat, not a second editable source of project state.

## Start a session

1. Read `AGENTS.md` and the manifest. Honor the current user request.
2. Fetch live branch heads and CI through GitHub. With a local mirror, refresh
   explicit remote-tracking refs; plain `git fetch origin branch` can leave the
   tracking ref stale. Inspect a dirty working tree and preserve unrelated work.
3. Validate references and compare refreshed implementation/design objects:

```sh
python tools/implementation_state.py validate
python tools/implementation_state.py check --implementation-ref HEAD --design-ref origin/design/beta-1.0-hld-lld --json
```

The tool does not fetch, call GitHub, install dependencies, execute recorded task
commands, or mutate state. Git and Python's standard library are sufficient; the
application's supported Python requirements remain unchanged. If an immutable
checkpoint object is missing in a shallow checkout, fetch that exact SHA before
retrying. A missing object is an error, never a claim that evidence is current.

`validate` checks shape, unique JSON keys, full commit IDs, available checkpoint
objects, exact referenced files/test functions, dependency cycles, task evidence
links, and CI-to-checkpoint SHA agreement. Recorded remote CI conclusions still
require independent GitHub verification. It does not semantically audit ledgers.

`check` compares committed trees, includes both sides of renames, detects ancestry
breaks, and propagates changed provider scopes to declared consumers. Shared
Foundation/migration/composition changes conservatively affect all scopes.
Unclassified changes also require broad review. Scoped evidence changes take
precedence over documentation exclusions. Patterns use Python `fnmatchcase`,
where `*` includes `/`; these are not Git pathspecs. Keep dependency mappings
conservative and review unmapped paths before refining them.

Exit codes: 0 = structurally valid/unchanged declared scopes; 1 = invalid or
unavailable input; 2 = `check` requires review or has dirty working-tree entries.
Remote freshness is always explicitly unverified by this offline tool. A clean
exit is not packet certification. Working-tree bytes are excluded from committed
diffs and cause a warning/nonzero check result.

## Produce a prompt-compatible handover

```sh
python tools/implementation_state.py prompt --design-ref origin/design/beta-1.0-hld-lld
python tools/implementation_state.py prompt --task infra-certification --design-ref origin/design/beta-1.0-hld-lld --output /path/outside/repo/SOMA-continuation.md
```

The output is directly pasteable into a new chat: role/mission, exact checkpoints,
freshness warnings, CI evidence, selected task, read-first references, completion
criteria, verification instructions, constraints, remaining queue and pause/update
instructions. It never says an observed failed run is green or silently replaces
the accepted design pin. `--task` selects a bounded context without changing the
manifest. The current user's authorization always controls execution.

The prompt lists at most 30 changed paths and explicitly reports omitted paths;
`check --json` provides the complete list. It links to exact sources instead of
embedding the whole specification or every historical ledger. Output defaults to
stdout. `--output` creates a new file and refuses to overwrite an existing one.
Generated prompts are not checked into this repository or edited manually.

Without local Git, use the same manifest with GitHub: fetch heads, compare each
relevant checkpoint to those heads, fetch changed owners and their normative
leaves, and inspect exact-head CI. Do not claim the offline tool verified remote
state. Missing context or unknown dependencies require expanding the review.

## Update a checkpoint

At a coherent checkpoint, update the one manifest:

- `observed_at` and `observed_heads`: actual capture time and fetched branch SHAs.
- `checkpoints`: exact implementation/design pair used for each evidence scope.
  Pin the inspected source commit, not the commit that will contain the manifest.
  This prevents endless self-referential SHA updates.
- `ci`: observed run ID, exact tested SHA, conclusion and concise lane/resource
  details. A later code commit does not inherit a previous green result.
- `scopes`: source patterns and conservative consumer dependencies. A source
  change invalidates continuity, not necessarily the original historical proof.
- `evidence`: checkpoint, implementation/design source, path, purpose, and optional
  top-level Python test node. The immutable Git commit binds its contents.
- `tasks`: status, dependencies, next action/resume note, read-first references,
  acceptance criteria and verification. A done task requires completion evidence;
  its human reviewer must verify that the evidence actually proves the criteria.
- `next_task`, `constraints`, `known_limits`: bounded next action and honest limits.

Run validation and focused tooling tests before publishing. Do not automatically
promote a semantic ledger, fix flags by majority vote, rewrite accepted migration
history, or erase future-owner exclusions. Domain owners review normative changes.
New schemas/validation behavior require a versioned tool/manifest change together.

## Lightweight verification

```sh
python -m unittest discover -s tests -p test_implementation_state.py -v
```

The dedicated workflow runs these tests and reference validation when continuation
files change. Existing application CI remains unchanged; one coherent tool commit
may also trigger its matrix through existing `tools/**` or `tests/**` filters.
Do not create repeated micro-commits to chase CI or self-referential checkpoint IDs.
