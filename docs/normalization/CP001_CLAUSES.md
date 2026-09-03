# SOMA Beta Normalization CP-001 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0001`–`BETA-REQ-0027`.  
Clause identities are stable normative references. They preserve the detailed mechanics removed from compact governing obligations.

## `BETA-REQ-0001`

**Governing obligation:** SOMA Beta shall maintain an independent product, repository, persistence, migration, and release lineage from Zeus and SOMA Alpha.

- **`LINEAGE-001`** — SOMA Beta owns an independent product, repository, persistence schema, migration lineage, and release history.
- **`LINEAGE-002`** — Zeus and SOMA Alpha are historical sources and shall not constitute executable, persistence, migration, or release ancestors of SOMA Beta.
- **`LINEAGE-003`** — Any artifact, behavior, asset, or implementation concept originating from Zeus or SOMA Alpha shall require explicit Beta evaluation before reuse.
- **`LINEAGE-004`** — Reuse of an approved historical artifact shall not imply compatibility, schema continuity, migration continuity, data continuity, or inheritance of unrelated historical behavior.

## `BETA-REQ-0002`

**Governing obligation:** SOMA Beta shall provide its primary operator experience through a locally served web interface backed by a Python application boundary.

- **`RUNTIME-001`** — SOMA Beta shall expose its primary operator interface through a locally served web application.
- **`RUNTIME-002`** — The application backend and authoritative domain/application execution boundary shall run in Python.
- **`RUNTIME-003`** — The browser interface shall act as a client of the local application boundary rather than owning authoritative domain behavior.
- **`RUNTIME-004`** — Frontend build tooling shall not require Node.js as an installed end-user runtime.

## `BETA-REQ-0003`

**Governing obligation:** SOMA Beta shall maintain its authoritative operational data through application-managed local persistence without requiring a separately administered database service.

- **`PERSIST-001`** — SOMA Beta shall maintain its authoritative operational persistence locally within the installation.
- **`PERSIST-002`** — Normal installation and operation shall not require the operator to deploy, configure, operate, or maintain a separate database server or database service.
- **`PERSIST-003`** — SOMA shall own the supported creation, opening, migration, integrity verification, backup, recovery, and shutdown boundaries of its local operational datastore.
- **`PERSIST-004`** — Loss or absence of network connectivity shall not prevent access to locally available authoritative operational data except where an explicitly external source is required for a separate import/export action.

## `BETA-REQ-0004`

**Governing obligation:** SOMA Beta 1.0 shall support 64-bit Windows 10 and Windows 11 with Python 3.13 and Python 3.14 as its required platform matrix; other operating systems are outside the Beta 1.0 support boundary.

- **`PLATFORM-001`** — Beta 1.0 shall support 64-bit Windows 10 and Windows 11.
- **`PLATFORM-002`** — Beta 1.0 shall support Python 3.13 and Python 3.14.
- **`PLATFORM-003`** — The accepted verification strategy shall demonstrate supported operation across the required Windows/Python combinations rather than validating only one preferred pairing.
- **`PLATFORM-004`** — Operating systems outside the accepted Windows 10/11 boundary are not Beta 1.0 support targets.
- **`PLATFORM-005`** — Exact Windows editions/builds, browser versions, CI runner images, and packaging combinations remain design details and shall not narrow the approved product support boundary without an explicit product decision.

## `BETA-REQ-0005`

**Governing obligation:** SOMA Beta source code, documentation, owned brand assets, and release artifacts shall remain proprietary and restricted to authorized internal use.

- **`DIST-001`** — SOMA Beta source code, documentation, owned brand assets, and release artifacts shall be proprietary material.
- **`DIST-002`** — Access and distribution shall be limited to the authorized internal team unless an explicit later authority changes that scope.
- **`DIST-003`** — Repository visibility, packaging method, or storage location shall not redefine the proprietary/internal distribution boundary.
- **`DIST-004`** — No SOMA Beta artifact shall be intentionally published or redistributed outside the authorized scope merely because it is technically exportable or buildable.

## `BETA-REQ-0006`

