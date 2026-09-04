# SOMA Beta Phase 1A — Requirement / Use-Case Traceability

Status: **P1A-002 PASS — UC-001 expansion proof and exhaustive transformation ledger complete; UC-002 Proposed after Specification Gate; owner review paused pending RC-006-A2; final coverage pending**

## Purpose

This is the Phase-1A forward coverage ledger. It deliberately does not duplicate the 11,524 canonical clauses. Exact canonical owner ranges remain authoritative in `docs/reconciliation/RC006_CLAUSE_DESTINATIONS.md`.

`P1A_001_UC001_EXPANSION_PROOF.md` preserves UC-001 accepted semantics, and `P1A_002_TRANSFORMATION_LEDGER.md` reconciles every allocated identity `UC-001..UC-095`.

P1A-002 controlled catalogue reconstruction corrected a systemic defect in the initial seed catalogue: several Goal Seeds cited unrelated or overly broad requirement ranges. No seed-level candidate mapping is allowed to masquerade as accepted coverage. Each active Goal Seed must pass the Specification Gate and re-derive its authority from canonical families before it can become `Proposed`.

## Coverage states

- `Goal Seed` — decomposition candidate only; not acceptance-ready and not counted as final coverage.
- `Draft` — expanded specification still undergoing internal gate review.
- `Proposed` — complete specification with Specification Gate PASS; eligible for owner review but not final coverage.
- `UC` — behavioral obligations exercised by accepted use case(s).
- `SI` — structural invariant only, with rationale/destination.
- `UC+SI` — mixed requirement; behavioral and structural portions both accounted for.
- `Blocked` — genuine product ambiguity returned for controlled Phase-0 handling.
- `Merged/Retired` — pre-acceptance seed disposition with successor/reference; provides no independent coverage.

## Current invariants

- registered requirement-owner set: **exactly `BETA-REQ-0001..0177` (177 / 177)**
- canonical source-owner ranges: **177 / 177** via `RC006_CLAUSE_DESTINATIONS.md`
- allocated UC IDs: **95 (`UC-001..UC-095`)**
- active goals: **94**
- accepted use cases: **1 (`UC-001`)**
- proposed use cases: **1 (`UC-002`)**
- active Goal Seeds: **92**
- pre-acceptance merged/retired seeds: **1 (`UC-043 → UC-069`)**
- finally resolved requirement coverage: **0 / 177** until owner-by-owner/family coverage is accepted
- next owner review after `RC-006-A2` PASS: **UC-002**
- current blocked product ambiguities: **0 known**

`UC-001` is accepted and has complete mandatory repository representation, but `BETA-REQ-0078` remains mixed and is not finally resolved: password-change, auto-login, security/key, backup/recovery and structural families still require accepted UC/SI coverage.

`UC-002` has passed the Specification Gate for the password-authentication goal but remains Proposed; owner review is paused pending `RC-006-A2`, and it provides no final accepted coverage until project-owner acceptance.

## Requirement registry

The registry is the exact contiguous accepted owner set `BETA-REQ-0001` through `BETA-REQ-0177`. Each owner resolves to its canonical family/range through `RC006_CLAUSE_DESTINATIONS.md`; Phase 1A shall not invent alternative owner ranges.

## Corrected active goal inventory by wave

This table is navigational only. It identifies domains/families to be re-derived during Specification Gate review and is **not final traceability**.

| Wave | Active UCs | Corrected primary candidate authority areas | State |
|---|---|---|---|
| `P1A-W1` | `001..012`, `078..080` | foundation/runtime/security/settings/reference plus Customer/Product Line/Contract/CPL/SLA policy | UC-001 Accepted; UC-002 Proposed; remainder Goal Seed |
| `P1A-W2` | `013..026`, `081`, `094` | SR/RFC/WFM/source intake, Workbench, Notes, CPL classification/SLA-facing behavior | Goal Seed |
| `P1A-W3` | `027..037`, `082..083` | Task/Objective identity/planning/grouping/execution/correction/retry, Device Reference participation, RFC cascade, archive/delete | Goal Seed |
| `P1A-W4` | `038..042`, `044..052`, `084..090` | Spare Need/Request/RMA/physical-unit/logistics/physical consequence/Fault Tag/warehouse/lifecycle | Goal Seed; `043` retired |
| `P1A-W5` | `053..061`, `091..092` | Site/Dispatch/Cloud/Device Reference/Network Element/placement/IP/containment/workbook/import-directory | Goal Seed |
| `P1A-W6` | `062..069` | Communication source/matching/coverage/proposals/evidence/terminal minimization/MSG | Goal Seed |
| `P1A-W7` | `070..077`, `093`, `095` | navigation/working copies/stale conflicts/Overview/reporting/warnings/bulk actions/history/Undo | Goal Seed |

Cross-wave overlaps are expected and do not transfer requirement ownership.

## P1A-002 authority corrections already applied

