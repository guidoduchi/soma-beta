# RC-006-A2 — Design Handoff

Status: SEMANTIC FOUNDATION READY FOR HLD/LLD

This checkpoint ends RC-006-A2 as a blocking design gate. Exhaustive assertion allocation, accumulated forward/reverse-map completion, and final 11,524-clause certification are deferred to pre-release assurance and do not block HLD/LLD.

## Completed before handoff

- All 16 A2 destination sources received semantic pre-pass review.
- Product authority and normalized requirements remain the governing Beta 1.0 product definition.
- Confirmed semantic defects discovered during A2 were corrected in current HEAD while pinned B002 evidence remains immutable.
- RFC/WFM candidate fingerprint defect F3 was repaired and `A2-ASSERT-000654..000824` was formally allocated.
- Current formal allocation frontier remains `A2-ASSERT-000824`; Workbench and later sources are intentionally not required for design start.
- Temporary Workbench-only A2 execution/diagnostic workflows were removed before this checkpoint.

## Implementation-authority clarifications required in the design branch

These are accepted product behaviors whose canonical reverse authority was incomplete. HLD/LLD shall encode them explicitly rather than weakening the behavior.

### F4 — RFC to Device Reference context

An RFC may hold Device Reference context directly. This includes an RFC with no Service Request and subordinate RFC-specific device context. The operational relationship is to a Device Reference; a Device Reference may remain unregistered or resolve to an Infrastructure Network Element without replacing the RFC relationship identity.

This clarification does not change the two-level RFC hierarchy or the rule that Service Request direct RFC linkage targets the master/root RFC while subordinate provenance is preserved.

### F6 — Infrastructure physical model

The implementation shall preserve the accepted physical model in which Site contains Room, Room contains Rack, and Rack placement may carry row/column/position semantics. Reusable Model/BOM/component compatibility knowledge is distinct from per-Network-Element installed Component identity and history. Installed Component history belongs to the physical Network Element instance and shall not be collapsed into reusable model compatibility data.

## Existing bounded correction

F5 — Product Line/SLA cohort identity was corrected in current HEAD. The original B002 assertion remains historical assurance evidence and shall not drive implementation. Compliance outcome is derived after cohort membership and is not part of cohort identity.

## Branch policy after this checkpoint

- `main` remains untouched.
- `foundation/product-contract-v0.1` is retained as the product-authority/assurance lineage and should receive only bounded authority corrections or later assurance work.
- Active HLD/LLD work proceeds on `design/beta-1.0-hld-lld`, created from this checkpoint.
- Later foundation corrections that materially affect design are cherry-picked or manually reconciled into the design branch; the branches are not repeatedly wholesale-merged.

## AI-first design rule

New design artifacts exist to answer at least one of these questions:

1. What must be built?
2. How must it be built?
3. How is the implementation proven correct?

The design branch will prefer small machine-addressable requirement, HLD, LLD, state, command, schema, and acceptance-test files over monolithic prose documents.