**Governing obligation:** SOMA Beta shall preserve explicit provenance for reused canonical brand assets while keeping Beta’s proprietary licensing boundary independent from SOMA Alpha’s Apache-2.0 license.

- **`PROVENANCE-001`** — Canonical SOMA brand assets reused in Beta shall have their ownership and provenance recorded within the Beta product records.
- **`PROVENANCE-002`** — Where the project owner possesses the required rights, those canonical brand assets shall be incorporated into Beta under the proprietary Beta distribution boundary.
- **`PROVENANCE-003`** — The existing Apache-2.0 licensing of SOMA Alpha shall remain an Alpha-repository property and shall not automatically govern SOMA Beta.
- **`PROVENANCE-004`** — Historical derivation, conceptual reuse, or repository ancestry shall not by itself cause Beta source, documentation, releases, or independently owned assets to inherit Alpha’s license.
- **`PROVENANCE-005`** — Any reused artifact that carries surviving third-party or license obligations shall retain whatever notices or attribution are legally required for that artifact, without expanding those obligations to unrelated Beta material.

## `BETA-REQ-0007`

**Governing obligation:** SOMA Beta source control shall exclude operational, customer, secret, runtime, persistence, communication, diagnostic, backup, export, and generated operational material.

- **`SCM-001`** — Operational and customer data shall not be committed to source control.
- **`SCM-002`** — Imported workbooks, PST/OST content, retained communications, generated MSG artifacts, and other operational evidence shall not be committed.
- **`SCM-003`** — Credentials, passwords, cryptographic keys, recovery material, tokens, and equivalent secrets shall not enter source control.
- **`SCM-004`** — Runtime state, local settings containing operational data, locks, process registries, temporary persistence, and other machine-local state shall not be committed.
- **`SCM-005`** — Operational databases, WAL/journals, backups, snapshots, and recovery artifacts shall not be committed.
- **`SCM-006`** — Operational logs and diagnostics shall not be committed, even if redacted for ordinary runtime use, unless they are intentionally fabricated sanitized test fixtures.
- **`SCM-007`** — Operational exports, reports, generated drafts, and similar outputs shall not be committed.
- **`SCM-008`** — Only deliberately synthetic or irreversibly sanitized governed fixtures may represent such data classes in the repository.

## `BETA-REQ-0008`

**Governing obligation:** SOMA Beta shall preserve complete bidirectional traceability from historical product authority through approved Beta requirements, design ownership, implementation scope, and acceptance evidence.

- **`TRACE-001`** — Every catalogued merged Alpha requirement and decision, explicitly identified unmerged Alpha proposal, and approved user-facing Zeus capability shall receive an explicit Beta disposition before Beta 1.0 acceptance.
- **`TRACE-002`** — Historical items shall receive a controlled disposition such as Retain, Replace, Defer, or Reject; unresolved/Open disposition is not permitted at the applicable acceptance gate.
- **`TRACE-003`** — Every retained or replaced historical capability shall map to at least one authoritative immutable `BETA-REQ-####`.
- **`TRACE-004`** — Every retained, replaced, or deferred capability shall identify its target release or explicit future-release boundary.
- **`TRACE-005`** — Every applicable Beta requirement shall trace to its normative clause ownership, use case or structural invariant, HLD ownership, future LLD specification, and acceptance evidence.
- **`TRACE-006`** — Every operator-visible capability shall trace to its implemented UI/UX workflow or explicitly documented non-UI/system behavior.
- **`TRACE-007`** — Deferred and rejected historical items shall preserve an explicit rationale sufficient to explain why the historical behavior is not part of Beta 1.0.
- **`TRACE-008`** — Every normative downstream contract clause shall trace back to one or more approved Beta requirements; design artifacts shall not silently introduce product authority.

## `BETA-REQ-0009`

**Governing obligation:** SOMA Beta shall provide a repeatable supported local setup and explicit operator controls for starting and stopping the application.

