# SOMA Beta Import Contract

Status: **Reconciled RC-002 — normative Beta 1.0.0 import/source contract**  
Target: **SOMA Beta 1.0.0**  
Authority: accepted source trust, field retention, identity, population, status-driven RFC/WFM history, local filtering, Infrastructure workbook exchange, and normalized source-review authority, including `BETA-REQ-0145`–`0177` where applicable.

## 1. Purpose and source authority

SOMA imports operational evidence; it does not mirror every column supplied by an external workbook. Only fields explicitly allowlisted here may enter normalized Beta persistence. A field may be retained as an active 1.0 fact or retained for a later release. Every other source column is discarded after staging and cannot influence Beta behavior.

The official source families are:

| Domain | Workbook layout | Authority |
|---|---|---|
| Service Requests | Advanced Search (Service Request) | SR source facts |
| Requests for Change | Enhanced Excel Data Export | RFC source facts |
| WFM Tasks | Service Provider Plan Creation | WFM source facts and provisional parent-RFC hints |

Enhanced Excel remains authoritative for RFC facts. WFM RFC fields may create or provisionally populate a missing parent RFC, but cannot silently override an accepted Enhanced Excel fact.

The SOMA-generated Infrastructure workbook is not an authoritative external population. It is an operator-authored, versioned bulk registration/update format and human-readable discovery export governed by section 9 and the [Infrastructure Contract](INFRASTRUCTURE_CONTRACT.md). Absence from that workbook never means disappearance, deletion, archival, relocation, unlinking, or clearing. Communication-processing eligibility and terminal unlinking are governed separately by the [Communications Contract](COMMUNICATIONS_CONTRACT.md).

## 2. Shared import behavior

