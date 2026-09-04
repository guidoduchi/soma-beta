# SOMA Beta Normalization CP-006 — Clause Authority Matrix

Status: **Accepted**  
Scope: all **3444** stable clauses owned by `BETA-REQ-0128`–`BETA-REQ-0152`.  
Purpose: explicit owner/supporting-authority evidence for the CP-006 reverse audit.

## Owner mapping

Every clause in each inclusive range has exactly one listed owner. Range notation is clause-level evidence and does not transfer ownership to supporting requirements.

| Clause range | Owner |
|---|---|
| `VIEW-PROJ-001..154` | `BETA-REQ-0128` |
| `INV-ACT-001..176` | `BETA-REQ-0129` |
| `UX-REF-001..132` | `BETA-REQ-0130` |
| `DB-FK-001..122` | `BETA-REQ-0131` |
| `DB-MIG-001..128` | `BETA-REQ-0132` |
| `DB-MIGFREEZE-001..137` | `BETA-REQ-0133` |
| `DB-MIGSTAT-001..118` | `BETA-REQ-0134` |
| `AUD-EVID-001..164` | `BETA-REQ-0135` |
| `JSON-CONTRACT-001..158` | `BETA-REQ-0136` |
| `TEST-CONTRACT-001..172` | `BETA-REQ-0137` |
| `CI-MATRIX-001..146` | `BETA-REQ-0138` |
| `UI-ACCEPT-001..160` | `BETA-REQ-0139` |
| `LOCAL-RUN-001..168` | `BETA-REQ-0140` |
| `DIAG-EXT-001..145` | `BETA-REQ-0141` |
| `DIAG-SAFE-001..158` | `BETA-REQ-0142` |
| `AUD-APPEND-001..148` | `BETA-REQ-0143` |
| `AUD-PAYLOAD-001..156` | `BETA-REQ-0144` |
| `IMP-DISC-001..112` | `BETA-REQ-0145` |
| `IMP-OBS-001..128` | `BETA-REQ-0146` |
| `IMP-STATUS-001..104` | `BETA-REQ-0147` |
| `IMP-ADOPT-001..108` | `BETA-REQ-0148` |
| `RFC-STATUS-001..124` | `BETA-REQ-0149` |
| `RFC-WFM-ELIG-001..096` | `BETA-REQ-0150` |
| `SR-LINK-CAND-001..106` | `BETA-REQ-0151` |
| `RFC-HIER-001..124` | `BETA-REQ-0152` |

## Additional supporting authority

Supporting authority strengthens provenance only; it does not transfer ownership or authorize new product behavior. CP-006 records cross-cutting support because this checkpoint converts UI projections and acceptance behavior into persistence/runtime guarantees and then applies those guarantees to governed RFC/WFM imports.

