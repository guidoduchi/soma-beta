# P1A-W6 — Communications Use Cases

Status: **Draft catalogue; UC-062..UC-069 pending owner review**

## UC-062 — Configure read-only Communication Source Scopes
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Define the local PST/OST source locations SOMA may read without granting write/send/receive authority.
- **Trigger/preconditions:** Authenticated installation; supported local source files/locations exist or may be configured.
- **Main flow:** add/edit/remove source scope; validate readable target and accepted scope rules; preserve path-independent source identity/coverage metadata; enable/disable processing as configured.
- **Alternates/failures:** unsupported/unreadable source is reported; no write-back to mailbox/source; exact parser/provider/subset mechanics remain `O-004`.
- **Postconditions/evidence:** versioned source-scope configuration and audit/history.
- **Authority:** `BETA-REQ-0111..0115`, `0122`, Communications Contract.

## UC-063 — Run the local Communication fetch-and-match pipeline
Status: **Draft — pending owner review**
- **Actor:** System / Local Administrator.
- **Goal:** Fetch eligible local messages, match them to governed targets, and persist only canonical matched Communications/links without implicit domain mutation.
- **Trigger/preconditions:** Hourly/default configured schedule, startup catch-up, or Check now; eligible target registry/source scopes exist.
- **Main flow:** enforce non-overlap; read source incrementally using coverage/high-water/overlap rules; parse transiently; establish canonical message identity/direction/participants; match only governed target identifiers; persist matched messages and independent multi-target links; produce proposals rather than domain writes.
- **Alternates/failures:** unmatched messages remain transient; parser/source failure preserves prior progress and reports bounded error; target gate prevents scanning solely for Infrastructure/descriptive Device data; no email is sent/received.
- **Postconditions/evidence:** canonical matched Communications, links, source/coverage/job history and proposals.
- **Authority:** `BETA-REQ-0111..0122`; Communications/Runtime contracts.

## UC-064 — Review Communication coverage and perform targeted backfill
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Understand whether relevant source periods have been covered and deliberately fill bounded gaps for a target/scope.
- **Trigger/preconditions:** Communication source/target exists; coverage may be incomplete or warning exists.
- **Main flow:** inspect per-scope coverage/high-water/warnings; choose target/time-bounded backfill; run bounded retrieval/matching; update coverage only from successful processing; review results.
- **Alternates/failures:** incomplete coverage remains explicit; backfill cannot silently become full Deep Scan; failure preserves previous coverage truth.
- **Postconditions/evidence:** updated bounded coverage and processing history.
- **Authority:** `BETA-REQ-0114..0121`; Communications Contract.

## UC-065 — Perform an explicit scoped Deep Scan
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Deliberately rescan a broader approved source/time scope when normal incremental/backfill behavior is insufficient.
- **Trigger/preconditions:** Operator invokes Deep Scan and specifies supported scope.
- **Main flow:** present scope/consequence; run explicit scan without changing target-gate/retention rules; deduplicate against canonical identities; persist only matched Communications; update scan/coverage history.
- **Alternates/failures:** Deep Scan does not bypass review, matching identity, content-minimization, or source read-only rules; interruption is restart-safe/bounded.
- **Postconditions/evidence:** explicit Deep Scan history, matched results and coverage updates.
- **Authority:** `BETA-REQ-0114..0121`; Communications Contract.

## UC-066 — Review and decide Communication-derived domain proposals
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Accept/reject/correct domain suggestions derived from matched Communication evidence without treating the message itself as authoritative mutation.
- **Trigger/preconditions:** Communication matching produced one or more domain proposals.
- **Main flow:** inspect exact target/message/source evidence and proposed change; compare with current domain truth; accept/reject/correct according to owning domain; commit accepted domain mutation with evidence reference.
- **Alternates/failures:** proposal rejection changes no domain state; stale proposals require refresh/review; manual domain action remains available without Communication evidence; no attachment/upload UI is required.
- **Postconditions/evidence:** proposal decision history and, if accepted, owning-domain mutation/evidence.
- **Authority:** `BETA-REQ-0063..0064`, `0089..0090`, `0111..0122`; Communications + owning domain contracts.

## UC-067 — Inspect and navigate canonical Communication evidence
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Review matched received/sent/unknown Communication evidence and navigate among all linked operational targets without duplicating message truth.
- **Trigger/preconditions:** Canonical matched Communication exists.
- **Main flow:** open workbench/right-pane or Communication view; inspect direction/participants/time/body/coverage context; see linked SR/RFC/WFM/Objective/Spare/RMA/Fault Tag targets; navigate to exact linked entity; preserve one canonical message body.
- **Alternates/failures:** MSG draft is not sent evidence; terminal frozen summaries may remain after reconstructable content purge; multi-target links remain independent.
- **Postconditions/evidence:** no mutation except explicit navigation/read acknowledgements where governed.
- **Authority:** `BETA-REQ-0032`, `0111..0122`; Workbench/Communications/UI contracts.

## UC-068 — Unlink terminal targets and minimize orphaned Communication content
Status: **Draft — pending owner review**
- **Actor:** System / Local Administrator where confirmation is required upstream.
- **Goal:** Apply the narrow Beta 1.0 terminal-link/grace/content-minimization lifecycle without deleting protected operational history.
- **Trigger/preconditions:** Authoritatively accepted terminal SR transition, or separately confirmed RFC terminal cascade, removes a direct Communication link.
- **Main flow:** remove only governed direct target link; determine whether any protected dependency/link remains; if orphaned start configurable positive grace (default seven exact days); cancel grace on relink; at expiry revalidate; purge reconstructable content while preserving non-reconstructable purge/decision evidence and frozen terminal summary.
- **Alternates/failures:** RFC provider terminal evidence alone cannot unlink; remaining protected link cancels orphan status; expiry failure preserves safe state/retries; this exception does not authorize general operational purge.
- **Postconditions/evidence:** correct links/orphan/grace/purge state and immutable purge/frozen-summary evidence.
- **Authority:** `BETA-REQ-0045`, `0072`, `0077`, `0116`, `0122`, `0161`; Communications Contract.

## UC-069 — Generate a local MSG draft from a supported workflow
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Generate an Outlook-compatible local message draft for a supported operational workflow while keeping artifact generation separate from sending and lifecycle evidence.
- **Trigger/preconditions:** Owning workflow has enough current reviewed data and an eligible recipient channel.
- **Main flow:** invoke Generate MSG; validate action-specific recipient; render current governed content/identifiers; create local `.msg`; expose/open/export according to accepted local behavior; retain generation history as appropriate.
- **Alternates/failures:** missing recipient blocks draft generation only; artifact creation never proves send/receive/submission; external edits/sending are outside SOMA authority; exact MSG library/format mechanics remain `O-004`.
- **Postconditions/evidence:** generated draft artifact/history, no implicit domain transition.
- **Authority:** `BETA-REQ-0015`, `0048`, `0067`, `0111..0122`; Communications Contract.