- **`DEPLOY-001`** — SOMA Beta shall provide a documented and repeatable supported local setup process.
- **`DEPLOY-002`** — The operator shall have an explicit supported mechanism for starting the application.
- **`DEPLOY-003`** — The operator shall have an explicit supported mechanism for stopping the application cleanly.
- **`DEPLOY-004`** — Supported Windows source deployments shall include direct launchers for setup/start/stop operations as applicable.
- **`DEPLOY-005`** — Normal supported setup shall not depend on undocumented manual environment mutation or ad hoc command reconstruction.
- **`DEPLOY-006`** — Setup/start/stop failures shall surface actionable failure information rather than appearing to succeed silently.

## `BETA-REQ-0010`

**Governing obligation:** Every persistent SOMA Beta entity shall retain an immutable opaque internal identity independent of its business identifiers.

- **`IDENT-001`** — Every persistent domain entity shall receive an immutable internal identifier.
- **`IDENT-002`** — Internal identifiers shall not encode mutable business meaning or depend on externally assigned identifiers.
- **`IDENT-003`** — External and locally generated business identifiers shall be modeled as validated domain attributes.
- **`IDENT-004`** — Business identifiers shall not serve as relational primary or foreign-key authority.
- **`IDENT-005`** — Correction, adoption, or later assignment of a business identifier shall preserve the entity’s internal identity and existing valid relationships.
- **`IDENT-006`** — Where a business identifier is required to be unique, that uniqueness shall be enforced as a domain constraint without converting it into relational identity.

## `BETA-REQ-0011`

**Governing obligation:** A Service Request shall retain one canonical business identity appropriate to its lifecycle: an eight-digit official identifier when assigned, or a non-reusable SOMA local identifier while official identity is absent.

- **`SR-ID-001`** — An official Service Request identifier shall canonicalize to exactly eight decimal digits.
- **`SR-ID-002`** — `SR` and `TT` prefixes or labels supplied by sources or presentation layers shall not form part of canonical Service Request identity.
- **`SR-ID-003`** — A manually created Service Request without an official external identifier shall receive a locally generated operator-visible identifier.
- **`SR-ID-004`** — That local identifier shall use the form `LSR-########`.
- **`SR-ID-005`** — The local Service Request sequence shall begin with `LSR-00000001`.
- **`SR-ID-006`** — An allocated local Service Request identifier shall never be reassigned to another Service Request.
- **`SR-ID-007`** — Later attachment of an official eight-digit identifier shall preserve the Service Request’s immutable internal identity and its historical local identifier.

## `BETA-REQ-0012`

**Governing obligation:** SOMA Beta shall enforce exact canonical RFC identity while distinguishing recognized non-mutating source branch artifacts from other malformed RFC identifiers.

- **`RFC-ID-001`** — An official RFC identifier shall consist of `NC` followed by exactly fourteen decimal digits.
- **`RFC-ID-002`** — SOMA shall not derive a canonical RFC identity by truncating, extracting, or otherwise altering additional characters or digits from a noncanonical imported identifier.
- **`RFC-ID-003`** — An imported identifier that contains the canonical RFC form plus additional source branch characters or digits shall be classified as a source branch artifact under the governed source rule.
- **`RFC-ID-004`** — A recognized branch artifact shall neither create a new RFC nor update an existing RFC.
- **`RFC-ID-005`** — Recognized branch artifacts shall appear as skipped items in the staged/reviewed import result with their classification visible.
- **`RFC-ID-006`** — A malformed RFC identifier that does not satisfy the recognized branch-artifact rule shall fail RFC identity validation rather than being mislabeled as a branch artifact.
- **`RFC-ID-007`** — A branch artifact or malformed value shall not be allowed to resolve to an otherwise valid RFC merely because a canonical RFC substring can be found within it.

## `BETA-REQ-0013`

**Governing obligation:** A WFM business identifier shall consist of `TK` followed by exactly fourteen decimal digits.

- **`WFM-ID-001`** — An official WFM identifier shall consist of `TK` followed by exactly fourteen decimal digits.
- **`WFM-ID-002`** — Values outside the canonical format shall not be accepted as official WFM identities unless a separately governed source rule explicitly defines their treatment.
- **`WFM-ID-003`** — Local Tasks shall not receive or fabricate WFM `TK##############` identities.

## `BETA-REQ-0014`

**Governing obligation:** Every Spare Request shall retain one stable SOMA identity across its locally tracked and officially identified lifecycle.

