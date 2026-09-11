# SOMA Beta Reconciliation RC-003 — Workbench and Contract Product Line/SLA Authority

Status: **Accepted reconciliation record**  
Baseline: `RC-002` commit `065972a98dc397532d288b339ad3c93747debba6`  
Scope: `docs/WORKBENCH_CONTRACT.md` and `docs/PRODUCT_LINE_SLA.md`

## Purpose

RC-003 reconciles operator-facing Ticket/Objective workbench behavior and Contract Product Line/SLA policy representation against the accepted normalized catalogue plus reconciled RC-001/RC-002 authority. It repairs representation drift only and introduces no new Ticket lifecycle, classification policy, SLA threshold, report-storage design, or Objective state machine.

Primary normalized authority includes `BETA-REQ-0053`, `0064`, `0065`, `0069`, `0071`, `0075`, `0076`, `0087`, `0116`, `0122`–`0127`, `0151`, `0154`, `0157`, `0158`, `0161`–`0168`, and `0171`–`0177`, together with their stable clauses and the reconciled core/import contracts.

## Forward reconciliation result

### Workbench Contract

RC-003 preserves the accepted split workbench, tabs, responsive interaction, Device Reference promotion, SR/RFC relationship review, Local/WFM Task workflows, Inventory navigation, Notes, Objective grouping, Historical presentation, and Infrastructure workbook surfaces.

The checkpoint repairs these authority boundaries:

1. RFC terminal source evidence no longer implies direct Communication unlink. RFC unlink follows only the separately confirmed local terminal cascade; SR terminal transition remains separately governed.
2. Terminal-to-nonterminal SR evidence is represented as a high-risk same-record lifecycle correction, not as a new/reopened ticket episode or presumptive data manipulation.
3. SR Overview distinguishes Contract Product Line classification from SLA calculability so missing Report Date cannot erase a valid classification.
4. Subordinate-origin SR relationship actions propose the governing Master/root RFC link while preserving subordinate provenance.
5. Provider-Complete WFM history may produce a reviewed historical-Objective proposal only with valid source planning and never fabricates execution or SOMA Task outcome.
6. Objective grouping consumes accepted operational Task plans. WFM source plan remains immutable provider evidence/default reviewed candidate, and source/plan acceptance remains separate from regrouping acceptance.
7. Objective envelope is derived from accepted member Task plans; Objective membership never silently overwrites an established Task plan.
8. Advanced Search historical lookback is explicitly source-scoped and does not create RFC/WFM age-based lifecycle.

### Contract Product Line/SLA Contract

The policy contract remains customer/Contract-specific, monthly-cohort based, Report-Date anchored, exact-duration based, revision-aware, and immutable for completed reports.

RC-003 repairs these authority boundaries:

1. New active classification requires a current/usable customer-compatible Contract Product Line; archived/inactive CPLs are not new-classification candidates unless their owning lifecycle explicitly allows it.
2. Reclassification preserves prior classification history, and batch classification exposes per-SR eligible/incompatible/stale/unresolved/individually-reviewable results rather than applying one selection blindly.
3. Missing Report Date means SLA duration/compliance is uncalculable; it does not automatically mean the SR is CPL-unclassified.
4. Terminal SLA endpoint is the first accepted **effective** Resolved/Closed observation, not import/acceptance/recording time.
5. Current corrections and accepted terminal reversals may recalculate current endpoint/results while completed report evidence remains immutable.
6. Report snapshot storage strategy remains explicitly open under `O-001`; the product contract requires internally consistent immutable completed report evidence without selecting persisted/on-demand/both.
7. Missing Report Date never fabricates monthly cohort membership, and warnings distinguish unclassified from classified-but-uncalculable state.

## Reverse reconciliation result

Every strengthened assertion traces to accepted normalized authority or reconciled RC-001/RC-002 authority. No patch selects a new SLA threshold, Product Line fallback, Objective outcome transition, report-persistence strategy, notification cadence, parser rule, or implementation-specific state machine.

## Product-owner decisions

New product-owner decisions opened by RC-003: **0**.

Known unresolved Phase-0 product ambiguities remain: **0**.

## Result

- Forward requirement coverage: **PASS**
- Reverse authority: **PASS**
- Workbench/domain ownership consistency: **PASS**
- CPL/SLA calculation and reporting consistency: **PASS**
- Requirement identities changed: **0**
- Stable clause identities changed: **0**
- Product behavior invented: **0**
- Open design boundaries silently resolved: **0**
