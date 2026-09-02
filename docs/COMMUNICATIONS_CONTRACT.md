# SOMA Beta Communications Contract

Status: **Foundation review v0.1**  
Target: **SOMA Beta 1.0.0**  
Authority: accepted `BETA-REQ-0111` through `BETA-REQ-0122` and decisions `D-085` through `D-096`.

## 1. Purpose and boundary

This contract governs offline PST/OST processing, message identity, matching, operational links, reviewed proposals, coverage, scheduling, terminal unlinking, orphan grace and content purge, MSG draft identity, and communication summaries.

SOMA Beta 1.0 does not connect to SMTP, Exchange, Microsoft Graph, IMAP, or another mail service. It never sends, receives, deletes, moves, marks, or edits an item in an external mail store. PST/OST access is read-only. MSG output is an operator-managed draft artifact.

The following remain separate authoritative concerns:

- domain entities and their accepted lifecycle events;
- Communication Source Scopes and processing coverage;
- canonical retained communications;
- independent communication-to-entity links;
- reviewed communication-derived proposals and decisions;
- locally generated MSG drafts;
- background processing jobs; and
- terminal unlink, grace, purge, and summary evidence.

No component may create implicit cross-writes between these concerns.

## 2. Communication Source Scope

A **Communication Source Scope** is the stable local boundary for one configured account or mailbox population. It owns:

- immutable local identity;
- operator-visible name;
- provider/account/mailbox identity when available;
- adapter family and version;
- selected folders and role mapping such as Inbox and Sent;
- current source-location reference;
- health and capability state;
- initial-boundary and coverage records;
- durable high-water marks and overlap policy; and
- job history and redacted diagnostics.

Source location is mutable configuration, not scope identity. Moving, renaming, or remounting the same store must not silently create a second account scope or change message uniqueness. A genuinely different account/mailbox requires a distinct scope even when its file path or filename resembles another source.

A configured store that is locked, missing, corrupt, unsupported, or partially parseable produces a bounded source-health result. SOMA does not modify the file and does not advance coverage beyond durably processed data.

## 3. Eligibility gate and trackable registry

Automatic or operator-triggered fetch-and-match work is ineligible while the installation has no trackable operational entity. A Network Element, Device Reference, Site, Room, Rack, Dispatch Location, Contact, Customer Organization, or other descriptive/master-data record alone does not satisfy the gate.

The versioned trackable registry includes:

| Entity context | Matching identity |
|---|---|
| Service Request / Trouble Ticket | accepted official identifier and retained aliases |
| Spare Request | internal/operator-visible request identifier and supported external identity |
| RMA return obligation | current C10 and retained aliases |
| Request for Change | accepted official RFC identifier and retained aliases |
| WFM Task | accepted WFM identifier and governed parent context |
| Objective | stable Objective identity and explicitly exported communication reference |
| Fault Tag | immutable operator-visible tracking identifier and governed aliases |

A local Task without an accepted external communication identifier is not automatically trackable. BOM, serial number, hostname, Device name, person name, filename, free prose, or email subject alone does not become a universal operational identity.

Terminal SR/RFC identities remain historically resolvable for suppression, correction, and coverage explanation. Once the owning terminal transition removes the direct link, they do not remain active targets that silently recreate that link. Reassociation requires an accepted terminal reversal, explicit reviewed correction, or another governed surviving entity context.

## 4. Initial boundary, incremental coverage, and high-water marks

For each eligible source scope, initial processing begins no earlier than the earliest independently accepted relevant creation boundary among current trackable targets:

- Service Request report/external creation time;
- RFC external creation time;
- Spare Request registration/submission boundary;
- RMA recognition boundary;
- WFM external creation time;
- Objective communication-eligibility boundary; or
- Fault Tag creation/submission boundary.

An unknown relevant time remains unknown. SOMA must not substitute import, discovery, indexing, or current-clock time. When the earliest boundary is unknown, the operator receives a coverage warning and may authorize a bounded targeted backfill or Deep Scan; SOMA does not silently claim complete historical coverage.