- Parsing creates exact-source staged observations before any operational record changes.
- Matching uses immutable official identity. An import never corrects an official identity in place.
- Population updates accepted source-owned facts while preserving SOMA-owned relationships, Tasks, Objectives, device references, spares, notes, review state, audit history, and other local meaning.
- Import review is the default. The operator may configure automatic acceptance only for explicitly approved low-risk source/change classes defined during LLD under `O-007`.
- Safe auto-accept shall never include RFC terminal-state proposals, material WFM terminal/history proposals, RFC hierarchy/reparenting, Customer/ownership reconciliation, material Task/WFM timeframe changes, disappearance or empty-population interpretation, Objective-regrouping consequences, or suspected competing WFM attempts. Identity reconciliation and hardware-serial contradictions likewise remain reviewed under their owning contracts.
- Independent targets shall receive dispositions at the smallest safe explainable idempotent scope. One safely isolatable invalid, conflicting, terminal, Customer, hierarchy, timeframe, or competing-attempt case shall not force rejection of unrelated valid targets. Whole-import rejection is reserved for genuine workbook-level integrity, identity, chronology, source-scope, safety, or inseparable-consistency failure.
- Before acceptance, every official source produces a proposal-oriented impact summary separating creations, updates, unchanged observations, skips, invalid rows, warnings, high-risk conflicts, and applicable identity, organization, hierarchy, ownership, or timeframe effects.
- RFC/WFM observed source presence is distinct from mutation acceptance. A valid canonical identity counts as present inside the declared source scope even when its proposal is rejected, deferred, or unresolved.
- RFC/WFM absence is never inferred, including from a full, partial, filtered, or empty workbook. Recognized status drives historical presentation and SOMA filters locally.
- For a source family that explicitly declares authoritative-population semantics, a valid empty authoritative population affecting previously accepted in-scope records requires explicit high-risk confirmation bound to the exact source family, chronology, logical fingerprint, scope, and impact summary. It may record reviewed disappearance warnings but cannot delete or finalize operational records. This rule does not grant RFC/WFM omission any lifecycle authority.
- Beta 1.0 displays nonempty population and Customer Organization distribution comparisons but applies no automatic accept/reject threshold based solely on an unvalidated count or percentage deviation.
- `SRNo` is the only universal Advanced Search header and row identity requirement. Missing allowlisted nonidentity headers create coverage warnings; a new SR may remain incomplete, and unusable values do not erase prior accepted facts unless the field contract explicitly permits clearing.
- For RFC/WFM adapters, only the governed identity headers are universally required. Missing optional-active coverage warns and preserves prior accepted truth; it does not silently clear source-owned facts.
- Import capture time is provenance only. It never substitutes for missing `Report Date` and never participates in SR duration or SLA calculations. A later accepted valid Report Date fills the missing source fact without changing identity or history.
- One official SRNo identifies one surviving SR. Later terminal observations reconcile normally, and a valid reappearance may clear a source-disappearance warning. A recognized nonterminal Status after accepted terminal evidence is a high-risk proposal that never auto-accepts; explicit acceptance updates the same SR while preserving prior terminal evidence and completed report snapshots.
- A missing, blank, malformed, or unknown Status cannot reverse accepted terminal evidence.
- For RFC imports, accepting recognized terminal evidence appends that source evidence and atomically creates its linked pending local-cascade proposal. It does **not** execute the cascade. Rejecting, deferring, or leaving the terminal proposal unresolved does not require rejecting unrelated valid rows.
- Structural validation, chronology, fingerprinting, and anomaly checks establish processing integrity but do not prove publisher authenticity, file origin, or absence of human editing for an unsigned workbook.
- Blank handling is field-specific. A blank does not globally mean delete, zero, or unknown.
- Persisted source observations retain source family, file fingerprint, import run, row locator, parsed identity, only meaningfully observed or changed allowlisted values, and applicable validation/review findings.
- Unallowlisted values are not persisted as generic metadata, searchable text, an opaque copy of the row, or a retained workbook copy. SOMA retains the file fingerprint and bounded provenance; the external original remains user-managed.
- Raw operational workbooks and their customer data are not committed to the source repository.
- Acceptance that creates the installation's first trackable communication entity makes Communication Processing eligible, but the import transaction never fetches, scans, matches, advances a communication high-water mark, or accepts a communication-derived proposal. The independent scheduler or **Check now** command performs that work afterward.
- An accepted terminal SR lifecycle transition may invoke its governed direct-communication unlink consequence. For RFCs, accepted source terminal evidence alone does not unlink Communications: only the separately reviewed and confirmed RFC terminal cascade may perform that local consequence under the RFC/WFM and Communications contracts. Staged, rejected, invalid, merely parsed, or merely source-accepted-but-uncascaded RFC terminal values never unlink or purge communication evidence.
- An accepted terminal reversal during orphan grace restores the applicable same-entity relationship when its evidence remains available and cancels pending purge. After content purge, the independent communication workflow may run a targeted backfill if the source remains available; otherwise the workbench records a coverage warning. Import never fabricates reconstructed content.
- Import runs do not create or update Communication Source Scopes, source health, coverage intervals, high-water marks, processing jobs, fallback message identities, MSG drafts, or orphan-purge due times except by invoking an accepted cross-domain command explicitly defined in the Communications Contract.

### 2.1 Current projection and compact history

- Each current source-owned SR field comes from its newest accepted usable observation under source chronology and that field's non-destructive rules. A newer unusable, missing, malformed, or unknown value does not automatically erase an older accepted value.
- Historical observations are compact field-level deltas, not snapshots of every source column or every unchanged accepted field.
- Current Problem Summary is stored on the SR; accepted changes remain in audit/delta history rather than repeating the same summary in every observation.
- Customer Organization and Contact source labels are retained only when meaningfully observed or changed for reconciliation evidence. Unchanged labels and contact channels are not copied into every observation.
- Beta 1.0 retains the SR, compact source deltas, and audit history. It does not create Alpha's terminated-SR snapshot or purge source history after report finalization.

### 2.2 Scheduled Advanced Search checks

- After an Advanced Search inbox is configured, its automatic daily check is enabled by default at 10:00 in the fixed operational timezone `America/Guayaquil`; changing the Objective scheduling timezone does not reinterpret this boundary.
- The operator may select another whole-minute local time or disable the automatic schedule. **Check now** remains available in either state.
- Startup after a missed enabled boundary performs at most one catch-up check and never repeatedly invokes every missed day.
- An automatic check discovers the newest eligible stable workbook without opening a file picker. Manual file selection remains available as a separate operator action.
- Every automatic candidate enters the same staging, validation, review, and configured safe-auto-accept boundary as a manual candidate.
- Satisfied schedule-boundary persistence prevents duplicate scheduled invocation; logical-content fingerprinting and idempotence independently prevent duplicate import mutation.

