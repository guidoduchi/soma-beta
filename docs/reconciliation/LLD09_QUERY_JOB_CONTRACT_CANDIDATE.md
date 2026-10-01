# LLD-09 query and durable-scope contract gaps

Status: ACCEPTED_OWNER_CLARIFICATION (2026-09-30).

The owner also accepted nullable `preview_fingerprint` on
`communication_job_scopes` in migration 16. Deep Scan requires the exact
confirmed fingerprint, and reviewed backfill records its reviewed fingerprint.
The durable job payload and checkpoint retain no deliberate-action proof or
session secret. Recovery preserves the confirmed fingerprint with the scope.

Backfill `target_identity_ids` are existing target UUIDs. Each UUID must resolve
to exactly one target type and selects all currently exported identifiers and
aliases for that target. Missing or ambiguous target references fail closed.

Provider ranges use the accepted pure adapter method
`compare_checkpoints(lower, upper) -> BEFORE|EQUAL|AFTER|INDETERMINATE`.
Only the adapter's own checkpoint format can establish ordering; indeterminate
ranges are rejected without opening source content or guessing token order.

Mail jobs also capture immutable `execution_config_json` in migration 16,
with the closed fields `{adapter_family, adapter_version, overlap_messages,
batch_messages}`. Settings changes affect later jobs. Source configuration
revision changes still invalidate current work. Housekeeping has no mail
execution configuration.

The owner accepted all three proposed resolutions in this implementation session:
the four closed DTO definitions, bounded active-link detail with its companion
query, and the installation-wide housekeeping scope.

Design pin: `9a0e891127a771251afccca1a281b7ef7dde9e5f`.

## Closed query DTOs

The pinned `types/queries.json` and `types/message.json` reference these objects
without defining their fields. Proposed definitions expose existing owner state:

- `CommunicationListItemV1`: `communication_id`, `source_scope_id`,
  `identity_state`, `chronology`, `direction`, `content_state`, `subject`,
  `retention_state`. Subject is nullable and unavailable for PURGED content.
- `AttachmentSummaryV1`: `communication_attachment_id`, `ordinal`, `filename`,
  `mime_type`, `size_bytes`, `sha256`. No content, stream handle or external path.
- `CommunicationLinkSummaryV1`: `communication_link_id`, `target_type`,
  `target_id`, `target_revision_at_link`, `revision`, `origin`, `direction`,
  `effective_chronology`, `matched_identity_kind`, `matched_identity_value`,
  `confidence_basis`, `match_rule_id`, `match_rule_version`, `state`.
- `CommunicationJobSummaryV1`: `job_id`, `source_scope_id`, `job_kind`, `state`,
  `phase`, `counters`, `percentage`, `created_at_utc`, `updated_at_utc`,
  `started_at_utc`, `ended_at_utc`, `attempt_count`, `next_attempt_at_utc`,
  `cancellation_requested`, `diagnostic_code`. Nullable timestamps remain null
  until independently recorded. Percentage is null without a positive known
  estimate. Diagnostic code is null or the Foundation stable error code.

IDs, target/direction/content/identity/retention enums, chronology, counters and
match metadata reuse their existing contracts. Job state is Foundation-owned;
phase is nullable until the handler has recorded a stable phase code. No job
projection invents a completed percentage, start/end time or mail content.

## Bounded active-link detail

`GetCommunication` requires all active links with no pagination. A Communication
can link to arbitrarily many governed targets; the packet sets no link maximum.
This conflicts with the repository rule against unbounded collection reads.

Proposed resolution: `CommunicationDetailV1.active_links` returns the first 100
links and adds `active_links_next_cursor: CURSOR_V1|null`. A separate read-only
`ListCommunicationLinks` query accepts `communication_id`, `state` (ACTIVE,
CLOSED or null), `cursor` and `limit` (default 50, maximum 100), and returns
`{items: array[CommunicationLinkSummaryV1], next_cursor}`. Ordering is the full
tuple `(target_type, target_id, communication_link_id)` ascending. Cursor identity
binds the exact Communication and state filter. Supporting indexes include
`(communication_id,state,target_type,target_id,communication_link_id)` and
`(communication_id,target_type,target_id,communication_link_id)`.

The companion query avoids repeatedly returning the body when paging links. It
introduces no link cardinality business limit and preserves sibling links/history.

## Installation-wide housekeeping scope

`CommunicationJobScopeV1` requires a nonnull source UUID and positive source
configuration revision for every job. Its owning schema permits a nullable source,
and the housekeeping registry explicitly defines one installation-wide job which
must run even when no source is configured or fetching is disabled.

Proposed resolution: only ORPHAN_HOUSEKEEPING uses `source_scope_id=null`,
`config_revision=null`, empty `folder_keys`/`target_identity_ids`, and null bounds.
All other kinds retain a real source UUID and positive source revision. No dummy
mailbox UUID or invented configuration revision is recorded.

