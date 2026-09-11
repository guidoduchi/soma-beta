# SOMA Beta Normalization CP-007 — Clause Authority Matrix

Status: **Accepted**  
Scope: all **2904** stable clauses owned by `BETA-REQ-0153`–`BETA-REQ-0177`.  
Purpose: explicit owner/supporting-authority evidence for the CP-007 reverse audit.

## Owner mapping

Every clause in each inclusive range has exactly one listed owner. Range notation is clause-level evidence and does not transfer ownership to supporting requirements.

| Clause range | Owner |
|---|---|
| `RFC-ARCH-001..110` | `BETA-REQ-0153` |
| `SR-RFC-LINK-001..112` | `BETA-REQ-0154` |
| `WFM-REG-001..110` | `BETA-REQ-0155` |
| `WFM-PLANINT-001..116` | `BETA-REQ-0156` |
| `OBJ-TEMP-GROUP-001..122` | `BETA-REQ-0157` |
| `OBJ-REGROUP-001..124` | `BETA-REQ-0158` |
| `IMP-HEAD-001..120` | `BETA-REQ-0159` |
| `IMP-MATRIX-001..112` | `BETA-REQ-0160` |
| `RFC-CASCADE-001..132` | `BETA-REQ-0161` |
| `OBJ-EXECLOCK-001..120` | `BETA-REQ-0162` |
| `WFM-HIERCTX-001..096` | `BETA-REQ-0163` |
| `ACT-UNDO-001..114` | `BETA-REQ-0164` |
| `RFC-CUST-001..108` | `BETA-REQ-0165` |
| `LOCAL-TASK-001..104` | `BETA-REQ-0166` |
| `TASK-OUTCOME-001..120` | `BETA-REQ-0167` |
| `OBJ-IDTZ-001..116` | `BETA-REQ-0168` |
| `BOUND-SCALE-001..116` | `BETA-REQ-0169` |
| `WFM-LINEAGE-001..104` | `BETA-REQ-0170` |
| `HIST-OBJ-001..116` | `BETA-REQ-0171` |
| `WFM-SCHED-001..112` | `BETA-REQ-0172` |
| `SLA-CLASS-001..116` | `BETA-REQ-0173` |
| `SLA-CALC-001..132` | `BETA-REQ-0174` |
| `SLA-COHORT-001..120` | `BETA-REQ-0175` |
| `IMP-STAGE-001..128` | `BETA-REQ-0176` |
| `TIME-AUTH-001..124` | `BETA-REQ-0177` |

## Additional supporting authority

Supporting authority strengthens provenance only; it does not transfer ownership or authorize new product behavior. References to `BETA-REQ-0152` resolve directly against the active canonical CP-006 `RFC-FOREST-*` range. `CP006_CLAUSE_ID_AMENDMENT.md` records the historical reason for that mechanical correction; no overlay transformation is required.

