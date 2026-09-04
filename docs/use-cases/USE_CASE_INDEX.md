# SOMA Beta Phase 1A — Use-Case Index

Status: **Complete draft catalogue committed for owner review — 77 UCs; 1 accepted, 76 draft**  
Phase-0 accepted baseline: `3c318a013ce4a81c34fc6e4c894cf87b5710360b`

## Governance

- Method: `USE_CASE_METHOD.md`
- Forward coverage ledger: `USE_CASE_TRACEABILITY.md`
- Canonical clause-range authority: `../reconciliation/RC006_CLAUSE_DESTINATIONS.md`
- Phase-0 owner acceptance: `../reconciliation/PHASE0_ACCEPTANCE.md`

## Status rule

Committing a use case does **not** accept it. `UC-001` is accepted from explicit project-owner review. `UC-002` through `UC-077` are stable draft candidates pending one-by-one owner review. Draft use cases do not satisfy the final Phase-1A coverage gate until accepted.

## Wave status

| Wave | Scope | Catalogue | Accepted | Draft |
|---|---|---:|---:|---:|
| `P1A-W1` | Foundation & Settings | 12 | 1 | 11 |
| `P1A-W2` | Tickets & Source Intake | 14 | 0 | 14 |
| `P1A-W3` | Objectives & Operational Work | 11 | 0 | 11 |
| `P1A-W4` | Inventory | 15 | 0 | 15 |
| `P1A-W5` | Infrastructure | 9 | 0 | 9 |
| `P1A-W6` | Communications | 8 | 0 | 8 |
| `P1A-W7` | Overview & Cross-domain Operations | 8 | 0 | 8 |
| **Total** |  | **77** | **1** | **76** |
| `P1A-W8` | Global traceability/reverse-authority audit | — | Not started | — |

## Catalogue

