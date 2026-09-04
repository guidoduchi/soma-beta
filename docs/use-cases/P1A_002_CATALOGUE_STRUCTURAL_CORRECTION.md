# P1A-002 — Controlled Use-Case Catalogue Reconstruction

Status: **COMPLETED — controlled reconstruction recorded; UC-002 Proposed; owner review paused pending RC-006-A2**  
Scope: Phase 1A catalogue representation, decomposition topology, and traceability; accepted product authority remains unchanged.  
Product authority: unchanged; Phase-0 accepted behavior remains authoritative.

## 1. Why this correction exists

The initial 77-item Phase-1A catalogue successfully decomposed SOMA Beta 1.0 into a useful goal inventory, but its repository representation was not consistently acceptance-ready under `USE_CASE_METHOD.md`.

The controlled reconstruction addressed four specification-assurance defects without reopening approved product behavior:

1. several draft UCs cited unrelated or overly broad `BETA-REQ` ranges;
2. the seed format omitted fields required for a Proposed/Accepted use case;
3. several seeds combined goals with materially different authority/end-state/recovery contracts; and
4. several material goals required by accepted contracts were absent or hidden as subordinate steps.

## 2. Governance disposition

- `UC-001` remains semantically **Accepted**. Its repository representation was expanded non-semantically to satisfy the mandatory use-case fields.
- `UC-002` onward owner acceptance remains **paused** until each candidate passes the Specification Gate.
- Existing nonaccepted IDs may be narrowed, split, merged, or retired because they have not acquired accepted identity authority; every such disposition is recorded.
- New/extracted goals received IDs from `UC-078` onward.
- Every narrowed, split, merged, retired, extracted, or added seed records its original identity, retained principal goal, successor/derived IDs, `derived-from` relationship, governing authority, reason, and whether observable behavior changed.
- An accepted UC may retain acceptance after repository expansion only when every added statement is demonstrably derived from already accepted authority. Any new actor decision, outcome, warning, exception, permission boundary, state transition, or other observable behavior returns the affected portion to owner review.
- Cross-cutting UI mechanics remain acceptance/SI obligations unless they independently form an actor/system goal.
- MOP generation remains outside Beta 1.0 and was not added.

## 3. Authority-reference defects corrected

The following known false/misleading references were removed from their affected seeds:

| UC | Invalid / misleading authority removed | Corrected direction |
|---|---|---|
| `UC-027`, `UC-028` | `BETA-REQ-0024` (`SITE-DISPATCH`) | Task/relationship and Device Reference authority |
| `UC-030` | `BETA-REQ-0007` (`SCM`) | Objective/Task grouping and lifecycle authority |
| `UC-047` | `BETA-REQ-0036` (`DATA-CRYPT`) | Inventory receipt/logistics/unit authority |
| `UC-049` | `BETA-REQ-0035..0037` | Task outcome + Inventory physical-consequence authority |
| `UC-050` | `BETA-REQ-0068` | applicable Fault Tag families |
| `UC-051` | `BETA-REQ-0061..0064` and `0102` | Fault Tag warehouse/log authority |
| `UC-054..058`, `UC-061` | `0076..0080` used as Infrastructure authority | physical hierarchy + `0049`, `0102..0110` as applicable |
| `UC-066` | SLA families `0063..0064` | Communications proposal authority + scenario-specific owning domain |
| `UC-067` | `0032` requester-Contact authority | Communications canonical evidence/link authority |
| `UC-069` | `0048` Objective grouping | Communications MSG authority + scenario-specific workflow authority |

Negative post-edit checks confirmed the representative stale mappings above are absent from their repaired wave files.

P1A-002 does **not** certify every Goal Seed's final authority. Instead, `USE_CASE_METHOD.md` now makes authority re-derivation and canonical-family/destination validation mandatory before a seed can become `Proposed`.

## 4. Goal corrections completed

### 4.1 Split/narrow