Each completed processing transaction advances a durable per-scope high-water mark only through the last safely committed provider position/time. Later jobs resume with a bounded overlap window. Replay within the overlap is idempotent and uses canonical identity. Failure, cancellation, or restart preserves the last committed mark and exposes incomplete coverage.

Coverage is an explicit projection over source scope, folders, intervals/provider positions, adapter version, job outcome, and warnings. Message counts never imply complete coverage by themselves.

## 5. Targeted backfill and Deep Scan

Adding or accepting an operational entity whose relevant creation boundary precedes current coverage may enqueue a bounded **targeted backfill**. Its scope is restricted to:

- the affected Communication Source Scope and folders;
- the affected entity identities and aliases;
- a declared time/provider-position window; and
- configured resource limits.

Targeted backfill does not reset unrelated high-water marks or reprocess the entire store.

**Deep Scan** is a separate explicit operator action. Before execution SOMA shows the selected scope/folders, time or position range, expected resource impact when estimable, existing coverage, and records that may be reviewed. Deep Scan requires confirmation, runs as a background job, preserves normal identity/idempotency rules, and never implies that an unreadable interval is complete.

## 6. Message identity, canonicalization, and participants

A retained communication has an immutable local identity. Uniqueness is scoped to the Communication Source Scope, never to a filesystem path or a provider identifier alone.

The adapter requests and preserves a provider-stable origin identifier when available. The LLD shall define its exact source field, normalization, immutability assumptions, and provider-version behavior.

When no stable origin identifier exists, the adapter uses an explicit versioned fallback canonicalization contract. The fallback may use bounded normalized header/body properties, but it shall:

- record the canonicalization version and contributing facts;
- avoid mutable local file path as identity;
- keep distinct account scopes distinct;
- detect ambiguous/colliding candidates;
- preserve both messages pending review rather than silently merge them; and
- allow a later stable identifier to reconcile through an audited alias/link without rewriting identity or evidence.

Sender, To, Cc, Bcc, reply-to, and other supported participants are typed structured collections with original normalized address and display evidence. Recipients are not stored as an invalid scalar or delimiter-dependent string. A versioned JSON representation may be used at a persistence/API boundary only when schema validation and typed query behavior remain defined.

Direction is derived from the source scope, folder role, and participants. Unknown or conflicting direction remains explicit.

## 7. Matched-only persistence and independent links

Parsing may inspect unmatched messages transiently within the protected local process. Only a communication matched to at least one governed operational entity or retained as part of an explicit reviewed collision/correction case persists as operational content.

One canonical retained communication may link to multiple Service Requests, Spare Requests, RMAs, RFCs, WFM Tasks, Objectives, or Fault Tags. Each link has an immutable identity and records:

- canonical communication and target identities;
- matched identifier or alias;
- matching rule/version and confidence;
- direction and effective chronology when independently known;
- automatic, reviewed, or manual origin;
- creation/removal/correction chronology; and
- proposal relationships when applicable.

A link never duplicates the message body or becomes ownership of the communication. Removing one link does not remove another. If rejection, correction, or a terminal transition removes the final protected link, section 8 governs orphan grace and any later content purge; matched-only persistence does not bypass that lifecycle.

Communication matching may create an idempotent reviewed proposal under the owning domain contract. A proposal preserves source communication, proposed targets/facts, rule/version, confidence, chronology, acceptance/rejection, operator, reason, and later correction. No proposal mutates a Service Request, Spare Request, RMA, Fault Tag, logistics event, warehouse decision, or another domain until accepted through that domain's command.

## 8. Terminal unlink, orphan grace, and purge

Accepted terminal Service Request or RFC state removes that entity's direct communication links through an audited domain event. It does not remove links to other protected operational entities, erase the terminal entity, or treat the communication body as part of the terminal record.

After link removal, a retained communication with no remaining operational link, unresolved reviewed proposal, correction dependency, collision review, protected export dependency, or other protected hold enters **Orphaned — Pending Purge**.

The orphan grace is:

