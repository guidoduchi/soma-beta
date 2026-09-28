# LLD-08 forward migration allocation clarification

Owner approval in the implementation conversation: preserve accepted runtime
`beta_0014_infrastructure` bytes/hash, and add a forward-only LLD-08 proposal
candidate-ID repair. The next contiguous runtime allocation is sequence 15,
`beta_0015_infrastructure_workbook_candidates`. The pinned design's LLD-09
through LLD-12 allocations 15–18 were provisional, not accepted runtime
history; they must shift to 16–19 in the next accepted design revision.

This clarification covers only the bounded `candidate_ids_json` proposal
field and its query. Existing proposal rows receive an empty candidate list;
new staging must persist unique, ascending UUIDv4 candidate IDs, capped at
500. Larger ambiguity is discovered through `NetworkElementCandidateQuery`.
No accepted migration 1–14 is modified. The pinned design packet has not yet
been revised, so design-integrity evidence must record this reconciliation
instead of claiming the old allocation file already agrees.
