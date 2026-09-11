# SOMA Beta Reconciliation RC-004 — Bidirectional Traceability

Status: **Accepted**

## Forward authority audit

| Authority | RC-004 destination | Result |
|---|---|---|
| `BETA-REQ-0014`–`0016` Spare Request/RMA/Spare Unit identity | Inventory lifecycle | Covered |
| `BETA-REQ-0023`, `0024`, `0026` Dispatch Location/Site relationship and neutrality | Inventory + Infrastructure | Covered |
| `BETA-REQ-0027`, `0033`, `0034` Site ownership/lifecycle and Dispatch lifecycle | Infrastructure | Covered |
| `BETA-REQ-0032` requester Contact lifecycle | Inventory | Covered |
| `BETA-REQ-0038` non-universal SR ownership | Inventory + Infrastructure | Covered |
| `BETA-REQ-0049` Device Reference pre-regularization use/promotion | Infrastructure | Covered |
| `BETA-REQ-0050` Task outcomes vs Inventory facts | Inventory + Infrastructure | Covered |
| `BETA-REQ-0079`–`0081` Spare Need/Device Part Unit lifecycle | Inventory | Covered |
| `BETA-REQ-0082`–`0093` Spare Request/RMA/unit/logistics/correction | Inventory | Covered |
| `BETA-REQ-0094`–`0101` Fault Tag lifecycle | Inventory | Covered |
| `BETA-REQ-0102` Device Reference/Infrastructure terminology | Infrastructure | Covered |
| `BETA-REQ-0103`–`0110` Network Element/IP/containment/Cloud/SQLite/workbook | Infrastructure | Covered |

## High-risk clause checks

| Clause family | Check | Result |
|---|---|---|
| `SPNEED-LIFE-*` | Need reuse/removal/hard-deletion rules represented | PASS |
| `SPUNIT-ALLOC-*` | Task allocation and physical consequence ownership do not transfer Task outcome authority | PASS |
| `INV-EVENT-*` | Physical corrections preserve append-oriented history | PASS |
| `FAULT-*` families | Return obligation/unit pairing, warehouse stages, correction vs resend remain distinct | PASS |
| `DISPATCH-*`, `SITE-DISPATCH-*`, `DISPATCH-CUST-*` | Site linkage, role neutrality, address derivation represented | PASS |
| `SITE-LIFE-*`, `DISPATCH-LIFE-*` | Ownership correction and archival blockers represented | PASS |
| `INFRA-TERM-*` | Device Reference regularization preserves identity/relationships | PASS |
| `NE-CORE-*`, `NE-IP-*`, `NE-CONTAIN-*`, `CLOUD-DEPLOY-*` | derived context and independent relationship families represented | PASS |

## Reverse authority audit

Material normative assertions introduced or strengthened by RC-004 resolve to the families above. No standalone assertion adds a new physical lifecycle, new topology edge, new credential capability, new deletion permission, or new outcome state.

Specific reverse checks:

- `Reviewed maintenance physical consequence` is a clarification of `SPUNIT-ALLOC-*`, not a new Task state.
- Site-created dedicated Dispatch Location is `SITE-DISPATCH-*` authority, not Infrastructure invention.
- Dispatch customer neutrality is `DISPATCH-CUST-*`/`DISPATCH-LIFE-*`, not a UI convenience.
- Terminal-ticket-independent Device Reference regularization is supporting accepted `INFRA-TERM-*` authority and its CP-005 owner clarification; it does not reopen ticket lifecycle.
- Component installation/removal remains physical relationship history and does not create a second Task outcome projection.

## Deferred design boundaries preserved

RC-004 intentionally does not resolve:

- exact Rack/U occupancy and capacity representation;
- exact Network Element name/serial/IP candidate matching implementation;
- exact IP duplicate scope/normalization mechanics;
- exact Infrastructure workbook schema/limits/fingerprints;
- any Beta 1.x connectivity/topology or SSH design;
- exact Task outcome transition/correction reason matrix (`O-003`).

## Result

Forward audit: **PASS**  
Reverse audit: **PASS**  
Orphan normative assertion discovered in RC-004 scope: **0**  
Requirement without destination coverage in RC-004 scope: **0**
