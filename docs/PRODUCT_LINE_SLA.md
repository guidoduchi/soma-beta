# Contract Product Line and SLA Contract

Contract Product Line classification and SLA control are a core reason SOMA exists. This document is normative for Beta 1.0.0.

## 1. Classification model

- A `Contract` represents the service agreement under which SLA performance is measured and belongs to exactly one Customer Organization.
- A `Product Line` is a reusable service or technology classification such as IT or NFV.
- A `Contract Product Line` is one occurrence of a reusable Product Line inside one Contract. It owns the applicable SLA policy.
- Different Customer Organizations may use the same Product Line under different Contracts and configure completely different SLA policies. Sharing the Product Line definition never shares the Contract or its policy.
- One Customer Organization may have multiple Contracts, including more than one Contract covering the same Product Line; these remain distinct Contract Product Lines.
- Each Service Request has at most one active Contract Product Line classification, whose Contract must belong to the SR's resolved Customer Organization.
- An imported SR may be classified automatically only by a deterministic configured mapping based on trusted allowlisted evidence, such as Customer Account Code.
- Advanced Search `Product` is discarded and never selects a Contract, Product Line, Contract Product Line, or SLA policy.
- An SR with an unresolved Customer Organization, no eligible mapping, an ambiguous mapping, or a cross-customer proposed Contract remains SLA-unclassified and requires review. SOMA does not apply a fabricated IT or other default.
- The operator may reclassify one SR to another active Contract Product Line belonging to that SR's Customer Organization. The change is audited and recalculates current results without rewriting completed report snapshots.
- Correcting an SR's Customer Organization invalidates an incompatible Contract Product Line classification and requires reviewed reclassification.

## 2. Cohort-compliance policies

An SLA tier is a cohort rule, not a fraction of one ticket's deadline. Each tier defines:

- a required percentage of eligible SRs; and
- a maximum inclusive elapsed duration.

For example, IT Major's `85% within 15 days` tier means at least 85% of the eligible IT Major cohort must be resolved or closed with effective elapsed time less than or equal to 15 days. Its `100% within 30 days` tier means every eligible member must satisfy 30 days.

Beta 1.0.0 provides these confirmed default policies:

| Default Product Line template | Severity | Required cohort percentage | Maximum inclusive duration |
|---|---|---:|---:|
| IT | Critical | 100% | 7 days |
| IT | Major | 85% | 15 days |
| IT | Major | 100% | 30 days |
| IT | Minor | 85% | 45 days |
| IT | Minor | 100% | 60 days |
| IT | Non-fault inquiry | 85% | 67.5 days |
| IT | Non-fault inquiry | 100% | 90 days |
| NFV | Critical | 100% | 3 days |
| NFV | Major | 100% | 15 days |
| NFV | Minor | 100% | 90 days |
| NFV | Non-fault inquiry | 100% | 135 days |

Non-fault inquiry derives from the corresponding Minor policy by multiplying each duration by `1.5` and preserving the Minor policy's tier structure. Therefore IT Non-fault inquiry retains both the 85% and 100% tiers, while NFV Non-fault inquiry has only the 100% tier.

The IT and NFV rows are policy templates, not global policies forced onto every customer. Each Customer Organization's Contract Product Lines may configure their own tier combinations according to the applicable Contract. Durations support exact fractional days; calculation does not round a 67.5-day rule into a whole-day bucket.

## 3. Effective SLA start

The only SLA start is the accepted source `Report Date`. If no valid source Report Date exists, the SR has no calculable elapsed-time or SLA result and remains explicitly incomplete or SLA-unclassified. Discovery, filename, filesystem, capture, import, manual-creation, and current timestamps are provenance or lifecycle facts only and never substitute for Report Date. A later accepted valid source value activates calculation without rewriting earlier provenance.

Instants are stored in UTC whole-second precision. SLA source interpretation, calendar boundaries, and ordinary display use the fixed operational timezone `America/Guayaquil`. The separately selectable Objective/Task scheduling timezone has no SLA authority.

## 4. Effective elapsed time and endpoint

For an active SR:

`effective elapsed time = max(0, now - accepted Report Date - cumulative suspension)`

An initially blank imported `Suspension Duration` means zero: the source reports that the SR has never been suspended and has no cumulative suspension. A later blank or zero value that conflicts with previously accepted nonzero suspension evidence requires review and cannot silently erase that evidence. `Suspend Planned End Date` is an active suspension fact only while the accepted status is `Customer Agreed Suspend` and the end is in the future. A suspended status with a missing or expired planned end is an import inconsistency requiring review; it is not silently treated as a valid future suspension.

