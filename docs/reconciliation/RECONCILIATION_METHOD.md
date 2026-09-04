# SOMA Beta Foundation Reconciliation Method

Status: **Accepted working doctrine**  
Applies to: Phase 0 contract reconciliation after completion of requirement normalization  
Normalization baseline: **177 / 177 requirements; 11,524 stable canonical clauses**

## 1. Purpose

Reconciliation aligns every foundation contract and synthesis document to the accepted normalized Beta requirement authority without reopening approved product behavior or inventing implementation design.

Normalization established the product obligations. Reconciliation repairs how those obligations are represented across foundation documents.

A reconciliation edit may:

- correct wording that is broader, narrower, stale, ambiguous, duplicated, or assigned to the wrong owner;
- add missing representation of already-approved authority;
- consolidate duplicated authority by reference;
- remove unsupported normative text;
- convert implementation detail into an explicit HLD/LLD design boundary;
- make release boundaries explicit; and
- preserve a traceable record of every material reconciliation finding.

A reconciliation edit shall not:

- change a `BETA-REQ-####` identity;
- change the owner of a normalized clause;
- weaken or extend accepted behavior without product-owner authority;
- treat Alpha implementation as Beta authority;
- resolve an open technical-design item merely for convenience; or
- allow a downstream synthesis document to override a normalized requirement or owning focused contract.

## 2. Authority order

When wording differs, reconciliation uses this authority order:

1. accepted normalized governing obligations and stable canonical clauses;
2. accepted product-owner clarifications recorded as confirmed decisions;
3. focused normative product contracts within their owning scope;
4. Product Contract and normative Glossary as cross-domain synthesis;
5. Decision Ledger as a stable record of confirmed/deferred/open authority;
6. Architecture and Roadmap as derived synthesis;
7. historical Alpha/Zeus material as non-normative evidence only.

A lower layer may be more specific only inside authority delegated to it. It may not contradict a higher owning authority.

## 3. Finding classifications

Every material statement reviewed receives one of these reconciliation dispositions:

| Disposition | Meaning |
|---|---|
| **Aligned** | Current wording faithfully represents accepted authority. |
| **Patch** | Approved meaning exists but current wording is stale, ambiguous, too broad/narrow, or assigned incorrectly. |
| **Add coverage** | Approved authority is missing from the reviewed document and belongs there. |
| **Consolidate** | Duplicate wording should defer to one governing owner/reference. |
| **Contradiction** | Current wording conflicts with accepted authority and must be corrected before the wave closes. |
| **Unsupported** | Normative wording has no accepted product authority and must be removed, downgraded, or returned to the owner as a gap. |
| **Design boundary** | The product rule is accepted but exact mechanics remain intentionally assigned to HLD/LLD/ADR work. |
| **Deferred** | The behavior is explicitly outside Beta 1.0 and remains in its accepted future-release boundary. |

A `Contradiction` or `Unsupported` finding does not authorize the reconciler to choose new behavior. If normalized authority does not resolve it, the item reopens as a product gap for the project owner.

## 4. Two-pass audit

Each reconciliation target receives two independent passes.

### Pass A — forward reconciliation

For each normalized obligation/clauses relevant to the document:

1. identify the owning `BETA-REQ-####` and canonical clause range;
2. determine whether the document should represent the rule directly or defer to an owning focused contract;
3. verify that meaning, exceptions, lifecycle boundaries, cardinalities, identities, temporal authority, release scope, and owner are preserved;
4. patch missing or conflicting representation; and
5. record the result in the cumulative reconciliation traceability record.

Absence from a high-level synthesis document is valid when the rule is intentionally owned by a focused contract and the synthesis does not contradict it.

### Pass B — reverse reconciliation

For every normative assertion added or retained in the document:

1. identify accepted normalized requirement/clause or confirmed decision authority;
2. verify that the assertion does not silently add a product rule;
3. verify that design mechanics are labelled and bounded where exact implementation remains open; and
4. remove, downgrade, defer, or reopen any assertion without authority.

The final Phase 0 reconciliation matrix must support both directions:

`stable clause → owning requirement → destination contracts → reconciliation result`

and

`normative contract assertion → supporting normalized/decision authority`.

## 5. Cross-document audit

After focused passes, reconciliation explicitly checks:

- canonical terminology and aliases;
- identity and cardinality;
- lifecycle ownership and transition authority;
- Task/Objective/Inventory ownership boundaries;
- temporal authority and timezone scope;
- source-of-truth and derived-projection boundaries;
- correction, archival, deletion, replacement, resend, and retention semantics;
- source/import presence versus accepted mutation versus downstream consequence;
- Beta 1.0 versus 1.x/1.1 scope;
- UI presentation versus domain authority;
- security/trust boundaries;
- duplicate ownership; and
- design detail accidentally presented as product authority.

## 6. Reconciliation waves

### Wave A — authority and vocabulary

1. `DECISIONS.md`
2. `GLOSSARY.md`
3. `PRODUCT_CONTRACT.md`

### Wave B — Tickets and operational work

4. `IMPORT_CONTRACT.md`
5. `RFC_WFM_CONTRACT.md`
6. `WORKBENCH_CONTRACT.md`
7. `PRODUCT_LINE_SLA.md`

### Wave C — physical domains

8. `INVENTORY_LIFECYCLE.md`
9. `INFRASTRUCTURE_CONTRACT.md`

### Wave D — cross-cutting product/runtime presentation

10. `COMMUNICATIONS_CONTRACT.md`
11. `UI_UX_CONTRACT.md`
12. `FOUNDATION_RUNTIME_CONTRACT.md`
13. `BRANDING.md`

### Wave E — derived synthesis

14. `ARCHITECTURE.md`
15. `ROADMAP.md`
16. repository-facing foundation indexes/status text where required

Architecture is reconciled after owning contracts so it assigns already-reconciled ownership rather than becoming a competing product authority.

## 7. Checkpoint naming

- `CP-*` remains reserved for the completed requirement-normalization lineage.
- `RC-*` identifies foundation reconciliation checkpoints.
- Later use-case and architecture checkpoints shall use their own stable prefixes rather than reusing `CP-*`.

## 8. Phase 0 closure rule

Reconciliation is complete only when:

- every normative foundation document has received forward and reverse audit;
- known cross-document contradictions are zero;
- unsupported product behavior is zero;
- any newly discovered genuine product gap is explicitly resolved/rejected/deferred by the project owner;
- all remaining open items are bounded downstream design questions rather than missing product decisions;
- terminology and release boundaries agree; and
- the project owner explicitly accepts Phase 0 closure.