## 3. Historical import boundary

Supported RFC/WFM workbooks may contain complete historical rows, including Closed, Cancelled, Complete, and Plan Cancel states. SOMA accepts them according to status and field rules and then filters active/historical presentation locally. It shall not require operators to pre-filter online reports or discard valid terminal rows merely because they are old. Any configurable lookback applies only to a source family whose separately accepted contract explicitly defines it; it does not authorize RFC/WFM disappearance inference.

The Advanced Search filename timestamp is interpreted as China Standard Time when it is used for source-file chronology. Operational row timestamps are interpreted under the accepted source/operational timezone rules. The WFM filename suffix is opaque and is not an operational timestamp.

## 4. Advanced Search Service Request mapping

### 4.1 Active in Beta 1.0

| Source column | Beta meaning | Blank and validation rule |
|---|---|---|
| `SRNo` | Official SR identity | Required for an imported SR; exactly eight digits after safe display-prefix normalization |
| `Problem Summary` | Source summary | Absence is shown in review; it does not invalidate the identity |
| `Report Date` | Source report date and SLA start | Invalid or absent values remain incomplete; no discovery, filename, filesystem, capture, import, or current timestamp may replace them |
| `Customer Contact` | Source contact reference | May propose a Contact match or creation; never silently merges ambiguous people |
| `Customer Severity` | Source severity | Source-owned and SLA-relevant |
| `Current Handler` | Current source handler | May be absent without deleting a registered Contact |
| `Status` | Current SR status | Terminal reversal is high risk and requires confirmation |
| `Customer Org.` | Customer Organization name | Used in reviewed organization reconciliation |
| `Customer Account Code` | Stable customer account key | Used for organization reconciliation and SR queries when present |
| `Suspend Planned End Date` | Current planned suspension end | Active only when status is `Customer Agreed Suspend` and the date is in the future at reconciliation time |
| `Suspension Duration` | Cumulative suspension | An initial blank means zero/no reported suspension; a later blank or zero conflicting with accepted nonzero evidence requires review and cannot erase it silently |
| `Last Update` | Source recency | Drives stale-observation ordering and the separately governed Advanced Search historical lookback |

If an SR is marked `Customer Agreed Suspend` but its planned end is absent or not in the future, SOMA stages an inconsistency warning for operator review. Outside that active-future condition, `Suspend Planned End Date` does not pause SLA or act as an active suspension fact.

### 4.2 Retained for future use

These values may be normalized and retained with provenance, but they drive no Beta 1.0 workflow, SLA calculation, relationship, warning, or UI decision unless another accepted contract explicitly says otherwise:

- `ResolveBy`
- `Resolve By Suspend`
- `Owner`
- `L2 Assignee`
- `L3 Assignee`
- `Related SR`
- `Authorization No.`
- `Escalation No`
- `Pr Number`

`Related SR` uses a comma delimiter. Each nonblank token is trimmed and validated as an eight-digit SR identity. `Pr Number` uses a semicolon delimiter. Each nonblank token is trimmed and validated as `SR` followed by seven digits. Malformed tokens are reported independently; one bad token does not erase valid tokens from the same cell.

### 4.3 Discard rule

Every Advanced Search column not named in sections 4.1 or 4.2 is untrusted for SOMA Beta and is discarded after staging. It cannot create Contracts, Products, Product Lines, Contract Product Lines, SLA policies, Network Elements, RFCs, spare relationships, ownership, contacts, dates, or classifications.

## 5. Enhanced Excel RFC mapping

Enhanced RFC and WFM discovery share one configured operational import directory, initially suggested as Downloads, while retaining separate exact source patterns. Only stable direct regular files are considered. RFC filesystem modification time may rank candidates but is not business chronology. WFM uses its supported embedded source timestamp; filename collision suffixes never determine recency. The newest invalid candidate fails visibly without silent fallback, and explicit manual selection remains available.

### 5.1 Active in Beta 1.0

