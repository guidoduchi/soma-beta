# SOMA Beta Reconciliation RC-002 — Traceability

Status: **Accepted**  
Scope: Import Contract + RFC/WFM Contract

## Forward authority coverage

| Normalized authority | RC-002 destination | Result |
|---|---|---|
| `BETA-REQ-0012` / RFC identity clauses | Import §5.1; RFC/WFM §3 | Canonical RFC, recognized source branch artifact, and malformed identity are distinct; no truncation/adoption by substring |
| `BETA-REQ-0013` | Import §6.1; RFC/WFM §3 | Canonical `TK` identity preserved |
| `BETA-REQ-0145` | Import §5 discovery; RFC/WFM §1 | One configured directory, stable direct files, deterministic family-specific candidate ordering, invalid-newest visible, manual selection preserved |
| `BETA-REQ-0146` | Import §2; RFC/WFM §§1–2 | Untrusted staging, chronology/fingerprint/replay discipline, omission neutrality |
| `BETA-REQ-0147` | Import §§2–3; RFC/WFM §2 | Status-owned historical presentation; no workbook-presence lifecycle or stop-tracking state |
| `BETA-REQ-0148` | Import §2; RFC/WFM §3 | Exact identity adopts manual records in place; provenance/history preserved |
| `BETA-REQ-0149` | Import §§2, 5.1; RFC/WFM §§2, 6–7 | Closed/Cancelled terminal evidence remains source evidence; acceptance creates pending cascade but does not execute it |
| `BETA-REQ-0150` | Import §§6–7; RFC/WFM §4 | Implement eligibility governs active WFM work; WFM hints cannot override accepted Enhanced pre-Implement truth; no SR fabrication |
| `BETA-REQ-0151` | RFC/WFM §4 | Summary/Task Name SR candidates target existing SRs only; subordinate provenance proposes governing Master/root link |
| `BETA-REQ-0152` | RFC/WFM §4 | Two-level acyclic RFC forest, derived roles, Customer consistency, reviewed reparenting, no arbitrary subordinate cap |
| `BETA-REQ-0153` | RFC/WFM §4 | Archive is reversible local presentation and non-cascading |
| `BETA-REQ-0154` | RFC/WFM §4 | SR↔RFC relationship does not couple lifecycles |
| `BETA-REQ-0155` | Import §7; RFC/WFM §§2–4 | Manual/accepted WFM identity and active/history boundary preserved |
| `BETA-REQ-0156` | Import §§6–8; RFC/WFM §5 | Source plan is optional provider evidence, valid arbitrary-minute pair, source timezone governed, retry uses new Task No. |
| `BETA-REQ-0157` | Import §7; RFC/WFM §5 | Global strict-overlap grouping over eligible accepted Task plans; explanatory Customer/RFC partitions; bridging consolidation |
| `BETA-REQ-0158` | RFC/WFM §5 | Source acceptance and regrouping remain separate exact-revision decisions; lifecycle locks respected |
| `BETA-REQ-0159` | Import §§5–6; RFC/WFM §3 | Versioned closed header semantics; RFC active registry includes Create Time, Creator, Customer, Severity, Owner, L1/L2, Last Update; WFM identity pair required and optional active coverage non-destructive |
| `BETA-REQ-0160` | Import §§2, 6; RFC/WFM §3 | Repeated RFC across distinct Task Nos valid; row-level safe isolation; measured parser/render limits |
| `BETA-REQ-0161` | Import §2; RFC/WFM §6 | Exact-scope confirmed cascade, impact preview, hold/revalidation, atomic local consequence, Objective handling, Communication consequence only after confirmation |
| `BETA-REQ-0163` | RFC/WFM §7 | WFM hierarchy context derives only through owning RFC; no WFM hierarchy/master fields |
| `BETA-REQ-0165` | Import §§5–7; RFC/WFM §§4, 7 | Customer Account Number strongest external evidence; names descriptive; unresolved Customer does not block temporal grouping |
| `BETA-REQ-0166` | RFC/WFM §5 | Local Task identity/optional context; Objective-created initialization does not erase independent Task-plan authority |
| `BETA-REQ-0167` | RFC/WFM §5 | Task plan/actual/outcome separation and mixed Objective outcomes preserved |
| `BETA-REQ-0170` | Import §2; RFC/WFM §§3, 5, 7–8 | Distinct Task Nos stay distinct; same-RFC WFMs may be valid; competing same-lineage attempts require review |
| `BETA-REQ-0171` | Import §7; RFC/WFM §6 | Provider-Complete historical Objective proposal requires usable source interval and fabricates no execution/Inventory consequence |
| `BETA-REQ-0172` | Import §§6–7; RFC/WFM §5 | WFM source plan is immutable default reviewed candidate; source/manual conflict review; clock passage does not lock |
| `BETA-REQ-0176` | Import §2/§10; RFC/WFM §§7–8 | Exact-source staging, presence distinct from acceptance, smallest-safe-scope disposition, restricted auto-accept, independent terminal review, whole-import rejection only for genuine workbook-level failure |
| `BETA-REQ-0177` | Import §§3/8; RFC/WFM §5 | UTC whole-second known instants, source-profile conversion, Objective timezone isolation |

## Reverse assertion audit

| Reconciled assertion | Supporting authority | Result |
|---|---|---|
| RFC terminal source acceptance does not itself unlink Communications | `BETA-REQ-0149`, `0161`, `0176` | Supported |
| Pending terminal cascade is created atomically with accepted terminal evidence but separately confirmed | `BETA-REQ-0149`, `0161`, `0176` | Supported |
| Safe auto-accept excludes terminal/hierarchy/ownership/timeframe/disappearance/empty-population/competing-attempt classes | `BETA-REQ-0176` | Supported; exact allowed classes remain `O-007` |
| RFC `Create Time`, `Creator`, L1 and L2 semantics are active | `BETA-REQ-0159` `IMP-HEAD-054`–`065` | Supported |
| RFC Last Update has chronology authority but no age-based lifecycle cutoff | `BETA-REQ-0146`, `0147`, `0159` | Supported |
| Branch-suffixed RFC source artifact is skipped rather than truncated or treated as subordinate RFC | `BETA-REQ-0012` | Supported |
| Subordinate-origin SR evidence proposes a Master/root relationship | `BETA-REQ-0151`, `0154` | Supported |
| Automatic Objective grouping consumes accepted Task plans, not raw provider plan authority | `BETA-REQ-0157`, `0158`, `0166`, `0172` | Supported |
| Provider Complete may yield reviewed historical Objective proposal without proving execution | `BETA-REQ-0171` | Supported |
| Whole-workbook rejection is exceptional and target-safe isolation is preferred | `BETA-REQ-0176` | Supported |

## Orphan check

- Normalized authority in RC-002 scope without destination representation: **0 known**.
- New normative RC-002 assertion without accepted requirement/clause authority: **0 known**.
- Requirement identity modifications: **0**.
- Stable clause-ID modifications: **0**.

Result: **PASS**.
