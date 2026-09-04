# SOMA Beta Phase 1A — Requirement / Use-Case Traceability

Status: **Seeded — 177/177 requirement owners registered; coverage classification pending**

## Purpose

This is the Phase-1A forward coverage ledger. It deliberately does not duplicate the 11,524 canonical clauses. For each requirement listed below, the exact canonical owner range is the row for that owner in `docs/reconciliation/RC006_CLAUSE_DESTINATIONS.md`; that file remains authoritative for stable clause identity/range.

A requirement is resolved only when its applicable canonical clause families are covered by one or more accepted `UC-*` use cases and/or a justified Structural Invariant (`SI`) classification. Dense mixed requirements may require both.

## Coverage states

- `Pending` — not yet classified.
- `UC` — behavioral obligations exercised by accepted use case(s).
- `SI` — structural invariant only, with rationale/destination.
- `UC+SI` — mixed requirement; behavioral and structural portions both accounted for.
- `Blocked` — genuine product ambiguity returned for controlled Phase-0 handling.

## Seed invariants

- registered requirement owners: **177 / 177**
- source owner ranges: **177 / 177** via `RC006_CLAUSE_DESTINATIONS.md`
- accepted use cases: **0**
- resolved requirement coverage: **0 / 177**
- current blocked product ambiguities: **0**

## Requirement registry

All owners are pre-registered and start `Pending`. The canonical owner range is bound by exact `BETA-REQ` identity to the accepted RC-006-A1 clause-destination map.