| Source column | Beta meaning | Rule |
|---|---|---|
| `Task ID` | RFC No. | Canonical `NC` plus fourteen digits is the only RFC identity. A recognized canonical-plus-suffix branch artifact is staged as a skipped source branch artifact; other malformed values fail RFC identity validation. SOMA never truncates a source value to manufacture a parent RFC. |
| `Create Time` | Source RFC creation chronology | Preserved separately from SOMA creation time, file/discovery chronology, and import capture time; absence remains unknown |
| `Creator` | Source creator evidence | Active source-owned RFC evidence; it does not create authentication identity or silently select a Contact |
| `Customer Account Number` | Customer account key | Strongest supported external key for reviewed Customer Organization reconciliation |
| `Customer Account Name` | Customer Organization name | Descriptive reconciliation evidence; name alone never establishes ownership |
| `Severity` | RFC source severity | Distinct from WFM Risk Level and SR severity |
| `Summary` | Authoritative RFC summary | Populates a provisional RFC without changing its identity |
| `Status` | Authoritative RFC status | Closed/Cancelled terminal evidence is reviewed; terminal acceptance creates a pending cascade proposal but never executes that cascade automatically |
| `Owner` | Authoritative external owner identity | Retained separately from the display name |
| `Owner Name` | Owner display/contact hint | Supports reviewed Contact reconciliation without replacing `Owner` identity |
| `L1 Handler Name` | Source L1 handler evidence | Active source-owned RFC evidence; absence does not clear unrelated accepted Contact or ownership truth |
| `L2 Handler Name` | Source L2 handler evidence | Active source-owned RFC evidence; absence does not clear unrelated accepted Contact or ownership truth |
| `Last Update Time` | Source recency | Drives stale-observation ordering/source chronology; it does not create an age-based RFC lifecycle or historical cutoff |

Recognized RFC branch artifacts are review-visible skips, not Beta subordinate RFCs and not malformed canonical RFCs. They neither create nor update the canonical parent. Other malformed `Task ID` values are invalid rows at the smallest safe scope.

All active RFC fields other than canonical identity remain optional according to their field rules. Missing optional-active headers or values warn/preserve prior accepted truth rather than silently clearing current facts.

### 5.2 Retained for future use

- `Service Type`
- `Scenario`
- `Product Line Code`
- `Product Line`
- `Product Code`
- `Product Name`

These fields cannot silently select a SOMA Product Line or Contract Product Line, choose an SLA policy, or create Product/Infrastructure relationships in Beta 1.0.

### 5.3 Discard rule

Every Enhanced Excel column not named in sections 5.1 or 5.2 is discarded after staging.

## 6. Service Provider WFM mapping

### 6.1 Active in Beta 1.0

| Source column | Beta meaning | Rule |
|---|---|---|
| `RFC No.` | Owning RFC identity | Required; canonical `NC` plus fourteen digits |
| `RFC Status` | Provisional parent-RFC status | Fallback/provisional evidence only; accepted Enhanced Excel status wins when available and WFM evidence cannot silently override a pre-Implement RFC state |
| `Task No.` | WFM Task identity | Required; `TK` plus fourteen digits |
| `Task Status` | WFM lifecycle status | `Complete` and `Plan Cancel` are terminal/cancelled provider history; neither creates active Objective work automatically |
| `Dispatch Progress` | Dispatch state | Blank is valid when `Task Status = Plan Cancel`; otherwise absence is reviewed |
| `Planned Start Time` | WFM source-plan start | With a usable end forms immutable provider planning evidence and the default reviewed operational-plan candidate; source acceptance alone never silently schedules/regroups an Objective |
| `Planned End Time` | WFM source-plan end | With a usable start forms the provider interval used by separately reviewed active or historical Objective proposals where eligible |
| `Rep Office` | Source office label | Descriptive; it grants no ownership or authorization |
| `Risk Level` | WFM operational risk | Distinct from SR/RFC severity and an SLA Result |
| `Task Name` | WFM name and provisional RFC-summary hint | Existing accepted Enhanced RFC Summary remains authoritative |
| `Description` | Source-owned task description | Never parsed to create devices, sites, parts, or relationships automatically |
| `Customer Organization` | Customer Organization hint | Allowed only as reviewed reconciliation evidence, including for a WFM-created provisional RFC |

Both planned timestamps may be absent; such a WFM remains unscheduled. Otherwise both must be usable, with end after start. Any valid minute is accepted. Exactly one timestamp or an invalid interval is a row-level failure by default and shall not fabricate scheduling or automatically reject unrelated valid rows.