- installation-level;
- configurable only to a positive duration under the LLD limits;
- seven exact elapsed days by default;
- measured from the accepted event that removed the last protected dependency; and
- visible with due chronology and reason in the Communication housekeeping surface.

Any restored or newly accepted protected dependency cancels pending purge immediately and preserves the former pending interval as audit history.

At the due time, housekeeping opens a transaction and revalidates every protected dependency. If any exists, purge is cancelled. Otherwise SOMA purges reconstructable retained message content and content-derived search material. It preserves a non-reconstructable purge record containing canonical local identity, source-scope identity, bounded provider/fallback identity evidence, prior link targets and removal chronology, due/decision/actor chronology, purge reason and outcome, and the frozen terminal summaries required by section 12. The purge record must not preserve the purged body, full attachment content, or an equivalent searchable copy.

Purge does not modify or delete an external PST/OST store, operator-exported MSG file, portable export already produced, or existing protected backup. Backup rotation follows the Backup Contract and does not reach backward into an existing backup to erase content.

If terminal state is reversed during grace, the governed relationship is restored and pending purge is cancelled. If reversal occurs after purge, SOMA may perform a bounded targeted backfill when the configured source remains available. If reconstruction is unavailable or incomplete, the workbench keeps the frozen summary and displays a coverage warning; it never fabricates the body.

This is a narrow Beta 1.0 communication-content minimization exception. It does not authorize purge of Service Requests, RFCs, Inventory entities, Tasks, Objectives, Infrastructure records, audit decisions, or other operational domain history.

## 9. Communication Processing schedule

Communication Processing is one combined local fetch-and-match pipeline. Fetch and matching do not have independent schedules.

The default interval is sixty minutes. The operator may select another positive whole-minute interval within LLD resource limits or disable scheduled processing. The UI exposes current configuration, last outcome, next eligible run, coverage/warnings, and **Check now**.

For each source scope:

- at most one processing run executes at a time;
- overlapping timer ticks coalesce;
- at most one catch-up request remains pending;
- Check now never creates unbounded parallel work;
- a durable run records the configuration snapshot it used; and
- housekeeping for orphan due times remains a separate idempotent scheduler because it must not depend on mail fetching.

Disabling scheduled processing does not delete source configuration, coverage, high-water marks, retained communications, links, or pending housekeeping.

## 10. Background jobs, cancellation, retry, and diagnostics

Initial scans, incremental processing, targeted backfills, Deep Scans, large match recalculations, and reconstructive work run as durable background jobs.

Every job exposes a stable identity, source scope, job kind, queued/running/cancelling/succeeded/failed/partial state, current phase, bounded processed/estimated counts when knowable, progress that does not fabricate precision, start/update/end chronology, cancellation availability, retry state, and redacted diagnostic code.

Cancellation is cooperative. A completed transaction remains committed; incomplete work rolls back to its safe checkpoint. The job records partial coverage and never advances a high-water mark past committed work.

Retries are bounded by count and backoff, distinguish transient from permanent errors, avoid tight loops, and remain idempotent. Restart recovery resumes from a safe checkpoint or records a stable partial/failure outcome. Diagnostics exclude message bodies, attachment content, credentials, recovery secrets, full customer datasets, and other unnecessary personal or operational content.

## 11. MSG draft identity and workflow independence

A generated MSG draft has an immutable local draft identity, originating domain command, intended recipients and recipient snapshot, subject/body template version, generated chronology, and exported location evidence when available. Saving, regenerating, or exporting a draft does not prove that it was sent and does not create a retained sent communication.

If a later PST/OST scan discovers the sent item, normal canonical message identity and reviewed matching apply. The draft may be linked as provenance without becoming the sent message's identity. Manual confirmation remains valid where the owning domain allows it and does not require an upload.

These workflows are independent and perform no implicit cross-write:

- official Advanced Search/RFC/WFM import and synchronization;
- Communication Processing and matching;
- communication-derived proposal acceptance/rejection;
- local MSG draft generation/persistence; and
- orphan housekeeping and purge.

An explicit accepted cross-domain command may coordinate them transactionally only where this contract and the owning domain contract define the effects.