- **`SPREQ-ID-001`** — Every persistent Spare Request represented by SOMA shall exist first as a local SOMA record, including requests initiated operationally outside SOMA.
- **`SPREQ-ID-002`** — A Spare Request shall receive a temporary operator-visible tracking identifier at creation.
- **`SPREQ-ID-003`** — That tracking identifier shall be immutable, non-reusable, chronologically sortable, and collision-safe.
- **`SPREQ-ID-004`** — The permanent external Spare Request identifier shall consist of `SR` followed by exactly seven decimal digits.
- **`SPREQ-ID-005`** — When the provider assigns the official identifier, it shall be attached to the existing Spare Request rather than causing creation of a replacement entity.
- **`SPREQ-ID-006`** — Official assignment shall not change the Spare Request’s immutable internal identity.
- **`SPREQ-ID-007`** — The temporary tracking identifier shall remain permanently available as historical identity after official assignment.

## `BETA-REQ-0015`

**Governing obligation:** An RMA shall represent one independently identified replacement-and-return obligation under exactly one officially identified Spare Request, without becoming the identity of any physical unit.

- **`RMA-001`** — An official RMA identifier shall consist of `C` followed by exactly ten decimal digits.
- **`RMA-002`** — Every RMA shall belong to exactly one Spare Request that already has its official Spare Request identifier.
- **`RMA-003`** — An RMA shall represent one obligation position rather than a physical inventory unit.
- **`RMA-004`** — Before fulfillment, the RMA represents the provider obligation to supply one replacement position.
- **`RMA-005`** — After reviewed maintenance outcome determines the applicable physical return unit, the same RMA represents the obligation to return that selected unit.
- **`RMA-006`** — Before receipt, an RMA may target at most one Device Part Unit associated with the requested replacement need.
- **`RMA-007`** — An RMA may reference at most one directly fulfilled inbound Spare Part Unit.
- **`RMA-008`** — The physical unit ultimately required for return shall be referenced independently from the direct inbound unit.
- **`RMA-009`** — The RMA, target Device Part Unit, inbound Spare Part Unit, and return unit shall retain distinct immutable identities.
- **`RMA-010`** — BOM, manufacturer serial, condition, and other physical facts shall belong to the applicable physical unit and shall not be fabricated or inherited merely from the RMA.

## `BETA-REQ-0016`

**Governing obligation:** Every Spare Part Unit shall retain an immutable SOMA local identity independent of whether official request, RMA, or manufacturer-serial provenance is known.

- **`SPUNIT-ID-001`** — Every manually registered Spare Part Unit shall receive an immutable SOMA local identifier.
- **`SPUNIT-ID-002`** — The local identifier shall use the form `LSU-########`.
- **`SPUNIT-ID-003`** — The sequence shall begin at `LSU-00000001`, increase according to the accepted allocation rule, and never reuse an allocated identifier.
- **`SPUNIT-ID-004`** — A Spare Part Unit may remain valid without a known official Spare Request.
- **`SPUNIT-ID-005`** — A Spare Part Unit may reference no origin RMA or at most one origin RMA.
- **`SPUNIT-ID-006`** — When an origin RMA exists, the parent Spare Request shall be derived from that RMA rather than independently contradicting it.
- **`SPUNIT-ID-007`** — Any supplied Spare Request provenance that conflicts with the selected origin RMA shall be rejected.
- **`SPUNIT-ID-008`** — Old, local, extracted, serial-less, or otherwise incompletely traceable Stock may still be represented as valid Spare Part Units.
- **`SPUNIT-ID-009`** — Later attachment of official Spare Request provenance, origin RMA, or manufacturer serial shall preserve the same Spare Part Unit and its LSU identity.

## `BETA-REQ-0017`

**Governing obligation:** SOMA Beta shall preserve exact canonical temporal meaning and arbitrary-minute precision for Task and Objective scheduling.

