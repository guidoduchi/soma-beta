# SOMA Beta Import Contract

Status: **Foundation review v0.3**  
Target: **SOMA Beta 1.0.0**  
Authority: confirmed source trust, field-retention, identity, population, and historical-selection decisions.

## 1. Purpose and source authority

SOMA imports operational evidence; it does not mirror every column supplied by an external workbook. Only fields explicitly allowlisted here may enter normalized Beta persistence. A field may be retained as an active 1.0 fact or retained for a later release. Every other source column is discarded after staging and cannot influence Beta behavior.

The official source families are:

| Domain | Workbook layout | Authority |
|---|---|---|
| Service Requests | Advanced Search (Service Request) | SR source facts |
| Requests for Change | Enhanced Excel Data Export | RFC source facts |
| WFM Tasks | Service Provider Plan Creation | WFM source facts and provisional parent-RFC hints |

Enhanced Excel remains authoritative for RFC facts. WFM RFC fields may create or provisionally populate a missing parent RFC, but cannot silently override a populated Enhanced Excel fact.

## 2. Shared import behavior

- Parsing creates staged source observations before any operational record changes.
- Matching uses immutable official identity. An import never corrects an official identity in place.
- Population updates accepted source-owned facts while preserving SOMA-owned relationships, Tasks, Objectives, device references, spares, notes, review state, audit history, and other local meaning.
- Import review is the default. The operator may configure automatic acceptance only for explicitly safe source/change classes defined during LLD.
- Identity changes, RFC/WFM ownership changes, hierarchy changes, time conflicts, terminal-state reversals, disappearance, and hardware-serial contradictions always require review.
- Blank handling is field-specific. A blank does not globally mean delete, zero, or unknown.
- Persisted source observations retain source family, file fingerprint, import run, row locator, parsed identity, accepted values, and validation findings.
- Unallowlisted values are not persisted as generic metadata, searchable text, an opaque copy of the row, or a retained workbook copy. SOMA retains the file fingerprint and bounded provenance; the external original remains user-managed.
- Raw operational workbooks and their customer data are not committed to the source repository.

## 3. Historical import boundary

The default historical lookback is **one month**, configurable in Settings.

A row is excluded from operational population when its record is in a recognized terminal state and its trusted recency reference is older than the configured lookback:

| Source | Trusted historical reference |
|---|---|
| Service Request | `Last Update` |
| RFC | `Last Update Time` |
| WFM | `Planned End Time` |

Active, nonterminal, unscheduled, and future work is not excluded by this terminal-record rule. Excluded rows do not create or update domain records. The import result reports their count and exclusion reason without retaining discarded source fields.

The Advanced Search filename timestamp is interpreted as China Standard Time when it is used for source-file chronology. Operational row timestamps are interpreted under the accepted Ecuador operational timezone rules. The WFM filename suffix is opaque and is not an operational timestamp.

## 4. Advanced Search Service Request mapping

### 4.1 Active in Beta 1.0

| Source column | Beta meaning | Blank and validation rule |
|---|---|---|
| `SRNo` | Official SR identity | Required for an imported SR; exactly eight digits after safe display-prefix normalization |
| `Problem Summary` | Source summary | Absence is shown in review; it does not invalidate the identity |
| `Report Date` | Preferred SLA start | Invalid or absent value uses the audited fallback defined by the SLA contract |
| `Customer Contact` | Source contact reference | May propose a Contact match or creation; never silently merges ambiguous people |
| `Customer Severity` | Source severity | Source-owned and SLA-relevant |
| `Current Handler` | Current source handler | May be absent without deleting a registered Contact |
| `Status` | Current SR status | Terminal reversal is high risk and requires confirmation |
| `Customer Org.` | Customer Organization name | Used in reviewed organization reconciliation |
| `Customer Account Code` | Stable customer account key | Used for organization reconciliation and SR queries when present |
| `Suspend Planned End Date` | Current planned suspension end | Active only when status is `Customer Agreed Suspend` and the date is in the future at reconciliation time |
| `Suspension Duration` | Cumulative suspension | An initial blank means zero/no reported suspension; a later blank or zero conflicting with accepted nonzero evidence requires review and cannot erase it silently |
| `Last Update` | Source recency | Drives stale-observation ordering and historical cutoff |

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

