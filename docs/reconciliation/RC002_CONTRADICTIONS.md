# SOMA Beta Reconciliation RC-002 — Contradiction Report

Status: **Accepted**

## Resolved in RC-002

### RC002-C01 — RFC terminal evidence was conflated with local Communication unlink

**Before:** Import Contract stated that an accepted terminal SR/RFC observation invoked the transition that removed direct Communication links.

**Authority:** `BETA-REQ-0149`, `0161`, and `0176` separate accepted RFC terminal source evidence from pending cascade creation, deliberate cascade execution, and downstream Communication consequence.

**Resolution:** SR and RFC consequence paths are now distinguished. RFC direct unlink can occur only after confirmed local cascade execution.

### RC002-C02 — Safe auto-accept boundary was under-specified

**Before:** Import Contract explicitly required review for some high-risk changes but did not enumerate the normalized `0176` exclusions.

**Authority:** `BETA-REQ-0176` excludes terminal, hierarchy, ownership, timeframe, disappearance/empty-population, and competing-attempt cases from safe auto-accept.

**Resolution:** Both source contracts now state the exclusions while preserving `O-007` for the exact allowed low-risk field/change classes.

### RC002-C03 — RFC active header semantics were split incorrectly

**Before:** `L1 Handler Name` and `L2 Handler Name` were listed as future-only in Import Contract, while `Create Time` and `Creator` were absent from the active table.

**Authority:** `BETA-REQ-0159` requires active RFC registry semantics for Summary, Status, Create Time, Creator, Customer Account Number/Name, Severity, Owner/Owner Name, L1, L2, and Last Update.

**Resolution:** The four missing/misclassified semantics are active in §5.1. Future-only list now contains only genuinely deferred fields.

### RC002-C04 — RFC Last Update incorrectly implied historical-cutoff authority

**Before:** Enhanced `Last Update Time` was described as driving stale ordering and historical cutoff.

**Authority:** `BETA-REQ-0147` prohibits age/omission-based RFC/WFM lifecycle disappearance. RFC/WFM history is filtered locally by lifecycle/status authority.

**Resolution:** Last Update retains chronology/stale-observation authority only; it creates no age-based RFC lifecycle or cutoff.

### RC002-C05 — RFC source branch artifact classification was incomplete

**Before:** The contract merely said a longer/suffixed RFC identifier was excluded.

**Authority:** `BETA-REQ-0012` distinguishes recognized canonical-plus-suffix source branch artifacts from other malformed identifiers.

**Resolution:** Recognized branch artifacts are staged as review-visible skips, never truncated, never treated as Beta subordinates; other malformed identities fail validation.

### RC002-C06 — Subordinate-origin SR evidence wording implied premature relationship mutation

**Before:** RFC/WFM Contract said subordinate evidence “creates” the direct link to its master even though the preceding rule required review.

**Authority:** `BETA-REQ-0151` requires a non-authoritative candidate and explicit review.

**Resolution:** Wording now says subordinate-origin evidence **proposes** the governing Master/root link and preserves provenance.

### RC002-C07 — Raw source planning could be read as grouping authority

**Before:** RFC/WFM Contract described source planning followed immediately by automatic grouping without explicitly stating the grouping input authority.

**Authority:** `BETA-REQ-0157`, `0158`, `0166`, and `0172` separate WFM source plan, accepted Task plan, Objective envelope, and regrouping acceptance.

**Resolution:** Automatic grouping now explicitly consumes eligible accepted operational Task plans. Source plan remains immutable/default candidate evidence.

### RC002-C08 — Historical Complete-WFM proposal boundary was absent from Import effects

**Before:** Import Contract correctly kept Complete historical but did not state the accepted historical-Objective proposal path.

**Authority:** `BETA-REQ-0171` permits a reviewed historical-Objective proposal only for provider Complete plus usable accepted source interval and forbids fabricated execution/outcome/Inventory effects.

**Resolution:** §7 now cross-represents that path without making it automatic.

## Not contradictions / intentionally left open

- Exact safe auto-accept field/change classes remain `O-007`.
- Exact parser resource ceilings, preview page size, transaction mechanics, workbook version detection, stabilization timings, and file-format implementation remain LLD.
- Exact Objective/Task outcome transition/correction matrix remains `O-003`; RC-002 only preserves already-approved outcome categories and ownership boundaries.

## Downstream queue

No new product ambiguity was opened. Cross-document audits still pending in later checkpoints may reveal stale representations in Workbench, SLA, Communications, Architecture, or other contracts; those documents were intentionally not patched in RC-002.

Result: **0 unresolved RC-002 source-contract contradictions**.