- **`TEMP-001`** — Known scheduled instants shall be represented persistently as canonical UTC whole-second values.
- **`TEMP-002`** — Task and Objective planned boundaries may occur at any valid minute.
- **`TEMP-003`** — SOMA shall not silently round, snap, or coerce valid Task or Objective boundaries to `:00`, `:30`, or any other fixed scheduling grid.
- **`TEMP-004`** — Manual Task and Objective schedule entry and calendar presentation shall use the currently selected Objective IANA timezone.
- **`TEMP-005`** — Timezone presentation shall not alter the canonical stored instant.
- **`TEMP-006`** — Imported timestamps shall be interpreted only by their owning source adapter/profile and shall preserve their source meaning and conversion provenance.
- **`TEMP-007`** — A source timestamp whose effective instant cannot be safely established shall remain unresolved rather than being silently interpreted through the Objective timezone.

## `BETA-REQ-0018`

**Governing obligation:** SOMA Beta shall enforce all structural and domain invariants transactionally across every persistent mutation path.

- **`VALID-001`** — Persistent state shall reject missing or structurally invalid required values.
- **`VALID-002`** — Broken persistent relationships shall not be committed.
- **`VALID-003`** — Duplicate values that violate an accepted uniqueness rule shall be rejected.
- **`VALID-004`** — Persisted state values governed by closed vocabularies shall reject invalid states.
- **`VALID-005`** — Structured persisted data shall satisfy its owned type, version, shape, and semantic validation rules.
- **`VALID-006`** — Referential, uniqueness, nullability, and other structurally enforceable invariants shall receive database protection where appropriate.
- **`VALID-007`** — Rules that depend on domain context or multiple records shall be validated within the owning transaction before commit.
- **`VALID-008`** — UI, import, background, recovery, and other mutation paths shall pass through the same governing invariant boundaries rather than bypassing them.
- **`VALID-009`** — Failure of a required invariant shall prevent the affected mutation from partially committing.

## `BETA-REQ-0019`

**Governing obligation:** SOMA Beta 1.0 shall preserve material operational history by default and permit hard deletion only through explicitly authorized domain rules.

- **`HIST-001`** — Imported, referenced, or operationally processed records shall preserve material history through explicit lifecycle state and evidence rather than silent erasure.
- **`HIST-002`** — Archive, cancellation, rejection, supersession, rollback/correction, replacement, resend, and deletion shall remain distinct semantics where their owning domains define them.
- **`HIST-003`** — Ordinary hard deletion shall be limited to records explicitly eligible under their domain rules, generally untouched manual records with no imported/adopted or protected operational history.
- **`HIST-004`** — A record that has participated in accepted Objective/Task execution or equivalent protected lifecycle evidence shall not become hard-deletable merely because it is no longer active.
- **`HIST-005`** — A domain may authorize deletion only through an explicit accepted correction rule that defines its scope and consequences.
- **`HIST-006`** — Any authorized deletion affecting dependent records or relationships shall present its exact impact before mutation.
- **`HIST-007`** — Dependent deletion shall require confirmation and commit transactionally with required lifecycle/audit evidence.
- **`HIST-008`** — Beta 1.0 shall provide no general operational-history purge policy.
- **`HIST-009`** — Any broader purge capability belongs to Beta 1.1 or later and requires separately accepted product and design authority.

## `BETA-REQ-0020`

**Governing obligation:** SOMA Beta shall preserve immutable historical logistics truth independently of later changes to mutable Dispatch Location master data.

- **`LOG-HIST-001`** — Changes to mutable Dispatch Location master data shall not alter historical delivery, pickup, dispatch, or return evidence.
- **`LOG-HIST-002`** — Historical logistics evidence shall preserve the effective location facts applicable when the operation occurred.
- **`LOG-HIST-003`** — Where mutable master-data references alone cannot preserve those effective facts, SOMA shall capture an immutable Dispatch Location snapshot.
- **`LOG-HIST-004`** — A logistics snapshot shall preserve only the governed facts needed to interpret the historical operation, including effective name and address and any other explicitly required logistics context.
- **`LOG-HIST-005`** — Where a Dispatch Location derives its effective address from a linked Site, historical capture shall preserve the address effective at the relevant logistics event rather than later Site edits.
- **`LOG-HIST-006`** — Historical snapshots shall not become competing current master data and shall not be editable through ordinary Dispatch Location maintenance.

## `BETA-REQ-0021`

