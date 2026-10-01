# LLD-09 proposal-contract reconciliation candidate

Status: ACCEPTED_OWNER_CLARIFICATION on 2026-09-30. The owner accepted the four-contract registry and requested implementation continuation. The historical CANDIDATE filename is retained for session traceability. These accepted focused clarifications refine the pinned design within LLD-09; upstream design normalization remains separate.

Design: `9a0e891127a771251afccca1a281b7ef7dde9e5f`.
Implementation parent: `47947c50` on `feat/beta-1.0-implementation`.

## Accepted session clarifications

- The three existing owning identity providers add indexed
  `lookup_trackable_identifier(reader,exact_value)` iterators of their existing
  TrackableIdentity objects. Processing compares the complete current candidate
  set for each matched token before commit, including changed ambiguity, without
  scanning every operational identity under a writer lock.
- They also add read-only
  `current_target_revision(reader,target_type,target_id) -> positive integer|null`.
  Link correction previews bind old and new current revisions. Closing a stale
  link remains possible and changes no owning-domain authority.

- Existing owner `validate_trackable_target` methods accept optional keyword
  `identity_kind` and verify it against their exact exported identity/alias
  records when supplied. Existing callers retain their original behavior.
- Link rejection requires the exact proposal revision/fingerprint. Acceptance
  additionally requires fresh retained source evidence and a current eligible
  target. Rejecting stale source/target evidence only closes the proposal hold
  and reevaluates retention; it creates no link or owning-domain mutation.

- Registered version-1 match rules are `COMM_EXACT_IDENTIFIER_V1`,
  `COMM_EXACT_ALIAS_V1` and `COMM_REVIEWED_MANUAL_V1`, corresponding exactly
  to `EXACT_IDENTIFIER`, `EXACT_ALIAS` and `REVIEWED_MANUAL`. Aliases and
  manual associations require review; only current official identifiers may
  qualify for auto-safe linking after writer validation.
- The existing Ticket identity provider adds
  `validate_communication_reassociation(reader,target_type,target_id,revision)`.
  It uses accepted SR terminal/reversal authority and applied RFC cascade state.
  Provider terminal evidence or a pending cascade alone does not make an RFC
  locally terminal. The result is `VALID|INVALID|INDETERMINATE` and grants no
  lifecycle mutation authority.

