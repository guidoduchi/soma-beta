# SOMA Beta Normalization CP-007 — Normative Clauses

Status: **Accepted**  
Scope: all **2904** stable clauses owned by `BETA-REQ-0153`–`BETA-REQ-0177`.  
Clause identities are stable normative references. The full clause body is split into three normative shards solely for repository readability and connector-safe persistence; the split does not alter clause identity, ownership, ordering, meaning, or authority.

## Normative shards

| Shard | Requirement scope | Clauses |
|---|---|---:|
| [`CP007_CLAUSES_0153_0161.md`](CP007_CLAUSES_0153_0161.md) | `BETA-REQ-0153`–`0161` | 1058 |
| [`CP007_CLAUSES_0162_0169.md`](CP007_CLAUSES_0162_0169.md) | `BETA-REQ-0162`–`0169` | 894 |
| [`CP007_CLAUSES_0170_0177.md`](CP007_CLAUSES_0170_0177.md) | `BETA-REQ-0170`–`0177` | 952 |
| **Total** | `BETA-REQ-0153`–`0177` | **2904** |

The clause IDs and clause text in those three linked files are normative exactly as if they were stored in one physical file.

## Canonical CP-007 clause prefixes

- `BETA-REQ-0153` — `RFC-ARCH`
- `BETA-REQ-0154` — `SR-RFC-LINK`
- `BETA-REQ-0155` — `WFM-REG`
- `BETA-REQ-0156` — `WFM-PLANINT`
- `BETA-REQ-0157` — `OBJ-TEMP-GROUP`
- `BETA-REQ-0158` — `OBJ-REGROUP`
- `BETA-REQ-0159` — `IMP-HEAD`
- `BETA-REQ-0160` — `IMP-MATRIX`
- `BETA-REQ-0161` — `RFC-CASCADE`
- `BETA-REQ-0162` — `OBJ-EXECLOCK`
- `BETA-REQ-0163` — `WFM-HIERCTX`
- `BETA-REQ-0164` — `ACT-UNDO`
- `BETA-REQ-0165` — `RFC-CUST`
- `BETA-REQ-0166` — `LOCAL-TASK`
- `BETA-REQ-0167` — `TASK-OUTCOME`
- `BETA-REQ-0168` — `OBJ-IDTZ`
- `BETA-REQ-0169` — `BOUND-SCALE`
- `BETA-REQ-0170` — `WFM-LINEAGE`
- `BETA-REQ-0171` — `HIST-OBJ`
- `BETA-REQ-0172` — `WFM-SCHED`
- `BETA-REQ-0173` — `SLA-CLASS`
- `BETA-REQ-0174` — `SLA-CALC`
- `BETA-REQ-0175` — `SLA-COHORT`
- `BETA-REQ-0176` — `IMP-STAGE`
- `BETA-REQ-0177` — `TIME-AUTH`

The final global clause-ID audit intentionally avoids reusing CP-002 `OBJ-GROUP-*` and `WFM-ATTEMPT-*`. The active CP-006 canonical files directly use `RFC-FOREST-*` for `BETA-REQ-0152`, preserving CP-002 `RFC-HIER-*` ownership. [`CP006_CLAUSE_ID_AMENDMENT.md`](CP006_CLAUSE_ID_AMENDMENT.md) remains historical evidence of that correction; canonical consumers require no overlay transformation.

## Authority

- Governing obligations and classifications: [`CP007_CATALOGUE.md`](CP007_CATALOGUE.md)
- Clause owner/supporting authority: [`CP007_CLAUSE_AUTHORITY.md`](CP007_CLAUSE_AUTHORITY.md)
- Forward/reverse audit and design seeds: [`CP007_TRACEABILITY.md`](CP007_TRACEABILITY.md)
