# SOMA Beta Normalization CP-002 — Catalogue

Status: **Accepted**  
Scope: `BETA-REQ-0028`–`BETA-REQ-0052`  
Source baseline: `docs/BETA_REQUIREMENTS.md` preserves the pre-normalization wording.

## Summary

- Reviewed: **25**
- Replace: **25**
- Retain: **0**
- Requirement identities changed: **0**
- Stable clauses: **275**

For every requirement in CP-002, the normalized obligation below supersedes the earlier wording as the governing obligation while the accepted detail remains normative in `CP002_CLAUSES.md`.

| Beta ID | Disposition | Classification | Accepted governing obligation |
|---|---|---|---|
| `BETA-REQ-0028` | **REPLACE** | Structural invariant; Business rule | Every Contact shall retain an independent SOMA identity that cannot be established, merged, or selected solely from descriptive or matching attributes. |
| `BETA-REQ-0029` | **REPLACE** | Structural invariant; Business rule | A Contact shall preserve one continuous identity independently of Customer Organization affiliation, while affiliation changes and operational organization context remain explicit historical relationships. |
| `BETA-REQ-0030` | **REPLACE** | Business rule; Structural invariant | SOMA Beta shall reconcile reference candidates through deterministic, scope-aware exact matching and shall preserve ambiguity rather than infer identity from approximate similarity. |
| `BETA-REQ-0031` | **REPLACE** | Business rule; Structural invariant | Contact lifecycle operations shall preserve affiliation history, prevent archival from stranding active dependencies, and require explicit reactivation before renewed operational use. |
| `BETA-REQ-0032` | **REPLACE** | Business rule; Structural invariant | Every Spare Request shall preserve its requester as a reusable Contact relationship governed by Contact lifecycle and historical-evidence rules. |
| `BETA-REQ-0033` | **REPLACE** | Business rule; Structural invariant | A Site shall preserve stable Customer Organization ownership and history-safe lifecycle behavior once it participates in operational Infrastructure. |
| `BETA-REQ-0034` | **REPLACE** | Business rule; Structural invariant | Dispatch Location lifecycle shall preserve customer neutrality and historical evidence while preventing archival or active reuse that conflicts with Site or unfinished logistics dependencies. |
| `BETA-REQ-0035` | **REPLACE** | Security/privacy constraint; Structural invariant | The singleton Local User Profile shall provide local administrator authentication without allowing its credentials or profile data to become operational-data encryption authority. |
| `BETA-REQ-0036` | **REPLACE** | Security/privacy constraint; Structural invariant | SOMA Beta shall protect live operational data with authenticated encryption under an independently generated Windows-protected data-encryption key whose lifecycle is separate from administrator authentication credentials. |
| `BETA-REQ-0037` | **REPLACE** | Security/privacy constraint; Quality/platform requirement | SOMA Beta shall export each portable backup as an independently encrypted, self-verifiable backup set with high-entropy recovery and required detached integrity/authenticity artifacts, and shall successfully validate that set before restore may modify live data. |
| `BETA-REQ-0038` | **REPLACE** | Structural invariant; Business rule | Service Requests shall provide pivotal operational context without becoming universal parents, while each related domain entity retains its explicitly governed ownership and relationship path. |
| `BETA-REQ-0039` | **REPLACE** | Structural invariant; Business rule | Direct Service Request relationships shall terminate at master RFCs, with subordinate RFCs inheriting Service Request context exclusively through their master hierarchy. |
| `BETA-REQ-0040` | **REPLACE** | Structural invariant; Business rule | RFCs shall form a strict two-level acyclic master/subordinate hierarchy whose corrections preserve identity, protected history, and inherited operational context. |
| `BETA-REQ-0041` | **REPLACE** | Structural invariant; Business rule | Every WFM shall retain exactly one RFC owner and at most one Objective membership, with unscheduled state and regrouping handled without duplicating WFM identity. |
| `BETA-REQ-0042` | **REPLACE** | Structural invariant; Business rule | Distinct WFM identities shall remain independent attempts, and potentially competing attempts shall be explicitly reviewed without identity collapse or overlapping-Objective workarounds. |
| `BETA-REQ-0043` | **REPLACE** | Structural invariant; Business rule | A persisted Objective shall be a first-class operational entity with one accepted timeframe and at least one Task, without requiring unrelated SR, RFC, Inventory, or Infrastructure context. |
| `BETA-REQ-0044` | **REPLACE** | Structural invariant; UI/UX obligation | An Objective shall derive all Service Request context exclusively through its constituent Tasks and shall expose that relationship provenance without maintaining independent Objective-level SR authority. |
| `BETA-REQ-0045` | **REPLACE** | Business rule; Structural invariant | A Service Request shall not require fabricated operational work and may participate in zero or multiple Objectives solely through its Tasks, subject to the global Task scheduling and grouping rules. |
| `BETA-REQ-0046` | **REPLACE** | Structural invariant; Business rule | Retries shall create new Task attempts linked through immutable predecessor lineage, while Objective retry context and membership shall remain derived from the participating Tasks and normal scheduling rules. |
| `BETA-REQ-0047` | **REPLACE** | Structural invariant; Business rule | Scheduled Objectives and Tasks shall use valid accepted temporal intervals without rounding or invented timestamps, and Objective membership shall require an accepted Task timeframe. |
| `BETA-REQ-0048` | **REPLACE** | Business rule; UI/UX obligation; Structural invariant | Eligible scheduled Tasks shall create or join Objectives through one uniform overlap algorithm, while RFC hierarchy contributes review context and warnings without fabricating or reclassifying work. |
| `BETA-REQ-0049` | **REPLACE** | Structural invariant; Business rule | Device References shall remain independently usable in operational relationships before Infrastructure regularization, with Objective Device context derived through Tasks and all existing relationships preserved when a Device Reference is promoted. |
| `BETA-REQ-0050` | **REPLACE** | Business rule; Structural invariant | Due Objective attempts shall require explicit review while preserving independent Task outcomes, true execution chronology, Inventory fact authority, and the distinction between outcome correction and retry. |
| `BETA-REQ-0051` | **REPLACE** | Functional capability; UI/UX obligation; Business rule | The Objectives workspace shall expose the governed Objective lifecycle and Task-management actions while preserving Task- and domain-owned relationship authority and protected operational history. |
| `BETA-REQ-0052` | **REPLACE** | Business rule; Structural invariant; UI/UX obligation | Service Requests and RFCs shall preserve independently editable Working Notes as SOMA-owned historical evidence whose creation facts, edit history, and audited deletion state remain protected from import reconciliation. |
