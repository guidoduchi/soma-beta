# Contract Product Line and SLA Contract

Contract Product Line classification and SLA control are a core reason SOMA exists. This document is normative for Beta 1.0.0.

## 1. Classification model

- A `Contract` represents the service agreement under which SLA performance is measured.
- A `Product Line` is a reusable service or technology classification such as IT or NFV.
- A `Contract Product Line` is the active Product Line configuration inside one Contract. It owns the applicable SLA policy.
- Each Service Request has at most one active Contract Product Line classification.
- An imported SR may be classified automatically only by a deterministic configured mapping based on trusted allowlisted evidence, such as Customer Account Code.
- Advanced Search `Product` is discarded and never selects a Contract, Product Line, Contract Product Line, or SLA policy.
- An unmatched or ambiguously matched SR remains SLA-unclassified and requires review. SOMA does not apply a fabricated IT or other default.
- The operator may reclassify one SR to another active Contract Product Line. The change is audited and recalculates current results without rewriting completed report snapshots.

## 2. Cohort-compliance policies

An SLA tier is a cohort rule, not a fraction of one ticket's deadline. Each tier defines:

- a required percentage of eligible SRs; and
- a maximum inclusive elapsed duration.

For example, IT Major's `85% within 15 days` tier means at least 85% of the eligible IT Major cohort must be resolved or closed with effective elapsed time less than or equal to 15 days. Its `100% within 30 days` tier means every eligible member must satisfy 30 days.

Beta 1.0.0 provides these confirmed default policies:

| Product Line | Severity | Required cohort percentage | Maximum inclusive duration |
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

Other Product Lines, Contract Product Lines, and tier combinations are configurable according to their Contract requirements. Durations support exact fractional days; calculation does not round a 67.5-day rule into a whole-day bucket.

## 3. Effective SLA start

The preferred start is the accepted source `Report Date`.

If no valid source Report Date exists, the start temporarily falls back to the system-assigned instant of import or manual creation. A later valid, newer source observation replaces that fallback according to import review rules. The provenance and prior calculation remain auditable.

Instants are stored in UTC and displayed in the operator-configured timezone, initially `America/Guayaquil`.

## 4. Effective elapsed time and endpoint

For an active SR:

`effective elapsed time = max(0, now - effective Report Date - cumulative suspension)`

A blank imported `Suspension Duration` is authoritative zero: the source reports that the SR has never been suspended and has no cumulative suspension. `Suspend Planned End Date` is an active suspension fact only while the accepted status is `Customer Agreed Suspend` and the end is in the future. A suspended status with a missing or expired planned end is an import inconsistency requiring review; it is not silently treated as a valid future suspension.

For a terminal SR, `now` is replaced by the first accepted `Resolved` or `Closed` observation timestamp. Cancelled SRs are excluded from SLA cohorts and compliance calculations.

Cumulative suspension retains exact fractional-day duration and must not use binary floating-point arithmetic for persisted calculations.

## 5. Derived results

An SR's elapsed-time evidence and every cohort-compliance result are derived from accepted source facts, operator classification, and the applicable Contract Product Line policy. They are not independently editable truth.

Changing Contract Product Line classification, severity, effective Report Date, accepted endpoint, suspension, or policy recalculates current results. Completed report exports and accepted persisted snapshots retain their calculation and policy context so historical results do not mutate retroactively.

## 6. Reporting cohorts

SLA operational review supports the configured Daily, Weekly, or Monthly reporting period and groups eligible SRs by at least:

- Contract Product Line;
- severity;
- policy tier; and
- current compliance outcome.

Cancelled SRs are excluded. The exact membership boundary, denominator treatment for active SRs that have not reached a tier duration, percentage rounding, and snapshot persistence are assigned to the Beta 1.0 use cases and LLD; they may not change the confirmed percentages, inclusive durations, classification rules, or cancelled exclusion.

## 7. Warnings and safeguards

SOMA exposes separate warnings rather than collapsing them into one generic risk label:

- SLA-unclassified SRs;
- ambiguous or unmatched automatic Contract Product Line classification;
- individual SRs approaching or exceeding an applicable duration;
- cohort tiers currently below their required compliance percentage;
- missing or passed Suspend Planned End while the SR is reported as currently suspended;
- source removal or reversal of a terminal observation, always requiring review; and
- retention review after 180 days, without silently deleting operational evidence.

Alpha's global age-risk and suspension-KPI severity schedules do not control Beta 1.0. `ResolveBy` and `Resolve By Suspend` remain future-use source facts and do not determine Beta 1.0 SLA behavior. Warning presentation may be configurable where the product contract permits, but policy truth, source provenance, and audit history are not optional.
