# SOMA Beta Normalization CP-006 — Clause ID Amendment A1

Status: **Accepted as part of final normalization audit**  
Affected owner: `BETA-REQ-0152` only  
Product-semantics change: **none**

## Reason

The final global clause-ID audit found that CP-006 reused prefix `RFC-HIER` for `BETA-REQ-0152`, while `RFC-HIER-001..009` had already been assigned in CP-002 to `BETA-REQ-0040`. Stable clause IDs must be globally unambiguous, so the later reuse cannot remain canonical.

## Canonical correction

All CP-006 clauses owned by `BETA-REQ-0152` are re-keyed by prefix only:

- legacy CP-006 representation: `RFC-HIER-001..124`
- canonical clause IDs after this amendment: `RFC-FOREST-001..124`
- owner remains: `BETA-REQ-0152`
- clause suffixes remain: `001..124`
- clause wording, order, count, governing obligation, supporting authority, and design traceability remain unchanged.

`RFC-HIER-001..009` remain canonical clauses owned by `BETA-REQ-0040` in CP-002. References to `RFC-HIER-010..124` as CP-006 identifiers are deprecated legacy references; new references to the CP-006 `0152` clauses shall use `RFC-FOREST-010..124`.

## Reading historical CP-006 artefacts

`CP006_CLAUSES.md` and `CP006_CLAUSE_AUTHORITY.md` preserve the checkpoint-as-landed text and therefore still display the legacy `RFC-HIER` prefix for `BETA-REQ-0152`. This amendment is the authoritative prefix overlay for those rows. Consumers shall resolve every `BETA-REQ-0152` CP-006 clause suffix through `RFC-FOREST` before performing global clause-ID uniqueness checks or downstream traceability.

## Audit consequence

After applying this prefix-only amendment:

- CP-002 retains `RFC-HIER-001..009` under `BETA-REQ-0040`;
- CP-006 owns `RFC-FOREST-001..124` under `BETA-REQ-0152`;
- no clause changes owner;
- no product behavior changes;
- CP-006 remains **3444** clauses;
- cumulative accepted clause count through CP-006 remains **8620**;
- global clause-ID ambiguity caused by the CP-006 reuse is removed.