For a terminal SR, `now` is replaced by the first accepted `Resolved` or `Closed` observation timestamp. Cancelled SRs are excluded from SLA cohorts and compliance calculations.

A recognized `Resolved`, `Closed`, or `Cancelled` status immediately suppresses active-work reminders and live SLA-risk notifications for that SR. Resolved and Closed SRs retain effective terminal-duration evidence and remain eligible for applicable cohorts; Cancelled SRs retain historical evidence but remain excluded. A suspected terminal-to-nonterminal reversal is a separate high-risk review warning and does not silently reactivate ordinary reminders.

Cumulative suspension retains exact fractional-day duration and must not use binary floating-point arithmetic for persisted calculations.

## 5. Derived results

An SR's elapsed-time evidence and every cohort-compliance result are derived from accepted source facts, operator classification, and the applicable Contract Product Line policy. They are not independently editable truth.

An SR without an accepted valid Report Date has no calculable elapsed-time or SLA result and is presented as incomplete or SLA-unclassified. Import discovery, filename, filesystem, capture, and current timestamps never substitute for Report Date. A later accepted valid Report Date activates calculation without rewriting earlier import provenance.

Changing Contract Product Line classification, severity, effective Report Date, accepted endpoint, suspension, or policy recalculates current results. An accepted policy revision applies to every existing SR currently classified under that Contract Product Line, including SRs created before the revision and terminal SRs; Report Date does not grandfather an SR into the previous policy. All subsequent current views, warnings, calculations, and reports use the revised policy.

An explicitly accepted terminal-to-nonterminal reversal recalculates the same SR's current endpoint, elapsed-time evidence, and applicable cohort results while preserving prior terminal observations and every completed report snapshot.

Every policy revision preserves its prior values and change evidence in audit history. Completed report exports and accepted persisted snapshots retain the calculation and policy revision captured when they were completed, so historical evidence does not mutate even though the live SR projection is recalculated.

Each completed report is derived from one internally consistent accepted-state snapshot. It preserves the report period, timezone, organization scope, included members, reported calculations, applicable policy revisions, and minimum provenance needed for reproduction, but not complete source observations or unrelated operational or personal data. Completion occurs only after the artifact is written and verified. Later accepted changes never mark a completed report stale or eligible for cleanup.

## 6. Reporting cohorts

Canonical contractual SLA cohorts are monthly. Membership consists of eligible non-cancelled SRs whose accepted Report Date falls in the calendar month interpreted in `America/Guayaquil`. Objective timezone changes never move cohort membership. Cohorts partition by at least:

- Customer Organization, Contract, and Contract Product Line;
- severity;
- policy tier; and
- current compliance outcome.

Cancelled SRs are excluded. Individual duration and cohort compliance are different results. Live projections distinguish Pending, Currently Met, At Risk, Breached, and Final Met using deterministic lower-bound and best-possible calculations. An open changing month is never represented as final. Daily, Weekly, and selected-range views are as-of progress snapshots of monthly cohorts, not alternate contractual cohort boundaries. Each snapshot identifies timezone, month, scope, included/excluded/unclassified populations, denominator, policy revision, and result. Percentage rounding and finalization rules belong to the Beta 1.0 LLD and may not weaken configured percentages or inclusive durations.

## 7. Warnings and safeguards

SOMA exposes separate warnings rather than collapsing them into one generic risk label:

- SLA-unclassified SRs;
- ambiguous or unmatched automatic Contract Product Line classification;
- individual SRs approaching or exceeding an applicable duration;
- cohort tiers currently below their required compliance percentage;
- missing or passed Suspend Planned End while the SR is reported as currently suspended;
- suspension ending soon when a currently suspended SR's valid future planned end enters the configured noncontractual warning threshold;
- source disappearance or conflict requiring review; and
- reversal of a terminal observation, always requiring high-risk review.

Individual duration evidence and cohort compliance are separate dimensions. Passing an individual policy-tier duration is evidence that may affect its cohort; it is not by itself failure of a percentage-based tier. Alpha's global age-risk and suspension-KPI severity schedules do not control Beta 1.0. `ResolveBy` and `Resolve By Suspend` remain future-use source facts and do not determine Beta 1.0 SLA behavior. Alpha's `no deadline`, `expiring`, `overdue`, and `pending source removal` labels are not Beta 1.0 policy truth. Warning presentation may be configurable where the product contract permits, but policy truth, source provenance, and audit history are not optional. Every state uses text and/or iconography in addition to color.

Overview and Needs Attention are the primary continuous warning surfaces. A supplemental local in-app or tray notification for the same SR and active condition may occur at most once per operator-local calendar day, including across application restarts.
