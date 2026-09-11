# RC-001 — Cross-Document Contradiction Report

Status: **RC-001 core scope closed; downstream queue remains**

## Resolved in RC-001

| ID | Finding | Prior risk | Resolution |
|---|---|---|---|
| `RC001-F01` | Objective timeframe presented as if it overwrote every member Task plan | Contradicted independent Task-plan + derived-envelope authority | Product Contract now separates source plan, operational Task plan, Objective envelope, and execution. |
| `RC001-F02` | `Master WFM` wording could imply one unique WFM per branch/timeframe | Conflicted with multiple distinct WFMs per RFC/activity rules | Glossary/Product Contract now define derived RFC context without WFM hierarchy or uniqueness. |
| `RC001-F03` | One-month historical lookback written without source scope | Could incorrectly discard RFC/WFM history | Scoped explicitly to Advanced Search; RFC/WFM omission/age remains non-lifecycle authority. |
| `RC001-F04` | Generic accepted RFC terminal wording could unlink communications before confirmed local cascade | Collapsed imported terminal evidence and local consequence | SR terminal transition and confirmed RFC cascade are now distinguished. |
| `RC001-F05` | Generic hard-deletion statement could be read as granting deletion to any untouched manual entity | Weakened domain-specific deletion allowlists | Product Contract now defers hard-delete eligibility to owning domain rules. |
| `RC001-F06` | Early appearance decision omitted System mode | Stale versus normalized UI theme authority | D-019 reconciled to Light/Dark/System + governed skins. |
| `RC001-F07` | Early timezone decision made `America/Guayaquil` sound globally authoritative | Conflicted with Objective scheduling IANA exception and source profiles | D-021 reconciled to explicit temporal authorities. |
| `RC001-F08` | Advanced Search scheduled check called `operator-timezone` | Could inherit Objective setting accidentally | D-049 fixed to `America/Guayaquil`. |
| `RC001-F09` | Glossary lacked canonical `Contact` while defining `Registered Person` | Could create two person entity types | `Contact` added; `Registered Person` made descriptive/non-separate. |
| `RC001-F10` | Master RFC glossary wording could suggest Local Tasks are master-only | Conflicted with accepted subordinate Local Task links | Definition now reserves master-only rule to direct SR links, not Local Tasks. |
| `RC001-F11` | Canonical brand-asset rights provenance was factually unresolved | Phase 0 proprietary/provenance exit gate could not be proven | Project owner confirmed sole/necessary rights with no surviving third-party material; recorded as D-158. |
| `RC001-F12` | Acceptance boundary omitted System/forced-color wording | Stale UI acceptance synthesis | Product Contract acceptance boundary reconciled to current UI/UX authority. |

## Known downstream findings intentionally not patched in RC-001

These have accepted authority and therefore require no product-owner decision. They remain queued for the owning reconciliation wave:

| Queue ID | Document | Finding | Planned wave |
|---|---|---|---|
| `RCQ-001` | `ARCHITECTURE.md` | Inventory ownership table includes Task outcomes; ownership must move to Objectives/Task lifecycle, with Inventory consuming reviewed physical consequences. | RC-006 |
| `RCQ-002` | `ROADMAP.md` | Status text still says Phase 0 normalization remains despite completed CP-001…CP-007 normalization. | RC-006 |
| `RCQ-003` | `BRANDING.md` | Language-switching deferral sentence is duplicated. | RC-005 |
| `RCQ-004` | Focused contracts | Every focused contract still requires full forward/reverse normalized-authority audit. | RC-002…RC-005 |

## Product-gap result

No RC-001 contradiction requires a new behavior decision after the accepted D-158 provenance clarification.

- Newly opened unresolved product gaps: **0**.
- Known unresolved Phase 0 product contradictions: **0** within reconciled core scope.
- Remaining open `O-*` items are downstream technical-design boundaries, not product gaps.