## Link chronology provenance

Accepted owner clarification (2026-09-30): add
`effective_chronology_source_kind` to migration 16. Link creation preserves the
canonical message's independently supported chronology and source kind. Target
corrections cannot invent a timestamp or chronology provenance. Unknown chronology
retains its null instant and UNKNOWN source kind.

## Literal search

Accepted owner clarification (2026-09-30): ListCommunications treats search as
literal whitespace-delimited words combined with AND. Whitespace is trimmed and
collapsed. SQLite FTS5 unicode61 owns tokenization, case folding and diacritic
handling for both the retained subject/body projection and the query. Every word
is quoted with embedded quotes escaped; operators and punctuation never become
executable FTS query syntax. Empty normalized search applies no search filter.

## Retry policy

Accepted owner clarification (2026-09-30): reconciliation retries only
SOURCE_LOCKED and IO_TRANSIENT; orphan housekeeping retries only PERSISTENCE_BUSY.
Each job's `max_attempts` counts all executions, including the first. Other errors
terminate the job. Existing per-job backoff arrays remain unchanged; no retry is
scheduled after the final allowed attempt.

## Accepted owner clarification: frozen chronology provenance

Accepted by the owner in this session. The pinned
`schema/orphan-purge.json#communication_terminal_summaries` stores only
`last_interaction_known` and `last_interaction_utc`, while
`types/message.json#CommunicationEntitySummaryV1` requires a complete
`ChronologyV1` and terminal summaries must remain frozen after direct links close.
The accepted clarification adds `last_interaction_source_kind` to migration 16 and
preserves the selected recorded message chronology source. Unknown chronology
retains a null instant and UNKNOWN source. No provenance may be inferred.

## Accepted recipient bounds and local MSG origin scope

The pinned
`types/common.json#GenerateMsgDraftRequestV1` calls `origin_domain` a closed string
without an enum, and gives no recipient-count, address-syntax/length or display-name
bounds. The owner accepted 1–2,000
TO/CC/BCC recipients, valid mailbox addresses of 1–320 characters, and nullable
display names of at most 512 characters. Validated address bytes and source order
within each role are preserved. These definitions grant no sending authority.

The owner subsequently clarified that local MSG generation currently applies to
completed Objectives and new Spare Requests, and explicitly required preserving
previously accepted behavior. The existing seven-family incoming identity,
matching and linking scope remains unchanged.

Local draft origins use the owning packet IDs LLD-05/OBJECTIVE and
LLD-07/SPARE_REQUEST. Read-only owner checks supply the origin-context validity
required by GenerateMsgDraft: an Objective's current accepted completed review
and its ReviewObjective command, or a current soma_draft Spare Request and its
CreateSpareRequestDraft command. The existing owner commands, events and reducers
remain authoritative. Communications revalidates the owner's evidence fingerprint
inside its writer UoW after publication; it never completes or submits an owner
entity. Template and authored recipient/content snapshots remain explicit input.

## Accepted current retention-event identity

The owner accepted `resulting_retention_revision` on
`communication_retention_events` in migration 16, unique for each
`(communication_id, resulting_retention_revision)`. Housekeeping joins the
retention row's exact current revision to its event and reason. UTC-second ties
and random UUID ordering cannot substitute for transition identity.

## Accepted Foundation job metadata projection

The owner accepted a read-only Foundation-owned `DurableJobMetadataV1`
projection for joining Communications scopes/counters. It exposes job identity,
registered type/version, durable state, recorded creation/update/start/end times,
attempt count, retry time, recorded cancellation and a safe diagnostic code.
Payloads, checkpoints, run/claim identities and other claim secrets stay private.
The consumer pages by the complete creation-time/job-ID key with a maximum of
100 items. Phase remains null without recorded Communications phase evidence.

## Accepted entity-summary coverage and chronology

The owner accepted COMPLETE only with recorded scan coverage for the target's
current exported identifiers and aliases, from its independently supported
eligibility boundary (or a reviewed full scan), across every configured selected
folder. Unproved boundary, range or identity gives UNKNOWN; explicit incomplete
coverage gives PARTIAL. UNKNOWN takes precedence over PARTIAL, then COMPLETE.
Forward high-water alone is not proof of historical target coverage.

At the latest known interaction time, tied RECEIVED and SENT messages yield
MIXED; otherwise uncertain direction yields UNKNOWN; otherwise return the single
known direction. With no known interaction time, direction remains UNKNOWN.
Chronology provenance comes from the message selected by the existing complete
timestamp/Communication-ID ordering.

## Accepted frozen-summary sequence

