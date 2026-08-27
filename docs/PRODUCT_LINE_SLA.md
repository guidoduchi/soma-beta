# Product Line and SLA Contract

Product Line classification and SLA control are a core reason SOMA exists. This document is normative for Beta 1.0.0.

## 1. Classification

- `Product` is descriptive source text.
- `Product Line` is an operator-controlled classification that selects an SLA policy.
- A Product value never silently assigns a Product Line.
- A Product Line belongs to exactly one Customer Organization.
- Its normalized name is unique within that organization, including archived Product Lines.
- An SR may use only an active Product Line owned by its Customer Organization.
- Batch assignment is a reviewed operation and supports at most 500 SRs per batch.
- When no Product Line is assigned, SOMA warns and calculates against IT defaults for guidance, but does not fabricate or persist a Product Line relationship.

## 2. Milestone policy

Milestones are whole calendar days from the effective SLA start after cumulative suspension.

| Product Line | Severity | 85% milestone | 100% milestone |
|---|---|---:|---:|
| IT | Critical | — | 7 days |
| IT | Major | 15 days | 30 days |
| IT | Minor | 45 days | 60 days |
| NFV | Critical | — | 3 days |
| NFV | Major | — | 15 days |
| NFV | Minor | — | 90 days |

For a non-fault inquiry, the 100% milestone is `ceil(Minor 100% milestone × 1.5)` for the selected Product Line; there is no 85% milestone.

## 3. Effective SLA start

The preferred start is the source Report Date.

If no valid source Report Date exists, the start temporarily falls back to the system-assigned instant of import or manual creation. A later valid, newer source observation replaces that fallback according to import review rules. The provenance and prior calculation remain auditable.

Dates are presented in `America/Guayaquil`; instants are stored in UTC.

## 4. Running time and endpoint

For an active SR:

`running time = max(0, now − effective Report Date − cumulative suspension)`

For a terminal SR, `now` is replaced by the first accepted terminal observation timestamp. Closed and resolved observations can establish the endpoint. Cancelled SRs are excluded from SLA cohorts and compliance calculations.

Cumulative suspension retains exact fractional-day duration and must not use binary floating-point arithmetic for persisted calculations.

## 5. Derived state

SLA state is derived from accepted source facts, operator classification, and the active policy. It is not stored as an independently editable truth.

Changing Product Line assignment, severity, effective Report Date, accepted endpoint, suspension, or SLA policy recalculates the current state. Generated exports retain their calculation snapshot and policy context so historical reports do not mutate retroactively.

## 6. Reporting cohorts

SLA reporting groups SRs by:

- month of effective Report Date;
- Product Line;
- severity; and
- state: pending, at risk, met, or breached.

Cancelled SRs are excluded. Weekly progress snapshots are the default SLA operational view, subject to final confirmation of snapshot persistence in low-level design.

## 7. Warnings and safeguards

SOMA exposes separate warnings rather than collapsing them into one generic risk label:

- approaching or passed 85%/100% SLA milestones;
- suspension duration thresholds at 3, 10, 15, and 30 days by default;
- `ResolveBy` and `ResolveBySuspend` inconsistencies;
- missing or passed Suspend Planned End;
- source removal or reversal of a terminal observation, always requiring review; and
- retention review after 180 days, without silently deleting operational evidence.

Threshold presentation is configurable where the product contract permits, but policy truth and audit history are not optional.
