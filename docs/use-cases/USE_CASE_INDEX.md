# SOMA Beta Phase 1A — Use-Case Index

Status: **P1A-002 controlled reconstruction completed — UC-002 Specification Gate PASS; owner review paused pending RC-006-A2**  
Phase-0 accepted baseline remains governed by `../reconciliation/PHASE0_ACCEPTANCE.md`.

## Governance

- Method: `USE_CASE_METHOD.md`
- Controlled catalogue reconstruction: `P1A_002_CATALOGUE_STRUCTURAL_CORRECTION.md`
- Forward coverage ledger: `USE_CASE_TRACEABILITY.md`
- Canonical clause-range authority: `../reconciliation/RC006_CLAUSE_DESTINATIONS.md`
- Phase-0 owner acceptance: `../reconciliation/PHASE0_ACCEPTANCE.md`

## Status rule

`UC-001` is accepted. `UC-002` has passed the internal Specification Gate and is **Proposed**, but project-owner review is paused until `RC-006-A2` passes.

All other active entries are **Goal Seeds** until they pass the Specification Gate in `USE_CASE_METHOD.md`. They are not to be presented for owner acceptance in seed form.

Pre-acceptance IDs may be split/merged/narrowed/retired with recorded disposition. Accepted IDs are immutable and never reused.

## Current catalogue state

- Allocated IDs: **95 (`UC-001..UC-095`)**
- Active goals: **94**
- Accepted: **1 (`UC-001`)**
- Proposed: **1 (`UC-002`)**
- Active Goal Seeds: **92**
- Pre-acceptance merged/retired seeds: **1 (`UC-043 → UC-069`)**
- Next owner review after `RC-006-A2` PASS: **UC-002**

## Wave status

| Wave | Scope | Active goals | Accepted | Proposed | Goal Seeds | Retired/merged |
|---|---|---:|---:|---:|---:|---:|
| `P1A-W1` | Foundation & Settings | 15 | 1 | 1 | 13 | 0 |
| `P1A-W2` | Tickets & Source Intake | 16 | 0 | 0 | 16 | 0 |
| `P1A-W3` | Objectives & Operational Work | 13 | 0 | 0 | 13 | 0 |
| `P1A-W4` | Inventory | 21 | 0 | 0 | 21 | 1 (`UC-043`) |
| `P1A-W5` | Infrastructure | 11 | 0 | 0 | 11 | 0 |
| `P1A-W6` | Communications | 8 | 0 | 0 | 8 | 0 |
| `P1A-W7` | Overview & Cross-domain Operations | 10 | 0 | 0 | 10 | 0 |
| **Total active** |  | **94** | **1** | **1** | **92** | **1** |
| `P1A-W8` | Global traceability/reverse-authority/duplicate audit | — | Not started | — | — | — |

## Catalogue

