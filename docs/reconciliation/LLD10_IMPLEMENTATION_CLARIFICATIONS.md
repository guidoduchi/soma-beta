# Accepted LLD-10 implementation clarifications

Implementation owner clarification, 2026-10-01, against design
`9a0e891127a771251afccca1a281b7ef7dde9e5f`. The design pin is unchanged.

1. The Beta 1.0 production WorkingCopyContractRegistry registrations are not
   closed. Do not invent contract IDs, versions, draft schemas, target/scope keys
   or allowed dirty paths. Implement the immutable registry and fail-closed
   infrastructure. Production registrations require design reconciliation.
2. CheckpointWorkingCopy must not persist the draft-bearing WorkingCopyRecordV1
   in immutable command results. Its result is a metadata-only checkpoint DTO,
   stored exactly under Foundation replay. Full drafts exist only in
   ui_working_copies and are read by GetWorkingCopy while that row exists.
3. tickets.rfc.hard_delete follows LLD-03: impact_preview_plus_hold, exact eligible
   preview/fingerprint, continuous 3000ms hold and single-use LLD-12 proof.
   Add it to impact_preview_plus_hold_allowlist, not plain hold_allowlist.
   The pinned LLD-10 impact_preview registry entry is stale.

The accompanying JSON makes the metadata result and confirmation refinement
machine-addressable. It does not register any production edit surface. None of
these changes transfers domain lifecycle, auth/session or proof consumption to
LLD-10. Production working-copy coverage remains a design-reconciliation gap;
synthetic contracts verify the mechanism without certifying missing registrations.

## LLD-05 Task-detail reconciliation

The owner confirmed a further transport inconsistency on 2026-10-01. The
canonical route remains `GET /api/v1/tasks/{task_id}` and its response remains
`TaskDetailV1`, owned by LLD-05. Its narrow transport leaf is stale relative to
the same packet's `TaskWorkbench` query and UI handoff. The owner approved
preserving the complete workbench projection, including identity, WFM context,
provider source plan, operational plan/history, Objective membership,
membership-pinned plan, actual execution, reviewed outcome, locks, retry/lineage,
relationships, operational-count inclusion and pending warnings. Prefer the
existing explicit field names `operational_plan`, `actual_execution`,
`reviewed_outcome` and `membership_pinned_plan`.

This is a direction for owner design reconciliation, not a completed exact
transport-leaf replacement. LLD-10 must consume the single reconciled LLD-05
DTO; it must not assemble Task truth by joining private owner data. Until that
leaf is reconciled, its production HTTP binding remains pending.

## LLD-07 Inventory transport reconciliation

The owner confirmed on 2026-10-01 that `SpareRequestV1` remains the compact
command/core DTO. Define a separate `SpareRequestListItemV1` for list facts and
`SpareRequestDetailV1` for the existing richer detail projection. The detail GET
route now names `SpareRequestDetailV1`; command routes retain `SpareRequestV1`.
The list must preserve immutable requester identity and bounded creation context
separately from receiver/current Contact context. Owner-produced response age is
bound to the page's `as_of_utc`; LLD-10 must not recalculate it.

The owner also authorized closing the missing `SpareNeedProjectionV1` and
implementing `InventoryNeedsQuery` in LLD-07. The current `list_needs` operation
implements the Inventory-owned facts only: bounded filter-bound keyset pages,
planned quantity, derived contributor count and allocation/history counts under
one read snapshot. Selection-event and submission-snapshot totals are historical
counts, not physical fulfillment or current effective submitted demand. It is
not yet bound to the HTTP route or consumed by LLD-10.

The complete list/Needs transport leaves remain pending: SR/customer derived
context, customer filtering and action blockers require the declared
`InventoryReferenceReader.service_request(reader, sr_id)` provider and closed
result contract, which have not been located. An owner clarification is pending.
No UI-local DTO, Inventory-private-table access from LLD-10, empty blocker list,
or inferred action eligibility substitutes for that missing authority.