**Governing obligation:** SOMA Beta shall provide reusable Customer Organization and Contact records with governed creation, maintenance, and lifecycle behavior across operational workflows.

- **`REF-001`** — SOMA Beta shall support persistent Customer Organization records as reusable business-reference entities.
- **`REF-002`** — SOMA Beta shall support persistent Contact records as reusable representations of operational people.
- **`REF-003`** — Customer Organizations and Contacts shall retain their own immutable internal identities independently of descriptive names or other matching evidence.
- **`REF-004`** — The operator shall be able to create and maintain Customer Organizations and Contacts subject to their governing validation, relationship, correction, and archival rules.
- **`REF-005`** — Owning workflows shall reference reusable Customer Organization and Contact identities rather than creating private duplicate person or organization records.
- **`REF-006`** — Changes to current reference data shall not silently rewrite the organization/person context preserved by historical operational evidence.
- **`REF-007`** — Archived records shall remain available for historical interpretation while new active relationships follow the applicable archival restrictions.

## `BETA-REQ-0022`

**Governing obligation:** SOMA Beta shall separate its single installation authentication identity from reusable Contact identities representing operational people and roles.

- **`ACTOR-001`** — Each SOMA Beta installation shall maintain exactly one authenticating Local User Profile.
- **`ACTOR-002`** — The Local User Profile shall represent the installation’s local administrator and authentication authority.
- **`ACTOR-003`** — Operational people shall be represented as reusable Contacts and shall not receive authentication profiles merely because they participate in SOMA workflows.
- **`ACTOR-004`** — The same Contact may participate across multiple workflows without being duplicated into role-specific person entities.
- **`ACTOR-005`** — One Contact may fulfill multiple operational roles, including requester, handler, owner, executor, or customer contact, where the owning workflow permits them.
- **`ACTOR-006`** — Operational roles shall describe how a Contact participates in a particular relationship or workflow rather than redefine the Contact’s identity.
- **`ACTOR-007`** — Operational Contact data shall not become authentication authority merely because a Contact represents the same human being as the local operator.

## `BETA-REQ-0023`

**Governing obligation:** A Dispatch Location shall represent reusable physical logistics location identity independently from its operation-specific role, Customer Organization context, or Datacenter Site identity.

- **`DISPATCH-001`** — A Dispatch Location shall represent one named and addressed physical logistics location.
- **`DISPATCH-002`** — The same Dispatch Location may be reused by multiple valid logistics operations.
- **`DISPATCH-003`** — Delivery, self-pickup, pickup origin, dispatch origin, and other logistics meanings shall be properties of the applicable operation/relationship rather than intrinsic types of the Dispatch Location itself.
- **`DISPATCH-004`** — A Spare Request may reference a Dispatch Location according to its governed delivery or self-pickup workflow.
- **`DISPATCH-005`** — Where the Fault Tag return method requires pickup, its Dispatch Location shall represent the physical origin from which the return unit is dispatched or collected.
- **`DISPATCH-006`** — A Fault Tag pickup-origin Dispatch Location shall not establish, infer, or represent the provider warehouse destination.
- **`DISPATCH-007`** — A Dispatch Location shall not inherently belong to a Customer Organization.
- **`DISPATCH-008`** — A Dispatch Location shall remain a distinct entity from a Datacenter Site even when the two are linked.

## `BETA-REQ-0024`

**Governing obligation:** Every Datacenter Site shall retain a distinct, dedicated Dispatch Location relationship through which its current logistics address is represented.

- **`SITE-DISPATCH-001`** — A Datacenter Site and a Dispatch Location shall remain distinct persistent entities even when linked.
- **`SITE-DISPATCH-002`** — Every Site shall reference exactly one Dispatch Location.
- **`SITE-DISPATCH-003`** — Registering a Site shall create and link its dedicated Dispatch Location as part of the governed Site-creation operation.
- **`SITE-DISPATCH-004`** — A Dispatch Location may exist independently without any Site.
- **`SITE-DISPATCH-005`** — A Dispatch Location shall reference at most one Site.
- **`SITE-DISPATCH-006`** — The dedicated Dispatch Location associated with a Site shall not simultaneously represent another Site.
- **`SITE-DISPATCH-007`** — A Site-linked Dispatch Location shall derive its current effective address from the linked Site.
- **`SITE-DISPATCH-008`** — Ordinary editing shall not permit the linked Dispatch Location’s current address to diverge independently from its Site’s effective address.
- **`SITE-DISPATCH-009`** — Later Site-address changes may update current derived Dispatch Location data but shall not rewrite previously captured logistics snapshots.