| UC | Goal | Wave | Status |
|---|---|---|---|
| `UC-001` | Initialize a new SOMA installation | W1 | **Accepted** |
| `UC-002` | Authenticate to an established SOMA installation | W1 | **Proposed — Specification Gate PASS** |
| `UC-003` | Maintain the Local Administrator profile and password | W1 | Goal Seed |
| `UC-004` | Configure automatic login | W1 | Goal Seed |
| `UC-005` | Change appearance, skin, and Objective scheduling timezone | W1 | Goal Seed |
| `UC-006` | Manage Contacts | W1 | Goal Seed |
| `UC-007` | Manage Customer Organizations | W1 | Goal Seed — narrowed |
| `UC-008` | Manage Dispatch Locations | W1 | Goal Seed |
| `UC-009` | Create and manage verified backups | W1 | Goal Seed |
| `UC-010` | Restore or recover an installation from protected backup | W1 | Goal Seed |
| `UC-011` | Start, reuse, and stop the local SOMA instance | W1 | Goal Seed |
| `UC-012` | Inspect runtime, migration, and diagnostic status | W1 | Goal Seed |
| `UC-013` | Create a manual Service Request | W2 | Goal Seed |
| `UC-014` | Discover and stage Advanced Search SR source data | W2 | Goal Seed |
| `UC-015` | Review and accept/reject staged SR source changes | W2 | Goal Seed |
| `UC-016` | Reconcile or correct an SR official identity and lifecycle observation | W2 | Goal Seed |
| `UC-017` | Work an SR through its workbench | W2 | Goal Seed |
| `UC-018` | Create a manual RFC | W2 | Goal Seed |
| `UC-019` | Manage RFC hierarchy and SR relationships | W2 | Goal Seed |
| `UC-020` | Discover and stage Enhanced Excel RFC source data | W2 | Goal Seed |
| `UC-021` | Review RFC source changes and terminal evidence | W2 | Goal Seed |
| `UC-022` | Register a WFM Task manually | W2 | Goal Seed — narrowed |
| `UC-023` | Review WFM plan changes and competing attempts | W2 | Goal Seed |
| `UC-024` | Classify an SR to a Contract Product Line | W2 | Goal Seed |
| `UC-025` | Evaluate current SR SLA and cohort status | W2 | Goal Seed |
| `UC-026` | Browse active, terminal, and historical Tickets | W2 | Goal Seed |
| `UC-027` | Create a Local Task | W3 | Goal Seed — corrected |
| `UC-028` | Maintain Task relationships and work context | W3 | Goal Seed — corrected |
| `UC-029` | Plan, schedule, or unschedule a Task | W3 | Goal Seed |
| `UC-030` | Create an Objective manually | W3 | Goal Seed — corrected |
| `UC-031` | Propose automatic Objective grouping from overlapping Task plans | W3 | Goal Seed |
| `UC-032` | Review, reassign, or regroup Objective membership | W3 | Goal Seed |
| `UC-033` | Execute a Task and record its actual outcome | W3 | Goal Seed |
| `UC-034` | Review or correct a Task execution/outcome record | W3 | Goal Seed |
| `UC-035` | Retry operational work as a new Task attempt | W3 | Goal Seed |
| `UC-036` | Cancel eligible operational work | W3 | Goal Seed — narrowed |
| `UC-037` | Confirm the local RFC terminal cascade | W3 | Goal Seed |
| `UC-038` | Record a faulty Device Part and create/contribute to a Spare Need | W4 | Goal Seed |
| `UC-039` | Manage a Spare Need through its lifecycle | W4 | Goal Seed |
| `UC-040` | Review Stock suggestions and choose a fulfillment strategy | W4 | Goal Seed |
| `UC-041` | Allocate or release local Stock for planned work | W4 | Goal Seed |
| `UC-042` | Prepare a Spare Request draft | W4 | Goal Seed |
| `UC-043` | Generate a Spare Request MSG draft | W4 | **Merged/retired → UC-069** |
| `UC-044` | Register a Spare Request initiated outside SOMA | W4 | Goal Seed |
| `UC-045` | Accept actual Spare Request submission | W4 | Goal Seed |
| `UC-046` | Reconcile provider response and RMA obligations | W4 | Goal Seed — corrected |
| `UC-047` | Record inbound spare dispatch, receipt, and physical unit identity | W4 | Goal Seed — corrected |
| `UC-048` | Allocate a Spare Part Unit to a Task | W4 | Goal Seed |
| `UC-049` | Record reviewed physical maintenance consequences | W4 | Goal Seed — corrected |
| `UC-050` | Create and submit a Fault Tag return | W4 | Goal Seed — corrected |
| `UC-051` | Process Fault Tag warehouse receipt and final decision | W4 | Goal Seed — corrected |
| `UC-052` | Correct an accepted Inventory event or relationship | W4 | Goal Seed — narrowed |
| `UC-053` | Create a Site and its dedicated Dispatch Location | W5 | Goal Seed |
| `UC-054` | Manage Cloud Types and site-bound Cloud Deployments | W5 | Goal Seed — corrected |
| `UC-055` | Manage Rooms and Racks within a Site | W5 | Goal Seed — corrected |
| `UC-056` | Promote an unregistered Device Reference into a new Network Element | W5 | Goal Seed — corrected |
| `UC-057` | Resolve a Device Reference to an existing Network Element | W5 | Goal Seed — corrected |
| `UC-058` | Maintain Network Element facts, IP, placement, containment, and components | W5 | Goal Seed — corrected |
| `UC-059` | Export a versioned Infrastructure workbook | W5 | Goal Seed — corrected |
| `UC-060` | Import and reconcile an Infrastructure workbook | W5 | Goal Seed — corrected |
| `UC-061` | Archive or reactivate Infrastructure references safely | W5 | Goal Seed — corrected |
| `UC-062` | Configure read-only Communication Source Scopes | W6 | Goal Seed |
| `UC-063` | Run the local Communication fetch-and-match pipeline | W6 | Goal Seed |
| `UC-064` | Review Communication coverage and perform targeted backfill | W6 | Goal Seed |
| `UC-065` | Perform an explicit scoped Deep Scan | W6 | Goal Seed |
| `UC-066` | Review and decide Communication-derived domain proposals | W6 | Goal Seed — corrected |
| `UC-067` | Inspect and navigate canonical Communication evidence | W6 | Goal Seed — corrected |
| `UC-068` | Unlink terminal targets and minimize orphaned Communication content | W6 | Goal Seed |
| `UC-069` | Generate a local MSG draft from a supported workflow | W6 | Goal Seed — common MSG owner |
| `UC-070` | Navigate SOMA workspaces, lists, and workbenches | W7 | Goal Seed |
| `UC-071` | Manage unsaved working copies and save/discard/recover edits | W7 | Goal Seed — narrowed |
| `UC-072` | Use Overview and Needs Attention to understand current operations | W7 | Goal Seed |
| `UC-073` | Generate a Daily, Weekly, or Monthly Excel report | W7 | Goal Seed |
| `UC-074` | Review completed report evidence against current recalculated truth | W7 | Goal Seed |
| `UC-075` | Review notifications, warnings, and actionable attention states | W7 | Goal Seed |
| `UC-076` | Execute a supported bulk action safely | W7 | Goal Seed — narrowed |
| `UC-077` | Inspect combined domain history, audit, jobs, and activity | W7 | Goal Seed |
| `UC-078` | Manage reusable Product Lines | W1 | Goal Seed — extracted |
| `UC-079` | Manage Contracts | W1 | Goal Seed — extracted |
| `UC-080` | Manage Contract Product Lines and customer-specific SLA policy | W1 | Goal Seed — extracted |
| `UC-081` | Discover and stage provider WFM source data | W2 | Goal Seed — extracted |
| `UC-082` | Archive or reactivate eligible operational work records | W3 | Goal Seed — extracted |
| `UC-083` | Hard-delete an untouched eligible manual operational record | W3 | Goal Seed — extracted |
| `UC-084` | Register a manual Spare Part Unit | W4 | Goal Seed — added |
| `UC-085` | Cancel an eligible Spare Request | W4 | Goal Seed — extracted |
| `UC-086` | Cancel an eligible Fault Tag | W4 | Goal Seed — extracted |
| `UC-087` | Replace a materially incorrect submitted Fault Tag | W4 | Goal Seed — extracted |
| `UC-088` | Resend a rejected Fault Tag return | W4 | Goal Seed — extracted |
| `UC-089` | Archive or reactivate an eligible Inventory record | W4 | Goal Seed — extracted |
| `UC-090` | Hard-delete an untouched eligible Inventory record | W4 | Goal Seed — extracted |
| `UC-091` | Configure the Infrastructure Import Directory and run Check now | W5 | Goal Seed — added |
| `UC-092` | Correct or reassign an accepted Device Reference resolution | W5 | Goal Seed — added |
| `UC-093` | Resolve a stale accepted-state edit conflict | W7 | Goal Seed — extracted |
| `UC-094` | Manage Working Notes | W2 | Goal Seed — added |
| `UC-095` | Perform bounded safe Undo of an eligible recent action | W7 | Goal Seed — extracted |