| UC / area | Removed misleading authority | Corrected direction |
|---|---|---|
| `UC-027`, `UC-028` | `0024` Site/Dispatch | Task relationship + `DEVICE-REF` authority; Task links Device References, not Network Elements directly |
| `UC-030` | `0007` source-control discipline | Objective/Task grouping/lifecycle families |
| `UC-046` | Fault Tag/Contact padding | Spare Request/RMA/provider-response/logistics families |
| `UC-047` | `0036` data encryption | RMA/physical-unit/logistics/receipt families |
| `UC-049` | `0035..0037` security/backup and unrelated Fault Tag IDs | Task outcome + Inventory physical-consequence families |
| `UC-050` | `0068` Advanced Search scheduling | `FT-SCOPE`, `FT-ID`, `FT-MEMBER`, `FT-REL` and logistics snapshot authority |
| `UC-051` | `0061..0064` source/SLA and `0102` Infrastructure | `FT-WH`, `FT-LOG` and applicable Fault Tag relation authority |
| `UC-054..061` | `0076..0080` used as Infrastructure authority | physical hierarchy + `0049`, `0102..0110` as applicable |
| `UC-066` | `0063..0064` SLA authority | Communications proposal authority + exact scenario owning-domain authority |
| `UC-067` | `0032` requester Contact | canonical Communication identity/link/evidence authority |
| `UC-069` | `0048` Objective grouping | Communications MSG authority + exact invoking-workflow authority |

These corrections remove known false references. Final Proposed/Accepted traceability still requires canonical-family/subrange validation under the Specification Gate.

## UC-002 Specification Gate traceability

| Element | Verified authority | Result |
|---|---|---|
| Singleton authenticating Local User Profile | `BETA-REQ-0035`; `AUTH-001..002` | PASS |
| Password is authentication authority only | `AUTH-003`; separation constraints `AUTH-005..006` | PASS |
| Password persistence uses salted memory-hard verifier | `AUTH-004`; `ADMIN-SETUP-038` | PASS |
| Login requires no username | `BETA-REQ-0078`; `ADMIN-SETUP-007`; Product Contract §3 | PASS |
| Password does not become live/backup encryption authority | `AUTH-005..006`; `ADMIN-SETUP-039..042` | PASS |
| Automatic login is separate optional behavior | `AUTH-007..009`; `ADMIN-SETUP-043..045`; owned primarily by `UC-004` | PASS boundary |
| Explicit application lock/unlock | **No accepted normalized/canonical authority found** | REMOVED from UC-002 before proposal |
| Primary normative destination | `PRODUCT_CONTRACT.md` §3 Deployment and operator model | PASS |
| Runtime/security mechanics | Downstream HLD/LLD constrained by normalized authority; Foundation Runtime is supporting, not password-policy owner | PASS boundary |

### UC-002 reverse-authority result

The original seed title `Authenticate, lock, and unlock the installation` contained unsupported lock/unlock behavior. No accepted `BETA-REQ` or canonical clause authorizes an explicit application lock/unlock workflow. The Proposed UC is therefore narrowed to **Authenticate to an established SOMA installation**. This correction removes unsupported seed behavior and does not reopen or change Phase-0 product authority.

**UC-002 SPECIFICATION GATE: PASS — Proposed; owner acceptance pending.**

## Working coverage table

| BETA-REQ | Canonical family/range | Coverage | UC/SI reference | Rationale / coverage note | Result |
|---|---|---|---|---|---|
| `BETA-REQ-0035` | `AUTH-001..010` | UC candidate | `UC-002`, `UC-003`, `UC-004` | UC-002 Proposed for password-login subset; credential change/auto-login portions remain separate and pending | **Pending final coverage** |
| `BETA-REQ-0078` | `ADMIN-SETUP-001..067` | `UC+SI` candidate | `UC-001`, `UC-002`, `UC-003..010`, SI security/key invariants | UC-001 accepted for first-run subset; UC-002 Proposed for login subset; remaining families pending | **Pending final coverage** |
| `BETA-REQ-0052` | `NOTE-HIST-001..013` | UC candidate | `UC-094` | Working Notes has an explicit goal seed; full specification/acceptance pending | Pending |
| `BETA-REQ-0086` | `SPUNIT-REG-001..036` | UC candidate | `UC-084` | Manual Spare Part Unit registration now explicit | Pending |
| `BETA-REQ-0110` | `INFRA-XLSX-001..132` | multiple UC candidate | `UC-059`, `UC-060`, `UC-091` | Export, import/reconcile, and import-directory/Check-now goals separated | Pending |
| `BETA-REQ-0049` | `DEVICE-REF-001..014` | multiple UC candidate | `UC-027`, `UC-028`, `UC-056`, `UC-057`, `UC-092` | Operational Device Reference participation kept distinct from NE regularization/correction | Pending |

## Duplicate/merge record

| Seed | Disposition | Successor | Coverage consequence |
|---|---|---|---|
| `UC-043` | Merged/retired before acceptance | `UC-069` | Spare Request MSG behavior becomes a required `UC-069` scenario; no independent UC-043 coverage |

## Final Phase-1A audit requirements

Before Phase 1A acceptance:

1. owner set equals exactly `BETA-REQ-0001..0177`;
2. every behavioral canonical clause family/subrange is exercised by at least one **accepted** `UC-*`;
3. every `SI` classification has exact owner/family, rationale and downstream design/test destination;
4. every Proposed/Accepted UC cites only semantically relevant accepted authority;
5. every Proposed/Accepted UC validates `BETA-REQ → canonical family/subrange → owning normative destination`;
6. no accepted use-case behavior lacks accepted Phase-0 authority;
7. requirements with both structural and behavioral clauses are `UC+SI` where necessary rather than overclassified as structural;
8. every active Goal Seed/Draft has been Proposed/Accepted/Reworked/Split/Merged/Retired/SI-classified;
9. duplicate independently-governing use-case goals are zero;
10. forward behavioral clause-family orphan count is zero; and
11. unresolved coverage / blocked product ambiguity count is zero.