`BETA-REQ-0001`, `BETA-REQ-0002`, `BETA-REQ-0003`, `BETA-REQ-0004`, `BETA-REQ-0005`, `BETA-REQ-0006`, `BETA-REQ-0007`, `BETA-REQ-0008`, `BETA-REQ-0009`, `BETA-REQ-0010`, `BETA-REQ-0011`, `BETA-REQ-0012`, `BETA-REQ-0013`, `BETA-REQ-0014`, `BETA-REQ-0015`, `BETA-REQ-0016`, `BETA-REQ-0017`, `BETA-REQ-0018`, `BETA-REQ-0019`, `BETA-REQ-0020`, `BETA-REQ-0021`, `BETA-REQ-0022`, `BETA-REQ-0023`, `BETA-REQ-0024`, `BETA-REQ-0025`, `BETA-REQ-0026`, `BETA-REQ-0027`, `BETA-REQ-0028`, `BETA-REQ-0029`, `BETA-REQ-0030`, `BETA-REQ-0031`, `BETA-REQ-0032`, `BETA-REQ-0033`, `BETA-REQ-0034`, `BETA-REQ-0035`, `BETA-REQ-0036`, `BETA-REQ-0037`, `BETA-REQ-0038`, `BETA-REQ-0039`, `BETA-REQ-0040`, `BETA-REQ-0041`, `BETA-REQ-0042`, `BETA-REQ-0043`, `BETA-REQ-0044`, `BETA-REQ-0045`, `BETA-REQ-0046`, `BETA-REQ-0047`, `BETA-REQ-0048`, `BETA-REQ-0049`, `BETA-REQ-0050`, `BETA-REQ-0051`, `BETA-REQ-0052`, `BETA-REQ-0053`, `BETA-REQ-0054`, `BETA-REQ-0055`, `BETA-REQ-0056`, `BETA-REQ-0057`, `BETA-REQ-0058`, `BETA-REQ-0059`, `BETA-REQ-0060`, `BETA-REQ-0061`, `BETA-REQ-0062`, `BETA-REQ-0063`, `BETA-REQ-0064`, `BETA-REQ-0065`, `BETA-REQ-0066`, `BETA-REQ-0067`, `BETA-REQ-0068`, `BETA-REQ-0069`, `BETA-REQ-0070`, `BETA-REQ-0071`, `BETA-REQ-0072`, `BETA-REQ-0073`, `BETA-REQ-0074`, `BETA-REQ-0075`, `BETA-REQ-0076`, `BETA-REQ-0077`, `BETA-REQ-0078`, `BETA-REQ-0079`, `BETA-REQ-0080`, `BETA-REQ-0081`, `BETA-REQ-0082`, `BETA-REQ-0083`, `BETA-REQ-0084`, `BETA-REQ-0085`, `BETA-REQ-0086`, `BETA-REQ-0087`, `BETA-REQ-0088`, `BETA-REQ-0089`, `BETA-REQ-0090`, `BETA-REQ-0091`, `BETA-REQ-0092`, `BETA-REQ-0093`, `BETA-REQ-0094`, `BETA-REQ-0095`, `BETA-REQ-0096`, `BETA-REQ-0097`, `BETA-REQ-0098`, `BETA-REQ-0099`, `BETA-REQ-0100`, `BETA-REQ-0101`, `BETA-REQ-0102`, `BETA-REQ-0103`, `BETA-REQ-0104`, `BETA-REQ-0105`, `BETA-REQ-0106`, `BETA-REQ-0107`, `BETA-REQ-0108`, `BETA-REQ-0109`, `BETA-REQ-0110`, `BETA-REQ-0111`, `BETA-REQ-0112`, `BETA-REQ-0113`, `BETA-REQ-0114`, `BETA-REQ-0115`, `BETA-REQ-0116`, `BETA-REQ-0117`, `BETA-REQ-0118`, `BETA-REQ-0119`, `BETA-REQ-0120`, `BETA-REQ-0121`, `BETA-REQ-0122`, `BETA-REQ-0123`, `BETA-REQ-0124`, `BETA-REQ-0125`, `BETA-REQ-0126`, `BETA-REQ-0127`, `BETA-REQ-0128`, `BETA-REQ-0129`, `BETA-REQ-0130`, `BETA-REQ-0131`, `BETA-REQ-0132`, `BETA-REQ-0133`, `BETA-REQ-0134`, `BETA-REQ-0135`, `BETA-REQ-0136`, `BETA-REQ-0137`, `BETA-REQ-0138`, `BETA-REQ-0139`, `BETA-REQ-0140`, `BETA-REQ-0141`, `BETA-REQ-0142`, `BETA-REQ-0143`, `BETA-REQ-0144`, `BETA-REQ-0145`, `BETA-REQ-0146`, `BETA-REQ-0147`, `BETA-REQ-0148`, `BETA-REQ-0149`, `BETA-REQ-0150`, `BETA-REQ-0151`, `BETA-REQ-0152`, `BETA-REQ-0153`, `BETA-REQ-0154`, `BETA-REQ-0155`, `BETA-REQ-0156`, `BETA-REQ-0157`, `BETA-REQ-0158`, `BETA-REQ-0159`, `BETA-REQ-0160`, `BETA-REQ-0161`, `BETA-REQ-0162`, `BETA-REQ-0163`, `BETA-REQ-0164`, `BETA-REQ-0165`, `BETA-REQ-0166`, `BETA-REQ-0167`, `BETA-REQ-0168`, `BETA-REQ-0169`, `BETA-REQ-0170`, `BETA-REQ-0171`, `BETA-REQ-0172`, `BETA-REQ-0173`, `BETA-REQ-0174`, `BETA-REQ-0175`, `BETA-REQ-0176`, `BETA-REQ-0177`

## Working coverage table

During each wave, only affected requirements are added/updated below; the seed registry above guarantees global owner presence.

| BETA-REQ | Canonical family/range | Coverage | UC/SI reference | Rationale / coverage note | Result |
|---|---|---|---|---|---|

## Final Phase-1A audit requirements

Before Phase 1A acceptance, expand this working table so every registered owner has an explicit final row and verify:

1. owner set equals exactly `BETA-REQ-0001..0177`;
2. every behavioral canonical clause family is exercised by at least one accepted `UC-*`;
3. every `SI` classification has rationale and downstream design/test destination;
4. no accepted use-case behavior lacks accepted Phase-0 authority;
5. requirements with both structural and behavioral clauses are `UC+SI` where necessary rather than overclassified as structural; and
6. unresolved coverage / blocked product ambiguity count is zero.
