# SOMA Beta Normalization CP-005 — Clause Authority Matrix

Status: **Accepted**  
Scope: all **2669** stable clauses owned by `BETA-REQ-0103`–`BETA-REQ-0127`.  
Purpose: explicit owner/supporting-authority evidence for the CP-005 reverse audit.

## Owner mapping

Every clause in each inclusive range has exactly one listed owner. Range notation is clause-level evidence and does not transfer ownership to supporting requirements.

| Clause range | Owner |
|---|---|
| `NE-CORE-001..066` | `BETA-REQ-0103` |
| `NE-IP-001..044` | `BETA-REQ-0104` |
| `NE-CONTAIN-001..060` | `BETA-REQ-0105` |
| `CLOUD-DEPLOY-001..065` | `BETA-REQ-0106` |
| `INFRA-CONN-001..095` | `BETA-REQ-0107` |
| `INFRA-SECRET-001..086` | `BETA-REQ-0108` |
| `STORE-AUTH-001..092` | `BETA-REQ-0109` |
| `INFRA-XLSX-001..132` | `BETA-REQ-0110` |
| `COMM-GATE-001..070` | `BETA-REQ-0111` |
| `COMM-ID-001..110` | `BETA-REQ-0112` |
| `COMM-COVER-001..099` | `BETA-REQ-0113` |
| `COMM-BACKFILL-001..115` | `BETA-REQ-0114` |
| `COMM-RETAIN-001..095` | `BETA-REQ-0115` |
| `COMM-ORPHAN-001..112` | `BETA-REQ-0116` |
| `COMM-RUN-001..083` | `BETA-REQ-0117` |
| `COMM-SCOPE-001..103` | `BETA-REQ-0118` |
| `COMM-MSGID-001..116` | `BETA-REQ-0119` |
| `COMM-JOB-001..150` | `BETA-REQ-0120` |
| `WF-ISO-001..150` | `BETA-REQ-0121` |
| `COMM-SUM-001..119` | `BETA-REQ-0122` |
| `UI-NAV-001..128` | `BETA-REQ-0123` |
| `UI-AUTO-001..116` | `BETA-REQ-0124` |
| `UI-RESP-001..138` | `BETA-REQ-0125` |
| `UI-THEME-001..148` | `BETA-REQ-0126` |
| `UI-DRAFT-001..177` | `BETA-REQ-0127` |

## Additional supporting authority

Supporting authority strengthens provenance only; it does not transfer ownership or authorize new product behavior. CP-005 deliberately records support broadly because most requirements refine already accepted cross-domain identity, history, transaction, temporal, import, communication, and UI contracts.

