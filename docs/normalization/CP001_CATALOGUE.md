# SOMA Beta Normalization CP-001 — Catalogue

Status: **Accepted**  
Scope: `BETA-REQ-0001`–`BETA-REQ-0027`  
Source baseline: `docs/BETA_REQUIREMENTS.md` preserves the pre-normalization wording.

## Summary

- Reviewed: **27**
- Replace: **26**
- Retain: **1** (`BETA-REQ-0013`)
- Requirement identities changed: **0**
- Stable clauses: **183**

For **REPLACE**, the obligation below supersedes the earlier wording as the governing obligation while the accepted detail remains normative in `CP001_CLAUSES.md`. For **RETAIN**, the source wording remains governing.

| Beta ID | Disposition | Classification | Accepted governing obligation |
|---|---|---|---|
| `BETA-REQ-0001` | **REPLACE** | Structural invariant; Quality/platform requirement | SOMA Beta shall maintain an independent product, repository, persistence, migration, and release lineage from Zeus and SOMA Alpha. |
| `BETA-REQ-0002` | **REPLACE** | Functional capability; Quality/platform requirement | SOMA Beta shall provide its primary operator experience through a locally served web interface backed by a Python application boundary. |
| `BETA-REQ-0003` | **REPLACE** | Quality/platform requirement; Structural invariant | SOMA Beta shall maintain its authoritative operational data through application-managed local persistence without requiring a separately administered database service. |
| `BETA-REQ-0004` | **REPLACE** | Quality/platform requirement | SOMA Beta 1.0 shall support 64-bit Windows 10 and Windows 11 with Python 3.13 and Python 3.14 as its required platform matrix; other operating systems are outside the Beta 1.0 support boundary. |
| `BETA-REQ-0005` | **REPLACE** | Security/privacy constraint; Quality/platform requirement | SOMA Beta source code, documentation, owned brand assets, and release artifacts shall remain proprietary and restricted to authorized internal use. |
| `BETA-REQ-0006` | **REPLACE** | Structural invariant; Quality/platform requirement | SOMA Beta shall preserve explicit provenance for reused canonical brand assets while keeping Beta’s proprietary licensing boundary independent from SOMA Alpha’s Apache-2.0 license. |
| `BETA-REQ-0007` | **REPLACE** | Security/privacy constraint; Quality/platform requirement | SOMA Beta source control shall exclude operational, customer, secret, runtime, persistence, communication, diagnostic, backup, export, and generated operational material. |
| `BETA-REQ-0008` | **REPLACE** | Structural invariant; Quality/platform requirement | SOMA Beta shall preserve complete bidirectional traceability from historical product authority through approved Beta requirements, design ownership, implementation scope, and acceptance evidence. |
| `BETA-REQ-0009` | **REPLACE** | Functional capability; Quality/platform requirement | SOMA Beta shall provide a repeatable supported local setup and explicit operator controls for starting and stopping the application. |
| `BETA-REQ-0010` | **REPLACE** | Structural invariant | Every persistent SOMA Beta entity shall retain an immutable opaque internal identity independent of its business identifiers. |
| `BETA-REQ-0011` | **REPLACE** | Structural invariant; Business rule | A Service Request shall retain one canonical business identity appropriate to its lifecycle: an eight-digit official identifier when assigned, or a non-reusable SOMA local identifier while official identity is absent. |
| `BETA-REQ-0012` | **REPLACE** | Business rule; Structural invariant | SOMA Beta shall enforce exact canonical RFC identity while distinguishing recognized non-mutating source branch artifacts from other malformed RFC identifiers. |
| `BETA-REQ-0013` | **RETAIN** | Structural invariant | A WFM business identifier shall consist of `TK` followed by exactly fourteen decimal digits. |
| `BETA-REQ-0014` | **REPLACE** | Structural invariant; Business rule | Every Spare Request shall retain one stable SOMA identity across its locally tracked and officially identified lifecycle. |
| `BETA-REQ-0015` | **REPLACE** | Structural invariant; Business rule | An RMA shall represent one independently identified replacement-and-return obligation under exactly one officially identified Spare Request, without becoming the identity of any physical unit. |
| `BETA-REQ-0016` | **REPLACE** | Structural invariant; Business rule | Every Spare Part Unit shall retain an immutable SOMA local identity independent of whether official request, RMA, or manufacturer-serial provenance is known. |
| `BETA-REQ-0017` | **REPLACE** | Structural invariant; Business rule | SOMA Beta shall preserve exact canonical temporal meaning and arbitrary-minute precision for Task and Objective scheduling. |
| `BETA-REQ-0018` | **REPLACE** | Structural invariant; Quality/platform requirement | SOMA Beta shall enforce all structural and domain invariants transactionally across every persistent mutation path. |
| `BETA-REQ-0019` | **REPLACE** | Business rule; Structural invariant | SOMA Beta 1.0 shall preserve material operational history by default and permit hard deletion only through explicitly authorized domain rules. |
| `BETA-REQ-0020` | **REPLACE** | Structural invariant; Business rule | SOMA Beta shall preserve immutable historical logistics truth independently of later changes to mutable Dispatch Location master data. |
| `BETA-REQ-0021` | **REPLACE** | Functional capability; Business rule | SOMA Beta shall provide reusable Customer Organization and Contact records with governed creation, maintenance, and lifecycle behavior across operational workflows. |
| `BETA-REQ-0022` | **REPLACE** | Structural invariant; Security/privacy constraint | SOMA Beta shall separate its single installation authentication identity from reusable Contact identities representing operational people and roles. |
| `BETA-REQ-0023` | **REPLACE** | Structural invariant; Business rule | A Dispatch Location shall represent reusable physical logistics location identity independently from its operation-specific role, Customer Organization context, or Datacenter Site identity. |
| `BETA-REQ-0024` | **REPLACE** | Structural invariant; Business rule | Every Datacenter Site shall retain a distinct, dedicated Dispatch Location relationship through which its current logistics address is represented. |
| `BETA-REQ-0025` | **REPLACE** | Business rule; Structural invariant | Reference records with protected operational history shall support history-preserving archival instead of destructive removal. |
| `BETA-REQ-0026` | **REPLACE** | Structural invariant; Business rule | Dispatch Locations shall remain Customer-Organization-neutral physical logistics references regardless of any customer context derived through an optional linked Site. |
| `BETA-REQ-0027` | **REPLACE** | Structural invariant; Business rule | SOMA Beta shall anchor regularized Infrastructure ownership and placement to Customer-owned physical Sites while keeping Cloud Types reusable and provisional Device References independently usable before regularization. |