All active WFM fields other than `RFC No.` and `Task No.` remain optional according to their field rules. Missing optional-active coverage warns/preserves prior accepted truth rather than silently clearing current facts.

### 6.2 Retained for future use

- `Request Type`
- `Operation`
- `Task Creator`
- `Task Executor`
- `Product Line`
- `Product`

These fields drive no Beta 1.0 actor assignment, Product Line or Contract Product Line selection, SLA policy, or Infrastructure creation.

### 6.3 Discard rule

Every Service Provider column not named in sections 6.1 or 6.2 is discarded after staging.

## 7. Parent RFC and Objective effects

- A WFM always belongs to exactly one RFC.
- If its RFC exists, the WFM attaches to that RFC without rewriting accepted RFC facts.
- If its RFC does not exist, the WFM creates a provisional RFC using the WFM Task Name as provisional Summary and may use WFM RFC Status and Customer Organization as reviewed provisional hints.
- A later Enhanced Excel observation populates that provisional RFC by official identity while preserving its Tasks and SOMA-owned relationships.
- Only an Implement-eligible RFC may ordinarily own active nonterminal WFM work. WFM evidence may support separately reviewed provisional eligibility for a missing RFC but cannot override accepted Enhanced pre-Implement evidence.
- A valid accepted nonterminal WFM source interval is the default reviewed operational-plan candidate. Accepting the import never silently accepts Objective membership or regrouping; eligible accepted Task planning enters the separate Objective grouping review governed by the RFC/WFM and Workbench contracts.
- A WFM without a complete accepted timeframe remains unscheduled and creates no Objective.
- `Complete` and `Plan Cancel` rows remain historical provider evidence. `Plan Cancel` may create or adopt its exact identity but cannot promote/reactivate an RFC or create an Objective. An accepted provider-`Complete` WFM with no Objective and a usable accepted source interval may produce a separate reviewed historical-Objective proposal; that proposal proves neither actual execution nor SOMA Task outcome or downstream Inventory/Device effects.
- RFC/WFM source omission never changes lifecycle, archival, links, tracking, or Communication state. The complete governing rules are in the [RFC/WFM Contract](RFC_WFM_CONTRACT.md).

## 8. Observed historical blank profile

This section records aggregate evidence from the three official sample exports reviewed for the foundation. It is evidence, not a promise that future files will have identical completeness.

### Service Requests — 263 rows

| Field | Blank observations |
|---|---:|
| `L3 Assignee` | 263 / 263 — 100% |
| `Escalation No` | 262 / 263 — 99.6% |
| `Suspend Planned End Date` | 260 / 263 — 98.9% |
| `Related SR` | 234 / 263 — 89.0% |
| `L2 Assignee` | 211 / 263 — 80.2% |
| `Pr Number` | 203 / 263 — 77.2% |
| `Suspension Duration` | 151 / 263 — 57.4% |
| `ResolveBy` | 17 / 263 — 6.5% |
| `Resolve By Suspend` | 17 / 263 — 6.5% |
| `Owner` | 1 / 263 — 0.4% |

Every other active SR field was populated. All three currently suspended rows had a future `Suspend Planned End Date`. An initial blank `Suspension Duration` is normatively zero rather than unknown; a later blank or zero conflicting with accepted nonzero evidence remains subject to reviewed reconciliation.

## Temporal authority

Known accepted instants persist as UTC whole-second values. Each adapter applies an explicit offset or its governed source-family timezone at ingestion and preserves conversion provenance. A timezone-less timestamp without an unambiguous source contract remains unresolved. Offsetless WFM source planning uses its accepted `America/Guayaquil` source-time rule. The operator-selectable Objective timezone never reinterprets SR, RFC, WFM, workbook, filename, communication, or import chronology.

### RFCs — 22 source rows

Every active RFC field observed in the reviewed sample was populated except `L2 Handler Name`, which was blank in 4 of 22 rows (18.2%). One nonblank `Task ID` was a recognized branch-suffixed source artifact rather than a canonical RFC identity; branch-artifact classification therefore remains mandatory. Twenty-one rows had canonical RFC identities.

### WFM Tasks — 17 rows

