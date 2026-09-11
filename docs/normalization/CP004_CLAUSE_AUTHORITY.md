# SOMA Beta Normalization CP-004 — Clause Authority Matrix

Status: **Accepted**  
Scope: all **1383** stable clauses owned by `BETA-REQ-0078`–`BETA-REQ-0102`.  
Purpose: explicit owner/supporting-authority evidence for the CP-004 reverse audit.

## Owner mapping

Every clause in each inclusive range has exactly one listed owner. Range notation is clause-level evidence and does not transfer ownership to supporting requirements.

| Clause range | Owner |
|---|---|
| `ADMIN-SETUP-001..067` | `BETA-REQ-0078` |
| `SPNEED-001..021` | `BETA-REQ-0079` |
| `DEV-PART-001..029` | `BETA-REQ-0080` |
| `SPNEED-LIFE-001..027` | `BETA-REQ-0081` |
| `SPREQ-CTX-001..032` | `BETA-REQ-0082` |
| `SPREQ-SUBMIT-001..036` | `BETA-REQ-0083` |
| `RMA-BRIDGE-001..039` | `BETA-REQ-0084` |
| `SPUNIT-PHYS-001..040` | `BETA-REQ-0085` |
| `SPUNIT-REG-001..036` | `BETA-REQ-0086` |
| `SPUNIT-ALLOC-001..036` | `BETA-REQ-0087` |
| `INV-EVENT-001..047` | `BETA-REQ-0088` |
| `INV-COMM-001..044` | `BETA-REQ-0089` |
| `INV-MANUAL-001..062` | `BETA-REQ-0090` |
| `SPREQ-ORIGIN-001..066` | `BETA-REQ-0091` |
| `INV-ID-001..064` | `BETA-REQ-0092` |
| `INV-LOG-001..061` | `BETA-REQ-0093` |
| `FT-SCOPE-001..064` | `BETA-REQ-0094` |
| `FT-ID-001..073` | `BETA-REQ-0095` |
| `FT-MEMBER-001..070` | `BETA-REQ-0096` |
| `FT-REL-001..097` | `BETA-REQ-0097` |
| `FT-REPLACE-001..078` | `BETA-REQ-0098` |
| `FT-WH-001..092` | `BETA-REQ-0099` |
| `FT-REMOVE-001..089` | `BETA-REQ-0100` |
| `FT-LOG-001..080` | `BETA-REQ-0101` |
| `INFRA-TERM-001..033` | `BETA-REQ-0102` |

## Additional supporting authority

Clauses absent from this table are fully established by their owner. Supporting authority strengthens provenance only; it does not transfer ownership or authorize new product behavior.