| Clause range | Supporting authority |
|---|---|
| `RFC-ARCH-001..110` | `BETA-REQ-0019`; `BETA-REQ-0025`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0149`; `BETA-REQ-0152`; Communications terminal/orphan-grace authority |
| `SR-RFC-LINK-001..112` | `BETA-REQ-0019`; `BETA-REQ-0039`; `BETA-REQ-0040`; `BETA-REQ-0147`; `BETA-REQ-0151`; `BETA-REQ-0152`; SLA and Communications lifecycle-independence authority |
| `WFM-REG-001..110` | `BETA-REQ-0013`; `BETA-REQ-0041`; `BETA-REQ-0042`; `BETA-REQ-0046`; `BETA-REQ-0148`; `BETA-REQ-0149`; `BETA-REQ-0150`; Objective regrouping remains separately owned |
| `WFM-PLANINT-001..116` | `BETA-REQ-0017`; `BETA-REQ-0047`; `BETA-REQ-0048`; `BETA-REQ-0146`; `BETA-REQ-0155`; Task retry/history authority |
| `OBJ-TEMP-GROUP-001..122` | `BETA-REQ-0043`; `BETA-REQ-0047`; `BETA-REQ-0048`; `BETA-REQ-0050`; `BETA-REQ-0152`; `BETA-REQ-0156`; Customer resolution authority |
| `OBJ-REGROUP-001..124` | `BETA-REQ-0019`; `BETA-REQ-0048`; `BETA-REQ-0050`; `BETA-REQ-0135`; `BETA-REQ-0146`; `BETA-REQ-0157`; lifecycle/history locks |
| `IMP-HEAD-001..120` | `BETA-REQ-0012`; `BETA-REQ-0013`; `BETA-REQ-0030`; `BETA-REQ-0059`; `BETA-REQ-0146`; `BETA-REQ-0157`; Customer reconciliation authority |
| `IMP-MATRIX-001..112` | `BETA-REQ-0013`; `BETA-REQ-0059`; `BETA-REQ-0136`; `BETA-REQ-0142`; `BETA-REQ-0146`; `BETA-REQ-0159`; measured LLD bounds only |
| `RFC-CASCADE-001..132` | `BETA-REQ-0019`; `BETA-REQ-0040`; `BETA-REQ-0041`; `BETA-REQ-0149`; `BETA-REQ-0152`; `BETA-REQ-0155`; `BETA-REQ-0158`; Communications orphan-grace authority; Task/Objective lifecycle authority |
| `OBJ-EXECLOCK-001..120` | `BETA-REQ-0019`; `BETA-REQ-0043`; `BETA-REQ-0050`; `BETA-REQ-0135`; `BETA-REQ-0158`; `BETA-REQ-0161`; Task/Objective lifecycle authority |
| `WFM-HIERCTX-001..096` | `BETA-REQ-0013`; `BETA-REQ-0040`; `BETA-REQ-0041`; `BETA-REQ-0042`; `BETA-REQ-0152`; `BETA-REQ-0155`; `BETA-REQ-0158`; `BETA-REQ-0161` |
| `ACT-UNDO-001..114` | `BETA-REQ-0019`; `BETA-REQ-0127`; `BETA-REQ-0129`; `BETA-REQ-0135`; `BETA-REQ-0143`; `BETA-REQ-0152`; `BETA-REQ-0154`; `BETA-REQ-0155`; `BETA-REQ-0158`; `BETA-REQ-0161`; `BETA-REQ-0162` |
| `RFC-CUST-001..108` | `BETA-REQ-0010`; `BETA-REQ-0027`; `BETA-REQ-0030`; `BETA-REQ-0146`; `BETA-REQ-0151`; `BETA-REQ-0152`; `BETA-REQ-0157`; `BETA-REQ-0159`; `BETA-REQ-0164` |
| `LOCAL-TASK-001..104` | `BETA-REQ-0010`; `BETA-REQ-0041`; `BETA-REQ-0043`; `BETA-REQ-0046`; `BETA-REQ-0102`; `BETA-REQ-0155`; `BETA-REQ-0157`; `BETA-REQ-0158`; `BETA-REQ-0162` |
| `TASK-OUTCOME-001..120` | `BETA-REQ-0017`; `BETA-REQ-0043`; `BETA-REQ-0046`; `BETA-REQ-0050`; `BETA-REQ-0135`; `BETA-REQ-0156`; `BETA-REQ-0161`; `BETA-REQ-0162`; `BETA-REQ-0166`; Objectives/Task lifecycle owns execution/outcome/review/correction/retry |
| `OBJ-IDTZ-001..116` | `BETA-REQ-0010`; `BETA-REQ-0017`; `BETA-REQ-0043`; `BETA-REQ-0157`; `BETA-REQ-0158`; `BETA-REQ-0162`; `BETA-REQ-0167`; report-snapshot authority; technical design item `O-001` only for snapshot persistence mechanics |
| `BOUND-SCALE-001..116` | `BETA-REQ-0018`; `BETA-REQ-0059`; `BETA-REQ-0124`; `BETA-REQ-0125`; `BETA-REQ-0136`; `BETA-REQ-0137`; `BETA-REQ-0141`; `BETA-REQ-0142`; `BETA-REQ-0159`; `BETA-REQ-0160`; `BETA-REQ-0166` |
| `WFM-LINEAGE-001..104` | `BETA-REQ-0013`; `BETA-REQ-0042`; `BETA-REQ-0046`; `BETA-REQ-0155`; `BETA-REQ-0156`; `BETA-REQ-0157`; `BETA-REQ-0158`; `BETA-REQ-0160`; `BETA-REQ-0161`; `BETA-REQ-0163`; `BETA-REQ-0167` |
| `HIST-OBJ-001..116` | `BETA-REQ-0019`; `BETA-REQ-0043`; `BETA-REQ-0050`; `BETA-REQ-0128`; `BETA-REQ-0135`; `BETA-REQ-0143`; `BETA-REQ-0155`; `BETA-REQ-0156`; `BETA-REQ-0157`; `BETA-REQ-0158`; `BETA-REQ-0162`; `BETA-REQ-0167`; `BETA-REQ-0168` |
| `WFM-SCHED-001..112` | `BETA-REQ-0017`; `BETA-REQ-0146`; `BETA-REQ-0155`; `BETA-REQ-0156`; `BETA-REQ-0157`; `BETA-REQ-0158`; `BETA-REQ-0162`; `BETA-REQ-0166`; `BETA-REQ-0167`; `BETA-REQ-0168`; `BETA-REQ-0164` |
| `SLA-CLASS-001..116` | Customer/reference authority; Advanced Search field disposition authority; `BETA-REQ-0064`; `BETA-REQ-0065`; `BETA-REQ-0128`; `BETA-REQ-0129`; `BETA-REQ-0135`; `BETA-REQ-0143`; `BETA-REQ-0165`; current-report snapshot authority |
| `SLA-CALC-001..132` | `BETA-REQ-0017`; `BETA-REQ-0063`; `BETA-REQ-0064`; `BETA-REQ-0065`; `BETA-REQ-0071`; `BETA-REQ-0128`; `BETA-REQ-0135`; `BETA-REQ-0143`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0171`; `BETA-REQ-0173` |
| `SLA-COHORT-001..120` | `BETA-REQ-0017`; `BETA-REQ-0064`; `BETA-REQ-0065`; `BETA-REQ-0071`; `BETA-REQ-0128`; `BETA-REQ-0168`; `BETA-REQ-0169`; `BETA-REQ-0171`; `BETA-REQ-0173`; `BETA-REQ-0174` |
| `IMP-STAGE-001..128` | `BETA-REQ-0012`; `BETA-REQ-0013`; `BETA-REQ-0059`; `BETA-REQ-0074`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0148`; `BETA-REQ-0149`; `BETA-REQ-0150`; `BETA-REQ-0152`; `BETA-REQ-0158`; `BETA-REQ-0159`; `BETA-REQ-0160`; `BETA-REQ-0161`; `BETA-REQ-0169`; `BETA-REQ-0170`; `BETA-REQ-0172`; technical design item `O-007` only for exact low-risk auto-accept classes |
| `TIME-AUTH-001..124` | `BETA-REQ-0017`; `BETA-REQ-0061`; `BETA-REQ-0063`; `BETA-REQ-0064`; `BETA-REQ-0071`; `BETA-REQ-0135`; `BETA-REQ-0146`; `BETA-REQ-0156`; `BETA-REQ-0162`; `BETA-REQ-0167`; `BETA-REQ-0168`; `BETA-REQ-0172`; `BETA-REQ-0174`; `BETA-REQ-0175` |

## Reverse-authority audit

- Clauses: **2904**
- Owner ranges: **25**
- Missing owners: **0**
- Overlapping CP-007 owner ranges: **0**
- Clauses with explicit supporting-authority/design-boundary evidence: **2904**
- Unexplained normative clauses: **0**

**Result: 2904/2904 PASS.**
