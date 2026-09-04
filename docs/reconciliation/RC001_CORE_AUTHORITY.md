# RC-001 — Core Product Authority Reconciliation

Status: **Accepted reconciliation checkpoint content**  
Scope: `DECISIONS.md`, `GLOSSARY.md`, `PRODUCT_CONTRACT.md`  
Method: `RECONCILIATION_METHOD.md`

## 1. Product-owner clarification closed

The project owner confirmed that the canonical SOMA brand assets are owned by the project owner, may be used and distributed under SOMA Beta's proprietary/internal-use terms, and contain no third-party material requiring a surviving third-party license.

This closes the only product-owner ambiguity found in the pre-RC-001 sweep and is recorded as `D-158`.

This clarification implements the already-normalized provenance boundary under `BETA-REQ-0005` and `BETA-REQ-0006`: Beta remains proprietary; Alpha's Apache-2.0 license remains an Alpha-repository property; historical origin is recorded as provenance rather than silently becoming Beta licensing authority.

## 2. Decision Ledger reconciliation

Material patches:

| Decision | RC-001 finding | Reconciliation |
|---|---|---|
| `D-019` | Patch | Add independent Light/Dark/System appearance and governed skins so early wording no longer omits accepted System mode. |
| `D-021` | Contradiction/patch | Scope `America/Guayaquil` to ordinary operational/SLA authority; preserve selected IANA Objective/Task scheduling authority and source-adapter time rules. |
| `D-027` | Patch | Narrow the statement to RFC/WFM/Objective hard-deletion rules rather than reading as a universal domain deletion contract. |
| `D-039` | Contradiction/patch | Scope the one-month terminal-row lookback to Advanced Search; RFC/WFM history does not disappear by age/omission. |
| `D-049` | Patch | Replace ambiguous `operator-timezone` wording with fixed operational timezone `America/Guayaquil`. |
| `D-090` | Contradiction/patch | Distinguish accepted SR terminal transition from the confirmed RFC terminal-cascade decision required before RFC direct communication unlink. |
| `D-152` | Add coverage | Include the first-run built-in skin choice independently from appearance mode. |
| `D-158` | Add coverage | Record accepted proprietary rights/provenance clarification for canonical SOMA brand assets. |

No confirmed decision is renumbered or removed.

## 3. Glossary reconciliation

Material patches:

| Term | Finding | Reconciliation |
|---|---|---|
| Registered Person | Patch | Mark as descriptive phrase for the canonical `Contact` entity, not a second entity type. |
| Contact | Add coverage | Add the canonical reusable operational-person entity explicitly. |
| Master RFC | Patch | Reserve direct SR-link authority to master/root RFCs while making clear Local Tasks may also link to subordinate RFCs. |
| Master WFM | Contradiction/patch | Remove implication of one unique master WFM; the term is a derived WFM role/context from owning RFC and multiple master-owned WFMs may coexist. |
| WFM source plan | Add coverage | Make immutable provider/source planning distinct. |
| Operational Task plan | Add coverage | Make accepted local Task scheduling authority distinct from source plan and Objective envelope. |
| Objective envelope | Add coverage | Define the Objective planned interval as derived from accepted member Task plans rather than as authority that overwrites them. |
| Actual execution interval | Add coverage | Preserve independently accepted execution chronology as distinct from all planning. |

These terms implement accepted temporal and ownership authority from normalized `BETA-REQ-0156`, `0157`, `0166`, `0167`, `0170`, `0172`, and `0177` without selecting LLD state-machine mechanics.

## 4. Product Contract reconciliation

Material corrections:

### 4.1 Authority header

The Product Contract now identifies normalized requirements as its authority and includes all current supporting normative contracts, including RFC/WFM, Foundation Runtime, and Brand/UX.

### 4.2 Brand provenance

The lineage section records the accepted D-158 rights clarification while preserving historical Alpha provenance and Beta's independent proprietary boundary.

### 4.3 Reporting/time authority

Overview/report wording no longer implies that every operator-visible timestamp is globally rendered under one timezone. Ordinary/SLA calendar interpretation remains fixed to `America/Guayaquil`; Objective/Task schedule presentation/grouping uses its selected IANA timezone; source adapters retain source-profile authority; canonical known instants remain UTC whole seconds.

### 4.4 WFM hierarchy context

The Product Contract no longer implies one unique `master WFM` per branch/timeframe. A WFM owned by a master RFC projects master-RFC context; a subordinate-owned WFM projects subordinate context. This role is derived and never becomes a WFM-to-WFM hierarchy or uniqueness constraint.

### 4.5 Task plan versus Objective envelope

The pre-RC statement that every Objective member Task "uses the Objective planned timeframe" contradicted the accepted normalized model.

RC-001 restores the four separate temporal facts:

1. WFM source plan;
2. accepted operational Task plan;
3. derived Objective envelope; and
4. actual execution.

A Task created inside an Objective may initialize its plan from that Objective, but accepted Task planning remains independently reviewable and the Objective envelope is derived from accepted member Task plans. Timezone presentation cannot merge these authorities.

### 4.6 Task lifecycle ownership

The Product Contract now states explicitly that Task execution, outcome, review, correction, cancellation, and retry belong to Objectives/Task lifecycle. Inventory consumes only separately reviewed physical consequences and does not become Task-lifecycle authority.

This is a cross-document ownership invariant required for the later Architecture reconciliation.

### 4.7 Advanced Search historical lookback

The one-month configurable default is explicitly scoped to Advanced Search under its accepted source-specific recency rule. It does not create an RFC/WFM age or omission lifecycle rule.

### 4.8 Terminal communication unlink

The Product Contract distinguishes:

- accepted SR terminal lifecycle transition; and
- confirmed RFC terminal cascade under the RFC/WFM contract.

Parsing, staging, or merely accepting imported RFC terminal evidence does not by itself perform the local RFC communication unlink/cascade consequence.

### 4.9 Hard deletion

The Product Contract now treats hard deletion as an owning-domain allowlist. The generic audit section states the preservation upper bound but does not grant deletion merely because a record appears untouched. Domain-specific rules remain authoritative.

### 4.10 Acceptance presentation

The Beta 1.0 acceptance boundary includes independent Light/Dark/System appearance and high-contrast/forced-color behavior under the accepted UI/UX contract.

## 5. RC-001 result

- Core authority documents reconciled: **3 / 3**.
- Product-owner ambiguities opened: **1**.
- Product-owner ambiguities resolved: **1**.
- Unresolved product contradictions inside RC-001 scope: **0**.
- Open design items resolved by RC-001: **0**.
- Normalized requirement/clause identities modified: **0**.
- New product behavior introduced: **0**.
