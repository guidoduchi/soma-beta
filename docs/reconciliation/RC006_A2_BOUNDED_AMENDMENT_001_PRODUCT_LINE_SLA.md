# RC-006-A2 — Bounded Amendment 001: Product Line/SLA cohort identity

Status: **ACTIVE — semantic contradiction corrected in repository HEAD; B002 remains immutable; corrected assertion supersession deferred until post-initial AMENDMENT allocation**  
Baseline: `A2-BASELINE-002`  
Affected destination: `docs/PRODUCT_LINE_SLA.md` §6 `Reporting cohorts`  
B002 source commit/tree: `61bbd665535e942ef3b05c5ed45661639d3a37a9` / `b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8`  
B002 Product Line/SLA blob: `e5fd8308721ec67ab175a755c7be13021b0114f5`  
Correction commit: `3465d229dd48f43005fc556fd079eb9eb9d91caa`  
Corrected Product Line/SLA blob: `d0169320e60ede8ebde3b675183af620585266ce`

## 1. Trigger

During RC-006-A2 reverse-authority review, B002 `PRODUCT_LINE_SLA.md` §6 represented `current compliance outcome` as an SLA cohort partition dimension.

That representation conflicts with accepted canonical `BETA-REQ-0175` (`SLA-COHORT`). The canonical cohort identity is the contractual population keyed by calendar month, Customer Organization, Contract, Contract Product Line, severity, and policy tier. Compliance outcome/state is derived from that population after membership and denominator authority are established; it is not a cohort-identity dimension.

Treating current compliance outcome as a partition would split one contractual cohort according to its derived result, changing population/denominator semantics and making percentage compliance self-referential.

## 2. Canonical authority

Controlling normalized authority includes:

- `SLA-COHORT-001..004` — canonical SLA cohorts are monthly eligible populations and Cancelled SRs are excluded;
- `SLA-COHORT-009..019` — membership derives from accepted Report Date and fixed `America/Guayaquil` calendar authority;
- `SLA-COHORT-029..049` — canonical partitions are Customer Organization, Contract, Contract Product Line, severity, and policy tier, with calendar month included in the canonical key;
- `SLA-COHORT-050..056` — equivalent keys identify the same current contractual population and individual/cohort state remains separate from cohort identity;
- `SLA-COHORT-059..084` — percentage/result state derives from the canonical cohort population, denominator, policy and deterministic bounds;
- `SLA-COHORT-085..120` — live/final state presentation and Daily/Weekly/range snapshots consume the canonical cohort rather than redefining it.

No requirement identity, clause identity, clause owner, SLA percentage, duration, eligibility rule, or finality rule changes through this correction.

## 3. Exact destination correction

The B002 destination text stated:

> Cohorts partition by at least:
>
> - Customer Organization, Contract, and Contract Product Line;
> - severity;
> - policy tier; and
> - current compliance outcome.

Repository HEAD now states:

> The canonical cohort key is calendar month, Customer Organization, Contract, Contract Product Line, severity, and policy tier. Current compliance outcome is derived from that cohort and is not part of cohort identity or a partition dimension.

Commit `3465d229dd48f43005fc556fd079eb9eb9d91caa` changed exactly one repository path, `docs/PRODUCT_LINE_SLA.md`, with one replacement hunk in §6. Git reports 1 addition / 6 deletions. No other destination text, canonical authority, requirement, or control artifact changed in that correction commit.

## 4. B002 preservation and bounded validity

`A2-BASELINE-002`, its exact source commit/tree, manifest, and recorded Product Line/SLA B002 blob remain unchanged and are never reassigned.

This amendment therefore does not pretend that the corrected HEAD blob was part of B002. Instead:

1. initial Product Line/SLA assertion extraction remains against exact B002 blob `e5fd8308721ec67ab175a755c7be13021b0114f5`;
2. the B002 assertion that includes `current compliance outcome` as a partition dimension shall receive `semantic_review: FAIL` and `contradiction_status: OPEN_FINDING` when its initial assertion identity is allocated;
3. every unaffected B002 assertion remains reviewable against its original exact B002 source span and fingerprint;
4. because the correction commit changes only the identified §6 span, no unaffected Product Line/SLA source assertion is replaced by this amendment;
5. all other B002 source paths and blobs are unaffected by correction commit `3465d229...`;
6. the corrected HEAD sentence is the intended replacement destination representation for later controlled supersession.

This is the explicitly bounded-amendment path permitted by `RC006_A2_EXECUTION_BASELINE.md`: affected evidence is isolated while unaffected assertion/clause evidence remains valid against B002.

## 5. Stable assertion treatment

Extraction Schema V1 prohibits `AMENDMENT` assertion allocation until all 16 initial destination-source batches are complete. The hardened allocator also fails closed for AMENDMENT allocation until an explicit frozen amendment identity rule exists.

Therefore this amendment allocates **no new `A2-ASSERT` identity now** and renumbers/reuses **none**.

After all 16 initial destination sources are allocated:

1. freeze the exact corrected replacement assertion/span from Product Line/SLA blob `d0169320e60ede8ebde3b675183af620585266ce` under an explicit amendment identity rule;
2. allocate the next never-used `A2-ASSERT-######` in `AMENDMENT` mode;
3. map that assertion to `BETA-REQ-0175` / `SLA-COHORT` authority;
4. mark the original contradictory B002 assertion `SUPERSEDED` and cross-link `superseded_by` / `supersedes`;
5. close its contradiction as `RESOLVED_FINDING` only after accumulated validation proves the supersession and unaffected-evidence boundary.

## 6. Product-authority effect

- approved product behavior changed: **0**;
- requirement identities changed: **0**;
- canonical clauses changed: **0**;
- clause owners changed: **0**;
- SLA policy numbers changed: **0**;
- B002 evidence mutated: **0**;
- destination representation contradictions corrected in HEAD: **1**;
- assertion IDs allocated by this amendment now: **0**.

RC-006-A2 certification remains **OPEN**.