The subsequent owner clarification confirms the provider contract is incomplete.
LLD-03 must close a general downstream Service Request reference provider rather
than forcing Inventory to consume the import-specific reader. LLD-07 adapts it
locally. LLD-02 CustomerScopeProvider resolves all/specific/unassigned scope and
display identity; it does not own SR membership. Specific scope matches the
current LLD-03 SR Customer relationship, unassigned matches its absence, and all
adds no Customer predicate. The provider must offer a bounded batch/set read for
list pages up to 500. Customer binding remains deferred until reconciliation;
the non-Customer Inventory facts and pagination may proceed independently.

## LLD-09 chronology refinement

The owner confirmed that ChronologyV1 uses `utc_epoch_seconds` for canonical
UTC whole-second application/message chronology. The `utc_epoch_ms` field in
`types/common.json` is stale relative to schema, query and proposal authority
and the existing owner serializer. LLD-10 consumes that DTO unchanged.
`ProviderCheckpointV1.provider_time_source_epoch_ms` remains provider precision
and must never substitute for application chronology. This applies to summary,
detail, message list, frozen terminal, trackable identity and panel projections.

The unreleased synthetic historical fixture now uses an explicit unknown
ChronologyV1 rather than null. Its source provenance hash was refreshed for this
semantic correction; pixel baseline approval remains pending.

## LLD-05 grouping list transport and warnings

The accepted focused owner refinement is recorded in
[LLD05_GROUPING_LIST_TRANSPORT_V1.json](LLD05_GROUPING_LIST_TRANSPORT_V1.json).
It closes state (including superseded), risk and origin filters, the complete
filter/order/version-bound CURSOR_V1 and dedicated GroupingProposalListItemV1.
The owner list preserves exact filtered totals and the existing timestamp/UUID
ordering. It does not enlarge mutation GroupingProposalV1.

The only list warning codes are GROUPING_PROPOSAL_STALE and
GROUPING_EQUIVALENT_REJECTION. List and detail now share the exact complete
material/reproduction and unreconsidered exact-fingerprint predicates. Reads
are batched in one snapshot with one grouping capture, snapshot-local candidate
reuse and prefetched manual merge support. Uncertain or oversized supporting
work fails closed as GROUPING_INDETERMINATE rather than emitting an unproven
empty warning array. No migration or index allocation was introduced.

The accepted adjacent refinement splits recompute from the live page:
GroupingRecomputeResultV1.proposals uses GroupingRecomputeProposalPageV1 with
GroupingRecomputeProposalV1 items. Those contain only committed identity,
revision, fingerprint, state, kind, origin, risk and exact affected counts.
They never contain current warnings or stale/rejection classification. Durable
recompute keeps its empty immediate page and job_id. Exact replay returns the
original stored response, including historical response shapes, without owner
reconstruction. Accept/reject/reconsider retain compact GroupingProposalV1.
LLD-10 obtains current presentation from the live owner list separately.

## LLD-05 bounded Task detail and collections

The owner confirmed on 2026-10-02 that the initial creation limit of 62 Task
relationship IDs is not a business maximum. The accepted focused refinement in
[LLD05_TASK_COLLECTIONS_TRANSPORT_V1.json](LLD05_TASK_COLLECTIONS_TRANSPORT_V1.json)
replaces the complete active relationships and pending source-terminal/regroup/
historical ID sets with exact bounded owner summaries. Separate Task-scoped
relationships and attention GET collections use closed requests, CURSOR_V1,
exact totals and pages of at most 500 items. No collection cursor is added to
TaskIdQueryV1 or TaskDetailV1. Immediate retry predecessor/successor edges and
current activity lineage remain directly available in the detail.

The warning-code literals remain unclosed. Current attention_summary contains
exact counts and omits warning_codes; no empty array represents an unimplemented
classification. Warning-dependent LLD-10 Task binding remains pending. Existing
WFM SR context and the remaining full Task transport closure require owner
review before claiming that every detail projection is bounded or UI-ready.
The collection reads do not transfer owner classification, eligibility or
mutation authority to the UI.
