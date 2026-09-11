# SOMA Beta Normalization CP-001 — Clause Authority Matrix

Status: **Accepted — amendment A1 applied**  
Scope: all **183** stable clauses owned by `BETA-REQ-0001`–`BETA-REQ-0027`.  
Purpose: explicit clause-level evidence for the CP-001 reverse-authority audit.

## Reading the matrix

- **Owner** is the normalized requirement under which the clause is stored.
- **Supporting authority** is recorded when the clause also relies on another approved requirement or an already accepted product/design boundary.
- `—` means the owning requirement fully establishes the clause and no additional product authority is required.
- Supporting authority does **not** transfer ownership and does not create new behavior.
- A later normalization of a supporting requirement may change its compact governing wording, but its immutable `BETA-REQ-####` identity remains the authority reference.
- This matrix is evidence only; the normative rule text remains in `CP001_CLAUSES.md`.

## Authority mapping

| Clause | Owner | Supporting authority |
|---|---|---|
| `LINEAGE-001` | `BETA-REQ-0001` | — |
| `LINEAGE-002` | `BETA-REQ-0001` | — |
| `LINEAGE-003` | `BETA-REQ-0001` | — |
| `LINEAGE-004` | `BETA-REQ-0001` | — |
| `RUNTIME-001` | `BETA-REQ-0002` | — |
| `RUNTIME-002` | `BETA-REQ-0002` | — |
| `RUNTIME-003` | `BETA-REQ-0002` | — |
| `RUNTIME-004` | `BETA-REQ-0002` | `BETA-REQ-0004`; Architecture installed-runtime boundary; approved Beta runtime decision |
| `PERSIST-001` | `BETA-REQ-0003` | — |
| `PERSIST-002` | `BETA-REQ-0003` | — |
| `PERSIST-003` | `BETA-REQ-0003` | `BETA-REQ-0009`, `BETA-REQ-0037`, `BETA-REQ-0109`, `BETA-REQ-0131`–`BETA-REQ-0134` |
| `PERSIST-004` | `BETA-REQ-0003` | Product Contract §3 (local/offline operating model) |
| `PLATFORM-001` | `BETA-REQ-0004` | — |
| `PLATFORM-002` | `BETA-REQ-0004` | — |
| `PLATFORM-003` | `BETA-REQ-0004` | `BETA-REQ-0138` |
| `PLATFORM-004` | `BETA-REQ-0004` | — |
| `PLATFORM-005` | `BETA-REQ-0004` | — |
| `DIST-001` | `BETA-REQ-0005` | — |
| `DIST-002` | `BETA-REQ-0005` | — |
| `DIST-003` | `BETA-REQ-0005` | — |
| `DIST-004` | `BETA-REQ-0005` | — |
| `PROVENANCE-001` | `BETA-REQ-0006` | — |
| `PROVENANCE-002` | `BETA-REQ-0006` | — |
| `PROVENANCE-003` | `BETA-REQ-0006` | — |
| `PROVENANCE-004` | `BETA-REQ-0006` | — |
| `PROVENANCE-005` | `BETA-REQ-0006` | `BETA-REQ-0005` |
| `SCM-001` | `BETA-REQ-0007` | — |
| `SCM-002` | `BETA-REQ-0007` | — |
| `SCM-003` | `BETA-REQ-0007` | — |
| `SCM-004` | `BETA-REQ-0007` | — |
| `SCM-005` | `BETA-REQ-0007` | — |
| `SCM-006` | `BETA-REQ-0007` | `BETA-REQ-0130`, `BETA-REQ-0137`, `BETA-REQ-0138`, `BETA-REQ-0141`, `BETA-REQ-0142` |
| `SCM-007` | `BETA-REQ-0007` | — |
| `SCM-008` | `BETA-REQ-0007` | `BETA-REQ-0130`, `BETA-REQ-0137`, `BETA-REQ-0138` |
| `TRACE-001` | `BETA-REQ-0008` | — |
| `TRACE-002` | `BETA-REQ-0008` | — |
| `TRACE-003` | `BETA-REQ-0008` | — |
| `TRACE-004` | `BETA-REQ-0008` | — |
| `TRACE-005` | `BETA-REQ-0008` | `BETA-REQ-0137`; CP-001 normalization doctrine |
| `TRACE-006` | `BETA-REQ-0008` | — |
| `TRACE-007` | `BETA-REQ-0008` | — |
| `TRACE-008` | `BETA-REQ-0008` | `BETA-REQ-0137`; CP-001 normalization doctrine |
| `DEPLOY-001` | `BETA-REQ-0009` | — |
| `DEPLOY-002` | `BETA-REQ-0009` | — |
| `DEPLOY-003` | `BETA-REQ-0009` | — |
| `DEPLOY-004` | `BETA-REQ-0009` | — |
| `DEPLOY-005` | `BETA-REQ-0009` | — |
| `DEPLOY-006` | `BETA-REQ-0009` | `BETA-REQ-0139`, `BETA-REQ-0140` |
| `IDENT-001` | `BETA-REQ-0010` | — |
| `IDENT-002` | `BETA-REQ-0010` | — |
| `IDENT-003` | `BETA-REQ-0010` | — |
| `IDENT-004` | `BETA-REQ-0010` | — |
| `IDENT-005` | `BETA-REQ-0010` | `BETA-REQ-0053`, `BETA-REQ-0092`, `BETA-REQ-0148` |
| `IDENT-006` | `BETA-REQ-0010` | `BETA-REQ-0018`, `BETA-REQ-0131` |
| `SR-ID-001` | `BETA-REQ-0011` | — |
| `SR-ID-002` | `BETA-REQ-0011` | — |
| `SR-ID-003` | `BETA-REQ-0011` | — |
| `SR-ID-004` | `BETA-REQ-0011` | — |
| `SR-ID-005` | `BETA-REQ-0011` | — |
| `SR-ID-006` | `BETA-REQ-0011` | — |
| `SR-ID-007` | `BETA-REQ-0011` | `BETA-REQ-0010`, `BETA-REQ-0053` |
| `RFC-ID-001` | `BETA-REQ-0012` | — |
| `RFC-ID-002` | `BETA-REQ-0012` | — |
| `RFC-ID-003` | `BETA-REQ-0012` | — |
| `RFC-ID-004` | `BETA-REQ-0012` | — |
| `RFC-ID-005` | `BETA-REQ-0012` | — |
| `RFC-ID-006` | `BETA-REQ-0012` | — |
| `RFC-ID-007` | `BETA-REQ-0012` | — |
| `WFM-ID-001` | `BETA-REQ-0013` | — |
| `WFM-ID-002` | `BETA-REQ-0013` | `BETA-REQ-0018`, `BETA-REQ-0155`, `BETA-REQ-0159`, `BETA-REQ-0160` |
| `WFM-ID-003` | `BETA-REQ-0013` | `BETA-REQ-0166` |
| `SPREQ-ID-001` | `BETA-REQ-0014` | — |
| `SPREQ-ID-002` | `BETA-REQ-0014` | — |
| `SPREQ-ID-003` | `BETA-REQ-0014` | — |
| `SPREQ-ID-004` | `BETA-REQ-0014` | — |
| `SPREQ-ID-005` | `BETA-REQ-0014` | — |
| `SPREQ-ID-006` | `BETA-REQ-0014` | — |
| `SPREQ-ID-007` | `BETA-REQ-0014` | — |
| `RMA-001` | `BETA-REQ-0015` | — |
| `RMA-002` | `BETA-REQ-0015` | — |
| `RMA-003` | `BETA-REQ-0015` | — |
| `RMA-004` | `BETA-REQ-0015` | — |
| `RMA-005` | `BETA-REQ-0015` | — |
| `RMA-006` | `BETA-REQ-0015` | — |
| `RMA-007` | `BETA-REQ-0015` | — |
| `RMA-008` | `BETA-REQ-0015` | — |
| `RMA-009` | `BETA-REQ-0015` | — |
| `RMA-010` | `BETA-REQ-0015` | — |
| `SPUNIT-ID-001` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-002` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-003` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-004` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-005` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-006` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-007` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-008` | `BETA-REQ-0016` | — |
| `SPUNIT-ID-009` | `BETA-REQ-0016` | — |
| `TEMP-001` | `BETA-REQ-0017` | `BETA-REQ-0047`, `BETA-REQ-0156`, `BETA-REQ-0177` |
| `TEMP-002` | `BETA-REQ-0017` | `BETA-REQ-0047`, `BETA-REQ-0156` |
| `TEMP-003` | `BETA-REQ-0017` | `BETA-REQ-0047`, `BETA-REQ-0156` |
| `TEMP-004` | `BETA-REQ-0017` | `BETA-REQ-0168`, `BETA-REQ-0172`, `BETA-REQ-0177` |
| `TEMP-005` | `BETA-REQ-0017` | `BETA-REQ-0172`, `BETA-REQ-0177` |
| `TEMP-006` | `BETA-REQ-0017` | `BETA-REQ-0061`, `BETA-REQ-0156`, `BETA-REQ-0177` |
| `TEMP-007` | `BETA-REQ-0017` | `BETA-REQ-0061`, `BETA-REQ-0177` |
| `VALID-001` | `BETA-REQ-0018` | — |
| `VALID-002` | `BETA-REQ-0018` | — |
| `VALID-003` | `BETA-REQ-0018` | — |
| `VALID-004` | `BETA-REQ-0018` | — |
| `VALID-005` | `BETA-REQ-0018` | `BETA-REQ-0136` |
| `VALID-006` | `BETA-REQ-0018` | `BETA-REQ-0131` |
| `VALID-007` | `BETA-REQ-0018` | `BETA-REQ-0132`, `BETA-REQ-0135` |
| `VALID-008` | `BETA-REQ-0018` | `BETA-REQ-0121`, `BETA-REQ-0131`, `BETA-REQ-0135` |
| `VALID-009` | `BETA-REQ-0018` | `BETA-REQ-0132`, `BETA-REQ-0135` |
| `HIST-001` | `BETA-REQ-0019` | — |
| `HIST-002` | `BETA-REQ-0019` | `BETA-REQ-0090`, `BETA-REQ-0129`, `BETA-REQ-0164` |
| `HIST-003` | `BETA-REQ-0019` | `BETA-REQ-0152`, `BETA-REQ-0162` |
| `HIST-004` | `BETA-REQ-0019` | `BETA-REQ-0162` |
| `HIST-005` | `BETA-REQ-0019` | `BETA-REQ-0090`, `BETA-REQ-0092`, `BETA-REQ-0164` |
| `HIST-006` | `BETA-REQ-0019` | `BETA-REQ-0129`, `BETA-REQ-0135` |
| `HIST-007` | `BETA-REQ-0019` | `BETA-REQ-0135`, `BETA-REQ-0143` |
| `HIST-008` | `BETA-REQ-0019` | `BETA-REQ-0057` |
| `HIST-009` | `BETA-REQ-0019` | — |
| `LOG-HIST-001` | `BETA-REQ-0020` | — |
| `LOG-HIST-002` | `BETA-REQ-0020` | — |
| `LOG-HIST-003` | `BETA-REQ-0020` | — |
| `LOG-HIST-004` | `BETA-REQ-0020` | — |
| `LOG-HIST-005` | `BETA-REQ-0020` | `BETA-REQ-0024`, `BETA-REQ-0093` |
| `LOG-HIST-006` | `BETA-REQ-0020` | `BETA-REQ-0093` |
| `REF-001` | `BETA-REQ-0021` | — |
| `REF-002` | `BETA-REQ-0021` | — |
| `REF-003` | `BETA-REQ-0021` | `BETA-REQ-0010`, `BETA-REQ-0028` |
| `REF-004` | `BETA-REQ-0021` | `BETA-REQ-0025`, `BETA-REQ-0029`, `BETA-REQ-0031` |
| `REF-005` | `BETA-REQ-0021` | `BETA-REQ-0022`, `BETA-REQ-0032`, `BETA-REQ-0058` |
| `REF-006` | `BETA-REQ-0021` | `BETA-REQ-0029`, `BETA-REQ-0057` |
| `REF-007` | `BETA-REQ-0021` | `BETA-REQ-0025`, `BETA-REQ-0031`, `BETA-REQ-0033`, `BETA-REQ-0034` |
| `ACTOR-001` | `BETA-REQ-0022` | — |
| `ACTOR-002` | `BETA-REQ-0022` | — |
| `ACTOR-003` | `BETA-REQ-0022` | — |
| `ACTOR-004` | `BETA-REQ-0022` | — |
| `ACTOR-005` | `BETA-REQ-0022` | — |
| `ACTOR-006` | `BETA-REQ-0022` | — |
| `ACTOR-007` | `BETA-REQ-0022` | `BETA-REQ-0035` |
| `DISPATCH-001` | `BETA-REQ-0023` | — |
| `DISPATCH-002` | `BETA-REQ-0023` | — |
| `DISPATCH-003` | `BETA-REQ-0023` | — |
| `DISPATCH-004` | `BETA-REQ-0023` | — |
| `DISPATCH-005` | `BETA-REQ-0023` | — |
| `DISPATCH-006` | `BETA-REQ-0023` | — |
| `DISPATCH-007` | `BETA-REQ-0023` | — |
| `DISPATCH-008` | `BETA-REQ-0023` | — |
| `SITE-DISPATCH-001` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-002` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-003` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-004` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-005` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-006` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-007` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-008` | `BETA-REQ-0024` | — |
| `SITE-DISPATCH-009` | `BETA-REQ-0024` | `BETA-REQ-0020`, `BETA-REQ-0093` |
| `ARCHIVE-001` | `BETA-REQ-0025` | — |
| `ARCHIVE-002` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0033`, `BETA-REQ-0034` |
| `ARCHIVE-003` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0034` |
| `ARCHIVE-004` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0033`, `BETA-REQ-0034` |
| `ARCHIVE-005` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0033`, `BETA-REQ-0034` |
| `ARCHIVE-006` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0034` |
| `ARCHIVE-007` | `BETA-REQ-0025` | `BETA-REQ-0031`, `BETA-REQ-0034` |
| `DISPATCH-CUST-001` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-002` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-003` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-004` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-005` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-006` | `BETA-REQ-0026` | — |
| `DISPATCH-CUST-007` | `BETA-REQ-0026` | — |
| `INFRA-OWN-001` | `BETA-REQ-0027` | — |
| `INFRA-OWN-002` | `BETA-REQ-0027` | — |
| `INFRA-OWN-003` | `BETA-REQ-0027` | — |
| `INFRA-OWN-004` | `BETA-REQ-0027` | `BETA-REQ-0106` |
| `INFRA-OWN-005` | `BETA-REQ-0027` | `BETA-REQ-0106` |
| `INFRA-OWN-006` | `BETA-REQ-0027` | `BETA-REQ-0106` |
| `INFRA-OWN-007` | `BETA-REQ-0027` | `BETA-REQ-0106` |
| `INFRA-OWN-008` | `BETA-REQ-0027` | `BETA-REQ-0049`, `BETA-REQ-0106` |
| `INFRA-OWN-009` | `BETA-REQ-0027` | — |
| `INFRA-OWN-010` | `BETA-REQ-0027` | — |

## Audit result

- Clause rows: **183**
- Unique clause identifiers: **183**
- Clauses whose owner alone is sufficient: **129**
- Clauses with explicit additional supporting authority: **54**
- Clauses without recorded owner authority: **0**
- Cross-cutting clauses without recorded support where additional support was found necessary: **0**

**Reverse-authority evidence: 183/183 PASS.**

The amendment changes no governing obligation, clause rule, requirement identity, disposition, release scope, or product behavior. It records the evidence that was previously implicit.