## Wave files

- `P1A_W1_FOUNDATION_SETTINGS.md` — `UC-001..012`, `078..080`
- `P1A_W2_TICKETS_SOURCE.md` — `UC-013..026`, `081`, `094`
- `P1A_W3_OBJECTIVES_WORK.md` — `UC-027..037`, `082..083`
- `P1A_W4_INVENTORY.md` — `UC-038..052`, `084..090` (`UC-043` retired/merged)
- `P1A_W5_INFRASTRUCTURE.md` — `UC-053..061`, `091..092`
- `P1A_W6_COMMUNICATIONS.md` — `UC-062..069`
- `P1A_W7_OVERVIEW_CROSSDOMAIN.md` — `UC-070..077`, `093`, `095`

## Review protocol after P1A-002

For each next ID:

1. expand the seed to the complete mandatory specification;
2. validate requirement → canonical owner/family → normative destination;
3. run duplicate/atomicity/recovery/evidence checks;
4. mark `Proposed` only after Specification Gate PASS; and
5. then present it to the project owner for Approve/Rework/Split/Merge/SI disposition.

`UC-002` has completed steps 1–4 and remains the next project-owner review item after `RC-006-A2` passes; owner review is currently paused.

`P1A-W8` begins only after all active goals are accepted/reworked/merged/SI-classified and the forward ledger can prove every behavioral canonical clause family is exercised by accepted use cases or explicitly covered as SI.