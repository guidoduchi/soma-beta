# SOMA AI-first design specification

This tree is the active machine-addressable design surface for Beta 1.0 HLD/LLD work. The accepted normalized catalogues and clauses remain product authority; these shards are lossless navigation records for AI design and implementation work.

## Layout

- `requirements/CP001..CP007/` — one accepted normalized requirement per JSON file.
- `requirements/_index.json` — global immutable-ID path index.
- `authority/implementation-clarifications.json` — accepted implementation clarifications discovered during semantic reconciliation.
- `hld/` — modular high-level design, created next.
- `lld/` — implementation-ready domain packets, created after HLD ownership is fixed.

Design artifacts should answer what must be built, how it must be built, or how correctness is proven.
