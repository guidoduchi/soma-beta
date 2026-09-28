# LLD-08 workbook owner reconciliation

This reconciliation records owner-approved Infrastructure workbook clarifications in the accepted design lane. It narrows or completes existing LLD-08 authority without transferring ownership to another packet.

## Reconciled authority

1. `INFRA_EXPORT_SCOPE_V1.network_element_ids` is bounded to 400 IDs. The workbook metadata cell remains subject to the existing 16,384-byte UTF-8 cell bound.
2. `infrastructure.import_directory` uses the LLD-02 `ordinary_nonsecret` storage class. LLD-08 continues to own path validation, observational access checks and nonrecursive discovery semantics.
3. Check-now requires an explicitly persisted import-directory setting with a positive revision. The computed display default has no synthetic revision and is not eligible until saved.
4. Normalized rows use `INFRA_WORKBOOK_NORMALIZED_ROW_V1`; logical identity uses `INFRA_WORKBOOK_LOGICAL_V1`. Logical identity ignores physical row order and generation time, preserves duplicate multiplicity, and retains source installation scope.
5. `INFRA_JOB_ACCEPTED_V1.state` includes `retry_wait` so coalesced durable jobs report their actual technical state.
6. Accepted sequence 14 remains immutable. Sequence 15 is allocated to the forward-only LLD-08 `beta_0015_infrastructure_workbook_candidates` repair; provisional LLD-09 through LLD-12 allocations shift to 16 through 19.

## Migration rule

The cumulative workbook schema includes bounded `candidate_ids_json`, but sequence 14 is not rewritten to create it. The addition belongs only to the sequence-15 forward migration. Existing proposal rows receive `[]`; new staging persists at most 500 unique ascending canonical UUIDv4 candidate IDs. Larger ambiguity remains query-owned.

## Scope

These clarifications do not certify the LLD-08 implementation branch, do not promote it into the Beta 1.0 implementation baseline, and do not authorize rewriting accepted runtime migration history. Implementation acceptance still requires branch integration, focused tests, failure injection, schema verification, packaging checks and CI evidence.