| UC | Goal | Wave | Status |
|---|---|---|---|
| `UC-001` | Initialize a new SOMA installation | W1 | **Accepted** |
| `UC-002` | Authenticate, lock, and unlock the installation | W1 | Draft |
| `UC-003` | Maintain the Local Administrator profile and password | W1 | Draft |
| `UC-004` | Configure automatic login | W1 | Draft |
| `UC-005` | Change appearance, skin, and Objective scheduling timezone | W1 | Draft |
| `UC-006` | Manage Contacts | W1 | Draft |
| `UC-007` | Manage Customers, Product Lines, Contracts, and Contract Product Lines | W1 | Draft |
| `UC-008` | Manage Dispatch Locations | W1 | Draft |
| `UC-009` | Create and manage verified backups | W1 | Draft |
| `UC-010` | Restore or recover an installation from protected backup | W1 | Draft |
| `UC-011` | Start, reuse, and stop the local SOMA instance | W1 | Draft |
| `UC-012` | Inspect runtime, migration, and diagnostic status | W1 | Draft |
| `UC-013` | Create a manual Service Request | W2 | Draft |
| `UC-014` | Discover and stage Advanced Search SR source data | W2 | Draft |
| `UC-015` | Review and accept/reject staged SR source changes | W2 | Draft |
| `UC-016` | Reconcile or correct an SR official identity and lifecycle observation | W2 | Draft |
| `UC-017` | Work an SR through its workbench | W2 | Draft |
| `UC-018` | Create a manual RFC | W2 | Draft |
| `UC-019` | Manage RFC hierarchy and SR relationships | W2 | Draft |
| `UC-020` | Discover and stage Enhanced Excel RFC source data | W2 | Draft |
| `UC-021` | Review RFC source changes and terminal evidence | W2 | Draft |
| `UC-022` | Create or import a WFM Task | W2 | Draft |
| `UC-023` | Review WFM plan changes and competing attempts | W2 | Draft |
| `UC-024` | Classify an SR to a Contract Product Line | W2 | Draft |
| `UC-025` | Evaluate current SR SLA and cohort status | W2 | Draft |
| `UC-026` | Browse active, terminal, and historical Tickets | W2 | Draft |
| `UC-027` | Create a Local Task | W3 | Draft |
| `UC-028` | Maintain Task relationships and work context | W3 | Draft |
| `UC-029` | Plan, schedule, or unschedule a Task | W3 | Draft |
| `UC-030` | Create an Objective manually | W3 | Draft |
| `UC-031` | Propose automatic Objective grouping from overlapping Task plans | W3 | Draft |
| `UC-032` | Review, reassign, or regroup Objective membership | W3 | Draft |
| `UC-033` | Execute a Task and record its actual outcome | W3 | Draft |
| `UC-034` | Review or correct a Task execution/outcome record | W3 | Draft |
| `UC-035` | Retry operational work as a new Task attempt | W3 | Draft |
| `UC-036` | Cancel, archive, or delete eligible operational work records | W3 | Draft |
| `UC-037` | Confirm the local RFC terminal cascade | W3 | Draft |
| `UC-038` | Record a faulty Device Part and create/contribute to a Spare Need | W4 | Draft |
| `UC-039` | Manage a Spare Need through its lifecycle | W4 | Draft |
| `UC-040` | Review Stock suggestions and choose a fulfillment strategy | W4 | Draft |
| `UC-041` | Allocate or release local Stock for planned work | W4 | Draft |
| `UC-042` | Prepare a Spare Request draft | W4 | Draft |
| `UC-043` | Generate a Spare Request MSG draft | W4 | Draft |
| `UC-044` | Register a Spare Request initiated outside SOMA | W4 | Draft |
| `UC-045` | Accept actual Spare Request submission | W4 | Draft |
| `UC-046` | Reconcile provider response and RMA obligations | W4 | Draft |
| `UC-047` | Record inbound spare dispatch, receipt, and physical unit identity | W4 | Draft |
| `UC-048` | Allocate a Spare Part Unit to a Task | W4 | Draft |
| `UC-049` | Record reviewed physical maintenance consequences | W4 | Draft |
| `UC-050` | Create and submit a Fault Tag return | W4 | Draft |
| `UC-051` | Process Fault Tag warehouse receipt and final decision | W4 | Draft |
| `UC-052` | Correct/cancel/replace/resend/archive/delete eligible Inventory records | W4 | Draft |
| `UC-053` | Create a Site and its dedicated Dispatch Location | W5 | Draft |
| `UC-054` | Manage Cloud Types and site-bound Cloud Deployments | W5 | Draft |
| `UC-055` | Manage Rooms and Racks within a Site | W5 | Draft |
| `UC-056` | Promote an unregistered Device Reference into a new Network Element | W5 | Draft |
| `UC-057` | Resolve a Device Reference to an existing Network Element | W5 | Draft |
| `UC-058` | Maintain Network Element facts, IP, placement, containment, and components | W5 | Draft |
| `UC-059` | Export a versioned Infrastructure workbook | W5 | Draft |
| `UC-060` | Import and reconcile an Infrastructure workbook | W5 | Draft |
| `UC-061` | Archive or reactivate Infrastructure references safely | W5 | Draft |
| `UC-062` | Configure read-only Communication Source Scopes | W6 | Draft |
| `UC-063` | Run the local Communication fetch-and-match pipeline | W6 | Draft |
| `UC-064` | Review Communication coverage and perform targeted backfill | W6 | Draft |
| `UC-065` | Perform an explicit scoped Deep Scan | W6 | Draft |
| `UC-066` | Review and decide Communication-derived domain proposals | W6 | Draft |
| `UC-067` | Inspect and navigate canonical Communication evidence | W6 | Draft |
| `UC-068` | Unlink terminal targets and minimize orphaned Communication content | W6 | Draft |
| `UC-069` | Generate a local MSG draft from a supported workflow | W6 | Draft |
| `UC-070` | Navigate SOMA workspaces, lists, and workbenches | W7 | Draft |
| `UC-071` | Manage unsaved working copies, conflicts, and safe Undo | W7 | Draft |
| `UC-072` | Use Overview and Needs Attention to understand current operations | W7 | Draft |
| `UC-073` | Generate a Daily, Weekly, or Monthly Excel report | W7 | Draft |
| `UC-074` | Review completed report evidence against current recalculated truth | W7 | Draft |
| `UC-075` | Review notifications, warnings, and actionable attention states | W7 | Draft |
| `UC-076` | Execute bulk, destructive, or consequential actions safely | W7 | Draft |
| `UC-077` | Inspect combined domain history, audit, jobs, and activity | W7 | Draft |

## Wave files

- `P1A_W1_FOUNDATION_SETTINGS.md` — `UC-001..012`
- `P1A_W2_TICKETS_SOURCE.md` — `UC-013..026`
- `P1A_W3_OBJECTIVES_WORK.md` — `UC-027..037`
- `P1A_W4_INVENTORY.md` — `UC-038..052`
- `P1A_W5_INFRASTRUCTURE.md` — `UC-053..061`
- `P1A_W6_COMMUNICATIONS.md` — `UC-062..069`
- `P1A_W7_OVERVIEW_CROSSDOMAIN.md` — `UC-070..077`

## Review protocol

Review proceeds by stable ID. For each Draft UC the project owner may **Approve**, **Replace/Rework**, **Split**, **Merge**, or **Reject as non-use-case/SI**. Accepted IDs remain stable; a split/merge must preserve traceability and never silently reuse an accepted identity for a different goal.

`P1A-W8` begins only after the catalogue review resolves every draft and the forward ledger can prove every behavioral canonical clause family is exercised by accepted use cases or explicitly covered as SI where appropriate.