| Clause range | Supporting authority |
|---|---|
| `ADMIN-SETUP-001..003` | `BETA-REQ-0010`; `BETA-REQ-0022`; `BETA-REQ-0035` |
| `ADMIN-SETUP-004..015` | `BETA-REQ-0022`; `BETA-REQ-0035` |
| `ADMIN-SETUP-018..022` | `BETA-REQ-0017`; `BETA-REQ-0061`; `BETA-REQ-0177` |
| `ADMIN-SETUP-031..035` | `BETA-REQ-0065`; `BETA-REQ-0075` |
| `ADMIN-SETUP-038..045` | `BETA-REQ-0035` |
| `ADMIN-SETUP-046..049` | `BETA-REQ-0036` |
| `ADMIN-SETUP-050..053` | `BETA-REQ-0037` |
| `ADMIN-SETUP-055..060` | `BETA-REQ-0037` |
| `ADMIN-SETUP-061..066` | Technical design item `O-005` — algorithms, parameters, recovery/rotation/restore details remain Security LLD decisions |
| `SPNEED-LIFE-016..027` | `BETA-REQ-0019`; `BETA-REQ-0072`; `BETA-REQ-0077` |
| `SPREQ-CTX-001..005` | `BETA-REQ-0010`; `BETA-REQ-0014` |
| `SPREQ-CTX-013..015` | `BETA-REQ-0027`; `BETA-REQ-0065`; `BETA-REQ-0075` |
| `SPREQ-CTX-016..019` | `BETA-REQ-0032`; `BETA-REQ-0067` |
| `SPREQ-CTX-020..025` | `BETA-REQ-0023`; `BETA-REQ-0026` |
| `SPREQ-CTX-026..030` | `BETA-REQ-0014` |
| `SPREQ-SUBMIT-011..036` | `BETA-REQ-0082`; `BETA-REQ-0089`; `BETA-REQ-0091` |
| `RMA-BRIDGE-001..003` | `BETA-REQ-0010`; `BETA-REQ-0015` |
| `RMA-BRIDGE-008..014` | `BETA-REQ-0015` |
| `RMA-BRIDGE-019..027` | `BETA-REQ-0015`; `BETA-REQ-0087` |
| `RMA-BRIDGE-028..039` | `BETA-REQ-0015`; `BETA-REQ-0092` |
| `SPUNIT-PHYS-010..015` | `BETA-REQ-0015`; `BETA-REQ-0016` |
| `SPUNIT-PHYS-021..030` | `BETA-REQ-0083`; `BETA-REQ-0084` |
| `SPUNIT-PHYS-037` | `BETA-REQ-0046`; `BETA-REQ-0050`; accepted HLD ownership correction boundary |
| `SPUNIT-REG-011..016` | `BETA-REQ-0010`; `BETA-REQ-0016` |
| `SPUNIT-REG-021..022` | `BETA-REQ-0016`; `BETA-REQ-0084` |
| `SPUNIT-ALLOC-001..010` | `BETA-REQ-0046`; `BETA-REQ-0048`; `BETA-REQ-0050` |
| `SPUNIT-ALLOC-011..036` | `BETA-REQ-0015`; `BETA-REQ-0046`; `BETA-REQ-0050`; `BETA-REQ-0084` |
| `INV-EVENT-016..017` | `BETA-REQ-0099` |
| `INV-EVENT-018..033` | `BETA-REQ-0019`; `BETA-REQ-0090`; `BETA-REQ-0092` |
| `INV-EVENT-034..047` | `BETA-REQ-0019`; `BETA-REQ-0090`; `BETA-REQ-0099` |
| `INV-COMM-001..044` | `BETA-REQ-0067`; `BETA-REQ-0083`; `BETA-REQ-0088`; technical design item `O-004` for exact PST/OST/MSG library/subset |
| `INV-MANUAL-001..014` | `BETA-REQ-0088`; `BETA-REQ-0089` |
| `INV-MANUAL-015..022` | `BETA-REQ-0089` |
| `INV-MANUAL-037..055` | `BETA-REQ-0088`; `BETA-REQ-0092` |
| `INV-MANUAL-056..062` | `BETA-REQ-0010`; `BETA-REQ-0092` |
| `SPREQ-ORIGIN-001..022` | `BETA-REQ-0082`; `BETA-REQ-0083` |
| `SPREQ-ORIGIN-023..036` | `BETA-REQ-0083`; `BETA-REQ-0089`; `BETA-REQ-0090` |
| `SPREQ-ORIGIN-053..060` | `BETA-REQ-0014`; `BETA-REQ-0089`; `BETA-REQ-0092` |
| `SPREQ-ORIGIN-061..066` | `BETA-REQ-0092` |
| `INV-ID-001..021` | `BETA-REQ-0010`; `BETA-REQ-0014`; `BETA-REQ-0015`; `BETA-REQ-0016`; `BETA-REQ-0084`; `BETA-REQ-0085`; `BETA-REQ-0086` |
| `INV-ID-022..049` | `BETA-REQ-0088`; `BETA-REQ-0090` |
| `INV-ID-050..057` | `BETA-REQ-0014`; `BETA-REQ-0015`; `BETA-REQ-0084` |
| `INV-ID-061..064` | `BETA-REQ-0019`; `BETA-REQ-0090` |
| `INV-LOG-001..018` | `BETA-REQ-0083`; `BETA-REQ-0091` |
| `INV-LOG-019..025` | `BETA-REQ-0085`; `BETA-REQ-0088`; `BETA-REQ-0089`; `BETA-REQ-0090` |
| `INV-LOG-026..031` | `BETA-REQ-0090`; `BETA-REQ-0092` |
| `INV-LOG-032..038` | `BETA-REQ-0089` |
| `INV-LOG-039..050` | `BETA-REQ-0020`; `BETA-REQ-0023`; `BETA-REQ-0024`; `BETA-REQ-0091` |
| `INV-LOG-051..061` | `BETA-REQ-0085`; `BETA-REQ-0086` |
| `FT-SCOPE-010..015` | `BETA-REQ-0087`; `BETA-REQ-0088` |
| `FT-SCOPE-016..025` | `BETA-REQ-0088`; `BETA-REQ-0090`; `BETA-REQ-0092` |
| `FT-SCOPE-026..045` | `BETA-REQ-0088`; `BETA-REQ-0089`; `BETA-REQ-0090`; `BETA-REQ-0095`; `BETA-REQ-0099` |
| `FT-ID-007..015` | `BETA-REQ-0092` |
| `FT-ID-018..034` | `BETA-REQ-0020`; `BETA-REQ-0023`; `BETA-REQ-0026`; `BETA-REQ-0093`; `BETA-REQ-0101` |
| `FT-ID-035..073` | `BETA-REQ-0088`; `BETA-REQ-0089`; `BETA-REQ-0090`; `BETA-REQ-0094`; `BETA-REQ-0098` |
| `FT-MEMBER-001..020` | `BETA-REQ-0084`; `BETA-REQ-0087`; `BETA-REQ-0094` |
| `FT-MEMBER-031..059` | `BETA-REQ-0090`; `BETA-REQ-0092`; `BETA-REQ-0094` |
| `FT-MEMBER-060..070` | **Explicit project-owner amendment during normalization of `BETA-REQ-0096`** — approved substitute BOMs may be provider-implied or operator-confirmed; mismatch warns rather than automatically rejects |
| `FT-REL-001..017` | `BETA-REQ-0010`; `BETA-REQ-0092`; `BETA-REQ-0096` |
| `FT-REL-018..033` | `BETA-REQ-0049`; `BETA-REQ-0082`; `BETA-REQ-0084`; `BETA-REQ-0102` |
| `FT-REL-039..041` | `BETA-REQ-0092` |
| `FT-REL-042..052` | **Explicit project-owner amendment during normalization of `BETA-REQ-0096`**; `BETA-REQ-0092` |
| `FT-REL-053..097` | `BETA-REQ-0092`; `BETA-REQ-0095`; `BETA-REQ-0098` |
| `FT-REPLACE-005..022` | `BETA-REQ-0095` |
| `FT-REPLACE-023..044` | `BETA-REQ-0092`; `BETA-REQ-0096`; `BETA-REQ-0097` |
| `FT-REPLACE-045` | **Explicit project-owner amendment during normalization of `BETA-REQ-0096`** |
| `FT-REPLACE-046..078` | `BETA-REQ-0019`; `BETA-REQ-0072`; `BETA-REQ-0077`; `BETA-REQ-0090`; `BETA-REQ-0092`; `BETA-REQ-0099` |
| `FT-WH-001..025` | `BETA-REQ-0088`; `BETA-REQ-0094`; `BETA-REQ-0096` |
| `FT-WH-026..036` | `BETA-REQ-0089`; `BETA-REQ-0090` |
| `FT-WH-044..051` | `BETA-REQ-0089`; `BETA-REQ-0090` |
| `FT-WH-052..080` | `BETA-REQ-0017`; `BETA-REQ-0061`; `BETA-REQ-0088`; `BETA-REQ-0090`; `BETA-REQ-0092`; future Temporal Contract boundary |
| `FT-WH-088..092` | `BETA-REQ-0098` |
| `FT-REMOVE-009..068` | `BETA-REQ-0019`; `BETA-REQ-0072`; `BETA-REQ-0077`; `BETA-REQ-0092`; `BETA-REQ-0098`; `BETA-REQ-0099` |
| `FT-REMOVE-069..086` | `BETA-REQ-0018`; `BETA-REQ-0019`; `BETA-REQ-0090` |
| `FT-LOG-001..080` | `BETA-REQ-0020`; `BETA-REQ-0023`; `BETA-REQ-0024`; `BETA-REQ-0026`; `BETA-REQ-0093`; `BETA-REQ-0095`; `BETA-REQ-0098`; `BETA-REQ-0099` |
| `INFRA-TERM-004..015` | `BETA-REQ-0027`; `BETA-REQ-0049`; `BETA-REQ-0075`; `BETA-REQ-0097` |
| `INFRA-TERM-016..033` | `BETA-REQ-0010`; `BETA-REQ-0027`; `BETA-REQ-0049` |

## Audit totals

- Clauses: **1383**
- Owner ranges: **25**
- Owner alone sufficient: **288**
- Explicit additional supporting authority/design boundary: **1095**
- Missing owners: **0**
- Overlapping owner ranges: **0**
- Unexplained clauses: **0**

The substitute rules in `FT-MEMBER-060..070`, the no-copy/current-truth consequences in `FT-REL-042..052`, and replacement revalidation in `FT-REPLACE-045` preserve the project owner's explicit normalization-time clarification: exact BOM equality is neither necessary nor sufficient for compatibility; provider-dispatched different-BOM fulfillment may establish provider-approved substitute evidence, and an operator may explicitly approve a warned different-BOM substitute without rewriting any physical or historical BOM facts.

The known preliminary-HLD wording that assigns “Task outcomes” to Inventory remains a design defect only. CP-004 preserves Objectives/Task lifecycle as the owner of execution/outcome/review/correction/retry facts; Inventory owns only Task-to-unit allocation and physical consequences derived from reviewed outcomes.

**Reverse-authority result: 1383/1383 PASS.**