- The owner confirmed migration 16 for LLD-09 until merge back into main. Use `beta_0016_communications` / `0016_communications.sql`; preserve accepted runtime migrations 1-15. This also corrects the stale sequence-12 traceability edge and sequence-15 packet leaf.
- The owner confirmed reuse of the paged LLD-03 RFC cascade preview contract: `preview_terminal_cascade(snapshot, proposal_snapshot, after_key, limit)` returns `RfcTerminalCascadeImpactProviderPageV1`. Align the stale unpaged Communications cross-packet registry with that owner contract.
- The owner confirmed whole UTC seconds for application chronology and preservation of provider milliseconds only in coverage checkpoints.
- The owner confirmed nullable `internet_message_id` on the closed transient message type as one fallback identity input; it is not standalone identity authority.
- The owner confirmed exact identity evidence fields `provider_identity_bytes` and `fallback_canonical_json` in migration 16. A digest match is only candidate evidence: retained-message reuse must compare provider key bytes or the complete fallback object. Purge removes the reconstructable fallback object; minimized provider key/digest evidence remains. Fallback-only reconstruction after purge requires reviewed reconciliation when exact identity cannot be established.
- The owner confirmed the nested fallback shapes: `from` contains FROM/SENDER participants and `recipients` all remaining roles, ordered by source ordinal and role to resolve ordinal ties. Each participant is `{role, ordinal, address, display_name}`. Attachments are ordered by source ordinal and each is `{ordinal, filename, size_bytes, content_sha256}`. Canonical fallback evidence is limited to 1 MiB, with the existing 2,000-participant and 500-attachment limits; oversize evidence rejects without truncation.
- The owner confirmed `SourceScopeSummaryV1` as the closed object `{source_scope_id, revision, display_name, health_state, processing_enabled, selected_folders}`; selected folders use `SourceFolderV1` and are bounded to 64.
- The owner confirmed `communications.orphan_grace.cancelled@1` / `CommGraceCancelledAuditV1@1`, targeted at the Communication, with exact bounded payload `{retention_revision, reason_code}` and immutable Communication/retention-event refs. This action records an actual cancellation caused by restored protection. It does not use or fabricate `communications.orphan_purged` evidence.
- The owner confirmed case-sensitive exact identifier matching. An occurrence is rejected when either adjacent character is a Unicode letter, mark, number or connector punctuation (including underscore). Alias matches remain review-only.
- The owner confirmed the existing immutable Objective `MW-########` tracking id as the explicitly exported LLD-05 communication reference, without a new editable field or lifecycle command.
- The owner confirmed `direction_conflict: boolean` as required transient adapter evidence. Recognized INBOX/SENT roles produce RECEIVED/SENT only with no conflict; any conflict produces UNKNOWN. This flag is not reconstructed from scan time or a generated MSG draft.
- The owner confirmed `validate_target_revision(reader,target_type,target_id,revision)` on the existing LLD-03, LLD-05 and LLD-07 identity providers. Domain-fact wrappers carry UUID/revision without a matched identifier string. This method validates current governed owner identity/revision; it adds no lifecycle mutation authority. Inventory's existing participant still validates the parent/membership and proposed facts.
- The owner confirmed an optional `communication_proposal` object `{proposal_id, proposal_revision, proposal_fingerprint}` on the three existing Inventory acceptance commands. When supplied, the owning command verifies that its exact target/facts equal the reviewed Communications evidence and records acceptance in its existing outer receipt/UoW. Manual calls remain valid. No separately committed Inventory proposal or second acceptance command is introduced.

## Accepted release registry

The adjacent JSON file defines closed payload schemas and mappings.

| Contract/version | Owner | Target | Proposed fact | Acceptance owner |
| --- | --- | --- | --- | --- |
| COMM_LINK_V1 / 1 | LLD-09 | All seven governed target types | Exact reviewed identifier/alias/manual match and registered rule | DecideCommunicationLink |
| COMM_INVENTORY_SUBMISSION_V1 / 1 | LLD-07 | SPARE_REQUEST | Draft fingerprint and known/unknown submission time | AcceptSpareRequestSubmission |
| COMM_INVENTORY_WAREHOUSE_RECEIPT_V1 / 1 | LLD-07 | FAULT_TAG with exact membership id/revision | Known/unknown receipt time | RecordWarehouseReceipt |
| COMM_INVENTORY_WAREHOUSE_DECISION_V1 / 1 | LLD-07 | FAULT_TAG with exact membership id/revision | accepted/rejected, bounded reason, known/unknown time | RecordWarehouseFinalDecision |

The three Inventory `facts` objects reuse the exact accepted `INVENTORY_PROPOSAL_TARGET_V1` variants in `spec/lld/inventory/schema/proposals-projections.json#proposal_target_payload_contract_v1`. New wrapper ids and the parent-tag/membership binding are proposed here. Identity, match-rule string bounds and the outer 4096-byte/depth-4/item-32 representation budget are explicit accepted additions; owner identity validators still control which values mean a real identity.

Unknown fields, versions and owner/target combinations reject. Schema validity does not establish identity, eligible lifecycle state or source truth. All field types and nulls remain exact; a boolean cannot satisfy an integer field. All payloads pass Foundation strict canonical JSON and typed validation.

A rejected warehouse decision requires an already-normalized nonempty reason with no NUL/CR/LF and at most 384 UTF-8 bytes. JSON Schema length is only a character guard; the UTF-8 byte limit is enforced separately by the owner validator.

## Evidence and fingerprint authority

The existing `CommunicationProposalEvidenceV1` envelope remains unchanged. It carries proposal id/revision, canonical Communication id, source-scope id, target type/id/revision, contract id/version, typed payload, source fingerprint and proposal fingerprint.