The owner accepted positive per-target `summary_revision` in migration 16,
unique for `(target_type, target_id, summary_revision)`. The freeze allocates it
in the caller's UnitOfWork. Queries select the highest sequence; same-second
timestamps and random UUIDs cannot determine which freeze was accepted last.

The owner also accepted the previously undefined
`FrozenTerminalCommunicationSummaryV1`: `terminal_summary_id`, `target_type`,
`target_id`, `governing_event_id`, `summary_revision`, `received_count`,
`sent_count`, `unknown_count`, `last_interaction: ChronologyV1`, `last_direction`,
`coverage_state`, `unlink_utc`, and `summary_fingerprint`. This is a closed,
minimized projection of the frozen record and contains no reconstructable content.

Target-scoped read iterators reuse the owners' existing identity exports and
indexed target predicates; summaries do not scan the complete owner registry
for each entity. Immutable matching-run evidence retains the identities actually
searched by recorded scans. No source content is opened by these queries.

## Accepted SR terminal owner handoff

The accepted status-observation UUID is the SR governing event. Its local
`recorded_at_utc` starts orphan grace; provider source chronology may be old or
unknown and is never substituted. RFC grace likewise starts at accepted local
cascade execution time. The existing SR owner passes the outer command's
`{command_id, actor_kind, actor_id}` and exports exact read-only status-event
evidence, including current-target revision validation and acceptance time.

The owner accepted the previously undefined bounded `CommunicationImpact`:
`target_type`, `target_id`, `target_revision`, `summary`, `closed_link_count`,
`orphaned_communication_count`, and `impact_fingerprint`. Apply exports only the
immutable frozen-summary reference. Complete link and retention history stays
relational under the same caller command rather than entering an unbounded
owner result array.

The owner accepted `communications.terminal_links.restored@1` with bounded
payload `{target_type, target_id, governing_event_id, restored_link_count,
cancelled_grace_count, reconstruction_required_count}`. RESTORED link events and
cancelled-grace events remain immutable same-UoW evidence. No sending or owner
lifecycle mutation is inferred from Communications evidence.

For post-purge reversal the owner accepted atomic durable reconstruction enqueue
inside the caller UoW, with work becoming runnable only after commit. The worker
must revalidate source readability. Missing readable configuration or unproved
message chronology cannot authorize an inferred range or an implicit full scan;
the minimized frozen summary and incomplete-coverage warning survive.

## Accepted RFC captured-membership projection

The owner accepted read-only LLD-03 `RfcTerminalCascadeRfcMembersV1`, exposing
only `proposal_id`, `proposal_revision`, `rfc_id`, `captured_rfc_revision`, and
`captured_role`. Communications joins this published projection to its own
indexed links for bounded impact pages. No unbounded SQL parameter list or
Ticket-private table access is permitted. Existing LLD-03 capture, freshness,
deliberate-action and execution authority remains with LLD-03.

The owner accepted the executed cascade proposal UUID as each RFC frozen
summary's `governing_event_id`. `unlink_utc` is the accepted local execution
time. The captured scope and executed-command reference remain LLD-03's
immutable governing evidence.

The owner accepted optional `accepted_execution_utc` on the existing
`RfcTerminalCascadeExecutionCommandContext`. LLD-03 always supplies its exact
recorded execution time after deliberate confirmation and before participant
apply. Communications requires this field for RFC apply; no provider chronology
or second clock read substitutes for it. Existing unrelated context callers
remain compatible, and no proof/session secret enters the handoff.

## Accepted conflicting provider content rule

When exact provider identity reuses an existing canonical Communication but
newly observed retained-content evidence conflicts, preserve the existing
retained content and require reviewed identity reconciliation under a
`COLLISION_REVIEW` protection hold. Do not silently overwrite content or replace
the canonical ID. Exact overlap replays remain unchanged.

The owner accepted transient `independently_distinct_source_item: boolean =
false`. True requires positive adapter evidence within the captured source
inspection. Folder moves, provider ordering changes and differing checkpoint
tokens alone are insufficient. This witness affects fallback reuse eligibility;
it is not a new canonical identity field or persistent unmatched-source key.

The owner accepted `communications.identity.review_required@1` with closed
payload `{reason_code, identity_state, protection_hold_id}` and canonical
Communication/hold references. Detection does not claim a reconciliation or
content replacement, and the audit never contains source content or raw keys.

## Accepted reviewed identity operations

The owner accepted dedicated identity preview/decision contracts for
`KEEP_SEPARATE`, `ATTACH_PROVIDER_IDENTITY` and
`CONSOLIDATE_LINKS_AND_ALIASES`. Review binds candidate UUIDs and revisions,
source revision, and an exact preview fingerprint. Canonical IDs and history
survive; conflicting provider content keeps the existing retained snapshot.
The ordinary link-correction command does not acquire canonical identity
mutation authority.

