# SOMA Beta Reconciliation RC-005 — Communications, UI/UX, Foundation Runtime, and Branding Authority

Status: **Accepted reconciliation record**  
Baseline: `RC-004` commit `6983fa4e3b2e1778448a34e073e5115f6e90636b`  
Scope: `docs/COMMUNICATIONS_CONTRACT.md`, `docs/UI_UX_CONTRACT.md`, `docs/FOUNDATION_RUNTIME_CONTRACT.md`, and `docs/BRANDING.md`

## Purpose

RC-005 reconciles SOMA's cross-cutting operational, interaction, runtime, security-adjacent, verification, and brand presentation contracts against the normalized catalogue and reconciled RC-001 through RC-004 authority. It repairs representation drift only. It introduces no new parser/library choice, cryptographic primitive, Windows/browser/runner/packaging matrix, confirmation-tier expansion, communication source, or product behavior.

Primary authority includes `BETA-REQ-0004`–`0007`, `0072`–`0078`, `0111`–`0144`, `0161`, the accepted provenance decision `D-158`, and the already reconciled owning-domain contracts.

## Communications reconciliation

RC-005 preserves read-only PST/OST operation, the no-target gate, source scopes, durable coverage/high-water state, targeted Backfill and explicit Deep Scan, matched-only canonical persistence, multi-target links, reviewed proposals, hourly-by-default processing, background jobs, MSG draft separation, terminal minimization, orphan grace, purge, and terminal summaries.

It repairs these boundaries:

1. **RFC terminal unlink** — generic terminal wording no longer permits provider terminal evidence or import acceptance to unlink RFC Communications. Only the separately reviewed and confirmed local terminal cascade may remove the RFC's direct links.
2. **Frozen summary timing** — SR summaries freeze at the governed SR unlink; RFC summaries freeze at the confirmed local-cascade unlink, not at provider evidence acceptance or pending-cascade creation.
3. **Other protected links** — terminal handling explicitly removes only the affected entity's direct links and never alters surviving protected relationships.
4. **Parser boundary** — exact PST/OST adapter/library/subset selection remains `O-004`; the contract preserves behavioral requirements without selecting implementation.

## UI/UX reconciliation

The shared interaction contract remains aligned for navigation/opening, scroll ownership, bounded autocomplete, responsive capability preservation, confirmation tiers, semantic tokens/skins, Light/Dark/System appearance, focus/dialog/motion, working-copy conflict/Undo, domain summaries, Inventory actions, visual references, fixtures, and accessibility acceptance.

RC-005 repairs one ownership shorthand: Inventory summaries may display reviewed Task-outcome context and Inventory-owned physical consequences, but Task outcome authority remains with Objectives/Task lifecycle. UI projection never transfers domain ownership.

## Foundation Runtime reconciliation

The Runtime contract remains aligned for SQLite integrity, migrations, read-only migration status, lifecycle/audit/proposal/diagnostic separation, JSON contracts, deterministic verification, loopback runtime safety, diagnostics/redaction, append-only audit, and minimized action-specific payloads.

RC-005 repairs platform representation by stating the fixed Beta 1.0 product support boundary directly: **64-bit Windows 10 and Windows 11 with Python 3.13 and Python 3.14**. Exact Windows editions/builds, browser versions, CI runner images, and packaging combinations remain `O-006` design/verification choices and may not narrow the accepted support boundary without a product decision.

## Branding reconciliation

Branding now represents accepted provenance rather than stale migration/licensing implication:

1. The five canonical SOMA assets are project-owner-owned assets usable under Beta's proprietary/internal boundary.
2. Their Alpha repository history remains provenance only; Alpha Apache-2.0 licensing does not automatically govern the Beta-owned assets.
3. `D-158` records that those canonical assets contain no third-party material requiring surviving third-party licensing.
4. Controlled reuse uses approved owner-controlled source/reference assets and visual comparison rather than recreation from memory.
5. The duplicated language-switching deferral line is removed; language switching remains deferred to 1.x.0 once.
6. Third-party visual references remain directional inspiration only and never asset/trade-dress authority.

## Reverse reconciliation

Every strengthened assertion traces to normalized authority, `D-158`, or an already reconciled owning-domain contract. RC-005 does not resolve `O-004`, `O-005`, `O-006`, `O-007`, or any other open technical design boundary.

## Product-owner decisions

New product-owner decisions opened by RC-005: **0**.

Known unresolved Phase-0 product ambiguities remain: **0**.

## Result

- Forward requirement coverage: **PASS**
- Reverse authority: **PASS**
- Communications/domain lifecycle consistency: **PASS**
- UI/domain ownership consistency: **PASS**
- Runtime/platform-boundary consistency: **PASS**
- Branding/provenance consistency: **PASS**
- Requirement identities changed: **0**
- Stable clause identities changed: **0**
- Product behavior invented: **0**
- Open design boundaries silently resolved: **0**