Accepted `SOMA_COMM_PROPOSAL_SOURCE_V1` source fingerprint inputs: canonical Communication id; source-scope id and current revision; identity state and canonicalization version; selected immutable identity-evidence digest; content revision; canonical direction and known/unknown chronology. Hash Foundation canonical UTF-8 JSON using lowercase SHA-256. Hashes are comparison evidence, never authenticity proof.

Accepted `SOMA_COMM_PROPOSAL_V1` proposal fingerprint inputs: source fingerprint; target type/id/revision; contract id/version; the exact canonical typed payload. No recording/current time, proposal id, parser handle or filesystem location is added. The current source-scope revision is freshness metadata; a reviewed relocation can therefore stale a pending proposal without changing canonical message identity.

The provider must revalidate these inputs inside the caller writer UoW. Changed source/content/identity/target/membership authority returns STALE; unavailable provider authority returns INDETERMINATE and blocks acceptance. No stale proposal is rewritten into a newly accepted meaning.

## Extraction and review boundary

Accepted warehouse clarification (2026-09-30): the identified thread contains
an earlier statement that items are in the warehouse and a later `CLOSED`
status. `CLOSED` does **not** establish acceptance or rejection: messy threads
can include items that were not accepted. Final disposition remains an explicit
operator decision under the existing Inventory confirmation contract. Do not
create an actionable accepted/rejected proposal from `CLOSED` alone.

`RTYYMMDDxx` identifies a **return batch** and provides optional warehouse
context alongside SR7, C10 and PartNumber/Bomcode evidence. It is not a new
operational identity, a physical-unit identifier, item-level receipt proof or
business chronology. A missing RT reference produces the bounded review warning
`WAREHOUSE_RETURN_BATCH_REFERENCE_MISSING`; it does not block an otherwise valid
operator-recorded item receipt. A present batch reference does not transfer
receipt or acceptance to every mentioned item. Exact Fault Tag membership,
physical unit and current owner eligibility remain mandatory. Descriptive
PartNumber/Bomcode similarity cannot substitute for those owner validations.

The owner accepted exact SR7+C10 resolution through the existing Inventory
identity provider's read-only
`resolve_warehouse_receipt_target(reader, exact_sr7, exact_c10)` method. It
returns null for an unresolved pair, membership or selected physical unit;
these cases require manual item selection. A resolved result is the closed
`WarehouseReceiptTargetV1` object `{fault_tag_id, fault_tag_revision,
membership_id, membership_revision}`, using existing immutable IDs and current
positive owner revisions. Exact registered former aliases remain governed
owner identity; every resulting domain-fact proposal still requires review.
Resolution reuses Inventory's receipt-eligibility predicate and changes no
lifecycle state. Acceptance revalidates membership, unit and obligation in the
owning writer UnitOfWork. This method supplies no receipt truth from mere
identifier presence or an optional batch number.

Local sample inspection (implementation evidence, not additional product authority):
the owner supplied private `.eml` examples under root `tmp/`. They were inspected
in memory; no source filename, identifier, address, body, attachment or private
fixture is copied into the repository. Exact governed-identifier boundary checks
passed on the samples. The examples contain forwarded delivery/collection
threads and quoted receipt/approval wording. The owner identified the warehouse
receipt passage and clarified the optional batch reference and unresolved final
disposition above. Replacement dispatch, pickup coordination and customer
approval cannot simply be relabeled as those existing Inventory events. No
natural-language lifecycle extractor has been enabled from these samples.

Root `tmp/` is excluded from Git staging, Git archives and source distributions.
Local commit/push hooks call `tools/check_local_only.py`, which checks the index
and publication history without reading or printing sample content or filenames.
The implementation CI invokes the same guard with complete checkout history.
Tests of forced staging and removed-file history use synthetic isolated Git
repositories, never the private samples. These safeguards prevent accidental
publication through the checked paths; deliberate hook bypass is not an access
control mechanism.

