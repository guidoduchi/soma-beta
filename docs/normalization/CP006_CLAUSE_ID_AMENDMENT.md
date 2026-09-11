# SOMA Beta Normalization CP-006 — Clause ID Amendment A1

Status: **Accepted as part of final normalization audit; active canonical files directly corrected**  
Affected owner: `BETA-REQ-0152` only  
Product-semantics change: **none**

## Reason

The final global clause-ID audit found that CP-006 reused prefix `RFC-HIER` for `BETA-REQ-0152`, while `RFC-HIER-001..009` had already been assigned in CP-002 to `BETA-REQ-0040`. Stable clause IDs must be globally unambiguous, so the later reuse cannot remain canonical.

## Canonical correction

All CP-006 clauses owned by `BETA-REQ-0152` are re-keyed by prefix only:

- legacy CP-006 checkpoint representation: `RFC-HIER-001..124`
- active canonical clause IDs: `RFC-FOREST-001..124`
- owner remains: `BETA-REQ-0152`
- clause suffixes remain: `001..124`
- clause wording, order, count, governing obligation, supporting authority, and design traceability remain unchanged.

`RFC-HIER-001..009` remain canonical clauses owned by `BETA-REQ-0040` in CP-002. Historical references to `RFC-HIER-010..124` as CP-006 identifiers are deprecated; current references to CP-006 `0152` shall use `RFC-FOREST-010..124`.

## Active canonical files and historical evidence

Git history preserves the original CP-006 checkpoint-as-landed representation in commit `3a2cd0798a25fa194bbebea6d8ca8478597302e9`. The active canonical normalization files now carry the correction directly:

- `CP006_CLAUSES.md` declares `BETA-REQ-0152` with prefix `RFC-FOREST`;
- `CP006_CLAUSE_AUTHORITY.md` uses `RFC-FOREST-001..124` for both owner and supporting-authority ranges;
- `CP006_TRACEABILITY.md` records `RFC-FOREST-001..124` as the active canonical range and states that no overlay is required.

This amendment remains historical evidence explaining why the mechanical correction occurred. It is **not** an overlay that canonical consumers must apply. Test generators, traceability tools, HLD/LLD mappers, and human reviewers may read the active canonical files literally.

## Audit consequence

After direct canonical-file correction:

- CP-002 retains literal `RFC-HIER-001..009` under `BETA-REQ-0040`;
- CP-006 carries literal `RFC-FOREST-001..124` under `BETA-REQ-0152`;
- no clause changes owner;
- no product behavior changes;
- CP-006 remains **3444** clauses;
- cumulative accepted clause count through CP-006 remains **8620**;
- no overlay transformation is required for global clause-ID uniqueness or downstream traceability;
- the complete normalization layer contains **11524 literal clause rows and 11524 globally unique canonical clause IDs, with 0 collisions**.
