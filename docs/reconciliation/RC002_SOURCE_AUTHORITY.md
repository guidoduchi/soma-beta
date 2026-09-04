# SOMA Beta Reconciliation RC-002 — Import and RFC/WFM Source Authority

Status: **Accepted reconciliation record**  
Baseline: `RC-001` commit `a4ec2fe676711c8fde6b267c3eb8759286d22ddd`  
Scope: `docs/IMPORT_CONTRACT.md` and `docs/RFC_WFM_CONTRACT.md`

## Purpose

RC-002 reconciles the two source-facing operational contracts against the accepted normalized requirement catalogue and RC-001 core authority. It repairs representation drift only. It introduces no new source family, lifecycle, relationship, scheduling, or auto-accept behavior.

Primary normalized authority for this checkpoint is `BETA-REQ-0145`–`0177`, together with earlier identity, import, Contact, temporal, and source-specific clauses referenced by those requirements, especially `BETA-REQ-0012`, `0013`, `0030`, `0042`, `0045`, `0050`, `0061`, `0068`, `0070`, `0073`, and `0078`.

## Forward reconciliation result

### Import Contract

The accepted contract continues to represent:

- explicit allowlists and discard boundaries;
- source-family authority and precedence;
- staged observations before mutation;
- identity-based adoption and reconciliation;
- Advanced Search incomplete-record behavior and source-owned current projection;
- RFC/WFM omission neutrality and historical local filtering;
- scheduled Advanced Search discovery in fixed `America/Guayaquil`;
- compact source-delta history;
- reviewed proposal summaries and exact-source presence;
- Infrastructure workbook exchange as operator-authored data rather than a fourth authoritative operational source.

RC-002 repaired these normalized-authority gaps:

1. Safe auto-accept exclusions now explicitly cover terminal, hierarchy, ownership, material timeframe, disappearance/empty-population, and competing-attempt classes while leaving the exact approved low-risk classes open under `O-007`.
2. RFC terminal evidence no longer implies immediate local cascade or Communication unlink. Accepted terminal evidence commits with the pending cascade proposal; cascade confirmation remains separate and protected.
3. Empty authoritative-population behavior is explicitly scoped to source families that actually declare authoritative population semantics; RFC/WFM omission remains non-authoritative.
4. Enhanced RFC `Create Time`, `Creator`, `L1 Handler Name`, and `L2 Handler Name` are represented as active Beta 1.0 source semantics rather than future-only data, matching normalized `IMP-HEAD` authority.
5. RFC `Last Update Time` remains source chronology/recency evidence and no longer claims an age-based historical cutoff.
6. Canonical-plus-suffix RFC source branch artifacts are classified as skipped branch artifacts; other malformed RFC identifiers fail validation rather than being conflated with branch artifacts.
7. WFM source planning is expressed as provider evidence/default reviewed operational-plan candidate; import acceptance never silently schedules or regroups Objectives.
8. Provider-`Complete` historical WFM evidence with a usable accepted source interval may produce a separate reviewed historical-Objective proposal without fabricating execution or Task outcome.

### RFC/WFM Contract

The contract already strongly represented the normalized lifecycle. RC-002 tightened several boundaries:

1. Enhanced RFC branch artifacts are explicitly separated from malformed identities and canonical RFC records.
2. Subordinate-origin SR evidence **proposes** the governing Master/root RFC link; it does not create that relationship before review.
3. Automatic Objective grouping consumes eligible accepted operational Task plans. WFM source plans remain immutable evidence/default candidates rather than direct scheduling authority.
4. Regrouping rejection evidence is described as bounded decision/equivalence evidence rather than an unconstrained retained proposal.
5. Safe auto-accept exclusions and smallest-safe-scope disposition are stated directly in the source-review section.
6. Terminal evidence acceptance, pending cascade creation, deliberate cascade confirmation, and Communication unlink remain distinguishable authorities.

## Reverse reconciliation result

Every material normative assertion added or strengthened by RC-002 traces to accepted requirement/clause authority. No patch depends on implementation convenience, Alpha behavior, or inferred provider semantics.

No assertion in RC-002 selects the exact low-risk auto-accept field/change classes. That remains `O-007` and belongs to Import reconciliation LLD.

No assertion selects exact parser resource ceilings, pagination sizes, file-stabilization timings, or transaction implementation. Those remain LLD details under existing bounds.

## Product-owner decisions

New product-owner decisions opened by RC-002: **0**.

The pre-RC ambiguity state therefore remains unchanged: **0 known unresolved Phase-0 product ambiguities**.

## Result

- Forward requirement coverage: **PASS**
- Reverse authority: **PASS**
- Cross-contract source/lifecycle consistency: **PASS**
- Requirement identities changed: **0**
- Stable clause identities changed: **0**
- Product behavior invented: **0**
- Open design boundaries silently resolved: **0**