The registry is a payload/ownership contract, not permission to interpret arbitrary prose as lifecycle truth. Exact governed identifier matching may create a link proposal under the accepted matching algorithm. Submission requires observed canonical SENT evidence; neither MSG generation/export nor an unknown direction proves sending.

This candidate does not add an automatic natural-language lifecycle extractor. Domain-fact creation needs complete typed facts bound to current owner targets and evidence. An unresolved member, time, decision or draft mapping is a review condition and cannot become an actionable owner proposal through guessing. Unknown effective times remain null where the owning payload permits them.

A single Communication may produce separate proposals for multiple exact memberships. Each Communications proposal addresses one membership under its governing tag, which fits the closed Communications target enum. The Inventory owner verifies membership-to-tag identity, revision, selected physical unit and obligation. Existing Inventory batch/proposal acceptance remains all-target atomic; this candidate adds no partial acceptance of an existing Inventory proposal.

## Atomic acceptance and disposition

The owning-domain command resolves exact replay first, then validates Communication evidence plus all owner revisions/fingerprints in one outer writer UoW. After inserting its one receipt, it performs its owned mutation and invokes `CommunicationProposalDispositionParticipant.record_accepted` in that same UoW. Disposition closes only the exact proposal hold, reevaluates current link/hold retention authority, and appends required history/audit. The owner persists the complete immutable result and commits once.

Do not call a public owning command from inside another authoritative command boundary. Existing Inventory reducer/participant operations must be reused or minimally extracted so that they accept the caller UoW/receipt. No separately committed Inventory proposal or Communication disposition is a substitute for atomicity.

Warehouse final acceptance still requires fresh explicit operator confirmation. An accepted domain-fact proposal never creates a Communication link unless a separately defined link contract says so. REJECT closes its proposal hold; DEFER retains it. Repeated semantic decisions follow the exact existing no-change contract.

## Registry scope

The pinned Inventory owner expressly supports these three proposal mappings and makes other kinds fail closed until a new exact mapping is defined. Reuse that boundary. Tickets and Tasks/Objectives support all applicable Communication link proposals; this candidate creates no new terminal, outcome, planning, customer or identity mutation contract for those owners. Their evidence/disposition seams remain available for a separately accepted future owner contract. New facts cannot be made authoritative merely by adding a string to the registry.

## Required implementation proof

- Exact known id/version/target/payload validation; unknown/extra fields, booleans-as-integers, malformed UUIDs/fingerprints and oversize/deep JSON reject.
- Source/Communication/target/membership revision or fingerprint drift blocks before receipt/mutation.
- SENT submission evidence excludes received/unknown messages and MSG artifacts.
- Membership parent, unit, obligation and explicit final-decision confirmation guards remain owner authority.
- Owner mutation + disposition + hold + retention + audit + exact replay result roll back together on failure at every boundary.
- Exact replay after later state change invokes no provider/current-state mutation.
- One message/multiple independent proposal targets preserve existing all-target Inventory acceptance.
- Pending/deferred holds prevent purge; rejection/acceptance removes only its own hold and safely evaluates grace.
- Payloads and durable job/audit/diagnostic evidence contain no reconstructed message content.
- Runtime authority captures the pinned leaves plus these accepted owner clarifications; upstream design normalization must preserve this accepted scope.

## Sources inspected

- `spec/lld/communications/_index.json`, `interfaces.json`, `interfaces/cross-packet-v2.json`, `types/common.json`, `types/message.json`, `types/proposal.json`, `schema/links-proposals.json`, `commands/v2/decide-link.json`, `commands/v2/reject-proposal.json`, `tests/traceability/cross-packet.json`.
- `docs/COMMUNICATIONS_CONTRACT.md` sections 7, 8, 11 and 15.
- `spec/lld/inventory/schema/proposals-projections.json` and `commands/{requests-rma,fault-tags,consequences-logistics}.json`.
- Current `src/soma/inventory/domain/proposals.py` and `services/corrections_bulk.py` confirm existing behavior but are not specification authority.