## `BETA-REQ-0025`

**Governing obligation:** Reference records with protected operational history shall support history-preserving archival instead of destructive removal.

- **`ARCHIVE-001`** — Reference records with protected operational history shall support an explicit archived lifecycle state rather than requiring deletion.
- **`ARCHIVE-002`** — Archived reference records shall remain available wherever needed to interpret existing historical evidence.
- **`ARCHIVE-003`** — Archived reference records shall not be selectable for new active operational relationships unless an owning workflow explicitly permits otherwise.
- **`ARCHIVE-004`** — Archival shall be blocked when it would strand an active dependent record whose owning workflow requires the reference to remain active.
- **`ARCHIVE-005`** — Blocked archival may proceed only after affected active dependencies are completed, cancelled, reassigned, corrected, or otherwise resolved through an authorized workflow.
- **`ARCHIVE-006`** — Reactivation shall be a deliberate lifecycle action and shall preserve prior archival history.
- **`ARCHIVE-007`** — Archive and reactivate actions shall preserve sufficient audit/lifecycle evidence to explain the transition.

## `BETA-REQ-0026`

**Governing obligation:** Dispatch Locations shall remain Customer-Organization-neutral physical logistics references regardless of any customer context derived through an optional linked Site.

- **`DISPATCH-CUST-001`** — A Dispatch Location shall not be owned by a Customer Organization.
- **`DISPATCH-CUST-002`** — A Dispatch Location shall not carry a direct Customer Organization assignment as part of its identity or lifecycle.
- **`DISPATCH-CUST-003`** — A Dispatch Location shall not maintain a Customer Organization preference relationship.
- **`DISPATCH-CUST-004`** — Where a Dispatch Location is linked to a Site, any displayed Customer Organization context shall derive from that Site’s ownership.
- **`DISPATCH-CUST-005`** — Derived Customer Organization context shall not alter the Dispatch Location’s independent physical identity.
- **`DISPATCH-CUST-006`** — Derived Site/customer context shall not by itself prevent the Dispatch Location from participating in another otherwise valid logistics operation.
- **`DISPATCH-CUST-007`** — Selectors, validation, and persistence shall not silently introduce customer exclusivity that is absent from the accepted logistics contract.

## `BETA-REQ-0027`

**Governing obligation:** SOMA Beta shall anchor regularized Infrastructure ownership and placement to Customer-owned physical Sites while keeping Cloud Types reusable and provisional Device References independently usable before regularization.

- **`INFRA-OWN-001`** — Each Site shall represent one physical Datacenter location.
- **`INFRA-OWN-002`** — Every Site shall belong to exactly one Customer Organization.
- **`INFRA-OWN-003`** — Site names, aliases, city codes, and other descriptive labels may repeat and shall not independently establish Site identity.
- **`INFRA-OWN-004`** — A Cloud Type shall be reusable across multiple Sites.
- **`INFRA-OWN-005`** — Every Cloud Deployment shall belong to exactly one Site and shall reference one reusable Cloud Type.
- **`INFRA-OWN-006`** — A regularized Network Element shall derive its Customer Organization through its owning Site rather than maintaining independent customer ownership.
- **`INFRA-OWN-007`** — When a Network Element references a Cloud Deployment, that deployment shall belong to the same Site as the Network Element.
- **`INFRA-OWN-008`** — A provisional or external Device Reference may participate in supported operational workflows without Site or Cloud placement until it is regularized into Infrastructure.
- **`INFRA-OWN-009`** — Site creation shall identify plausible duplicate physical locations using the governed normalized-address comparison.
- **`INFRA-OWN-010`** — Possible duplicate Sites shall be presented for operator review and shall never be merged automatically solely because their addresses appear equivalent.