| Clause range | Supporting authority |
|---|---|
| `VIEW-PROJ-001..154` | `BETA-REQ-0010`; `BETA-REQ-0017`; `BETA-REQ-0019`; `BETA-REQ-0061`; `BETA-REQ-0064`; `BETA-REQ-0113`; `BETA-REQ-0115`; `BETA-REQ-0116`; `BETA-REQ-0122`; Objectives/Task lifecycle authority; Inventory consumes reviewed Task outcomes without owning execution/outcome/review/correction/retry |
| `INV-ACT-001..176` | `BETA-REQ-0010`; `BETA-REQ-0018`; `BETA-REQ-0019`; Inventory lifecycle authority through CP-004; `BETA-REQ-0088`; `BETA-REQ-0090`; `BETA-REQ-0092`; `BETA-REQ-0120`; `BETA-REQ-0127`; `BETA-REQ-0139` |
| `UX-REF-001..132` | Branding Contract authority; `BETA-REQ-0049`; `BETA-REQ-0078`; `BETA-REQ-0123`; `BETA-REQ-0124`; `BETA-REQ-0125`; `BETA-REQ-0126`; `BETA-REQ-0137`; `BETA-REQ-0139` |
| `DB-FK-001..122` | `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0109`; migration/restore validation authority; owning domain deletion contracts |
| `DB-MIG-001..128` | `BETA-REQ-0018`; `BETA-REQ-0109`; `BETA-REQ-0131`; `BETA-REQ-0133`; `BETA-REQ-0140`; technical design boundaries `O-005` and `O-006` where applicable |
| `DB-MIGFREEZE-001..137` | `BETA-REQ-0001`; `BETA-REQ-0018`; `BETA-REQ-0109`; `BETA-REQ-0132`; repository protected-lineage authority |
| `DB-MIGSTAT-001..118` | `BETA-REQ-0018`; `BETA-REQ-0109`; `BETA-REQ-0131`; `BETA-REQ-0132`; `BETA-REQ-0133`; `BETA-REQ-0140` for authenticated live-instance status |
| `AUD-EVID-001..164` | `BETA-REQ-0010`; `BETA-REQ-0017`; `BETA-REQ-0019`; `BETA-REQ-0088`; `BETA-REQ-0090`; `BETA-REQ-0109`; `BETA-REQ-0120`; `BETA-REQ-0121`; `BETA-REQ-0143`; `BETA-REQ-0144` |
| `JSON-CONTRACT-001..158` | `BETA-REQ-0018`; `BETA-REQ-0108`; `BETA-REQ-0109`; `BETA-REQ-0120`; `BETA-REQ-0127`; `BETA-REQ-0142`; technical design item `O-005` only for secure recoverable-working-copy protection |
| `TEST-CONTRACT-001..172` | `BETA-REQ-0008`; all accepted requirements and clause authorities; `BETA-REQ-0018`; `BETA-REQ-0109`; `BETA-REQ-0110`; `BETA-REQ-0131`; `BETA-REQ-0132`; `BETA-REQ-0133`; `BETA-REQ-0143`; `BETA-REQ-0144` |
| `CI-MATRIX-001..146` | `BETA-REQ-0004`; `BETA-REQ-0007`; `BETA-REQ-0137`; technical design item `O-006` for exact supported Windows/browser/runtime/packaging matrix |
| `UI-ACCEPT-001..160` | `BETA-REQ-0049`; `BETA-REQ-0102`; `BETA-REQ-0123`; `BETA-REQ-0124`; `BETA-REQ-0125`; `BETA-REQ-0126`; `BETA-REQ-0127`; CP-005 Device Reference regularization clarification owned by `BETA-REQ-0102` |
| `LOCAL-RUN-001..168` | `BETA-REQ-0002`; `BETA-REQ-0003`; `BETA-REQ-0009`; `BETA-REQ-0018`; `BETA-REQ-0109`; `BETA-REQ-0131`; `BETA-REQ-0132`; `BETA-REQ-0133`; `BETA-REQ-0134`; technical design items `O-005` and `O-006` for exact security/platform mechanics |
| `DIAG-EXT-001..145` | `BETA-REQ-0003`; `BETA-REQ-0007`; `BETA-REQ-0109`; `BETA-REQ-0120`; `BETA-REQ-0135`; `BETA-REQ-0136`; `BETA-REQ-0140`; `BETA-REQ-0142` |
| `DIAG-SAFE-001..158` | `BETA-REQ-0007`; `BETA-REQ-0108`; `BETA-REQ-0115`; `BETA-REQ-0120`; `BETA-REQ-0136`; `BETA-REQ-0138`; `BETA-REQ-0140`; `BETA-REQ-0141` |
| `AUD-APPEND-001..148` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0109`; `BETA-REQ-0131`; `BETA-REQ-0132`; `BETA-REQ-0135`; `BETA-REQ-0136`; `BETA-REQ-0137`; `BETA-REQ-0144` |
| `AUD-PAYLOAD-001..156` | `BETA-REQ-0019`; `BETA-REQ-0108`; `BETA-REQ-0135`; `BETA-REQ-0136`; `BETA-REQ-0137`; `BETA-REQ-0142`; `BETA-REQ-0143` |
| `IMP-DISC-001..112` | `BETA-REQ-0017`; `BETA-REQ-0067`; `BETA-REQ-0121`; `BETA-REQ-0136`; `BETA-REQ-0137`; `BETA-REQ-0139`; `BETA-REQ-0146` |
| `IMP-OBS-001..128` | `BETA-REQ-0010`; `BETA-REQ-0017`; `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0113`; `BETA-REQ-0114`; `BETA-REQ-0121`; `BETA-REQ-0127`; `BETA-REQ-0139`; `BETA-REQ-0145`; `BETA-REQ-0147` |
| `IMP-STATUS-001..104` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0128`; `BETA-REQ-0145`; `BETA-REQ-0146`; `BETA-REQ-0148`; `BETA-REQ-0149` |
| `IMP-ADOPT-001..108` | `BETA-REQ-0010`; `BETA-REQ-0012`; `BETA-REQ-0013`; `BETA-REQ-0017`; `BETA-REQ-0019`; `BETA-REQ-0127`; `BETA-REQ-0135`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0149` |
| `RFC-STATUS-001..124` | `BETA-REQ-0017`; `BETA-REQ-0019`; `BETA-REQ-0125`; `BETA-REQ-0135`; `BETA-REQ-0139`; `BETA-REQ-0143`; `BETA-REQ-0144`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0148`; `BETA-REQ-0150`; later detailed cascade authority remains separately owned |
| `RFC-WFM-ELIG-001..096` | `BETA-REQ-0012`; `BETA-REQ-0013`; RFC/Task lifecycle authority; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0148`; `BETA-REQ-0149`; `BETA-REQ-0151`; `BETA-REQ-0152` |
| `SR-LINK-CAND-001..106` | `BETA-REQ-0011`; `BETA-REQ-0012`; `BETA-REQ-0013`; `BETA-REQ-0019`; SR↔master-RFC authority; `BETA-REQ-0135`; `BETA-REQ-0139`; `BETA-REQ-0146`; `BETA-REQ-0147`; `BETA-REQ-0148`; `BETA-REQ-0150`; `BETA-REQ-0152` |
| `RFC-HIER-001..124` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0027`; accepted master/subordinate RFC authority; `BETA-REQ-0124`; `BETA-REQ-0125`; `BETA-REQ-0135`; `BETA-REQ-0139`; `BETA-REQ-0148`; `BETA-REQ-0149`; `BETA-REQ-0150`; `BETA-REQ-0151` |

