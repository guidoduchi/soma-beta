# Pre-LLD-08 SR reference point-warning reconciliation

Date: 2026-09-23  
Status: candidate clarification pending paired implementation regression and current-design integrity CI.  
Owner: LLD-03 Tickets Core; LLD-02 remains owner of Contact affiliation.

## Forward authority check

The accepted LLD-03 GetServiceRequestReferenceContext contract already requires a bounded, read-only warning summary and immutable organization-at-use context. Its Contact mutation previews already issue SR_CONTACT_AFFILIATION_REVIEW_REQUIRED when known current affiliation conflicts with the known current canonical SR Customer. SRC005/SRC007 preserve organization-at-use and explicit reviewed mismatches; SRC009 keeps stale Current Handler resolution historical. LLD02-T013 independently requires all consumer organization-at-use snapshots to survive later affiliation changes.

## Explicit point-query clarification

The current SR point context derives the same known current mismatch warning from data it already fetches. It does so for customer_contact and aligned current_handler_reference only. The warning is a read-time summary, not an irreversible assertion that an accepted reviewed relationship was invalid, and it never rewrites either LLD-02 affiliation or historical LLD-03 context. Missing canonical SR Customer or unknown/null current affiliation cannot establish a mismatch; stale handler-only rows remain historical and retain their distinct stale warning. Historical relationship queries do not recalculate point-state warnings.

## Reverse authority and implementation boundary

No new mutation, error code, persisted data, foreign key, migration or release feature is authorized by this clarification. It makes previously accepted preview and point warning-summary behavior consistent. The code implementation is a bounded comparison in the existing point-query projection; no new lookup, audit or speculative source authority is introduced. Evidence obligation: later-affiliation drift, previously reviewed mismatch, both roles, missing/unknown affiliation, stale handler, snapshot/history immutability, and the exact LLD02-T013 regression. Final authority requires fresh design integrity and implementation matrix evidence for the exact paired SHAs.