### 5.1 Active in Beta 1.0

| Source column | Beta meaning | Rule |
|---|---|---|
| `Task ID` | RFC No. | Accept only `NC` followed by exactly fourteen digits |
| `Customer Account Number` | Customer account key | Supports reviewed Customer Organization reconciliation |
| `Customer Account Name` | Customer Organization name | Supports reviewed reconciliation and display |
| `Severity` | RFC source severity | Distinct from WFM Risk Level and SR severity |
| `Summary` | Authoritative RFC summary | Populates a provisional RFC without changing its identity |
| `Status` | Authoritative RFC status | Terminal reversal requires review |
| `Owner` | Authoritative external owner identity | Retained separately from the display name |
| `Owner Name` | Owner display/contact hint | Supports Contact reconciliation without replacing `Owner` identity |
| `Last Update Time` | Source recency | Drives stale-observation ordering and historical cutoff |

An identifier longer than canonical `NC` plus fourteen digits, including a suffixed source branch such as `NC…-004`, is excluded. SOMA does not truncate it to the parent and does not interpret it as a Beta subordinate RFC.

### 5.2 Retained for future use

- `Service Type`
- `Scenario`
- `L1 Handler Name`
- `L2 Handler Name`
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
| `RFC Status` | Provisional parent-RFC status | Fallback only; Enhanced Excel wins when available |
| `Task No.` | WFM Task identity | Required; `TK` plus fourteen digits |
| `Task Status` | WFM lifecycle status | Cancelled work does not create an Objective automatically |
| `Dispatch Progress` | Dispatch state | Blank is valid when `Task Status = Plan Cancel`; otherwise absence is reviewed |
| `Planned Start Time` | Planned interval start | A complete valid pair participates in Objective grouping |
| `Planned End Time` | Planned interval end | Also supplies the terminal historical reference |
| `Rep Office` | Source office label | Descriptive; it grants no ownership or authorization |
| `Risk Level` | WFM operational risk | Distinct from SR/RFC severity and an SLA Result |
| `Task Name` | WFM name and provisional RFC-summary hint | Existing Enhanced RFC Summary remains authoritative |
| `Description` | Source-owned task description | Never parsed to create devices, sites, parts, or relationships automatically |
| `Customer Organization` | Customer Organization hint | Allowed for reviewed reconciliation, including a WFM-created provisional RFC |

Both planned timestamps may be absent; such a WFM remains an unscheduled Task. Exactly one timestamp, an invalid interval, or a conflict with established work requires review rather than fabricated scheduling.

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
- A valid, future, noncancelled WFM interval enters the Objective grouping review described by the Workbench Contract.
- A WFM without a complete timeframe remains unscheduled and creates no Objective.

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

### RFCs — 22 source rows

Every selected active field was populated. `L2 Handler Name` was blank in 4 of 22 rows (18.2%). One nonblank `Task ID` was still invalid for Beta because it had a branch suffix; canonical-format validation therefore remains mandatory. Twenty-one rows had canonical RFC identities.

### WFM Tasks — 17 rows

Every selected field was populated except `Dispatch Progress`, blank in 3 of 17 rows (17.6%). Those three rows were exactly the `Plan Cancel` tasks. `Customer Organization` was populated in all 17 rows.

## 9. Remaining LLD responsibility

LLD must define exact workbook/header-version detection, data types, formula handling, cell-size limits, date-system handling, file stabilization, fingerprints, replay/idempotency, safe auto-accept classes, review presentation, import transaction boundaries, and sanitized golden fixtures. Those choices must implement this allowlist and may not reintroduce discarded columns without a Product Contract change.