## 12. Workbench summaries and terminal evidence

Active Service Request, Spare Request, and RFC communication panels distinguish:

- received count;
- sent count;
- mixed/received/sent/unknown direction;
- most recent independently known interaction chronology;
- last-interaction age or unknown state;
- source coverage and warnings;
- draft count separately from sent evidence; and
- navigation to the canonical retained message when content remains available.

Counts and age are derived from surviving accepted links and canonical messages. The workbench never stores a second body or changes a canonical message through a ticket view.

Immediately before accepted SR/RFC termination removes its direct links, SOMA freezes a data-minimized terminal communication summary: received/sent counts, last known direction, last independently known interaction chronology, coverage state, and unlink chronology. The summary is immutable historical evidence, not a retained message body. It survives orphan purge and does not provide body navigation after content is unavailable.

Spare Request or another entity that retains a protected link continues to show the canonical communication normally. One entity's terminal state must not falsify another entity's counts or purge eligibility.

## 13. Security, privacy, and failure boundaries

Communication content, participants, source configuration, indexes, links, and job state use the local security envelope. Temporary parse material is bounded, protected, and removed after commit/failure according to the technical-cleanup contract. Redaction is applied before diagnostics leave the owning process.

Source-store reads use least privilege and bounded resources. Parser failure is data, not permission to modify the source, skip validation, advance coverage, accept proposals, or discard a previously retained canonical communication.

Manual attachment/upload controls remain absent in Beta 1.0. External source files and exported artifacts remain operator-managed.

## 14. Required use cases and acceptance evidence

Beta 1.0 acceptance shall cover at least:

1. no-target gate and activation by each registry family;
2. initial boundary with known and unknown target chronology;
3. incremental replay, overlap, interruption, restart, and high-water integrity;
4. older target with bounded backfill and explicit Deep Scan;
5. matched-only persistence, unmatched transient handling, one message linked to multiple entities, and independent unlink;
6. provider-stable identity, fallback versions, account-scope separation, path move, collision review, and later reconciliation;
7. structured recipients and direction disagreement;
8. proposal creation, review, rejection, acceptance, correction, and no implicit mutation;
9. hourly default, configuration, disable, Check now, coalescing, one catch-up, and non-overlap;
10. progress, unknown estimates, cancellation, partial coverage, bounded retry, redacted diagnostics, and restart;
11. terminal SR/RFC unlink while another protected link survives;
12. last-link removal, seven-exact-day default grace, relink cancellation, due-time dependency race, purge, purge record, and backup/external-file nonmutation;
13. terminal reversal before and after purge, source unavailable, and coverage warning;
14. active and terminal workbench counts, direction, age, coverage, canonical navigation, draft separation, body nonduplication, and frozen summary;
15. MSG generation/export without sent evidence; and
16. independent import, communication, proposal, draft, and housekeeping workflows.

Each case requires responsive loading, empty, warning, error, cancelled, stale, locked-source, partial-coverage, retry, collision, pending-purge, purged, correction, and historical states where applicable, plus automated acceptance evidence.

## 15. LLD responsibility

The LLD shall define exact:

- supported PST/OST adapters, source fields, folder-role mapping, file stabilization, resource bounds, and encrypted local index shape;
- registry values and alias rules;
- time/provider-position cursor types, overlap window, coverage algebra, and watermark transactions;
- targeted-backfill and Deep Scan bounds;
- provider-origin field, fallback canonicalization versions, collision queries, and reconciliation commands;
- participant and direction schemas;
- message/link/proposal/draft/job/grace/purge/summary schemas and constraints;
- scheduler ownership, interval bounds, catch-up, cancellation, retry/backoff, restart, and housekeeping transactions;
- protected-dependency query and purge allowlist/denylist;
- terminal unlink and reversal integration commands;
- redaction allowlists and safe diagnostics;
- API commands, permissions, stable errors, no-op/idempotency behavior, concurrency, and rollback; and
- desktop/web UI states, accessibility, keyboard equivalence, localization-ready text, and deterministic tests.
