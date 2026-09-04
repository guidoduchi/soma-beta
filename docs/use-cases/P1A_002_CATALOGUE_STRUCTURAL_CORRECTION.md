# P1A-002 — Catalogue Structural Correction

Status: **OPEN — corrective pass required before UC-002 owner review**  
Scope: Phase 1A catalogue representation and traceability only.  
Product authority: unchanged; Phase-0 accepted behavior remains authoritative.

## 1. Why this correction exists

The initial 77-item Phase-1A catalogue successfully decomposed SOMA Beta 1.0 into a useful goal inventory, but its repository representation was not consistently acceptance-ready under `USE_CASE_METHOD.md`.

The corrective pass addresses four specification-assurance defects without reopening approved product behavior:

1. several draft UCs cite unrelated or overly broad `BETA-REQ` ranges;
2. the seed format omits fields required for a Proposed/Accepted use case;
3. several seeds combine goals with materially different authority/end-state/recovery contracts;
4. several material goals required by accepted contracts are absent or hidden as subordinate steps.

## 2. Governance disposition

- `UC-001` remains semantically **Accepted**. Its repository representation is expanded non-semantically to satisfy the mandatory use-case fields.
- `UC-002` onward owner acceptance is **paused** until each candidate passes the Specification Gate.
- Existing nonaccepted IDs may be narrowed, split, merged, or retired because they have not acquired accepted identity authority; every such disposition remains recorded.
- New/extracted goals receive IDs from `UC-078` onward.
- Cross-cutting UI mechanics remain acceptance/SI obligations unless they independently form an actor/system goal.
- MOP generation remains outside Beta 1.0 and is not added.

## 3. Confirmed authority-reference defects to remove

The following are representative, not exhaustive. P1A-002 requires a full catalogue re-derivation rather than patching only these rows.

| UC | Invalid / misleading authority | Correction direction |
|---|---|---|
| `UC-027`, `UC-028` | `BETA-REQ-0024` (`SITE-DISPATCH`) | Task/relationship and Device Reference authority only |
| `UC-030` | `BETA-REQ-0007` (`SCM`) | Objective/Task grouping and lifecycle authority |
| `UC-047` | `BETA-REQ-0036` (`DATA-CRYPT`) | Inventory receipt/logistics/unit authority |
| `UC-049` | `BETA-REQ-0035..0037` | Task outcome + Inventory physical-consequence authority |
| `UC-050` | `BETA-REQ-0068` | `FT-SCOPE` through applicable Fault Tag families |
| `UC-051` | `BETA-REQ-0061..0064` and `0102` | `FT-WH`/`FT-LOG` and applicable Fault Tag lifecycle |
| `UC-054..058`, `UC-061` | `0076..0080` used as Infrastructure authority | `0049`, `0102..0110`, and physical hierarchy authorities as applicable |
| `UC-066` | SLA families `0063..0064` | Communications proposal authority + scenario-specific owning domain |
| `UC-067` | `0032` requester-Contact authority | Communications canonical evidence/link authority |
| `UC-069` | `0048` Objective grouping | Communications MSG authority + scenario-specific workflow authority |

## 4. Goal corrections

### 4.1 Split/narrow

- `UC-007`: retain Customer Organization management as its principal goal; extract reusable Product Line, Contract, and Contract Product Line/SLA-policy goals.
- `UC-022`: retain manual WFM registration as its principal goal; extract provider WFM source discovery/staging.
- `UC-036`: retain cancellation as its principal lifecycle goal; extract archival and narrow hard deletion.
- `UC-052`: retain exact Inventory correction as its principal goal; extract cancellation, Fault Tag replacement, rejection resend, archival/reactivation, and narrow hard deletion.
- `UC-071`: retain unsaved working-copy/save/discard/recovery behavior; extract stale accepted-state conflict resolution and bounded post-action Undo.
- `UC-076`: narrow to supported bulk execution; generic confirmation-tier behavior remains cross-cutting SI/acceptance authority.

### 4.2 Missing goals

Add explicit coverage for:

- manual Spare Part Unit registration (`SPUNIT-REG` / LSU identity and optional provenance);
- Infrastructure Import Directory configuration/validation and `Check now`;
- correction/reassignment of an already accepted Device Reference → Network Element resolution;
- Working Notes edit/remove/history behavior;
- extracted commercial-reference goals;
- extracted WFM source intake;
- extracted operational/archive/deletion and Inventory exception lifecycles.

### 4.3 Duplicate/overlap disposition

`UC-043` and `UC-069` overlap on MSG generation. P1A-002 keeps `UC-069` as the common MSG-generation goal. `UC-043` becomes a pre-acceptance merged/retired seed whose Spare Request-specific requirements are acceptance scenarios of `UC-069` and the owning Spare Request workflow; generation never means sending or submission.

## 5. Device Reference terminology correction

Tasks and ticket work context select/link **Device References**. A resolved Device Reference may point to a registered Network Element, but Network Element identity is not substituted for the operational Device Reference relationship.

Therefore Task UCs use Device Reference relationships; Infrastructure regularization UCs own Device Reference → Network Element resolution/promotion/correction.

## 6. Affected files

P1A-002 updates:

- `USE_CASE_METHOD.md`;
- `USE_CASE_INDEX.md`;
- `USE_CASE_TRACEABILITY.md`;
- `P1A_W1_FOUNDATION_SETTINGS.md` through `P1A_W7_OVERVIEW_CROSSDOMAIN.md` as applicable; and
- this correction record.

## 7. Exit criteria

P1A-002 closes only when:

- `UC-001` has complete mandatory representation without semantic change;
- every remaining Goal Seed is clearly non-acceptance-ready until Specification Gate PASS;
- known invalid authority references are removed;
- extracted/missing goals are registered;
- duplicate-goal disposition is recorded;
- Device Reference terminology is corrected;
- use-case index and traceability ledger agree on statuses and IDs; and
- owner review remains paused at `UC-002` until its full specification passes the gate.

P1A-002 does not itself accept any additional use case.