## CP-006 reconciliation notes

- `BETA-REQ-0128` owns projection behavior only. It does **not** transfer Task execution, outcome, review, correction, or retry authority to Inventory; those remain owned by Objectives/Task lifecycle, while Inventory consumes reviewed Task outcomes for physical consequences.
- `BETA-REQ-0139` consumes the Device Reference deliberate-hold and regularization distinctions already owned by `BETA-REQ-0102`/`0125`; reassignment to an already-existing Network Element remains a correction path and does not inherit creation-hold semantics.
- `BETA-REQ-0140` strengthens local-runtime trust but does not redefine Local User authentication or the still-open exact crypto/KDF/backup mechanics under `O-005`.
- `BETA-REQ-0143`/`0144` protect application audit without claiming cryptographic immunity from privileged file replacement or turning audit JSON into a shadow database.
- `BETA-REQ-0145`–`0152` keep discovery chronology, source-observation chronology, business chronology, entity identity, relationship authority, and hierarchy authority separate. Workbook presence or text never gains destructive lifecycle authority.

## Audit totals

- Clauses: **3444**
- Owner ranges: **25**
- Clauses with explicit supporting-authority/design-boundary evidence: **3444**
- Missing owners: **0**
- Overlapping owner ranges: **0**
- Unexplained normative clauses: **0**

**Reverse-authority result: 3444/3444 PASS.**