- `UC-007`: narrowed to Customer Organization management; extracted `UC-078..080` for Product Line, Contract, and Contract Product Line/SLA-policy goals.
- `UC-022`: narrowed to manual WFM registration; extracted `UC-081` for provider WFM source discovery/staging.
- `UC-036`: narrowed to cancellation; extracted `UC-082` archival/reactivation and `UC-083` narrow hard deletion.
- `UC-052`: narrowed to exact Inventory correction; extracted `UC-085..090` for Spare Request cancellation, Fault Tag cancellation/replacement/resend, archival/reactivation, and narrow hard deletion.
- `UC-071`: narrowed to unsaved working-copy/save/discard/recovery behavior; extracted `UC-093` stale accepted-state conflict resolution and `UC-095` bounded safe Undo.
- `UC-076`: narrowed to supported bulk execution; generic confirmation-tier behavior remains cross-cutting SI/acceptance authority.

### 4.2 Missing goals added

- `UC-084` — manual Spare Part Unit registration (`SPUNIT-REG` / LSU identity and optional provenance).
- `UC-091` — Infrastructure Import Directory configuration/validation and `Check now`.
- `UC-092` — correction/reassignment of an already accepted Device Reference → Network Element resolution.
- `UC-094` — Working Notes edit/remove/history behavior.
- `UC-078..080`, `081`, `082..083`, `085..090`, `093`, `095` — extracted goals required to keep authority/end-state/recovery contracts atomic.

### 4.3 Duplicate/overlap disposition

`UC-043` and `UC-069` overlapped on MSG generation. `UC-069` is now the common MSG-generation goal. `UC-043` is a pre-acceptance merged/retired seed and is never reused; its Spare Request-specific behavior is preserved as required `UC-069` scenarios.

The common MSG goal explicitly preserves:

- **Generate MSG ≠ Send**;
- **Generate MSG ≠ Submit Spare Request**; and
- **Generate MSG ≠ Submit/Replace/Resend Fault Tag**.

## 5. Device Reference terminology correction

Tasks and ticket work context select/link **Device References**. A resolved Device Reference may point to a registered Network Element, but Network Element identity is not substituted for the operational Device Reference relationship.

`UC-027` and `UC-028` were corrected accordingly. Infrastructure regularization remains owned by `UC-056`, `UC-057`, and the new correction goal `UC-092`.

## 6. Resulting catalogue state

- Allocated IDs: **95 (`UC-001..UC-095`)**.
- Active goals: **94**.
- Accepted UCs: **1 (`UC-001`)**.
- Active Goal Seeds: **92**.
- Merged/retired pre-acceptance seeds: **1 (`UC-043 → UC-069`)**.
- Finally resolved requirement coverage: **0 / 177** until accepted UC/SI family-level coverage is completed.
- Product decisions changed by P1A-002: **0**.
- New implementation technology selected: **0**.

## 7. Exit criteria result

| Exit criterion | Result |
|---|---|
| `UC-001` expansion derived exclusively from accepted authority; no new observable behavior introduced | **PASS — acceptance retained under the accepted-specification expansion gate** |
| Remaining seeds explicitly non-acceptance-ready until Specification Gate | **PASS** |
| Known invalid authority references removed | **PASS** |
| Extracted/missing goals registered | **PASS** |
| Duplicate-goal disposition recorded | **PASS** |
| Device Reference terminology corrected | **PASS** |
| Index and traceability ledger synchronized | **PASS** |
| Owner review remains paused before UC-002 until full Specification Gate | **PASS** |

**P1A-002 CONTROLLED CATALOGUE RECONSTRUCTION: PASS / COMPLETED.**

## 8. Next action

`UC-002` has been expanded and has passed its Specification Gate, so it remains `Proposed`. Project-owner review is nevertheless paused after `UC-001` until RC-006-A2 passes its forward and reverse section-level assurance gates.

After A2 PASS, `UC-002` is the next business-use-case owner review item. Subsequent seeds must still pass:

`requirement → canonical family/subrange → normative destination → behavioral/recovery/evidence → duplicate/atomicity`

before they may move to `Proposed` and be presented for project-owner acceptance.

P1A-002 itself accepts no additional product behavior and no additional use case.