| Clause range | Supporting authority |
|---|---|
| `NE-CORE-001..066` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0020`; `BETA-REQ-0027`; `BETA-REQ-0049`; `BETA-REQ-0102` |
| `NE-IP-001..044` | `BETA-REQ-0010`; `BETA-REQ-0102`; `BETA-REQ-0110` |
| `NE-CONTAIN-001..060` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0102` |
| `CLOUD-DEPLOY-001..065` | `BETA-REQ-0020`; `BETA-REQ-0027`; `BETA-REQ-0102` |
| `INFRA-CONN-001..095` | `BETA-REQ-0102`; future 1.x connectivity design remains non-authoritative until separately accepted |
| `INFRA-SECRET-001..086` | `BETA-REQ-0035`; `BETA-REQ-0036`; `BETA-REQ-0037`; `BETA-REQ-0078`; technical design item `O-005` only for separately governed SOMA authentication/encryption mechanics |
| `STORE-AUTH-001..092` | `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0092`; accepted Architecture persistence direction |
| `INFRA-XLSX-001..132` | `BETA-REQ-0010`; `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0027`; `BETA-REQ-0067`; `BETA-REQ-0102`; explicit CP-005 Device Reference regularization clarification where reconciliation is implicated |
| `COMM-GATE-001..070` | `BETA-REQ-0067`; `BETA-REQ-0089`; `BETA-REQ-0112`; technical design item `O-004` for exact PST/OST/MSG adapter/library support |
| `COMM-ID-001..110` | `BETA-REQ-0010`; `BETA-REQ-0014`; `BETA-REQ-0015`; `BETA-REQ-0048`; `BETA-REQ-0092`; `BETA-REQ-0111` |
| `COMM-COVER-001..099` | `BETA-REQ-0017`; `BETA-REQ-0061`; `BETA-REQ-0067`; `BETA-REQ-0111`; `BETA-REQ-0112` |
| `COMM-BACKFILL-001..115` | `BETA-REQ-0111`; `BETA-REQ-0112`; `BETA-REQ-0113`; technical design item `O-004` for adapter-specific range/discovery mechanics |
| `COMM-RETAIN-001..095` | `BETA-REQ-0089`; `BETA-REQ-0090`; `BETA-REQ-0108`; `BETA-REQ-0111`; `BETA-REQ-0112`; `BETA-REQ-0116`; technical design item `O-007` for exact approved safe-auto-accept classes |
| `COMM-ORPHAN-001..112` | `BETA-REQ-0017`; `BETA-REQ-0019`; `BETA-REQ-0072`; `BETA-REQ-0077`; `BETA-REQ-0112`; `BETA-REQ-0115`; `BETA-REQ-0114` for targeted recovery after purge |
| `COMM-RUN-001..083` | `BETA-REQ-0111`; `BETA-REQ-0113`; `BETA-REQ-0114`; `BETA-REQ-0116`; `BETA-REQ-0120` |
| `COMM-SCOPE-001..103` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0028`; `BETA-REQ-0031`; `BETA-REQ-0113`; `BETA-REQ-0115`; `BETA-REQ-0119` |
| `COMM-MSGID-001..116` | `BETA-REQ-0010`; `BETA-REQ-0019`; `BETA-REQ-0083`; `BETA-REQ-0091`; `BETA-REQ-0113`; `BETA-REQ-0115`; `BETA-REQ-0118`; technical design item `O-004` for adapter-specific identity extraction |
| `COMM-JOB-001..150` | `BETA-REQ-0017`; `BETA-REQ-0018`; `BETA-REQ-0108`; `BETA-REQ-0109`; `BETA-REQ-0113`; `BETA-REQ-0114`; `BETA-REQ-0117` |
| `WF-ISO-001..150` | `BETA-REQ-0018`; `BETA-REQ-0067`; `BETA-REQ-0083`; `BETA-REQ-0089`; `BETA-REQ-0090`; `BETA-REQ-0091`; `BETA-REQ-0109`; `BETA-REQ-0110`; `BETA-REQ-0117`; `BETA-REQ-0120`; explicit CP-005 Device Reference regularization clarification for Infrastructure-only correction boundaries |
| `COMM-SUM-001..119` | `BETA-REQ-0017`; `BETA-REQ-0061`; `BETA-REQ-0113`; `BETA-REQ-0115`; `BETA-REQ-0116`; `BETA-REQ-0118`; `BETA-REQ-0119` |
| `UI-NAV-001..128` | accepted Workbench interaction authority; `BETA-REQ-0049`; `BETA-REQ-0124`; `BETA-REQ-0125`; `BETA-REQ-0126` |
| `UI-AUTO-001..116` | `BETA-REQ-0010`; `BETA-REQ-0018`; `BETA-REQ-0049`; `BETA-REQ-0123`; `BETA-REQ-0125`; `BETA-REQ-0126` |
| `UI-RESP-001..138` | `BETA-REQ-0049`; `BETA-REQ-0102`; `BETA-REQ-0123`; `BETA-REQ-0124`; `BETA-REQ-0126`; explicit CP-005 Device Reference regularization clarification for `UI-RESP-107..110` |
| `UI-THEME-001..148` | `BETA-REQ-0078`; `BETA-REQ-0123`; `BETA-REQ-0124`; `BETA-REQ-0125`; Branding Contract authority |
| `UI-DRAFT-001..177` | `BETA-REQ-0010`; `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0088`; `BETA-REQ-0090`; `BETA-REQ-0092`; `BETA-REQ-0112`; `BETA-REQ-0125`; technical design item `O-005` only for secure local protection of recoverable working-copy storage |

## CP-005 Device Reference owner clarification

The project owner's review-time clarification is not owned by `BETA-REQ-0110` or `BETA-REQ-0125`. It strengthens the already accepted `BETA-REQ-0102` Device Reference regularization authority:

> A provisional or temporary Device Reference created from operational data remains reviewably resolvable or correctable to an existing Network Element from Infrastructure even after every related Service Request is terminal. Ticket terminality does not freeze Infrastructure reconciliation. The Device Reference identity, Network Element identity, source-time/imported text, prior resolution evidence, and correction history remain preserved; the correction does not reopen or rewrite the terminal Service Request.

CP-005 clauses may consume that authority only where their own owner independently governs the relevant workbook, workflow-isolation, responsive-action, or draft behavior. This prevents ownership transfer from Infrastructure to UI/import concerns.

## Audit totals

- Clauses: **2669**
- Owner ranges: **25**
- Clauses with explicit additional supporting authority/design-boundary evidence: **2669**
- Missing owners: **0**
- Overlapping owner ranges: **0**
- Unexplained normative clauses: **0**

The known preliminary-HLD wording that assigns “Task outcomes” to Inventory remains a design defect only. Nothing in CP-005 transfers execution/outcome/review/correction/retry ownership away from Objectives/Task lifecycle.

**Reverse-authority result: 2669/2669 PASS.**
