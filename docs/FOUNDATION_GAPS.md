# SOMA Beta Foundation Gaps Register

Status: **Active during Phase 0 product stabilization**  
Target: **SOMA Beta 1.0.0**

This register is the separate authority for contradictions, omissions, and incomplete historical coverage discovered while establishing the Beta foundation. It does not replace normative requirements, the decision ledger, or assigned HLD/LLD questions.

## Status meanings

| Status | Meaning |
|---|---|
| Open | A product contradiction, omission, or coverage gap still requires resolution. |
| Resolved | Normative Beta requirements and destination contracts resolve the gap. |
| Deferred | An explicit accepted release decision places the capability after Beta 1.0.0. |
| Assigned design | Product behavior is settled; implementation detail is assigned to HLD or LLD. |

Phase 0 cannot close while any product gap remains Open. Historical-catalogue work may remain In progress only while the Phase 0 review itself is active.

## Register

| ID | Gap | Status | Resolution or required action | Authority |
|---|---|---|---|---|
| `FND-GAP-001` | The merged Alpha requirement catalogue has not yet been completely dispositioned, and unmerged Alpha proposals remain to be catalogued. | Open | Continue one-row-per-Alpha-ID review from `ALPHA:SPR-012`, then catalogue every unmerged proposal. Close only when no historical source item lacks a final disposition. | Roadmap Phase 0; Alpha Traceability Register |
| `FND-GAP-002` | Alpha global ticket-age and suspension-KPI schedules conflicted with Beta's customer-and-contract-specific SLA meaning. | Resolved | `BETA-REQ-0064` and `BETA-REQ-0065` establish Customer Organization → Contract → Contract Product Line → cohort SLA policy, customer-specific policies for reusable Product Lines, retroactive live recalculation after policy revision, immutable completed report snapshots, and cancelled exclusion. | Contract Product Line and SLA Contract; Decision D-016 |
| `FND-GAP-003` | Earlier foundation wording treated Sites as customer-neutral and Clouds as customer-owned objects spanning Sites. | Resolved | `BETA-REQ-0027` establishes one Customer Organization per physical Datacenter Site plus reusable Cloud Types instantiated through site-bound Cloud Deployments. | Product Contract §9; Architecture; Decisions D-011 and D-029 |
| `FND-GAP-004` | Alpha Objective-level retry lineage conflicted with Beta's Task-first work model. | Resolved | `BETA-REQ-0046` creates new Task attempts and derives Objective lineage through normal overlap grouping. | Product Contract §7; Workbench Contract §4; Decision D-026 |
| `FND-GAP-005` | Earlier Spare Request wording risked treating the official SR7 as the entity's creation identity and omitted local units without official provenance. | Resolved | `BETA-REQ-0014`–`0016` require local Spare Request origin with retained temporary identity, define the RMA as a separate obligation bridge, and preserve optional-provenance `LSU-########` units. | Inventory Lifecycle Contract; Glossary; Decisions D-009 and D-010 |
| `FND-GAP-006` | Alpha trusted source fields and fixed minimum-header behavior exceeded the reviewed Beta workbook allowlists. | Resolved | `BETA-REQ-0055` and `BETA-REQ-0060`–`0063` establish identity-only minimum acceptance, position-independent headers, active/future allowlists, discarded Product, source chronology, and non-destructive field rules. | Import Contract; Alpha Traceability Register |
| `FND-GAP-007` | Alpha report-finalization, episode purge, and 180-day retention behavior conflicted with Beta 1.0 Historical views and the accepted no-purge boundary. | Resolved | `BETA-REQ-0019` and `BETA-REQ-0057` preserve operational history in Beta 1.0; general purge policy is deferred to Beta 1.1. | Product Contract §§6 and 14; Decisions D-039 and D-045; Deferred F-009 |
| `FND-GAP-008` | The security concept originally risked coupling the login password or a short recovery code to data and backup encryption. | Resolved | `BETA-REQ-0035`–`0037` separate authentication, Windows-protected random live-data keys, and independently encrypted portable backups with a high-entropy recovery secret. | Architecture §5; Decision D-005 |

| `FND-GAP-009` | The earlier Beta draft incorrectly made Spare Needs device-level and modeled an RMA primarily as an accepted position containing one received unit. It also conflated warehouse receipt with final acceptance and left the Beta 1.0 evidence-control boundary unclear. | Resolved | `BETA-REQ-0079`–`0089` establish SR-level BOM aggregation from Device Part Unit contributors, stock-first choice, the RMA obligation bridge, deterministic incremental assignment, separate physical outcomes and return units, cross-request Fault Tags, warehouse rejection/resend loops, and backend evidence support without a Beta 1.0 attachment UI. | Inventory Lifecycle Contract; Product Contract §8; Decisions D-009, D-010, D-034, D-035, D-060–D-063 |

## Assigned design questions

The unresolved technical questions in `DECISIONS.md` remain owned by their stated HLD/LLD destinations. They do not reopen settled product rules. If design work exposes a new product contradiction or omission, it receives a new `FND-GAP-###` entry before any downstream artifact changes.