Every selected field was populated except `Dispatch Progress`, blank in 3 of 17 rows (17.6%). Those three rows were exactly the `Plan Cancel` tasks. `Customer Organization` was populated in all 17 rows.

## 9. Infrastructure workbook import and export

### 9.1 Workbook family and locations

SOMA generates one versioned, macro-free `.xlsx` workbook family with three modes:

1. an empty Network Element registration template;
2. a human-readable current-device discovery export; and
3. a round-trip export for reviewed updates.

Infrastructure imports are discovered only from one operator-configured directory through an explicit **Check now** action. SOMA does not recurse into unrelated directories or fall back to broad scanning. Exports are written to an operator-selected destination; successful export does not register an import or mutate Infrastructure.

The workbook declares its format version, mode, source-installation scope, generation chronology, and included filter/scope. The exact representation belongs in the LLD, but it must remain human-readable in ordinary spreadsheet software and usable without SOMA for device discovery.

### 9.2 Allowed capability boundary

The format may represent current Network Element name, Model, optional manufacturer serial, Site, same-Site Cloud Deployment, Room/Rack/U placement, zero-many IP addresses and primary selection, compound-containment parent, and permitted notes or import comments.

It contains no password, private key, token, reusable secret, credential-provider reference, or Beta 1.0 connectivity/topology/interface/port edge. Export never creates those facts, and import never infers connectivity from co-occurrence, placement, Cloud assignment, IP patterns, or containment.

### 9.3 Identity and cross-installation handling

A valid same-installation round-trip identity may target one existing entity or relationship. A workbook identity originating in another installation is retained only as bounded provenance and matching evidence; it never authorizes an update to a coincidentally equal local identifier. Names, hostnames, Models, manufacturer serials, IP addresses, and placement labels are candidate evidence, not identity proof.

New accepted rows receive new immutable local identities. Ambiguous or contradictory candidates remain unresolved proposals. Unknown Sites, Models, Racks, Cloud Deployments, or parents require explicit resolution or reviewed creation and are never silently invented.

### 9.4 Staging and mutation

Every eligible workbook is parsed without modifying its source file or domain state. Review distinguishes creations, proposed updates, unchanged rows, duplicate/ambiguous candidates, unknown references, invalid placement/containment/IP-primary facts, skipped rows, and warnings.

Site, Rack, Cloud Deployment, one-primary-IP, containment-forest, archival, and dependency invariants remain enforced by the same application services as manual changes. Material Site/Rack/Cloud/containment reassignment is always explicit.

Missing rows do not imply deletion, archival, movement, unlinking, or clearing. Blank or unusable optional cells preserve prior valid data unless a future explicit clearing operation is accepted in the contract. Batch acceptance commits transactionally or rolls back, and replay of identical accepted content is idempotent.

Locked, corrupt, malformed, unsupported-version, inaccessible, or partially invalid workbooks produce bounded results without source modification or broader scanning. SOMA records bounded content identity, template version, source-installation scope, row/result decisions, warnings, actor, and chronology rather than a secret-bearing or unnecessary full workbook copy. Source and exported workbooks remain user-managed and are never automatically deleted, renamed, moved, or overwritten.

## 10. Remaining LLD responsibility

LLD must define exact workbook/header-version detection, data types, formula handling, cell-size limits, date-system handling, file stabilization, fingerprints, replay/idempotency, the centrally governed/versioned low-risk safe-auto-accept classes permitted by `O-007`, review presentation, import transaction boundaries, and sanitized export golden fixtures under the UI/UX Interaction Contract. Those implementation choices shall preserve the RC-002 exclusions: terminal, hierarchy, ownership, material timeframe, disappearance/empty-population, Objective-regrouping consequence, and competing-attempt cases are not safe auto-accept classes. Each fixture identifies format/schema version, synthetic or irreversibly sanitized inputs, expected normalized structure/content/rendering, and explicitly allowlisted nondeterminism; raw package-byte equality is not a substitute for semantic validation. The automated contract suite required by `BETA-REQ-0137` covers the Infrastructure Device template, discovery export, same-installation round trip, foreign identity, duplicates, ambiguity, malformed/modified workbooks, partial failure, and authoritative hierarchy preservation. Those choices must implement this allowlist and may not reintroduce discarded columns without a Product Contract change.