The owner accepted nullable `alias_evidence_bytes` in migration 16, required
for provider aliases. Alias rows are append-only, and provider keys survive
purge as minimized identity evidence. Lookup compares exact kind and bytes
after a digest candidate match; a digest never authorizes alias reuse.

The owner accepted `KEEP_RETAINED_CONTENT` for a single canonical ID's provider
content conflict and separate bounded review evidence containing the canonical
fallback object (maximum 1 MiB), tied to its hold and immutable decision.
Exact acknowledged objects are unchanged on overlap; different evidence
requires review again. Purge deletes the reconstructable object and retains
minimized identity/decision metadata. A declined variant cannot supply new
automatic links or content-derived facts for the retained snapshot.

The closed `CommunicationIdentityReviewRequestV1` carries `source_scope_id`,
`source_scope_revision`, `decision`, `retained_communication_id`,
`retained_content_revision`, `other_communication_id`, `other_content_revision`
and `review_evidence_id`. The single-candidate content decision requires an
evidence UUID and null other candidate/revision. The three pairwise decisions
require two distinct canonical UUIDs with positive revisions and null evidence
UUID. Execute adds `command_id` and `preview_fingerprint`. The bounded result
is `{status: APPLIED|NO_CHANGE, identity_review_event_id}`; complete immutable
consequence references remain in the owned relational result rows.

Content acknowledgement binds the current source revision, retained snapshot,
exact captured evidence, governed hold, whether another protected dependency
remains and current grace setting. Indexed existence checks bind this complete
retention impact without enumerating unrelated siblings. The captured source revision remains immutable
provenance; keeping existing content under a current configuration does not
accept incoming content or create associations. It closes only that variant's
hold and reevaluates retention. It does not increment content revision. An
already acknowledged evidence row for the unchanged retained snapshot yields
`NO_CHANGE` and the original event reference, without mutation or new audit.
Eligible receipt replay returns its original result even after purge; fresh
review or restoration cannot be authorized from purged reconstructable evidence.

The owner accepted (2026-09-30) requiring identical complete fallback evidence
and two retained snapshots for `ATTACH_PROVIDER_IDENTITY` and
`CONSOLIDATE_LINKS_AND_ALIASES`. Digest equality alone is insufficient; differing,
missing or purged evidence fails closed. `KEEP_SEPARATE` does not transfer
identity or links and does not require content equality.

Pairwise execution is one reviewed candidate group in an LLD-01 durable
reconciliation job. Its closed review request and execution command UUID are
stored in an immutable Communications-owned row keyed by job UUID. The existing
job payload remains `CommunicationJobScopeV1`, with no candidate content, raw
provider keys or repurposed operational `target_identity_ids`. Enqueue returns
the bounded job reference; execution records the immutable review event. Each
candidate group applies atomically, streams collections in indexed pages and
commits the review result, audit, checkpoint, counters and job completion together.

Alias consolidation preserves all old alias rows. An append-only ownership
assignment references the newly attached exact provider alias and governing
review event, with a positive per-source assignment revision. Exact provider
lookup uses the highest recorded assignment revision for that exact key; it
does not choose between tied seconds or random UUIDs. A reviewed group cannot
take a key currently owned outside its two captured candidates. Historical
aliases and canonical IDs survive reassignment and purge. Non-provider aliases
remain historical evidence and do not acquire provider identity authority.

Only generic collision-review holds on the two candidates can close in a
pairwise decision. Content-variant, proposal, correction and export holds stay
with their existing owners. Consolidation closes donor active links and creates
missing reviewed links on the selected canonical ID, preserving original link
chronology and direction and checking each target's current owner revision and
reassociation eligibility. Already-active selected-target pairs keep their
existing link. Proposals and retained snapshots do not move or change.

The owner accepted (2026-09-30) `CancelCommunicationJob {command_id, job_id}`,
an immutable cancellation event and `communications.job.cancelled@1` with the
closed payload `{job_kind, prior_state, resulting_state}`. The command validates
the Communications-owned scope against Foundation's published metadata and calls
Foundation cancellation in its outer UoW. Cancellation, event, audit and exact
receipt result commit together. The event records Foundation's exact transition
time and whether a running claim was revoked, including its attempt ordinal.
Previously committed content, coverage, checkpoints and counters survive.
Source readability, processing settings and changed source revisions do not
prevent cancellation. Already cancelled, completed or failed jobs return
`NO_CHANGE`, their current states and a null cancellation-event reference,
without creating another event or audit. Receipt replay returns the original
immutable response. The bounded result is `{status, job_id, prior_state,
resulting_state, cancellation_event_id}`. The browser mutation route is
`POST /api/v1/communications/jobs/{job_id}/cancel`; transport must compare the
path UUID with the request UUID.
