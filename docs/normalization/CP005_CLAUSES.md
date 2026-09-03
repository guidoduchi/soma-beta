# SOMA Beta Normalization CP-005 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0103`–`BETA-REQ-0127`.  
Clause identities are stable normative references. Under each requirement, the displayed prefix plus the three-digit suffix forms the full clause ID.

## `BETA-REQ-0103` — prefix `NE-CORE`

**Governing obligation:** Each registered Network Element shall preserve one immutable device identity, a nonblank operational name, and exactly one governing physical Site while allowing optional model, serial, placement, Cloud, and descriptive information to be progressively completed through consistency-checked relationships whose derived context, Notes history, and credential boundaries remain governed by their respective authorities.

`001` — Every registered Network Element shall have immutable internal identity.
`002` — A Network Element internal identity shall not be replaced by an imported identifier.
`003` — A Network Element internal identity shall not be derived from its name.
`004` — A Network Element internal identity shall not be derived from serial number.
`005` — A Network Element internal identity shall not be derived from IP address.
`006` — A Network Element shall have a nonblank operational name.
`007` — Operational name shall be editable without replacing Network Element identity.
`008` — Equal operational names shall not prove identity.
`009` — Every registered Network Element shall belong to exactly one physical Site.
`010` — A registered Network Element shall not exist without a governing Site.
`011` — Changing Site shall be a governed placement correction or movement rather than identity replacement.
`012` — Site relationship shall be authoritative for Network Element physical Site.
`013` — Customer Organization shall derive through the governing Site relationship.
`014` — Derived Customer Organization shall not be copied as competing Network Element truth.
`015` — Model may be absent during progressive registration.
`016` — Model shall be represented as a relationship to a reusable Network Element Model.
`017` — A Model relationship shall not replace Network Element identity.
`018` — Equal Model shall not imply equal Network Element.
`019` — Manufacturer serial may be absent.
`020` — Manufacturer serial shall be descriptive evidence rather than relational identity.
`021` — Equal serial values shall be reconciliation evidence rather than automatic identity proof.
`022` — Serial correction shall not replace Network Element identity.
`023` — Rack placement may be absent.
`024` — A Network Element without Rack placement shall remain valid at Site level.
`025` — Rack placement shall reference at most one current Rack.
`026` — A selected Rack shall belong to the Network Element governing Site.
`027` — Cross-Site Rack placement shall be rejected.
`028` — Rack placement shall imply its authoritative Room through the Rack hierarchy.
`029` — Derived Room shall not be copied as competing Network Element truth.
`030` — Rack-unit position may be absent when the Network Element is unracked.
`031` — Rack-unit position shall not be accepted without compatible Rack placement when the placement model requires Rack context.
`032` — Rack-unit position shall remain descriptive placement evidence rather than identity.
`033` — Placement correction shall preserve historical relationship evidence.
`034` — Containment shall remain distinct from Rack placement.
`035` — A contained Network Element shall preserve its own immutable identity.
`036` — Containment shall not create a second Site authority.
`037` — Containment shall not silently override governing Site.
`038` — Contradictory containment and Site placement shall be rejected or explicitly corrected.
`039` — Cloud Deployment assignment may be absent.
`040` — A Network Element shall have at most one current Cloud Deployment assignment.
`041` — A selected Cloud Deployment shall belong to the Network Element governing Site.
`042` — Cross-Site Cloud Deployment assignment shall be rejected.
`043` — Cloud Type shall derive through Cloud Deployment.
`044` — Cloud Type shall not be copied directly onto Network Element as competing truth.
`045` — Cloud assignment shall remain distinct from physical placement.
`046` — Cloud assignment shall remain distinct from containment.
`047` — Cloud assignment shall remain distinct from IP inventory.
`048` — Optional descriptive facts may be completed progressively after initial registration.
`049` — Missing optional descriptive facts shall remain unknown rather than fabricated.
`050` — Progressive completion shall not create a duplicate Network Element.
`051` — Progressive completion shall preserve previously accepted facts unless explicitly corrected.
`052` — Conflicting progressive-completion evidence shall require reviewed reconciliation.
`053` — Derived Site context shall resolve from authoritative relationships.
`054` — Derived Room context shall resolve from authoritative relationships.
`055` — Derived Customer context shall resolve from authoritative relationships.
`056` — Derived Cloud Type context shall resolve from authoritative relationships.
`057` — Derived facts shall not be persisted as independently editable competing authorities.
`058` — Network Element Notes shall use the governed Notes-history contract.
`059` — Editing Notes shall preserve accepted Notes history.
`060` — Notes shall not become identity evidence.
`061` — Beta 1.0 shall expose no SSH credential field on Network Element.
`062` — Beta 1.0 shall expose no password field for device access on Network Element.
`063` — Beta 1.0 shall expose no private-key field for device access on Network Element.
`064` — Credential absence shall not make a Network Element invalid.
`065` — Network Element registration shall not require future SSH capability.
`066` — All accepted registration, placement, Cloud, and correction changes shall preserve immutable Network Element identity and governed history.

## `BETA-REQ-0104` — prefix `NE-IP`

**Governing obligation:** Network Elements may maintain zero or many descriptive IP addresses with at most one accepted primary address, while absence or similarity of IP values never determines entity identity and Beta 1.0 IP inventory shall remain strictly separate from interface, discovery, reachability, connectivity, topology, and SSH capabilities.

`001` — A Network Element may have zero stored IP addresses.
`002` — A Network Element with no IP address shall remain valid.
`003` — A Network Element may have one stored IP address.
`004` — A Network Element may have many stored IP addresses.
`005` — Each stored IP relationship shall reference one Network Element.
`006` — IP values shall be descriptive address inventory.
`007` — IP values shall not become Network Element internal identity.
`008` — Equal IP values shall not prove that two Device References are the same entity.
`009` — Equal IP values shall not prove that two Network Elements are the same entity.
`010` — IP similarity may be used only as reconciliation evidence.
`011` — An IP address shall not be fabricated when unknown.
`012` — Device Reference validity shall not require an IP address.
`013` — Network Element validity shall not require an IP address.
`014` — Cloud Type validity shall not require an IP address.
`015` — Cloud Deployment validity shall not require an IP address.
`016` — Other logical or organizational records shall not require fabricated IP addresses.
`017` — A Network Element may designate at most one accepted primary IP address.
`018` — Zero primary addresses shall be valid when no primary has been accepted.
`019` — Selecting a primary address shall not delete other stored addresses.
`020` — Changing the primary address shall preserve the Network Element identity.
`021` — Primary designation shall be a relationship/property of accepted IP inventory rather than separate identity.
`022` — Removing a primary designation shall not require deleting the IP value.
`023` — Duplicate candidate IP evidence shall be reviewable rather than silently merged.
`024` — IP correction shall preserve applicable relationship/correction history.
`025` — IP import shall respect installation identity and reconciliation rules.
`026` — Blank IP import cells shall not fabricate clearing without explicit reviewed operation.
`027` — IP inventory shall not imply network-interface modeling.
`028` — Beta 1.0 shall not require interface entities for stored IP addresses.
`029` — IP inventory shall not imply physical-port modeling.
`030` — IP inventory shall not activate automated discovery.
`031` — IP inventory shall not prove device reachability.
`032` — IP inventory shall not create connectivity edges.
`033` — IP inventory shall not create topology paths.
`034` — Shared subnet or address pattern shall not imply connectivity.
`035` — Shared IP-related evidence shall not imply containment.
`036` — Shared IP-related evidence shall not imply Cloud assignment.
`037` — Shared IP-related evidence shall not imply Site placement.
`038` — Beta 1.0 IP inventory shall not expose SSH capability.
`039` — An IP address shall not authorize credential storage.
`040` — An IP address shall not authorize automated login attempts.
`041` — IP display shall preserve unknown or malformed source evidence according to import validation rules.
`042` — Invalid IP input shall be staged or rejected rather than silently normalized into a different address.
`043` — Current IP projection shall derive from accepted IP relationships and corrections.
`044` — Network Element identity shall survive all IP additions, removals, primary changes, and corrections.

## `BETA-REQ-0105` — prefix `NE-CONTAIN`

**Governing obligation:** Network Element containment shall form an acyclic one-parent forest of independently identified device instances, with containment remaining separate from placement, Cloud assignment, model/component compatibility, and connectivity and with every accepted or corrected parent/child relationship preserved through governed relationship history.

`001` — Network Element containment shall be represented as a parent/child relationship.
`002` — A parent Network Element may contain zero children.
`003` — A parent Network Element may contain one child.
`004` — A parent Network Element may contain many children.
`005` — Each contained child shall have at most one direct containment parent.
`006` — A child with no containment parent shall remain valid where otherwise registrable.
`007` — Containment shall preserve the child's immutable Network Element identity.
`008` — Containment shall preserve the parent's immutable Network Element identity.
`009` — A contained child shall not become a component record merely because it is contained.
`010` — A Network Element shall not contain itself.
`011` — Direct self-containment shall be rejected.
`012` — Two-node direct containment cycles shall be rejected.
`013` — Indirect containment cycles shall be rejected.
`014` — Any proposed containment that makes a node its own ancestor shall be rejected.
`015` — Containment validation shall evaluate the accepted parent chain before mutation.
`016` — Containment shall therefore form an acyclic forest.
`017` — Multiple independent containment roots shall be permitted.
`018` — A root shall not require a synthetic parent.
`019` — Reparenting shall be a governed relationship correction/change.
`020` — Reparenting shall not replace the child identity.
`021` — Reparenting shall not replace the parent identities.
`022` — Reparenting shall validate the one-parent constraint.
`023` — Reparenting shall validate the acyclic constraint.
`024` — Removing containment shall not delete either Network Element.
`025` — Removing containment shall preserve applicable relationship history.
`026` — Accepted containment creation shall preserve chronology.
`027` — Accepted containment correction shall preserve chronology.
`028` — Original corrected containment evidence shall remain historical.
`029` — Current containment projection shall derive from accepted relationship history.
`030` — Containment shall remain distinct from Site placement.
`031` — A parent/child relationship shall not imply that parent and child are the same Site fact.
`032` — Containment shall not silently relocate a child.
`033` — Containment shall not replace Rack placement.
`034` — Containment shall not create Room placement.
`035` — Containment shall remain distinct from Cloud Deployment assignment.
`036` — A child shall not inherit Cloud Deployment as authoritative truth solely from its parent.
`037` — A parent shall not inherit Cloud Deployment solely from a child.
`038` — Containment shall remain distinct from reusable Model.
`039` — Equal Model shall not imply containment.
`040` — Model compatibility shall not create containment automatically.
`041` — Component compatibility shall not create containment automatically.
`042` — A reusable Component definition shall not become a contained Network Element.
`043` — Containment shall remain distinct from physical connectivity.
`044` — Containment shall remain distinct from logical connectivity.
`045` — Containment shall not create network edges.
`046` — Shared IP addresses or patterns shall not create containment.
`047` — Shared Site shall not create containment.
`048` — Shared Rack shall not create containment.
`049` — Shared Cloud Deployment shall not create containment.
`050` — Operational co-occurrence shall not create containment.
`051` — Import batch membership shall not create containment.
`052` — Workbook containment references shall be staged and validated before acceptance.
`053` — Unknown containment parents shall not be fabricated.
`054` — Ambiguous containment parents shall require review.
`055` — Ineligible parent relationships shall be rejected with a bounded reason.
`056` — Containment correction shall not rewrite unrelated placement facts.
`057` — Containment correction shall not rewrite unrelated Cloud facts.
`058` — Containment correction shall not rewrite unrelated IP facts.
`059` — Containment correction shall not rewrite unrelated Model/component facts.
`060` — Containment history shall remain independently auditable from all other Infrastructure relationships.

## `BETA-REQ-0106` — prefix `CLOUD-DEPLOY`

**Governing obligation:** SOMA shall model reusable Cloud Types separately from independently identified Site-scoped Cloud Deployments, allowing each registered Network Element at most one same-Site Deployment while deriving Cloud Type and Customer Organization through authoritative relationships and preserving unresolved Device References without fabricated placement or ownership.

`001` — Cloud Type shall be a reusable logical definition.
`002` — Cloud Type identity shall remain distinct from Cloud Deployment identity.
`003` — One Cloud Type may be represented at zero Sites.
`004` — One Cloud Type may be represented at one Site.
`005` — One Cloud Type may be represented at many Sites.
`006` — Cloud Deployment shall represent one Site-scoped deployment instance.
`007` — Every Cloud Deployment shall have immutable internal identity.
`008` — Every Cloud Deployment shall belong to exactly one Cloud Type.
`009` — Every Cloud Deployment shall belong to exactly one Site.
`010` — A Site may contain zero Cloud Deployments.
`011` — A Site may contain one Cloud Deployment.
`012` — A Site may contain many Cloud Deployments.
`013` — Two Deployments of the same Cloud Type at different Sites shall remain distinct Deployments.
`014` — Two Deployments at one Site shall remain distinct when independently identified.
`015` — Deployment identity shall not be derived from Cloud Type name.
`016` — Deployment identity shall not be derived from Site name.
`017` — Cloud Type renaming shall not replace Deployment identity.
`018` — Site renaming shall not replace Deployment identity.
`019` — A registered Network Element shall belong to exactly one governing Site.
`020` — A registered Network Element may have zero Cloud Deployment assignments.
`021` — A registered Network Element may have one Cloud Deployment assignment.
`022` — A registered Network Element shall not have more than one current Cloud Deployment assignment.
`023` — Assigned Cloud Deployment shall belong to the Network Element governing Site.
`024` — Cross-Site Network Element-to-Deployment assignment shall be rejected.
`025` — Network Element shall not be assigned directly to Cloud Type as a substitute for Deployment.
`026` — Cloud Type shall derive through accepted Cloud Deployment assignment.
`027` — Derived Cloud Type shall not be copied as competing Network Element truth.
`028` — Customer Organization shall derive through Site authority.
`029` — Customer Organization shall not derive directly from Cloud Type.
`030` — Customer Organization shall not be copied onto Network Element as competing ownership truth.
`031` — Changing Deployment assignment shall not replace Network Element identity.
`032` — Changing Deployment assignment shall preserve relationship history.
`033` — Changing Cloud Type on a Deployment shall be governed as a Deployment correction/change without rewriting unrelated Network Elements silently.
`034` — Moving a Deployment across Sites shall not silently preserve invalid cross-Site Network Element assignments.
`035` — Site-change operations shall revalidate affected Deployment relationships.
`036` — Cloud assignment shall remain distinct from Rack placement.
`037` — Cloud assignment shall remain distinct from Room placement.
`038` — Cloud assignment shall remain distinct from containment.
`039` — Cloud assignment shall remain distinct from IP inventory.
`040` — Cloud assignment shall remain distinct from connectivity.
`041` — Shared Cloud Type shall not imply connectivity.
`042` — Shared Deployment shall not imply connectivity.
`043` — Shared Deployment shall not imply containment.
`044` — Shared Deployment shall not imply Rack placement.
`045` — Cloud Deployment may be progressively assigned after Network Element registration.
`046` — Missing Cloud assignment shall remain unknown/unassigned rather than fabricated.
`047` — An unregistered Device Reference shall remain valid without a Site.
`048` — An unresolved Device Reference shall remain valid without a Cloud Deployment.
`049` — An unresolved Device Reference shall not receive fabricated Customer Organization ownership.
`050` — An unresolved Device Reference shall not receive fabricated Site placement.
`051` — An unresolved Device Reference shall not receive fabricated Cloud Type.
`052` — Resolving a Device Reference to a Network Element may expose derived Site/Customer/Cloud facts through that relationship.
`053` — Device Reference resolution shall not copy those derived facts as competing historical truth.
`054` — Workbook Cloud labels shall be matching/reconciliation evidence rather than identity proof.
`055` — Workbook Deployment identity from the same installation may target the exact Deployment under the workbook contract.
`056` — Foreign-installation Deployment identity shall be evidence only until reconciled.
`057` — Unknown Cloud Type references shall be staged for review rather than fabricated.
`058` — Unknown Site references shall be staged for review rather than fabricated.
`059` — Invalid cross-Site assignments shall be reported distinctly.
`060` — Current Cloud projection shall derive from accepted Site/Deployment relationships.
`061` — Cloud history shall preserve accepted relationship chronology.
`062` — Correcting Cloud relationships shall preserve original evidence.
`063` — Cloud relationship correction shall not rewrite unrelated physical placement.
`064` — Cloud relationship correction shall not rewrite unrelated containment or IP inventory.
`065` — Cloud Type, Cloud Deployment, Site, Customer Organization, Network Element, and Device Reference identities shall remain distinct authorities.

## `BETA-REQ-0107` — prefix `INFRA-CONN`

**Governing obligation:** SOMA shall keep containment, physical placement, Cloud assignment, IP inventory, and connectivity as independent Infrastructure authorities; Beta 1.0 shall provide no canonical topology, interfaces, discovery, reachability, or connectivity inference, while any future 1.x connectivity capability must use independently identified, provenance-rich, temporally reviewable, and precisely correctable relationships without rewriting existing Infrastructure facts.

`001` — Containment shall remain independent from physical placement.
`002` — Containment shall remain independent from Cloud assignment.
`003` — Containment shall remain independent from IP inventory.
`004` — Containment shall remain independent from connectivity.
`005` — Physical placement shall remain independent from Cloud assignment.
`006` — Physical placement shall remain independent from IP inventory.
`007` — Physical placement shall remain independent from connectivity.
`008` — Cloud assignment shall remain independent from IP inventory.
`009` — Cloud assignment shall remain independent from connectivity.
`010` — IP inventory shall remain independent from connectivity.
`011` — Beta 1.0 shall not provide canonical connectivity edges.
`012` — Beta 1.0 shall not provide canonical physical-link entities.
`013` — Beta 1.0 shall not provide canonical logical-link entities.
`014` — Beta 1.0 shall not provide interface entities as an Infrastructure requirement.
`015` — Beta 1.0 shall not provide port entities as an Infrastructure requirement.
`016` — Beta 1.0 shall not provide automated device discovery.
`017` — Beta 1.0 shall not provide automated network discovery.
`018` — Beta 1.0 shall not provide canonical path calculation.
`019` — Beta 1.0 shall not provide reachability determination.
`020` — Beta 1.0 shall not provide topology management.
`021` — Shared Site shall not imply connectivity.
`022` — Shared Room shall not imply connectivity.
`023` — Shared Rack shall not imply connectivity.
`024` — Shared Cloud Deployment shall not imply connectivity.
`025` — Shared Cloud Type shall not imply connectivity.
`026` — Shared IP subnet shall not imply connectivity.
`027` — Similar IP address shall not imply connectivity.
`028` — Consecutive IP addresses shall not imply connectivity.
`029` — Containment shall not imply connectivity.
`030` — Parent/child relationship shall not imply network connectivity.
`031` — Operational co-occurrence in one Service Request shall not imply connectivity.
`032` — Operational co-occurrence in one RFC shall not imply connectivity.
`033` — Operational co-occurrence in one Objective shall not imply connectivity.
`034` — Same import batch shall not imply connectivity.
`035` — Same workbook row neighborhood shall not imply connectivity.
`036` — Same Model shall not imply connectivity.
`037` — Component compatibility shall not imply connectivity.
`038` — Presence of an IP address shall not imply reachability.
`039` — Presence of a primary IP shall not imply management reachability.
`040` — Absence of IP shall not imply disconnection.
`041` — Beta 1.0 UI shall not present inferred topology as authoritative.
`042` — Beta 1.0 exports shall not contain canonical topology edges.
`043` — Beta 1.0 Infrastructure imports shall not create topology edges.
`044` — Beta 1.0 shall not silently interpret workbook adjacency as topology.
`045` — Connectivity capability is deferred to the 1.x line.
`046` — Deferral shall not weaken Beta 1.0 Infrastructure identity or placement requirements.
`047` — Future connectivity shall require separately accepted design before implementation.
`048` — Future connectivity relationships shall have immutable internal identity.
`049` — Future connectivity relationship identity shall be distinct from endpoint identities.
`050` — Future connectivity shall preserve exact endpoint A identity.
`051` — Future connectivity shall preserve exact endpoint B identity.
`052` — Future connectivity shall preserve relationship type.
`053` — Future connectivity shall preserve directionality when the relationship is directional.
`054` — Future connectivity shall preserve bidirectional semantics when applicable.
`055` — Future connectivity shall preserve interface identity when independently known.
`056` — Future connectivity shall preserve port identity when independently known.
`057` — Missing interface/port evidence shall remain unknown rather than fabricated.
`058` — Future connectivity shall preserve provenance.
`059` — Provenance shall identify operator or accepted source as applicable.
`060` — Future connectivity shall preserve recording chronology.
`061` — Future connectivity shall preserve independently known effective start when available.
`062` — Future connectivity shall preserve independently known effective end when available.
`063` — Unknown effective time shall remain unknown.
`064` — Discovery time shall not substitute for unknown effective time.
`065` — Future connectivity shall preserve reviewed verification state.
`066` — Future connectivity may preserve confidence evidence where separately accepted.
`067` — Confidence shall not replace verification state.
`068` — Low-confidence evidence shall not silently become accepted connectivity.
`069` — Future relationship correction shall target the exact connectivity relationship.
`070` — Connectivity correction shall not replace endpoint identities.
`071` — Connectivity correction shall preserve original relationship evidence.
`072` — Connectivity correction shall preserve correction reason.
`073` — Connectivity correction shall preserve actor/source chronology.
`074` — Connectivity correction shall not rewrite Site placement.
`075` — Connectivity correction shall not rewrite Rack placement.
`076` — Connectivity correction shall not rewrite containment.
`077` — Connectivity correction shall not rewrite Cloud assignment.
`078` — Connectivity correction shall not rewrite IP inventory.
`079` — Placement correction shall not silently rewrite future connectivity.
`080` — Cloud correction shall not silently rewrite future connectivity.
`081` — IP correction shall not silently rewrite future connectivity.
`082` — Containment correction shall not silently rewrite future connectivity.
`083` — Future topology projections shall derive from accepted connectivity relationships.
`084` — Future topology projections shall not become independent relational truth.
`085` — Failure to build a future topology projection shall not rewrite connectivity evidence.
`086` — Future connectivity import shall stage ambiguity before acceptance.
`087` — Future connectivity import shall not infer endpoints from names alone.
`088` — Future connectivity shall preserve unresolved evidence rather than fabricate endpoints.
`089` — Connectivity absence shall not invalidate a Network Element.
`090` — Connectivity absence shall not invalidate a Cloud Deployment.
`091` — Connectivity absence shall not invalidate a Device Reference.
`092` — Beta 1.0 testing shall verify that no connectivity is created from shared placement.
`093` — Beta 1.0 testing shall verify that no connectivity is created from shared IP patterns.
`094` — Beta 1.0 testing shall verify that no connectivity is created from containment.
`095` — Infrastructure facts shall remain semantically stable whether or not a future connectivity subsystem exists.

## `BETA-REQ-0108` — prefix `INFRA-SECRET`

**Governing obligation:** SOMA shall never persist reusable device or authentication secrets in ordinary domain, evidence, audit, log, Notes, IP, or workbook data; Beta 1.0 shall expose no device-credential or SSH controls, and any future credential capability may persist only a non-secret opaque reference to an approved external provider whose unavailability produces a bounded unavailable state without local secret fallback.

`001` — Passwords are reusable authentication secrets.
`002` — Private keys are reusable authentication secrets.
`003` — Reusable tokens are authentication secrets.
`004` — Recovery codes are reusable authentication secrets.
`005` — Other reusable device authentication material is secret.
`006` — Reusable secrets shall not be stored in ordinary domain tables.
`007` — Reusable secrets shall not be stored in Device Reference fields.
`008` — Reusable secrets shall not be stored in Network Element fields.
`009` — Reusable secrets shall not be stored in Model fields.
`010` — Reusable secrets shall not be stored in Component fields.
`011` — Reusable secrets shall not be stored in IP-address records.
`012` — Reusable secrets shall not be stored in Notes.
`013` — Reusable secrets shall not be stored in evidence payloads.
`014` — Reusable secrets shall not be stored in audit payloads.
`015` — Reusable secrets shall not be stored in application logs.
`016` — Reusable secrets shall not be stored in job diagnostics.
`017` — Reusable secrets shall not be stored in Infrastructure workbooks.
`018` — Reusable secrets shall not be stored in import staging.
`019` — Reusable secrets shall not be stored in exported discovery workbooks.
`020` — Reusable secrets shall not be stored in round-trip workbooks.
`021` — Secret prohibition applies even when the source workbook contains such a value.
`022` — Secret-bearing source columns shall be rejected, ignored safely, or warned according to import design rather than persisted.
`023` — Base64 or similar encoding shall not make a secret non-secret.
`024` — Reversible encoding shall not permit secret persistence.
`025` — Encryption inside an ordinary domain field shall not turn that field into an approved credential store.
`026` — Hashing a reusable secret shall not authorize domain persistence unless separately required for SOMA authentication authority.
`027` — Beta 1.0 shall expose no device password control.
`028` — Beta 1.0 shall expose no device private-key control.
`029` — Beta 1.0 shall expose no device token control.
`030` — Beta 1.0 shall expose no SSH credential editor.
`031` — Beta 1.0 shall expose no SSH connection action requiring stored credentials.
`032` — Beta 1.0 shall not require device credentials for Network Element validity.
`033` — Beta 1.0 shall not require device credentials for IP inventory.
`034` — Beta 1.0 shall not require device credentials for workbook exchange.
`035` — Notes shall never be offered as a credential workaround.
`036` — Evidence references shall never be offered as a credential workaround.
`037` — Logs shall never be offered as a credential workaround.
`038` — A future device-credential capability requires separate acceptance.
`039` — A future capability may persist only a non-secret opaque provider reference.
`040` — The opaque reference shall identify an approved external or operating-system credential provider entry.
`041` — The opaque reference shall not contain the secret itself.
`042` — The opaque reference shall not reversibly encode the secret.
`043` — The opaque reference shall not embed a password.
`044` — The opaque reference shall not embed a private key.
`045` — The opaque reference shall not embed a reusable token.
`046` — The opaque reference shall not embed a recovery code.
`047` — Strictly non-secret resolution metadata may accompany the reference.
`048` — Resolution metadata shall be minimized.
`049` — Resolution metadata shall not permit recovery of the secret.
`050` — Provider entry display labels may be stored only as non-secret metadata.
`051` — Provider-specific opaque identifiers may be stored only when non-secret.
`052` — Provider availability state may be persisted as non-secret operational metadata.
`053` — Missing provider reference shall produce a bounded unavailable state.
`054` — Revoked provider reference shall produce a bounded unavailable state.
`055` — Inaccessible provider reference shall produce a bounded unavailable state.
`056` — Provider unavailability shall not cause SOMA to ask to persist the secret locally as fallback.
`057` — Provider unavailability shall not copy the secret into Notes.
`058` — Provider unavailability shall not copy the secret into logs.
`059` — Provider unavailability shall not copy the secret into domain tables.
`060` — Provider unavailability shall not fabricate a credential.
`061` — A future credential lookup shall remain separate from Network Element identity.
`062` — Deleting or changing a credential reference shall not replace Network Element identity.
`063` — Credential reference correction shall preserve applicable audit history.
`064` — Credential reference history shall not include recovered secret material.
`065` — Infrastructure workbook import shall not create credential references unless a future explicitly accepted workbook contract permits non-secret references.
`066` — Beta 1.0 workbook contract shall exclude credential-reference columns.
`067` — Communication processing shall not mine messages for reusable secrets into domain storage.
`068` — Recoverable UI working copies shall not become a secret-storage loophole.
`069` — Background-job diagnostics shall not become a secret-storage loophole.
`070` — Export artifacts shall not become an automatic secret-storage loophole.
`071` — SOMA Local Administrator password authority remains separate from device credentials.
`072` — SOMA password verification remains governed by the authentication contract.
`073` — Live-data encryption keys remain governed separately from device credentials.
`074` — Portable-backup recovery secrets remain governed separately from device credentials.
`075` — The device-secret prohibition shall not redefine Local Administrator authentication fields.
`076` — The device-secret prohibition shall not redefine live-data encryption storage design.
`077` — The device-secret prohibition shall not redefine backup-recovery design.
`078` — Any future provider integration shall fail safely when provider API resolution fails.
`079` — Any future provider integration shall surface remediation without exposing secret material.
`080` — Any future provider integration shall preserve least-privilege access to the provider.
`081` — Exact provider technology remains a future design decision.
`082` — Exact provider resolution API remains a future design decision.
`083` — Exact provider authentication mechanics remain a future design decision.
`084` — No future design decision may weaken the no-local-secret-fallback invariant without new product authority.
`085` — Security tests shall verify that prohibited surfaces do not persist reusable device secrets.
`086` — Security tests shall verify that redaction and opaque-reference handling preserve the secret boundary.

## `BETA-REQ-0109` — prefix `STORE-AUTH`

**Governing obligation:** SQLite shall remain the complete authoritative operational datastore for every Beta 1.0 domain fact, relationship, invariant, lifecycle event, projection, import decision, and audit record, while any later measurement-justified graph engine may serve only as a versioned, rebuildable, disposable, non-authoritative projection whose absence or staleness cannot affect authoritative operation or meaning.

`001` — SQLite shall be SOMA Beta 1.0 authoritative operational datastore.
`002` — Every Beta 1.0 entity shall be persistable in SQLite.
`003` — Every Beta 1.0 relationship shall be persistable in SQLite.
`004` — Every Beta 1.0 invariant shall be enforceable using SQLite-backed authoritative state and application validation.
`005` — Every Beta 1.0 lifecycle event shall be persistable in SQLite.
`006` — Every Beta 1.0 current projection shall be reproducible from authoritative SQLite state.
`007` — Every Beta 1.0 import decision shall be persistable in SQLite.
`008` — Every Beta 1.0 audit record shall be persistable in SQLite.
`009` — Infrastructure Site placement shall be persistable in SQLite.
`010` — Room/Rack placement shall be persistable in SQLite.
`011` — IP inventory shall be persistable in SQLite.
`012` — Containment shall be persistable in SQLite.
`013` — Cloud Type shall be persistable in SQLite.
`014` — Cloud Deployment shall be persistable in SQLite.
`015` — Network Element Model shall be persistable in SQLite.
`016` — Component definitions/relationships shall be persistable in SQLite.
`017` — Infrastructure correction/history shall be persistable in SQLite.
`018` — Ticket facts shall be persistable in SQLite.
`019` — Objective/Task facts shall be persistable in SQLite.
`020` — Inventory facts shall be persistable in SQLite.
`021` — Communication retained facts shall be persistable in SQLite.
`022` — Settings and governed operational configuration shall be persistable or otherwise durably represented without requiring a separate database server.
`023` — Beta 1.0 authoritative queries shall work without a graph database.
`024` — Beta 1.0 authoritative writes shall work without a graph database.
`025` — Beta 1.0 startup shall work without a graph database.
`026` — Beta 1.0 imports shall work without a graph database.
`027` — Beta 1.0 background jobs shall work without a graph database.
`028` — Beta 1.0 reports shall work without a graph database.
`029` — Beta 1.0 shall not require a separately administered database server for authoritative operation.
`030` — SQLite constraints shall remain authoritative for relational integrity where applicable.
`031` — Application-level invariants shall not be weakened merely because SQLite lacks a native graph primitive.
`032` — Recursive relationship queries shall remain implementable without transferring truth to another engine.
`033` — Performance inconvenience alone shall not authorize dual authoritative stores.
`034` — A future graph engine shall require representative measurement before adoption.
`035` — Representative measurement shall demonstrate a justified use case rather than aesthetic preference.
`036` — Future graph adoption shall require an explicit architecture/design decision.
`037` — A future graph engine may only hold derived projection state.
`038` — Graph projection state shall derive from authoritative SQLite state.
`039` — Graph projection shall be rebuildable from SQLite.
`040` — Graph projection shall be disposable.
`041` — Graph projection shall be versioned.
`042` — Graph projection schema/version shall be independently identifiable.
`043` — Graph projection shall own no unique business fact.
`044` — Graph projection shall own no unique relationship.
`045` — Graph projection shall own no unique lifecycle event.
`046` — Graph projection shall own no unique audit record.
`047` — Graph projection shall accept no independent authoritative business write.
`048` — Graph projection write paths shall be projection-building paths only.
`049` — A graph mutation shall not bypass SQLite validation.
`050` — A graph mutation shall not become the source used to update SQLite as business truth.
`051` — Graph projection shall not weaken relational constraints.
`052` — Graph projection shall not reinterpret immutable identities.
`053` — Graph projection shall not invent missing relationships.
`054` — Graph projection shall not merge entities based on graph similarity.
`055` — Graph projection shall preserve authoritative identifiers as references.
`056` — Absence of the graph projection shall not block authoritative operation.
`057` — Staleness of the graph projection shall not block authoritative operation.
`058` — Failure to rebuild graph projection shall not corrupt SQLite truth.
`059` — Graph projection corruption shall be recoverable by rebuild.
`060` — Graph projection loss shall not cause authoritative data loss.
`061` — Graph projection staleness shall be detectable if surfaced to users.
`062` — Stale graph-derived UI shall not be presented as current authoritative state without qualification.
`063` — Graph projection shall not change the meaning of domain relationships.
`064` — Graph projection shall not change deletion eligibility.
`065` — Graph projection shall not change lifecycle eligibility.
`066` — Graph projection shall not change SLA results.
`067` — Graph projection shall not change communication matching authority.
`068` — Graph projection shall not change Inventory physical state.
`069` — Graph projection shall not change Infrastructure identity.
`070` — Projection rebuilding shall be idempotent.
`071` — Projection rebuilding shall tolerate restart from SQLite authoritative state.
`072` — Projection version changes shall not silently reinterpret authoritative history.
`073` — Projection migration shall remain separate from authoritative schema migration.
`074` — SQLite schema migration remains governed by the Foundation Runtime contract.
`075` — Foreign-key enforcement remains required on authoritative SQLite connections.
`076` — Transaction boundaries remain governed by SQLite/application persistence authority.
`077` — Import staging shall not become a second authoritative datastore.
`078` — UI caches shall not become a second authoritative datastore.
`079` — Background-job state shall not become a second domain datastore.
`080` — Exported workbooks shall not become an authoritative datastore.
`081` — PST/OST source stores shall not become SOMA domain truth merely because they provide evidence.
`082` — Portable backups shall represent protected copies rather than concurrent authoritative stores.
`083` — Restore shall establish one authoritative SQLite state according to recovery rules.
`084` — Tests shall demonstrate SQLite-only operation for core Beta 1.0 workflows.
`085` — Tests shall demonstrate projection absence does not change authoritative results.
`086` — Tests shall demonstrate projection staleness does not change authoritative results.
`087` — Tests shall demonstrate projection rebuild from SQLite.
`088` — Tests shall reject graph-only business writes if future graph support is introduced.
`089` — Operational support shall be able to identify the authoritative SQLite data instance.
`090` — Authoritative SQLite state shall remain inspectable through governed application diagnostics without exposing secrets.
`091` — No Beta 1.0 requirement may depend on an unapproved external database service.
`092` — Any future persistence change that makes another engine authoritative requires new explicit product/architecture authority.

## `BETA-REQ-0110` — prefix `INFRA-XLSX`

**Governing obligation:** SOMA Beta 1.0 shall provide versioned, macro-free, human-readable Infrastructure `.xlsx` templates and exports whose explicitly discovered imports are staged and transactionally reviewed, use installation-scoped identity safely, treat descriptive matches only as reconciliation evidence, preserve omission and blank values as non-destructive by default, remain idempotent, and never modify user-managed source workbooks or carry credentials or topology.

`001` — Beta 1.0 shall provide an Infrastructure `.xlsx` workbook family.
`002` — The workbook family shall be versioned.
`003` — Supported workbook versions shall be identifiable in the workbook format.
`004` — Unsupported versions shall not be silently imported as current format.
`005` — Infrastructure workbooks shall be macro-free.
`006` — SOMA shall not require VBA/macros for Infrastructure workbook behavior.
`007` — Infrastructure workbooks shall remain human-readable without SOMA.
`008` — The workbook family shall include an empty device-registration template.
`009` — The empty template shall be suitable for registering new Infrastructure device data.
`010` — The workbook family shall include a current-device discovery export.
`011` — The discovery export shall be human-readable.
`012` — The workbook family shall include a round-trip update export.
`013` — The round-trip export shall preserve same-installation identity needed for safe targeting.
`014` — Import source discovery shall use one configured Infrastructure directory.
`015` — Merely configuring the directory shall not import files automatically.
`016` — Import discovery shall occur through an explicit operator check/action.
`017` — Explicit discovery shall identify supported candidate workbooks.
`018` — Unsupported files shall be ignored or surfaced boundedly rather than parsed as supported workbooks.
`019` — Exports shall be written only to an operator-selected destination.
`020` — Export destination shall not redefine the configured import directory automatically.
`021` — Exporting shall not mutate the authoritative source workbook previously imported.
`022` — Exported workbooks shall remain operator-managed artifacts.
`023` — Supported format may represent Network Element internal/round-trip identity.
`024` — Supported format may represent Network Element operational name.
`025` — Supported format may represent Network Element Model relationship.
`026` — Supported format may represent manufacturer serial evidence.
`027` — Supported format may represent governing Site.
`028` — Supported format may represent same-Site Cloud Deployment.
`029` — Supported format may represent Room context.
`030` — Supported format may represent Rack placement.
`031` — Supported format may represent rack-unit position.
`032` — Supported format may represent zero-many IP addresses.
`033` — Supported format may represent primary-IP selection.
`034` — Supported format may represent containment parent.
`035` — Supported format may represent permitted Notes fields/content according to Notes authority.
`036` — Workbook shall not contain reusable device credentials.
`037` — Workbook shall not contain passwords.
`038` — Workbook shall not contain private keys.
`039` — Workbook shall not contain reusable authentication tokens.
`040` — Workbook shall not contain recovery codes.
`041` — Workbook shall not contain canonical connectivity edges in Beta 1.0.
`042` — Workbook shall not contain canonical topology paths in Beta 1.0.
`043` — Workbook shall not contain interface/port topology as Beta 1.0 authoritative data.
`044` — Workbook shall not imply SSH capability.
`045` — Every discovered import shall enter staging before authoritative mutation.
`046` — Staging shall identify proposed creations.
`047` — Staging shall identify proposed updates.
`048` — Staging shall identify unchanged rows.
`049` — Staging shall identify ambiguous matches.
`050` — Staging shall identify duplicate candidates.
`051` — Staging shall identify unknown references.
`052` — Staging shall identify invalid relationships.
`053` — Staging shall identify skipped rows where applicable.
`054` — Staging shall identify material warnings.
`055` — Staging shall distinguish warnings from errors.
`056` — Staging shall not itself accept domain mutations.
`057` — Operator review shall precede authoritative acceptance of staged material changes.
`058` — Acceptance shall revalidate current authoritative state.
`059` — Accepted workbook mutation shall commit transactionally within its governed scope.
`060` — Failed acceptance shall leave authoritative state unchanged for the failed transaction.
`061` — Partial acceptance shall occur only where the staging/transaction contract explicitly supports a complete valid subset.
`062` — Same-installation round-trip identity may target an existing Network Element exactly.
`063` — Same-installation identity shall be scoped to the installation that issued it.
`064` — Same-installation identity shall not be inferred from workbook filename.
`065` — Same-installation identity shall not be inferred from operator path.
`066` — Foreign-installation identity shall not directly target the local entity by identity alone.
`067` — Foreign-installation identity may be preserved as provenance.
`068` — Foreign-installation identity may be used as reconciliation evidence.
`069` — Foreign identity match shall require reviewed reconciliation before local identity association.
`070` — Operational names shall never prove entity identity.
`071` — Manufacturer serials shall never prove entity identity by themselves.
`072` — IP addresses shall never prove entity identity by themselves.
`073` — Site/Rack/Cloud labels shall never prove entity identity by themselves.
`074` — Descriptive combinations may form reconciliation evidence without becoming automatic identity proof.
`075` — Ambiguous descriptive matching shall not silently choose a target.
`076` — Duplicate candidate matching shall preserve separate identities until reviewed.
`077` — Missing workbook rows shall not imply deletion.
`078` — Missing workbook rows shall not imply archival.
`079` — Missing workbook rows shall not imply movement.
`080` — Missing workbook rows shall not imply unlinking.
`081` — Missing workbook rows shall not imply clearing optional facts.
`082` — Blank optional cells shall not imply deletion.
`083` — Blank optional cells shall not imply archival.
`084` — Blank optional cells shall not imply movement.
`085` — Blank optional cells shall not imply unlinking.
`086` — Blank optional cells shall not imply clearing an accepted optional value.
`087` — Clearing an accepted optional value shall require an explicit reviewed operation.
`088` — Deleting an entity shall require the owning deletion contract rather than omission from a workbook.
`089` — Moving a Network Element shall require explicit reviewed placement mutation.
`090` — Changing Cloud assignment shall require explicit reviewed relationship mutation.
`091` — Changing containment shall require explicit reviewed relationship mutation.
`092` — Changing primary IP shall require explicit reviewed mutation.
`093` — Import shall validate same-Site Rack relationships.
`094` — Import shall validate same-Site Cloud Deployment relationships.
`095` — Import shall validate containment acyclicity.
`096` — Import shall validate one-parent containment.
`097` — Import shall validate primary-IP cardinality.
`098` — Import shall reject credential-bearing authoritative fields.
`099` — Import shall reject or ignore unsupported topology fields without creating topology.
`100` — Reprocessing unchanged accepted workbook content shall be idempotent.
`101` — Reprocessing shall not duplicate Network Elements.
`102` — Reprocessing shall not duplicate IP relationships.
`103` — Reprocessing shall not duplicate containment relationships.
`104` — Reprocessing shall not duplicate Cloud assignments.
`105` — Reprocessing shall not duplicate accepted corrections.
`106` — Idempotency shall use accepted workbook identity/provenance rather than row order alone.
`107` — Source workbook shall remain unmodified during discovery.
`108` — Source workbook shall remain unmodified during parsing.
`109` — Source workbook shall remain unmodified during staging.
`110` — Source workbook shall remain unmodified during review.
`111` — Source workbook shall remain unmodified during acceptance.
`112` — SOMA shall not write result markers back into a user-managed source workbook.
`113` — SOMA shall expose import results separately from the source workbook.
`114` — Workbook parse errors shall not partially mutate authoritative Infrastructure.
`115` — Unsupported workbook version shall not partially mutate authoritative Infrastructure.
`116` — Import cancellation before commit shall not claim accepted mutations.
`117` — Import job failure shall preserve inspectable staging/result state where safe.
`118` — Export shall reflect accepted Infrastructure state rather than unsaved editor values.
`119` — Export shall not silently include unresolved secrets.
`120` — Export shall identify enough version/install provenance for safe round trip.
`121` — Human-readable labels may accompany stable round-trip identity.
`122` — Human-readable labels shall not replace stable round-trip identity where exact targeting is intended.
`123` — Temporary/provisional Device Reference evidence may appear in review where the workbook touches unresolved operational devices.
`124` — Workbook processing shall not force every Device Reference into a new Network Element.
`125` — A provisional Device Reference may be reconciled to an existing Network Element through governed Infrastructure resolution.
`126` — Reconciliation to an existing Network Element shall preserve the Device Reference identity.
`127` — Reconciliation to an existing Network Element shall preserve Network Element identity.
`128` — Reconciliation shall preserve original imported/descriptive evidence historically.
`129` — Terminal status of related Service Requests shall not make an Infrastructure reconciliation target immutable.
`130` — Infrastructure reconciliation shall not reopen a terminal Service Request.
`131` — Infrastructure reconciliation shall not rewrite terminal Service Request source-time text.
`132` — Workbook import/export shall remain a bounded Infrastructure workflow rather than a generalized synchronization authority.

## `BETA-REQ-0111` — prefix `COMM-GATE`

**Governing obligation:** SOMA shall read or process PST/OST message content only while at least one accepted communication-trackable entity exists, treating source validation and all Customer, Contact, Infrastructure, and other non-trackable records as insufficient to activate scanning, while no-target operation remains idle, retained history survives pauses, proposal review remains mandatory, and source stores remain read-only.

`001` — PST/OST message discovery requires at least one accepted trackable entity.
`002` — PST/OST message enumeration requires at least one accepted trackable entity.
`003` — PST/OST message parsing requires at least one accepted trackable entity.
`004` — PST/OST message indexing requires at least one accepted trackable entity.
`005` — PST/OST message matching requires at least one accepted trackable entity.
`006` — Staged or unsaved candidate entities do not satisfy the gate.
`007` — Rejected proposals do not satisfy the gate.
`008` — Source configuration alone does not satisfy the gate.
`009` — Valid source path alone does not satisfy the gate.
`010` — Successful source-access validation alone does not satisfy the gate.
`011` — Customer Organization records do not satisfy the gate.
`012` — Contact records do not satisfy the gate.
`013` — Site records do not satisfy the gate.
`014` — Dispatch Location records do not satisfy the gate.
`015` — Device Reference records do not satisfy the gate.
`016` — Network Element records do not satisfy the gate.
`017` — Network Element Model records do not satisfy the gate.
`018` — Component records do not satisfy the gate.
`019` — IP-address records do not satisfy the gate.
`020` — Infrastructure workbook presence does not satisfy the gate.
`021` — Other non-trackable descriptive facts do not satisfy the gate.
`022` — Local Tasks excluded by the tracking registry do not satisfy the gate.
`023` — With no trackable target, scheduled communication processing shall remain idle.
`024` — With no trackable target, manual Check now shall not read messages.
`025` — With no trackable target, targeted backfill shall not read messages unless a valid historical trackable target exists for that job.
`026` — With no trackable target, Deep Scan shall not enumerate messages.
`027` — No-target state shall be bounded and inspectable.
`028` — No-target state shall be distinguishable from source failure.
`029` — No-target state shall be distinguishable from operator-disabled scanning.
`030` — Source path/access validation may occur without message reads.
`031` — Validation without reads shall not enumerate folders/messages beyond what is strictly required to prove source accessibility.
`032` — Validation shall not persist unmatched message content.
`033` — Acceptance of the first trackable entity makes communication processing eligible.
`034` — Eligibility shall not mean that scanning has already occurred.
`035` — The workflow accepting the first target shall not scan inside its own import transaction.
`036` — Communication scanning shall run through its governed pipeline after eligibility.
`037` — Eligibility shall not bypass normal matching rules.
`038` — Eligibility shall not bypass retention rules.
`039` — Eligibility shall not bypass proposal review.
`040` — Eligibility shall not authorize lifecycle mutation from message content without acceptance.
`041` — If all active targets disappear or become non-active matching targets, ordinary scanning shall pause.
`042` — Pausing scanning shall not delete already retained Communications.
`043` — Pausing scanning shall not delete accepted Communication links that remain valid.
`044` — Pausing scanning shall not erase coverage history.
`045` — Pausing scanning shall not erase high-water history.
`046` — Re-enabling eligibility shall resume from governed durable state rather than start from zero automatically.
`047` — Retained historical/suppression identities may survive even when not active matching targets.
`048` — Terminal SR identity may remain suppression/history evidence without satisfying active-target matching.
`049` — Terminal RFC identity may remain suppression/history evidence without satisfying active-target matching.
`050` — PST source access shall remain read-only.
`051` — OST source access shall remain read-only.
`052` — Source validation shall not write to PST.
`053` — Source validation shall not write to OST.
`054` — Ordinary scanning shall not write to PST.
`055` — Ordinary scanning shall not write to OST.
`056` — Backfill shall not write to PST/OST.
`057` — Deep Scan shall not write to PST/OST.
`058` — Gate evaluation shall use accepted tracking-registry state.
`059` — Unsaved identifier edits shall not activate the gate.
`060` — Ambiguous identifiers shall not activate a new target automatically.
`061` — Unknown valid-looking identifiers shall not create targets.
`062` — Infrastructure typo correction alone shall not trigger a Deep Scan.
`063` — Device Reference reconciliation alone shall not trigger a Deep Scan.
`064` — The gate shall not require network connectivity or online mailbox access.
`065` — The gate applies to local PST/OST processing only.
`066` — Exact PST/OST library support remains an adapter design decision.
`067` — Adapter design shall not weaken the no-target no-read rule.
`068` — UI shall explain why scanning is idle when no trackable target exists.
`069` — Tests shall verify that non-trackable-only databases cause no message reads.
`070` — Tests shall verify that accepted trackable identity activates eligibility without bypassing review or read-only constraints.

## `BETA-REQ-0112` — prefix `COMM-ID`

**Governing obligation:** SOMA shall maintain a communication-tracking registry in which only accepted governed ticket, request, obligation, WFM, Objective, and Fault Tag identities can resolve directly to exactly one owning entity, while Local Tasks, Customer/Contact, Infrastructure, and other descriptive facts remain non-trackable, unknown or ambiguous identifiers never authorize silent mutation, and terminal SR/RFC identities persist only as historical or suppression authority rather than active matching targets.

`001` — Communication tracking shall use a governed registry of trackable identities.
`002` — Each accepted trackable identity shall resolve to exactly one owning entity.
`003` — Registry resolution shall use immutable owning-entity identity internally.
`004` — A registry identity shall not create a duplicate owning entity.
`005` — Service Request official identity shall be trackable.
`006` — Official Service Request identifier shall contain exactly eight digits under the accepted SR convention.
`007` — `SR ` display context may represent the official eight-digit Service Request identity.
`008` — `TT ` display context may represent the same accepted Service Request identity where governed by presentation/source context.
`009` — Display prefix differences shall not create two Service Requests.
`010` — Locally represented Service Request identity such as LSR shall be trackable where accepted.
`011` — LSR identity shall resolve to one Service Request.
`012` — Spare Request local/temporary identity may be trackable before official SR7 exists.
`013` — Spare Request official SR7 identity shall be trackable after acceptance.
`014` — Temporary and official Spare Request identities shall resolve to the same owning Spare Request when reconciled.
`015` — Official SR7 shall not replace Spare Request internal identity.
`016` — RMA current C10 identifier shall be trackable.
`017` — Preserved accepted prior C10 aliases may remain trackable for reconciliation/history.
`018` — RMA alias shall resolve to the same RMA obligation rather than create a duplicate.
`019` — Correcting C10 shall preserve prior alias evidence.
`020` — RFC canonical `NC` plus fourteen-digit identifier shall be trackable.
`021` — Accepted provisional RFC identity may be trackable where the owning RFC contract permits it.
`022` — Provisional RFC identity shall resolve to one RFC.
`023` — Later canonical RFC identity shall enrich the same RFC rather than duplicate it.
`024` — WFM Task `TK` plus fourteen-digit identity shall be trackable.
`025` — WFM identity shall resolve to one WFM Task.
`026` — Objective immutable SOMA tracking identity shall be trackable.
`027` — Objective tracking identity shall resolve to one Objective.
`028` — Fault Tag immutable SOMA tracking identity shall be trackable.
`029` — Fault Tag operator-visible tracking identity may be recognized as governed alias where supported.
`030` — Fault Tag identities shall resolve to one Fault Tag.
`031` — Local Tasks shall not be automatically trackable by Communication Processing.
`032` — A Local Task name shall not become trackable identity.
`033` — A Local Task internal identity shall not automatically become a mail-search token without separate authority.
`034` — Customer Organization identity shall not be direct communication-trackable identity.
`035` — Customer name shall not be trackable identity.
`036` — Contact identity shall not be direct trackable identity.
`037` — Contact name shall not be trackable identity.
`038` — Contact email address shall not be direct trackable identity.
`039` — Device Reference identity shall not be direct trackable identity.
`040` — Network Element identity shall not be direct trackable identity.
`041` — Device name shall not be direct trackable identity.
`042` — Manufacturer serial shall not be direct trackable identity.
`043` — BOM/Part Number shall not be direct trackable identity.
`044` — IP address shall not be direct trackable identity.
`045` — Site identity/name shall not be direct trackable identity.
`046` — Rack identity/name shall not be direct trackable identity.
`047` — Cloud Type identity/name shall not be direct trackable identity.
`048` — Cloud Deployment identity/name shall not be direct trackable identity.
`049` — Model identity/name shall not be direct trackable identity.
`050` — Other descriptive facts shall not become direct trackable identity without explicit authority.
`051` — Matching descriptive facts may support proposal context but not registry identity proof.
`052` — A syntactically valid-looking SR identifier unknown to the registry shall remain unknown.
`053` — Unknown SR-like identity shall not create a Service Request silently.
`054` — Unknown SR7-like identity shall not create a Spare Request silently.
`055` — Unknown C10-like identity shall not create an RMA silently.
`056` — Unknown RFC-like identity shall not create an RFC silently.
`057` — Unknown TK-like identity shall not create a WFM silently.
`058` — Unknown Objective-like identity shall not create an Objective silently.
`059` — Unknown Fault-Tag-like identity shall not create a Fault Tag silently.
`060` — Ambiguous identity matches shall not choose an owner silently.
`061` — Ambiguity shall be surfaced for review or excluded from mutation.
`062` — One message may match several distinct accepted trackable entities.
`063` — Multiple target matches shall be represented as independent typed links to one canonical Communication.
`064` — Repeated occurrence of one entity alias shall not create duplicate links to that entity.
`065` — Current and historical aliases shall retain their observed matched identifier evidence.
`066` — Communication matching shall preserve which identifier or alias was observed.
`067` — Communication matching shall preserve match reason.
`068` — Communication matching shall preserve decision chronology.
`069` — Registry changes shall preserve accepted identity history.
`070` — Identifier correction shall not rewrite message source evidence.
`071` — Identifier correction shall not rewrite the owning entity internal identity.
`072` — Terminal Service Request identity shall remain historical/suppression evidence after direct active matching is removed.
`073` — Terminal RFC identity shall remain historical/suppression evidence after direct active matching is removed.
`074` — Terminal SR shall not remain an active direct target merely because its identifier still exists in history.
`075` — Terminal RFC shall not remain an active direct target merely because its identifier still exists in history.
`076` — Terminal-state proposal alone shall not deactivate the identity before terminal acceptance.
`077` — Staging alone shall not deactivate the identity.
`078` — Historical-view placement alone shall not deactivate the identity.
`079` — Accepted terminal decision shall trigger the separately governed direct-link/suppression behavior.
`080` — Terminal identity history shall support duplicate-suppression/recovery without preserving active link authority.
`081` — A later message containing terminal SR/RFC identity shall not itself reopen the ticket.
`082` — A later accepted owning-domain terminal correction may make the entity eligible again according to the ticket lifecycle contract.
`083` — Communication registry shall consume accepted terminal correction rather than own reopening.
`084` — Tracking registry shall not depend on message subject alone.
`085` — Tracking registry shall not depend on participant identity alone.
`086` — Tracking registry shall not depend on body similarity alone.
`087` — Tracking registry shall not depend on attachment content alone.
`088` — Tracking registry shall not use Customer name as fallback target identity.
`089` — Tracking registry shall not use device name as fallback target identity.
`090` — Tracking registry shall not use serial as fallback target identity.
`091` — Tracking registry shall not use IP as fallback target identity.
`092` — Registry lookup shall be deterministic for accepted unique identifiers.
`093` — Registry lookup shall preserve alias type.
`094` — Registry lookup shall preserve owning entity type.
`095` — Registry lookup shall preserve current/historical/suppression eligibility state.
`096` — Registry entries shall be queryable without scanning PST/OST content.
`097` — Registering a trackable identity shall be a domain acceptance result, not a mail-side mutation.
`098` — Communication Processing shall not edit domain identifiers directly.
`099` — Communication proposals may suggest corrections only through owning-domain review paths where separately permitted.
`100` — Local Task exclusion shall remain explicit in UI/diagnostics where relevant.
`101` — Customer/Contact exclusion shall remain explicit in matching design.
`102` — Infrastructure exclusion shall remain explicit in matching design.
`103` — Registry shall support both current and accepted alias forms without duplicate ownership.
`104` — Registry shall reject one accepted identifier mapping to two active owning entities unless explicitly marked ambiguous for review.
`105` — Duplicate identifier conflict shall not be resolved by last-write-wins.
`106` — Registry correction shall preserve prior conflicting evidence.
`107` — Tests shall cover every supported trackable entity type.
`108` — Tests shall cover every explicitly non-trackable category.
`109` — Tests shall cover unknown and ambiguous valid-looking identifiers.
`110` — Tests shall cover terminal SR/RFC suppression without silent reopen or duplicate creation.

## `BETA-REQ-0113` — prefix `COMM-COVER`

**Governing obligation:** SOMA shall derive initial PST/OST coverage from the earliest independently supported chronology of active trackable entities without inventing missing business time, and shall thereafter maintain source-scoped durable high-water and historical-coverage state that advances only after successful durable work, supports bounded idempotent replay and reviewed source changes, and uses targeted backfill rather than global rewind for newly relevant older history.

`001` — Initial communication coverage shall derive from accepted trackable-entity chronology.
`002` — Initial lower bound shall use the earliest independently supported relevant time among active trackable entities.
`003` — Relevant chronology shall come from the owning domain's accepted facts.
`004` — Import time shall not substitute for missing business chronology.
`005` — Discovery time shall not substitute for missing business chronology.
`006` — Index time shall not substitute for missing business chronology.
`007` — Current-clock time shall not substitute for missing business chronology.
`008` — File modification time shall not substitute for missing business chronology unless separately accepted as source evidence for that exact purpose.
`009` — Missing business time shall remain unknown.
`010` — Unknown time shall not be fabricated merely to begin scanning.
`011` — When no reliable automatic lower bound exists, SOMA shall require operator-selected lower bound or explicit Deep Scan.
`012` — Operator-selected lower bound shall be recorded as coverage scope evidence.
`013` — Deep Scan remains separately confirmed under its contract.
`014` — Missing reliable lower bound shall produce a coverage warning.
`015` — Coverage warning shall remain visible until resolved or superseded by accepted coverage evidence.
`016` — Initial processing shall not rewrite source entity chronology.
`017` — Initial processing shall not rewrite ticket timestamps.
`018` — Initial processing shall not rewrite Spare Request/RMA chronology.
`019` — Initial processing shall not rewrite Objective/Fault Tag chronology.
`020` — Communication Source Scope shall participate in coverage identity.
`021` — Coverage state shall be source-scoped.
`022` — Coverage state shall be folder-scoped where folder scope is materially part of the adapter contract.
`023` — Coverage state shall be profile/account-scoped where applicable.
`024` — High-water state shall not be global across unrelated source scopes.
`025` — Historical coverage shall not be global across unrelated source scopes.
`026` — Ordinary forward processing shall maintain durable high-water state.
`027` — High-water shall advance only after successful durable processing of the applicable work.
`028` — Merely discovering content shall not advance high-water.
`029` — Merely inspecting transient content shall not advance high-water beyond failed durable work.
`030` — Merely matching content shall not advance high-water if required retention/proposal commit fails.
`031` — Cancellation shall not advance high-water beyond durable completed work.
`032` — Failure shall not advance high-water beyond durable completed work.
`033` — Crash shall not advance high-water based on volatile progress.
`034` — High-water shall never leap over failed content as though covered.
`035` — Historical coverage shall record durable completed ranges.
`036` — Partial historical work shall claim only completed durable ranges.
`037` — Unknown or failed gaps shall remain represented as gaps.
`038` — Historical coverage and forward high-water shall remain distinct concepts.
`039` — Forward high-water shall not imply complete historical coverage before the lower bound.
`040` — Historical backfill shall not reset forward high-water unnecessarily.
`041` — Ordinary processing shall use bounded overlap around durable progress where required for robustness.
`042` — Overlap size shall be bounded.
`043` — Overlap replay shall be idempotent.
`044` — Overlap replay shall not duplicate Communications.
`045` — Overlap replay shall not duplicate accepted links.
`046` — Overlap replay shall not duplicate lifecycle proposals.
`047` — Overlap replay shall not double-advance coverage.
`048` — Provider-stable or fallback message identity shall support overlap deduplication.
`049` — Source/folder change shall be detected rather than silently reuse unrelated watermark state.
`050` — Source path change alone shall not necessarily mean a new Source Scope.
`051` — Replacement store shall require reviewed source-scope reconciliation.
`052` — Overlapping store shall require reviewed source-scope reconciliation.
`053` — Reviewed source change may reuse compatible coverage where identity is established.
`054` — Reviewed source change may rescope coverage where appropriate.
`055` — Reviewed source change may reset coverage only through explicit governed decision.
`056` — Source change shall not silently claim old ranges complete in a new unrelated scope.
`057` — Folder change shall not silently share watermark without compatible scope semantics.
`058` — Source-scope reconciliation shall preserve previous provenance.
`059` — Newer source observation shall not erase prior coverage history.
`060` — Newly accepted older entity shall be compared with completed coverage.
`061` — Newly accepted older identifier shall be compared with completed coverage.
`062` — Newly accepted older alias shall be compared with completed coverage.
`063` — Newly accepted earlier chronology shall be compared with completed coverage.
`064` — If relevant older time lies outside completed coverage, targeted backfill shall be considered.
`065` — Older entity shall not force global rewind of unrelated target history.
`066` — Older entity shall not reset forward high-water.
`067` — Older entity shall not erase completed historical ranges.
`068` — Targeted backfill shall remain identity/range scoped under `0114`.
`069` — Initial coverage lower bound shall be reproducible from accepted chronology and operator decisions.
`070` — Coverage warnings shall distinguish missing-lower-bound from source-unavailable state.
`071` — Coverage warnings shall distinguish partial historical gaps from stale forward processing.
`072` — Coverage summary shall not claim completeness when gaps exist.
`073` — Communication counts shall be qualified by coverage where relevant.
`074` — No-message result with incomplete coverage shall not imply no historical message exists.
`075` — Source deletion/unavailability shall not fabricate completed coverage.
`076` — Source-unavailable intervals shall remain explainable.
`077` — Reconnected source shall resume from durable compatible state after validation.
`078` — Coverage state shall be independently auditable from message content.
`079` — Coverage metadata shall not reconstruct unmatched messages.
`080` — High-water metadata shall not reconstruct unmatched messages.
`081` — Coverage metadata may preserve bounded source/range/count facts.
`082` — Coverage metadata shall avoid unnecessary participant/body/subject data.
`083` — Manual Check now shall use the same durable coverage semantics.
`084` — Startup catch-up shall use the same durable coverage semantics.
`085` — Scheduled processing shall use the same durable coverage semantics.
`086` — Targeted backfill shall update historical coverage only for completed ranges.
`087` — Deep Scan shall update historical coverage only for completed ranges.
`088` — Cancellation of Backfill/Deep Scan shall preserve prior completed ranges.
`089` — Retry shall resume from durable range state idempotently.
`090` — Coverage state shall not become authoritative for ticket chronology.
`091` — Coverage state shall not become authoritative for message chronology.
`092` — Coverage state shall not become authoritative for domain lifecycle state.
`093` — Exact adapter cursor representation remains LLD design.
`094` — Exact overlap size remains LLD/configuration design within bounded replay.
`095` — Exact source/folder/profile key structure remains LLD design while preserving scope identity.
`096` — Tests shall cover initial earliest-supported chronology.
`097` — Tests shall cover missing chronology requiring operator lower bound or Deep Scan.
`098` — Tests shall cover failed/cancelled ranges not advancing state.
`099` — Tests shall cover older newly relevant history using targeted backfill without global rewind.

## `BETA-REQ-0114` — prefix `COMM-BACKFILL`

**Governing obligation:** SOMA shall repair newly discovered historical communication gaps through identity- and range-scoped targeted backfill that preserves unrelated forward progress, allowing only accepted bounded work to run without additional confirmation, while every broader Deep Scan requires explicit reviewed scope and both modes retain the ordinary read-only, identity, matched-only persistence, proposal, redaction, cancellation, idempotency, and durable-coverage rules.

`001` — SOMA shall detect when newly accepted historical facts fall outside completed relevant coverage.
`002` — Newly accepted older entity may create a backfill need.
`003` — Newly accepted older identifier may create a backfill need.
`004` — Newly accepted older alias may create a backfill need.
`005` — Reviewed identity reconciliation may create a backfill need.
`006` — Newly accepted earlier chronology may create a backfill need.
`007` — Backfill need shall be evaluated against completed source/folder coverage.
`008` — No backfill job shall be created when the relevant range is already durably covered and identity replay is unnecessary.
`009` — Targeted backfill shall identify the relevant target identity or identities.
`010` — Targeted backfill shall identify an exact bounded historical range.
`011` — Targeted backfill shall identify the Communication Source Scope.
`012` — Targeted backfill may identify folder scope where applicable.
`013` — Targeted backfill shall not imply global mailbox rewind.
`014` — Targeted backfill shall not reset unrelated forward high-water.
`015` — Targeted backfill shall not discard unrelated historical coverage.
`016` — Targeted backfill shall not rescan unrelated targets without scope justification.
`017` — Backfill scope shall be minimized to the missing identity/range need.
`018` — Backfill shall preserve ordinary source read-only behavior.
`019` — Backfill shall preserve Communication Source Scope rules.
`020` — Backfill shall preserve provider/fallback identity rules.
`021` — Backfill shall preserve canonical Communication deduplication.
`022` — Backfill shall preserve matched-only persistence.
`023` — Backfill shall inspect unmatched content transiently only.
`024` — Backfill shall not build a persistent index of unrelated unmatched messages.
`025` — Backfill shall preserve typed-link acceptance rules.
`026` — Backfill shall preserve lifecycle-proposal separation.
`027` — Backfill shall preserve redacted diagnostics.
`028` — Backfill shall preserve cancellation semantics.
`029` — Backfill shall preserve idempotency.
`030` — Backfill shall preserve durable-coverage semantics.
`031` — Backfill shall preserve failure behavior.
`032` — Backfill shall preserve retry behavior where applicable.
`033` — Backfill shall not write to PST.
`034` — Backfill shall not write to OST.
`035` — Backfill shall not modify source folders.
`036` — Backfill shall not alter source message flags.
`037` — Backfill shall not delete source messages.
`038` — A bounded-work class may be approved to run without extra per-job confirmation.
`039` — Only separately accepted bounded-work classes may skip added confirmation.
`040` — Bounded-work auto-run shall still expose its job/result where materially long.
`041` — Bounded-work auto-run shall not accept lifecycle effects automatically unless separately authorized.
`042` — Bounded-work auto-run shall not become Deep Scan.
`043` — Exact thresholds for bounded-work classes remain LLD/configuration subject to accepted authority.
`044` — Unknown scope shall require preview before backfill execution.
`045` — Large scope shall require preview before backfill execution.
`046` — Preview shall identify target/range/source scope sufficiently for review.
`047` — Preview shall not expose prohibited reconstructable message content.
`048` — Operator may cancel before executing an unaccepted large/unknown backfill.
`049` — Deep Scan shall remain distinct from targeted backfill.
`050` — Every Deep Scan shall require explicit operator scope confirmation.
`051` — Deep Scan confirmation shall identify the requested source scope.
`052` — Deep Scan confirmation shall identify historical range or breadth.
`053` — Deep Scan shall not start merely because SOMA starts.
`054` — Deep Scan shall not start merely because scheduled ordinary processing runs.
`055` — Deep Scan shall not start merely because source configuration changes.
`056` — Deep Scan shall not start merely because Infrastructure is imported.
`057` — Deep Scan shall not start merely because a device is created.
`058` — Deep Scan shall not start merely because a Device Reference is reconciled.
`059` — Deep Scan shall not start merely because a trackable entity is normally created.
`060` — Deep Scan shall not start as generic failure fallback.
`061` — Deep Scan shall not start because ordinary processing encounters an error.
`062` — Deep Scan shall not start because targeted backfill encounters an error.
`063` — Deep Scan shall not start because a report is generated.
`064` — Deep Scan shall not start because `.msg` is generated.
`065` — Deep Scan shall not start because orphan housekeeping runs.
`066` — `Check now` shall not silently become Deep Scan.
`067` — Startup catch-up shall not silently become Deep Scan.
`068` — Explicit multi-workflow actions shall label Deep Scan separately if offered.
`069` — Deep Scan shall preserve ordinary read-only source behavior.
`070` — Deep Scan shall preserve Communication Source Scope identity rules.
`071` — Deep Scan shall preserve provider/fallback message identity rules.
`072` — Deep Scan shall preserve canonical deduplication.
`073` — Deep Scan shall preserve matched-only retention.
`074` — Deep Scan shall preserve transient inspection of unmatched messages.
`075` — Deep Scan shall preserve typed-link acceptance rules.
`076` — Deep Scan shall preserve proposal review.
`077` — Deep Scan shall preserve redacted diagnostics.
`078` — Deep Scan shall preserve cancellation semantics.
`079` — Deep Scan shall preserve idempotency.
`080` — Deep Scan shall preserve durable historical coverage semantics.
`081` — Deep Scan shall not imply full coverage until completed durable ranges support that claim.
`082` — Partial Deep Scan shall record only completed ranges.
`083` — Cancelled Deep Scan shall not claim unfinished range coverage.
`084` — Failed Deep Scan shall not claim unfinished range coverage.
`085` — Deep Scan shall not reset forward high-water merely because it scans older history.
`086` — Backfill shall not reset forward high-water merely because it scans older history.
`087` — Backfill results shall remain distinguishable from ordinary-forward results.
`088` — Deep Scan results shall remain distinguishable from targeted-backfill results.
`089` — Backfill job identity shall be independently inspectable where job abstraction applies.
`090` — Deep Scan job identity shall be independently inspectable.
`091` — Backfill cancellation shall occur at safe job checkpoints.
`092` — Deep Scan cancellation shall occur at safe job checkpoints.
`093` — Retried backfill shall not duplicate Communications.
`094` — Retried Deep Scan shall not duplicate Communications.
`095` — Retried backfill shall not duplicate proposals.
`096` — Retried Deep Scan shall not duplicate proposals.
`097` — Backfill may rediscover a previously purged Communication after an accepted terminal correction.
`098` — Purge-recovery backfill shall reconcile rediscovered content using normal identity rules.
`099` — Purge-recovery backfill shall not reconstruct content from suppression metadata alone.
`100` — Source unavailability during required historical recovery shall produce a coverage warning.
`101` — Coverage warning shall not fabricate missing messages.
`102` — Newly available historical source may later satisfy previously warned gaps through targeted backfill.
`103` — Backfill shall preserve source/folder provenance.
`104` — Deep Scan shall preserve source/folder provenance.
`105` — Matching reason shall remain attributable to the target identity encountered.
`106` — Backfill shall not write directly to owning domain lifecycle state.
`107` — Deep Scan shall not write directly to owning domain lifecycle state.
`108` — Lifecycle effects remain reviewed proposals or separately permitted manual actions.
`109` — Exact bounded-work thresholds remain design/configuration decisions.
`110` — Exact backfill batching strategy remains LLD design.
`111` — Exact Deep Scan batching strategy remains LLD design.
`112` — LLD shall not weaken explicit Deep Scan confirmation through batching.
`113` — Tests shall cover targeted older identity without global rewind.
`114` — Tests shall cover Deep Scan never auto-starting from startup/schedule/import/failure.
`115` — Tests shall cover cancellation/idempotency/read-only/matched-only persistence equivalently across Backfill and Deep Scan.

## `BETA-REQ-0115` — prefix `COMM-RETAIN`

**Governing obligation:** SOMA shall inspect unmatched PST/OST content only transiently and retain no reconstructable per-message content unless at least one governed relationship to a trackable entity is accepted, after which one canonical Communication may hold independently correctable typed links to any number of targets while lifecycle effects remain separate proposals and loss of every valid dependency transfers the Communication to the governed orphan-grace process.

`001` — Unmatched PST/OST content may be inspected transiently.
`002` — Transient inspection shall not itself create a retained Communication.
`003` — Unmatched transient content shall not persist as reconstructable per-message state.
`004` — Processing may discard unmatched message content after the current bounded inspection step.
`005` — Unmatched message body shall not persist.
`006` — Unmatched message subject shall not persist.
`007` — Unmatched message participants shall not persist.
`008` — Unmatched message attachments shall not persist.
`009` — Unmatched per-message search-index content shall not persist.
`010` — Unmatched per-message normalized-body content shall not persist.
`011` — Unmatched per-message normalized-subject content shall not persist.
`012` — Unmatched per-message participant indexes shall not persist.
`013` — Unmatched attachment-derived search material shall not persist.
`014` — Unmatched opaque metadata shall not persist when it materially reconstructs the message.
`015` — Hash/fingerprint persistence shall not be used to create a permanent unmatched-message catalogue except bounded non-reconstructable scan/suppression evidence explicitly permitted elsewhere.
`016` — Unmatched source-folder observations shall not become a per-message retained index.
`017` — Unmatched source-path observations shall not become a per-message retained index.
`018` — Unmatched message-time facts shall not be retained as a reconstructable message catalogue.
`019` — Unmatched per-message identity evidence shall not persist solely to support later unrestricted search.
`020` — Retention minimization applies regardless of ordinary scan, backfill, or Deep Scan origin.
`021` — Bounded scan-level progress facts may persist without a matched Communication.
`022` — Bounded source coverage facts may persist without a matched Communication.
`023` — Bounded aggregate count facts may persist without a matched Communication.
`024` — Bounded error facts may persist without a matched Communication.
`025` — Permitted unmatched scan facts shall not reconstruct message body.
`026` — Permitted unmatched scan facts shall not reconstruct message subject.
`027` — Permitted unmatched scan facts shall not reconstruct participants or attachments.
`028` — Permitted unmatched scan facts shall remain source/range/job scoped rather than per-message content stores.
`029` — Retaining a canonical Communication requires at least one accepted governed relationship to a trackable entity.
`030` — A mere candidate relationship shall not satisfy the retention gate.
`031` — An ambiguous match shall not satisfy the retention gate.
`032` — A rejected relationship shall not satisfy the retention gate.
`033` — An operator-accepted relationship may satisfy the retention gate.
`034` — A safely accepted relationship may satisfy the retention gate only when its class is separately approved.
`035` — Safe relationship acceptance shall require an unambiguous approved class.
`036` — Safe relationship acceptance shall preserve the same target/link evidence required by reviewed acceptance.
`037` — Safe acceptance shall not be inferred merely because an identifier looks syntactically valid.
`038` — Safe acceptance shall not be inferred from descriptive Customer/Contact/Infrastructure evidence.
`039` — Exact safe-auto-accept classes remain governed by technical/product item `O-007`.
`040` — An unapproved class shall require review.
`041` — Accepting a Communication relationship shall remain distinct from accepting a lifecycle effect.
`042` — Retaining a matched Communication shall not automatically mark an RMA lifecycle step complete.
`043` — Retaining a matched Communication shall not automatically submit a Spare Request.
`044` — Retaining a matched Communication shall not automatically accept a warehouse decision.
`045` — Lifecycle effects shall remain separate proposals unless separately authorized.
`046` — Proposal rejection shall not require rejection of the underlying valid Communication relationship.
`047` — One retained real message shall have one canonical SOMA Communication identity.
`048` — Reobservation of the same canonical message shall not create a second retained Communication.
`049` — Folder duplication shall reconcile to the canonical Communication under message-identity rules.
`050` — Overlap replay shall reconcile to the canonical Communication under message-identity rules.
`051` — A canonical Communication may have zero or many historical link records while only accepted current links determine current relationship projection.
`052` — A canonical Communication may link to one trackable entity.
`053` — A canonical Communication may link to many distinct trackable entities.
`054` — Each Communication-to-entity link shall be independently identifiable.
`055` — Each link shall be typed by target entity/domain type as applicable.
`056` — Each link shall preserve target internal identity.
`057` — Multiple identifier occurrences for the same target shall not require duplicate canonical message copies.
`058` — Multiple aliases for one target shall not require duplicate current links.
`059` — One message may simultaneously link to SR, Spare Request, RMA, RFC, WFM, Objective, or Fault Tag identities where accepted.
`060` — Each link shall preserve the matched observed identifier or alias when available.
`061` — Correcting the target's current identifier shall not rewrite what identifier the historical message contained.
`062` — Alias correction shall preserve observed source evidence.
`063` — Link matching evidence shall remain distinguishable from current target display identity.
`064` — Each link shall preserve match reason.
`065` — Each link shall preserve acceptance/rejection/correction decision state.
`066` — Each link shall preserve decision chronology.
`067` — Each link shall preserve operator or safe-class source of acceptance where applicable.
`068` — Link correction shall preserve the original link decision historically.
`069` — Link correction shall target the exact relationship being corrected.
`070` — Current link projection shall derive from accepted relationship/correction history.
`071` — Correcting one link shall not rewrite the canonical Communication.
`072` — Correcting one link shall not rewrite another valid link.
`073` — Rejecting one candidate link shall not reject unrelated valid links.
`074` — Reassigning one mistaken link shall preserve other target relationships.
`075` — Removing one current link shall not delete the canonical Communication while another protected dependency remains.
`076` — Link-level correction shall be transactionally validated against current target identity.
`077` — A Communication with several entity links shall remain one message in storage.
`078` — A Communication with several entity links may appear in each linked entity's derived summary.
`079` — Per-entity counts shall avoid duplicate contribution from duplicate aliases/links to the same entity.
`080` — Link correction history shall remain auditable.
`081` — Loss of the final valid protected dependency shall not immediately hard-delete the Communication.
`082` — Loss of the final valid protected dependency shall invoke the orphan-grace contract in `BETA-REQ-0116`.
`083` — Orphan-grace timing is owned by `BETA-REQ-0116` rather than this requirement.
`084` — Terminal unlink timing is owned by `BETA-REQ-0116` rather than this requirement.
`085` — Revalidation before purge is owned by `BETA-REQ-0116` rather than this requirement.
`086` — Orphan purge shall not occur merely because one of several links is removed.
`087` — A restored valid dependency during grace shall be consumed under `0116` rather than creating a duplicate Communication.
`088` — Retention state shall remain reproducible from canonical Communication and dependency/link state.
`089` — After an eligible purge, only bounded non-reconstructable decision/suppression/purge evidence may remain.
`090` — Post-purge evidence shall not reconstruct the body.
`091` — Post-purge evidence shall not reconstruct the subject.
`092` — Post-purge evidence shall not reconstruct participants.
`093` — Post-purge evidence shall not reconstruct attachments.
`094` — Post-purge evidence may support duplicate suppression, audit, and targeted recovery without becoming a hidden retained message.
`095` — Tests shall prove unmatched-no-persistence, one-canonical-many-links, independent link correction, and final-dependency orphan transfer.

## `BETA-REQ-0116` — prefix `COMM-ORPHAN`

**Governing obligation:** Accepted terminal SR/RFC transitions shall remove only their own direct Communication links, and a Communication losing its final protected dependency shall enter a configurable positive orphan grace of seven exact elapsed days by default, after which transactional revalidation may purge only reconstructable SOMA-held content while preserving bounded suppression evidence and supporting dependency restoration or targeted source recovery after a later accepted terminal reversal.

`001` — Direct SR communication unlinking shall occur only after the SR's terminal-state decision is authoritatively accepted.
`002` — Direct RFC communication unlinking shall occur only after the RFC's terminal-state decision is authoritatively accepted.
`003` — A terminal-state proposal shall not trigger communication unlinking before acceptance.
`004` — A staged terminal transition shall not trigger communication unlinking before acceptance.
`005` — Merely displaying a record in Historical shall not trigger communication unlinking.
`006` — Disappearance from an active view shall not trigger communication unlinking.
`007` — Inclusion in a report shall not trigger communication unlinking.
`008` — Inactivity shall not trigger communication unlinking.
`009` — Elapsed time alone shall not make an active SR/RFC relationship terminal.
`010` — Accepted terminal SR handling shall target that SR's direct Communication links.
`011` — Accepted terminal RFC handling shall target that RFC's direct Communication links.
`012` — Terminal transition of one entity shall not automatically remove unrelated entity links from the same Communication.
`013` — Removal of a terminal entity link shall preserve the canonical Communication identity.
`014` — Removal of one terminal entity link shall preserve other valid Communication relationships.
`015` — A Communication linked to another valid trackable entity shall not become orphaned solely because one SR/RFC becomes terminal.
`016` — Protected lifecycle proposals may remain a dependency preventing purge.
`017` — Protected correction relationships may remain a dependency preventing purge.
`018` — Other protected operational dependencies defined by the communication lifecycle shall prevent orphan purge while valid.
`019` — Orphan determination shall consider all protected dependencies, not only direct SR/RFC links.
`020` — A Communication shall become orphan-eligible only when its final valid protected dependency is lost.
`021` — Loss of one among several dependencies shall not make the Communication orphaned.
`022` — Orphan determination shall derive from authoritative current relationship/correction state.
`023` — A Communication with at least one current valid dependency shall remain retained.
`024` — Loss of the final valid dependency shall transition the Communication to `Orphaned — Pending Purge`.
`025` — `Orphaned — Pending Purge` shall remain distinct from immediately purged.
`026` — Entering orphan state shall preserve the Communication's reconstructable content during the grace period.
`027` — Entering orphan state shall preserve existing identity and relevant history.
`028` — Orphan purge shall use a configurable positive grace period.
`029` — The default orphan grace period shall be seven exact elapsed days.
`030` — A configured grace period shall be greater than zero.
`031` — Grace duration shall use elapsed-time semantics rather than calendar-day counting.
`032` — Grace calculation shall follow the accepted Temporal contract.
`033` — Grace timing shall begin when loss of the final valid dependency is authoritatively accepted.
`034` — Proposal or staging time shall not start the grace period.
`035` — Historical-view placement shall not start the grace period.
`036` — Discovery/indexing/current time shall not substitute for the accepted orphan transition chronology.
`037` — Restoration of a valid dependency during grace shall cancel pending purge.
`038` — Dependency restoration shall preserve the same Communication identity.
`039` — Cancelled purge shall not discard the retained Communication body or metadata.
`040` — A later loss of the final dependency may begin a new governed orphan-grace cycle.
`041` — Previous orphan/cancellation history shall remain auditable.
`042` — Reaching the grace due time shall make the Communication eligible for purge evaluation.
`043` — Reaching the due time alone shall not authorize blind deletion.
`044` — Purge evaluation may occur at the due time or the next eligible startup/housekeeping boundary.
`045` — Delayed housekeeping shall not backdate an unperformed purge as though it happened exactly at the due instant.
`046` — Immediately before purge, SOMA shall revalidate that the Communication remains orphaned.
`047` — Revalidation shall consider restored entity relationships.
`048` — Revalidation shall consider protected proposal dependencies.
`049` — Revalidation shall consider protected correction dependencies.
`050` — Revalidation and purge shall be transactionally consistent.
`051` — If revalidation finds a valid dependency, purge shall not occur.
`052` — Failed purge transaction shall not claim that content was successfully purged.
`053` — Purge shall remove the retained Communication body.
`054` — Purge shall remove the retained Communication subject.
`055` — Purge shall remove retained participants.
`056` — Purge shall remove retained attachments.
`057` — Purge shall remove searchable reconstructable message content.
`058` — Purge shall remove opaque or transformed representations that would materially reconstruct the purged message.
`059` — SOMA may retain a non-reconstructable source-scoped fingerprint.
`060` — SOMA may retain the relevant former target identity context needed for suppression/audit.
`061` — SOMA may retain message direction evidence where required.
`062` — SOMA may retain the reason for unlink/orphan/purge decisions.
`063` — SOMA may retain the actor or accepted source responsible for relevant decisions.
`064` — SOMA may retain decision chronology.
`065` — Retained suppression evidence shall be source-scoped.
`066` — Retained suppression evidence shall not reconstruct the purged body.
`067` — Retained suppression evidence shall not reconstruct the purged subject.
`068` — Retained suppression evidence shall not reconstruct the original participant set.
`069` — Retained suppression evidence shall not reconstruct attachments.
`070` — Post-purge suppression evidence may preserve a frozen received time when independently known.
`071` — Post-purge suppression evidence may preserve a frozen sent time when independently known.
`072` — Post-purge suppression evidence may preserve an applicable final time when independently known.
`073` — Post-purge suppression evidence may preserve final message direction where known.
`074` — The optional summary shall remain non-reconstructable.
`075` — Unknown summary facts shall remain unknown rather than fabricated.
`076` — Orphan purge shall not modify the source PST.
`077` — Orphan purge shall not modify the source OST.
`078` — Orphan purge shall not delete the original source message.
`079` — Orphan purge shall not alter source-folder state.
`080` — Orphan purge shall not delete previously generated `.msg` artifacts stored outside SOMA's governed retained Communication content.
`081` — Orphan purge shall not modify portable exports already produced to operator-managed destinations.
`082` — Purging SOMA's retained message copy shall not imply revocation or destruction of previously exported artifacts.
`083` — Orphan purge shall not retroactively alter existing backups.
`084` — Existing backups may retain historical pre-purge state according to their own backup lifecycle.
`085` — Purge of current authoritative state shall not rewrite old backup media merely to enforce current retention.
`086` — Restore behavior shall respect the separately governed backup/retention contract.
`087` — An accepted terminal reversal during grace may restore an applicable direct Communication relationship.
`088` — Restoring a valid dependency during grace shall cancel pending purge.
`089` — Reversal during grace shall use the still-retained canonical Communication rather than create a duplicate.
`090` — Prior terminal unlink/orphan history shall remain preserved.
`091` — Terminal reversal after purge shall not reconstruct deleted content from suppression evidence.
`092` — Terminal reversal after purge shall trigger targeted source backfill where the communication history is again relevant.
`093` — Targeted recovery shall use the governed communication source rather than fabricated message content.
`094` — Recovery shall follow normal source-identity, matching, retention, proposal, and idempotency rules.
`095` — Successfully rediscovered content shall reconcile to its historical suppression/fingerprint evidence where safely supported.
`096` — If required source history is unavailable after terminal reversal, SOMA shall preserve a coverage warning.
`097` — Source unavailability shall not cause SOMA to fabricate the missing Communication.
`098` — Coverage warning shall explain that relevant historical Communication may no longer be recoverable.
`099` — Suppression/purge evidence shall remain available to explain that SOMA previously processed and purged the content where applicable.
`100` — Receipt of a later message shall not itself constitute an accepted terminal reversal.
`101` — Terminal reversal shall require the owning ticket domain's separately accepted correction/reversal authority.
`102` — Communication processing shall consume that accepted reversal rather than become authority for reopening the ticket.
`103` — Orphan-housekeeping execution shall remain independent from ordinary communication scanning.
`104` — Disabling automatic scanning shall not suspend already-due orphan purge revalidation.
`105` — Lack of active matching targets shall not prevent due orphan housekeeping from completing where otherwise eligible.
`106` — Terminal link removal shall remain auditable.
`107` — Entry into orphan state shall remain auditable.
`108` — Grace due time shall be reproducible from accepted configuration and chronology.
`109` — Dependency restoration and purge cancellation shall remain auditable.
`110` — Purge revalidation result shall remain auditable.
`111` — Successful purge shall preserve bounded purge evidence.
`112` — Terminal reversal and any resulting backfill shall remain traceable to the original terminal/unlink/purge history.

## `BETA-REQ-0117` — prefix `COMM-RUN`

**Governing obligation:** Beta 1.0 shall execute ordinary communication tracking through one non-overlapping local pipeline that validates the source, processes new and bounded-overlap content transiently through matching and governed retention/proposals, and advances durable coverage only after successful work, with hourly-by-default configurable scheduling, manual Check now, at most one startup catch-up, trigger coalescing, separate Backfill/Deep Scan, and independent orphan housekeeping.

`001` — Beta 1.0 shall use one ordinary local Communication Processing pipeline.
`002` — Ordinary source reading and matching shall not be scheduled as independent authoritative pipelines.
`003` — The pipeline shall own the ordered processing sequence for one ordinary run.
`004` — An ordinary run shall validate the configured source before message processing.
`005` — An ordinary run shall discover new and bounded-overlap content.
`006` — Discovered content shall be inspected transiently.
`007` — Transiently inspected content shall be matched against governed tracking identity.
`008` — Only accepted or safely accepted matches shall become retained Communications.
`009` — Lifecycle effects inferred from retained Communications shall remain proposals.
`010` — Coverage/high-water state shall be committed only after the durable work required for that range succeeds.
`011` — The ordered phase model shall not permit high-water advancement before required retention/proposal state is durable.
`012` — Ordinary source discovery shall not create a persistent backlog of unmatched message content for later independent matching.
`013` — Unmatched content shall remain subject to the transient-inspection rule from `0115`.
`014` — Separation of internal implementation stages shall not create a second externally scheduled matching workflow.
`015` — Automatic ordinary Communication Processing shall default to an hourly cadence.
`016` — The default cadence shall remain configurable by the operator.
`017` — Changing the configured cadence shall not alter already accepted Communication or lifecycle evidence.
`018` — The operator may configure another positive whole-minute interval.
`019` — A configured interval shall be greater than zero.
`020` — Fractional-minute cadence shall not be required by Beta 1.0.
`021` — Exact scheduling mechanics shall preserve the configured interval without inventing unsupported sub-minute execution.
`022` — The operator may disable automatic ordinary Communication Processing.
`023` — Disabling automatic scanning shall not delete source configuration.
`024` — Disabling automatic scanning shall not delete retained Communications.
`025` — Disabling automatic scanning shall not erase historical coverage/high-water state.
`026` — Re-enabling scanning shall resume under normal coverage rules rather than resetting history.
`027` — SOMA shall expose a manual `Check now` action where ordinary-processing prerequisites hold.
`028` — `Check now` shall use the same ordinary Communication Processing pipeline as scheduled execution.
`029` — `Check now` shall not bypass the accepted trackable-entity gate from `0111`.
`030` — `Check now` shall not bypass proposal-review authority.
`031` — `Check now` shall not automatically become Deep Scan.
`032` — SOMA may perform at most one ordinary startup catch-up for an eligible startup session.
`033` — Startup catch-up shall require ordinary-processing prerequisites to hold.
`034` — Startup catch-up shall use existing durable coverage/high-water state.
`035` — Startup catch-up shall not reset historical coverage.
`036` — Startup catch-up shall not become Deep Scan.
`037` — Startup catch-up shall not repeat indefinitely during one startup cycle.
`038` — Compatible ordinary-processing triggers shall coalesce when they would otherwise request overlapping work.
`039` — A scheduled trigger arriving while an equivalent ordinary run is already active shall not start a second overlapping job.
`040` — A `Check now` request may coalesce with an already-active compatible ordinary run.
`041` — Startup catch-up may coalesce with another compatible ordinary trigger.
`042` — Coalescing shall preserve the user's request as satisfied by the compatible run rather than silently discarding required work.
`043` — Ordinary Communication Processing jobs shall not overlap for the same compatible source scope.
`044` — A second compatible job shall not process the same forward range concurrently.
`045` — Mutual exclusion shall protect high-water/coverage correctness.
`046` — Job serialization shall not require overlapping work to be lost; compatible triggers shall be coalesced or queued according to LLD.
`047` — Targeted backfill shall remain a distinct job type from ordinary forward processing.
`048` — Ordinary scheduling shall not convert itself into targeted backfill without a qualifying historical-coverage condition.
`049` — Backfill shall preserve its own identity/range scope under `0114`.
`050` — Deep Scan shall remain a distinct job type.
`051` — Ordinary scheduled processing shall never silently become Deep Scan.
`052` — `Check now` shall never silently become Deep Scan.
`053` — Startup catch-up shall never silently become Deep Scan.
`054` — Deep Scan shall retain its explicit scope-confirmation requirement.
`055` — Automatic scheduling shall not itself accept lifecycle proposals.
`056` — Startup catch-up shall not itself accept lifecycle proposals.
`057` — `Check now` shall not itself accept lifecycle proposals.
`058` — The fact that a proposal was created during an automatic run shall not lower its review requirement.
`059` — Safe acceptance, where separately authorized, shall depend on the approved class rather than scheduler origin.
`060` — Orphan-housekeeping execution shall remain independent from ordinary communication scanning.
`061` — Disabling automatic scanning shall not suspend already-due orphan purge revalidation.
`062` — Absence of active scanning targets shall not suspend due orphan housekeeping.
`063` — Orphan housekeeping shall follow `0116` transactional revalidation rules.
`064` — Ordinary scan failure shall not prevent independently due orphan housekeeping from being evaluated.
`065` — Infrastructure workbook import scheduling or checks shall remain independent from Communication Processing.
`066` — Other domain imports shall retain their own mutation boundaries.
`067` — `.msg` draft generation shall remain independent from Communication Processing scheduling.
`068` — Generating a communication draft shall not be treated as a source scan.
`069` — Communication Processing shall not become the generic scheduler for unrelated SOMA background workflows.
`070` — Every ordinary Communication Processing run shall keep the source PST/OST read-only.
`071` — Scheduling shall not authorize mailbox mutation.
`072` — Manual execution shall not authorize mailbox mutation.
`073` — Multiple compatible triggers shall not duplicate retained Communications.
`074` — Multiple compatible triggers shall not duplicate lifecycle proposals.
`075` — Multiple compatible triggers shall not advance high-water inconsistently.
`076` — Crash/restart around trigger coalescing shall preserve durable-work semantics rather than infer success from the trigger itself.
`077` — Automatic-processing enabled/disabled state shall be persisted.
`078` — The configured positive whole-minute interval shall be persisted.
`079` — Changing scheduling settings shall not rewrite prior job or coverage history.
`080` — When `Check now` is unavailable because prerequisites do not hold, SOMA shall expose a bounded reason.
`081` — Disabled automatic scanning shall be distinguishable from no-target idle state.
`082` — Source-unavailable state shall be distinguishable from operator-disabled scanning.
`083` — An active coalesced job shall be distinguishable from a newly started second job.

## `BETA-REQ-0118` — prefix `COMM-SCOPE`

**Governing obligation:** Each retained Communication shall preserve immutable SOMA identity within exactly one accepted path-independent mailbox/account Source Scope whose provider-stable or governed fallback identity prevents duplicate messages without enabling cross-scope silent merges, while message participants remain structured role-bearing source evidence with optional reviewed Contact links and a validated queryable representation rather than opaque metadata.

`001` — Every retained Communication shall have immutable SOMA internal identity.
`002` — Communication internal identity shall remain independent from source path.
`003` — Communication internal identity shall remain independent from folder location.
`004` — Communication internal identity shall remain independent from provider message identifiers.
`005` — Communication internal identity shall remain independent from subject, participants, body, and message time.
`006` — Every retained Communication shall belong to exactly one accepted Communication Source Scope.
`007` — A retained Communication shall not simultaneously belong to multiple active source scopes.
`008` — Communication Source Scope shall represent mailbox/account context rather than filesystem path alone.
`009` — Source Scope identity shall remain distinct from the underlying PST/OST file path.
`010` — A changed file path shall not by itself create a new Communication Source Scope.
`011` — Moving a PST/OST source file shall not automatically redefine retained message identity.
`012` — Moving a message between folders shall not create a new Communication merely because its folder path changed.
`013` — Provider-visible folder duplication shall not automatically create a duplicate Communication.
`014` — Folder location may remain useful source evidence without becoming Communication identity.
`015` — Provider-stable message identity shall enforce uniqueness only within an accepted compatible source scope.
`016` — Accepted fallback message identity shall likewise be evaluated within its source scope.
`017` — Source scope shall participate in uniqueness enforcement for retained Communications.
`018` — A provider identifier shall not be assumed globally unique across unrelated source scopes.
`019` — Equal provider-origin message identifiers across unconfirmed source scopes shall not silently merge Communications.
`020` — Equal accepted fallback identities across unconfirmed source scopes shall not silently merge Communications.
`021` — Cross-scope identifier equality may create a reconciliation candidate.
`022` — Cross-scope identity candidates shall remain distinct until reviewed or otherwise safely reconciled under approved authority.
`023` — A coincidental identifier collision shall not replace either Communication identity.
`024` — Overlapping communication stores shall require source-scope reconciliation before sharing message identity.
`025` — Replacement stores shall require source-scope reconciliation before inheriting prior identity assumptions.
`026` — Replacement stores shall require reconciliation before inheriting prior historical coverage.
`027` — Replacement stores shall require reconciliation before inheriting prior high-water state.
`028` — Overlap or replacement shall not be inferred solely from similar paths, filenames, sizes, or timestamps.
`029` — Source-scope reconciliation shall preserve prior source provenance.
`030` — Coverage shall not be shared across source scopes before compatible scope reconciliation.
`031` — High-water state shall not be shared across source scopes before compatible scope reconciliation.
`032` — Confirmed compatible scopes may reuse or rescope coverage only through the governed coverage process from `0113`.
`033` — Scope reconciliation shall not convert unprocessed ranges into completed coverage.
`034` — Within a confirmed source scope, the same provider-stable message identity shall resolve to one canonical Communication.
`035` — Reobservation of the same stable identity in another folder shall not create another canonical Communication.
`036` — Reobservation of the same stable identity during overlap replay shall remain idempotent.
`037` — A canonical Communication may preserve multiple historical source-folder observations without duplicating the message entity.
`038` — Retained Communication participants shall be represented as structured values.
`039` — Participant structure shall preserve role.
`040` — Participant structure shall preserve available display name.
`041` — Participant structure shall preserve available address.
`042` — Participant structure shall preserve available order within a role where source semantics provide meaningful ordering.
`043` — Participant structure shall permit unknown values without fabrication.
`044` — Sender shall be represented as a distinct participant role when supplied by the source.
`045` — Sender shall not be silently conflated with From when the source distinguishes them.
`046` — From shall be represented as a distinct participant role.
`047` — Multiple source-supported From values shall be preserved where the source permits them.
`048` — To recipients shall be preserved as role-bearing participants.
`049` — Multiple To recipients shall remain individually representable.
`050` — To-recipient ordering shall be preserved when known and meaningful.
`051` — Cc recipients shall be preserved as role-bearing participants.
`052` — Multiple Cc recipients shall remain individually representable.
`053` — Bcc shall be represented only when known from the source.
`054` — Missing Bcc data shall remain unknown rather than imply that no Bcc existed in the original delivery context.
`055` — Reply-To shall be represented as a distinct role when supplied.
`056` — Reply-To shall not replace From or Sender identity.
`057` — Available participant display text shall be preserved separately from normalized matching values.
`058` — Available participant address text shall be preserved according to source evidence.
`059` — Normalization for Contact matching shall not rewrite historical source participant evidence.
`060` — A participant may optionally link to a reviewed Contact.
`061` — Participant identity shall remain valid without a Contact link.
`062` — Contact linkage shall not replace the source-observed participant value.
`063` — Changing a Contact's current affiliation shall not rewrite historical Communication participant evidence.
`064` — Correcting participant-to-Contact linkage shall preserve the original source participant evidence.
`065` — Equal participant display names shall not prove Contact identity.
`066` — Equal email addresses shall be matching evidence rather than universal Contact identity proof.
`067` — Participant name/address matching shall use the governed Contact reconciliation rules.
`068` — Ambiguous Contact candidates shall require review rather than silent selection.
`069` — A participant shall not cause silent Contact creation merely because an address or name is new.
`070` — Unknown participant display name shall remain unknown.
`071` — Unknown participant address shall remain unknown.
`072` — Malformed participant values shall not be fabricated into valid-looking addresses.
`073` — Malformed values may be retained as bounded source evidence where safe and useful.
`074` — Malformed participant data shall produce a warning where materially relevant.
`075` — One malformed participant shall not necessarily invalidate the entire retained Communication.
`076` — Corrections to parsed participant structure shall preserve original source evidence where applicable.
`077` — Correcting one participant shall not rewrite unrelated participant roles.
`078` — Correcting a Contact link shall not rewrite the Communication message itself.
`079` — LLD may represent participants through normalized relational rows.
`080` — LLD may alternatively use versioned validated structured JSON where that design satisfies the full participant contract.
`081` — A JSON participant representation shall have an explicit validated schema.
`082` — A JSON participant representation shall be versioned.
`083` — Storage representation shall preserve role, display/address evidence, order where applicable, and Contact-link semantics.
`084` — Participant metadata shall not be stored as an arbitrary unvalidated blob.
`085` — An arbitrary blob shall not become the sole authoritative participant representation.
`086` — LLD storage convenience shall not discard participant role semantics.
`087` — LLD storage convenience shall not prevent queryable participant relationships required by the product.
`088` — Communication Source Scope shall preserve enough provenance to distinguish different mailbox/account contexts.
`089` — Source-scope correction shall remain historical rather than silently rewrite prior source identity.
`090` — A reviewed scope reconciliation shall preserve why two source observations were accepted as the same or different scope.
`091` — Scope reconciliation shall not change canonical Communication identity unless the exact duplicate/reconciliation workflow explicitly resolves duplicate retained records while preserving lineage.
`092` — Source-scope reconciliation shall not silently merge Communications based only on equal subject.
`093` — Source-scope reconciliation shall not silently merge Communications based only on equal time.
`094` — Source-scope reconciliation shall not silently merge Communications based only on equal participants.
`095` — Source-scope reconciliation shall not silently merge Communications based only on equal body.
`096` — Provider/fallback identity and provenance shall remain the governing basis for reconciliation under `0119`.
`097` — Source-scope identity shall support one canonical Communication model from `0115`.
`098` — Multiple entity links shall attach to the canonical Communication rather than to independent folder copies.
`099` — Link correction shall not alter Communication Source Scope unless the source identity itself is under correction.
`100` — Participant persistence shall occur only for retained Communications.
`101` — Participant data from unmatched transiently inspected messages shall not persist as per-message content.
`102` — Source Scope metadata shall be minimized to what is needed for identity, coverage, reconciliation, and audit.
`103` — Diagnostics shall not dump participant content unnecessarily.

## `BETA-REQ-0119` — prefix `COMM-MSGID`

**Governing obligation:** SOMA shall identify retained PST/OST Communications using the strongest available provider-origin identity within their accepted Source Scope, falling back only to explicitly versioned deterministic scoped canonicalization that preserves collisions and never claims authenticity; stronger later identity shall enrich rather than replace immutable Communication identity, and SOMA-generated `.msg` artifacts shall remain distinct until explicitly reconciled with an observed sent-store Communication.

`001` — The PST/OST adapter shall preserve the most stable provider-origin message identity available.
`002` — Provider-origin identity shall be interpreted within the accepted Communication Source Scope.
`003` — SOMA shall prefer stronger provider-origin identity over deterministic fallback identity when reliably available.
`004` — Provider-origin identity shall remain evidence about a Communication rather than replace its immutable SOMA internal identity.
`005` — Failure to obtain one provider identity type shall not authorize fabrication of that identity.
`006` — Transport-level message identifiers shall remain explicitly typed.
`007` — MAPI-origin identifiers shall remain explicitly typed.
`008` — Entry/store identifiers shall remain explicitly typed.
`009` — Conversation identifiers shall remain explicitly typed.
`010` — SOMA-generated artifact identifiers shall remain explicitly typed.
`011` — Fallback identities shall remain explicitly distinguishable from provider-origin identities.
`012` — Equal textual values belonging to different identity namespaces shall not be assumed semantically equivalent.
`013` — Conversation identity shall not by itself prove individual Communication identity.
`014` — Multiple Communications may legitimately share one conversation/thread identity.
`015` — Conversation membership shall not silently merge messages.
`016` — A provider entry identifier shall be interpreted according to its documented stability and source scope.
`017` — An identifier known to change across folder/store movement shall not be treated as globally permanent message identity.
`018` — A transient or path-dependent provider identifier shall remain typed evidence rather than be silently elevated to stronger identity.
`019` — PST/OST file path shall not prove Communication identity.
`020` — Folder path shall not prove Communication identity.
`021` — Folder name shall not prove Communication identity.
`022` — Folder movement shall not create another Communication merely because path evidence changes.
`023` — Discovery order shall not prove Communication identity.
`024` — Source enumeration position shall not prove Communication identity.
`025` — Subject equality shall not prove Communication identity.
`026` — Message-time equality shall not prove Communication identity.
`027` — Participant equality shall not prove Communication identity.
`028` — Body equality shall not prove Communication identity.
`029` — Attachment similarity shall not prove Communication identity.
`030` — Any combination of descriptive message facts shall remain matching evidence rather than automatic relational identity unless governed by the accepted fallback algorithm.
`031` — The adapter shall detect when no sufficiently stable provider-origin message identity is available.
`032` — Missing stable identity shall remain an explicit condition.
`033` — Missing stable identity shall not cause SOMA to assign a random value and pretend it represents provider identity.
`034` — Missing stable provider identity may invoke only the governed deterministic fallback identity process.
`035` — Fallback identity generation shall be deterministic.
`036` — The same canonical fallback inputs under the same algorithm version and source scope shall yield the same fallback value.
`037` — Fallback canonicalization shall be versioned.
`038` — The fallback algorithm version shall be persisted for retained Communications that depend on fallback identity.
`039` — The fallback contract shall define its exact input fields explicitly.
`040` — The fallback implementation shall not silently add unversioned identity inputs.
`041` — The fallback implementation shall not silently remove identity inputs without a version change.
`042` — Input ordering shall be deterministic where ordering affects canonicalization.
`043` — Fallback canonicalization shall define normalization rules explicitly.
`044` — Normalization behavior shall be deterministic.
`045` — Changes to identity-affecting normalization shall require a new fallback version or explicit migration rule.
`046` — Canonicalization shall not rely on locale-sensitive or environment-dependent behavior without explicit governance.
`047` — The fallback contract shall define how missing inputs are represented.
`048` — Missing values shall not silently collapse into indistinguishable present values.
`049` — Unknown and known-empty values shall remain distinguishable where the future fallback design requires that distinction for deterministic identity.
`050` — Missing-value semantics shall be versioned with the fallback algorithm.
`051` — Fallback identity may use a deterministic digest of canonicalized inputs.
`052` — The digest algorithm and encoding shall be explicitly versioned.
`053` — Changing the digest algorithm shall not silently reinterpret historical fallback identities.
`054` — Exact cryptographic digest selection remains an adapter/LLD decision subject to the accepted identity contract.
`055` — Fallback identity shall be scoped to the accepted Communication Source Scope.
`056` — Equal fallback values from unrelated unconfirmed scopes shall not authorize silent merge.
`057` — Scope reconciliation shall occur before fallback identity is reused across overlapping/replacement stores.
`058` — Fallback identity evidence shall persist only for retained matched Communications.
`059` — SOMA shall not retain fallback fingerprints for every unmatched mailbox message merely to build a permanent mailbox index.
`060` — Fallback evidence shall remain subject to matched-only retention from `0115`.
`061` — Fallback evidence shall retain enough information to identify algorithm/version/scope without retaining prohibited unmatched message content.
`062` — A fallback digest shall not be treated as cryptographic authenticity proof.
`063` — Equal fallback hashes shall not prove that two independently observed messages are necessarily the same authentic message.
`064` — Hash equality shall not override contradictory stronger provider evidence.
`065` — Fallback identity shall remain an operational deduplication/reconciliation mechanism rather than a digital-signature claim.
`066` — Equal or compatible identity evidence may identify a duplicate candidate.
`067` — Duplicate candidates shall be reconciled according to governed identity rules.
`068` — Descriptive similarity alone shall not silently collapse candidate Communications.
`069` — A fallback identity collision shall not silently merge Communications.
`070` — When identity evidence collides while source evidence indicates distinct messages, both Communications shall retain distinct immutable SOMA identities.
`071` — Collision state shall be surfaced for review where unresolved.
`072` — Collision handling shall preserve both sets of source evidence.
`073` — Collision resolution shall not overwrite one Communication merely to satisfy uniqueness.
`074` — A later stronger provider-origin identity may be attached to an existing Communication.
`075` — Attaching stronger identity shall preserve the Communication's immutable SOMA identity.
`076` — The prior fallback identity shall remain historical alias/evidence where required.
`077` — Stronger identity shall become preferred for future provider-level reconciliation where valid.
`078` — Attaching stronger identity shall not rewrite previously observed source evidence.
`079` — Historical accepted message identifiers may remain typed aliases to the same Communication.
`080` — Alias relationships shall preserve identifier type and source scope.
`081` — An alias shall not create another canonical Communication.
`082` — Correcting one alias shall not replace the Communication's internal identity.
`083` — Later stronger identity may create a duplicate-reconciliation candidate between existing Communications.
`084` — Duplicate reconciliation shall not occur silently when material ambiguity remains.
`085` — Reconciliation shall preserve historical identities, links, decisions, and provenance.
`086` — Reconciliation shall not duplicate lifecycle effects already accepted from either observation.
`087` — The exact surviving canonical-record mechanics shall preserve lineage and remain governed by the correction/reconciliation contract.
`088` — A new fallback-identity version shall not silently invalidate historical fallback evidence.
`089` — Migration between fallback versions shall be explicit.
`090` — Migration shall preserve the previous fallback identity/version as historical evidence where needed.
`091` — Migration shall not automatically merge records merely because a new algorithm produces equal values.
`092` — Migration collisions shall use the same review-safe collision principles.
`093` — Folder movement shall not authorize silent Communication duplication.
`094` — Folder movement shall not authorize silent Communication merge.
`095` — New folder observation may attach as additional source-location evidence to the same Communication when identity is otherwise established.
`096` — Store replacement shall not authorize silent Communication merge.
`097` — Store replacement shall not authorize duplication of already identified Communications.
`098` — Overlapping/replacement stores shall use source-scope reconciliation before sharing identity assumptions.
`099` — Store migration shall not silently replace provider identifiers belonging to the earlier source observation.
`100` — A SOMA-generated `.msg` draft shall have artifact identity distinct from retained Communication identity.
`101` — `.msg` artifact identity shall not prove that the message was actually sent.
`102` — Generating a `.msg` file shall not create a canonical sent Communication record solely from generation.
`103` — Exporting a `.msg` file shall not create provider-origin sent-message identity.
`104` — A later corresponding message discovered in an accepted sent PST/OST store shall be reconciled explicitly with the prior `.msg` artifact where applicable.
`105` — Sent-store reconciliation shall use actual Communication source/provider identity rather than assume identity from the artifact alone.
`106` — A successful reconciliation may preserve the relationship between the generated artifact and the actual sent Communication.
`107` — The `.msg` artifact and actual sent Communication shall retain distinct identities even when reconciled.
`108` — Failure to find a corresponding sent-store message shall not fabricate sending evidence.
`109` — Multiple plausible sent-store candidates shall require reviewed reconciliation rather than arbitrary selection.
`110` — Message-identity correction shall target the relevant identifier/alias relationship.
`111` — Correcting provider identity evidence shall not rewrite Communication body/subject/participant evidence.
`112` — Correcting provider identity evidence shall not rewrite unrelated entity links.
`113` — Original accepted identity evidence shall remain historically explainable.
`114` — Reprocessing a retained message with the same accepted stable identity shall remain idempotent.
`115` — Reprocessing a retained message with the same fallback identity/version/scope shall remain idempotent unless collision evidence requires review.
`116` — Bounded-overlap replay shall use this identity authority to prevent duplicate Communications.

## `BETA-REQ-0120` — prefix `COMM-JOB`

**Governing obligation:** Every materially long communication-processing, historical-scan, reconciliation, or orphan-housekeeping operation shall execute as a nonblocking inspectable background job with immutable identity, minimized scope, truthful phase/state/count/coverage progress, cooperative transaction-safe cancellation, durable crash recovery, bounded backed-off idempotent retry, and stable redacted diagnostics that expose neither reconstructable communication content, secrets, unnecessary customer data, nor source mutations.

`001` — Every materially long ordinary Communication Processing operation shall execute as a background job.
`002` — Every targeted-backfill operation shall execute as a background job.
`003` — Every Deep Scan shall execute as a background job.
`004` — Materially long Communication Source reconciliation shall execute as a background job.
`005` — Materially long Communication identity reconciliation shall execute as a background job.
`006` — Large orphan-housekeeping operations shall execute as background jobs.
`007` — Background execution shall not block the primary SOMA operator interface for the duration of the work.
`008` — Every background job shall have immutable internal identity.
`009` — Retrying work shall not rewrite the identity/history of the original attempt.
`010` — A new retry attempt may reference its predecessor while remaining independently addressable where the LLD uses per-attempt identity.
`011` — Job identity shall remain distinct from source path, target entity, time range, or scheduler trigger.
`012` — Active background jobs shall be inspectable.
`013` — Completed background jobs shall retain sufficient bounded history for operational review.
`014` — Failed background jobs shall expose their bounded failure state.
`015` — Cancelled background jobs shall remain distinguishable from failed and successful jobs.
`016` — Retried background jobs shall preserve the relationship between prior and later attempts where required.
`017` — Every job shall preserve the applicable Communication Source Scope.
`018` — Folder scope shall be preserved only where relevant to the job.
`019` — Historical range scope shall be preserved where the job is range-bounded.
`020` — Identity/target scope shall be preserved where the job is target-bounded.
`021` — Persisted job scope shall be minimized to what is needed for execution, recovery, diagnostics, and audit.
`022` — Job metadata shall not copy unnecessary reconstructable communication content.
`023` — A job shall expose its current processing phase.
`024` — Phase shall remain distinct from overall lifecycle state.
`025` — Phase changes shall not imply success until durable completion criteria are met.
`026` — Job state shall distinguish pending/queued work from running work.
`027` — Job state shall distinguish successful completion.
`028` — Job state shall distinguish failure.
`029` — Job state shall distinguish cancellation.
`030` — Job state shall distinguish interrupted/recoverable work where applicable.
`031` — Exact state enumeration may be refined by LLD without collapsing materially distinct outcomes.
`032` — Job history shall preserve creation/registration chronology.
`033` — Actual start time shall remain distinct from job creation time.
`034` — Actual completion time shall be preserved on successful completion.
`035` — Failure time shall be preserved where applicable.
`036` — Cancellation time shall be preserved where applicable.
`037` — Unknown effective external times shall not be fabricated from job times.
`038` — Jobs shall expose the count of content discovered where that concept applies.
`039` — Discovered count shall not imply that all discovered content was inspected successfully.
`040` — Jobs shall expose the count of content durably or successfully inspected according to the phase contract.
`041` — Inspected count shall remain distinguishable from discovered count.
`042` — Jobs shall expose the count of matched content.
`043` — Matched count shall remain distinguishable from retained count.
`044` — Jobs shall expose the count of Communications retained through governed acceptance.
`045` — Retained count shall not include unmatched transiently inspected content.
`046` — Jobs shall expose unchanged/idempotently existing content count where applicable.
`047` — Unchanged count shall remain distinguishable from newly retained or newly proposed content.
`048` — Jobs shall expose the count of lifecycle or relationship proposals produced where applicable.
`049` — Proposed count shall not imply proposal acceptance.
`050` — Jobs shall expose skipped count where content is deliberately not processed under governed rules.
`051` — Skip reason shall remain available in bounded diagnostics where materially necessary.
`052` — Jobs shall expose warning count.
`053` — Warnings shall remain distinguishable from failures.
`054` — Jobs shall expose failure count where partial work can encounter independently counted failures.
`055` — Failure count shall not cause incomplete ranges to be reported as successfully covered.
`056` — Jobs affecting historical coverage shall expose exact durable coverage results.
`057` — Coverage counts/ranges shall reflect only durable completed work.
`058` — Partial coverage shall remain distinguishable from complete coverage.
`059` — Ordinary forward-processing jobs shall expose resulting high-water state where applicable.
`060` — High-water displayed by a job shall reflect committed durable state.
`061` — A speculative in-memory cursor shall not be presented as the committed high-water mark.
`062` — Job progress shall use exact counts when available.
`063` — A percentage shall be shown only when the total work denominator is known sufficiently to support that percentage.
`064` — Unknown total work shall not yield a fabricated completion percentage.
`065` — An estimated total shall not be presented as exact without clear distinction.
`066` — Unknown-total work may expose phase, elapsed time, exact processed counts, and bounded status without a percentage.
`067` — Cancellable long-running jobs shall expose cancellation.
`068` — Cancellation shall be cooperative.
`069` — Cancellation shall occur at safe processing checkpoints.
`070` — Cancellation request shall remain distinguishable from cancellation completion.
`071` — Cancellation shall not split an atomic database commit.
`072` — Cancellation shall not leave half of a governed transaction accepted.
`073` — If cancellation arrives during an atomic section, SOMA shall complete or roll back that section before ending at a safe checkpoint.
`074` — Job UI shall not claim cancellation completed while an indivisible commit remains unresolved.
`075` — Cancellation shall preserve already durable completed work.
`076` — Cancelled unfinished work shall not advance coverage.
`077` — Cancelled unfinished work shall not advance high-water.
`078` — Cancelled unfinished work shall not be marked successful.
`079` — Restart/retry shall resume from durable state rather than transient progress.
`080` — Application shutdown during a running job shall not mark the job successful.
`081` — Shutdown shall preserve already committed work.
`082` — Uncommitted transient work shall not be treated as completed after restart.
`083` — Graceful shutdown may request cooperative job stopping at safe checkpoints.
`084` — Application or process crash shall not mark a running job successful.
`085` — Crash recovery shall use authoritative durable job and domain state.
`086` — Restart shall not infer success solely because the prior process disappeared.
`087` — Interrupted atomic transactions shall rely on persistence guarantees to commit fully or roll back.
`088` — After restart, SOMA shall safely determine whether interrupted work can resume.
`089` — Recoverable work may resume from a safe durable checkpoint.
`090` — When safe automatic resume cannot be established, SOMA shall offer an explicit retry path.
`091` — Resume shall remain idempotent.
`092` — Resume shall not skip failed/uncommitted ranges.
`093` — Automatic retry shall apply only to failures classified as transient.
`094` — Permanent validation or domain errors shall not be retried automatically as though transient.
`095` — User cancellation shall not automatically become a retry request.
`096` — Deep Scan shall not be automatically invoked as retry fallback.
`097` — Automatic retries shall be bounded.
`098` — A job shall not retry indefinitely.
`099` — Retry exhaustion shall produce an inspectable failed state.
`100` — Exact retry-count limits may be defined by LLD/configuration within the bounded-retry invariant.
`101` — Automatic transient retries shall use backoff.
`102` — Retry scheduling shall avoid tight uncontrolled failure loops.
`103` — Exact backoff strategy may be defined by LLD.
`104` — Retried work shall be idempotent.
`105` — Retry shall not duplicate retained Communications.
`106` — Retry shall not duplicate accepted Communication links.
`107` — Retry shall not duplicate lifecycle proposals for the same exact source fact and target.
`108` — Retry shall not double-advance coverage or high-water.
`109` — Job diagnostics shall use stable machine-addressable diagnostic/error codes.
`110` — Diagnostic codes shall remain distinguishable from human-readable explanatory text.
`111` — Stable codes shall support testing, support, and remediation without relying on message wording.
`112` — Diagnostics may include bounded safe operational counts.
`113` — Diagnostic counts shall not expose reconstructable message content.
`114` — Diagnostics shall redact source scope where disclosure is unnecessary.
`115` — Diagnostics shall minimize filesystem paths.
`116` — Full user-specific paths shall not be logged when a bounded redacted scope is sufficient.
`117` — Diagnostics may preserve enough non-sensitive scope information to identify the failing job/source context.
`118` — Diagnostics may provide bounded remediation guidance.
`119` — Remediation shall not expose prohibited secrets or reconstructable message content.
`120` — Remediation shall distinguish operator-fixable configuration problems from internal processing failures where possible.
`121` — Diagnostics shall not contain reconstructable message bodies.
`122` — Diagnostics shall not contain reconstructable message subjects.
`123` — Diagnostics shall not dump per-message participants.
`124` — Diagnostics shall not dump attachments.
`125` — Diagnostics shall not persist opaque equivalents that reconstruct prohibited Communication content.
`126` — Diagnostics shall not contain passwords.
`127` — Diagnostics shall not contain private keys.
`128` — Diagnostics shall not contain reusable authentication tokens.
`129` — Diagnostics shall not contain backup recovery secrets.
`130` — Diagnostics shall not contain other reusable authentication secrets.
`131` — Diagnostics shall exclude unnecessary Customer Organization data.
`132` — Diagnostics shall exclude unnecessary Contact data.
`133` — Diagnostics shall exclude unnecessary device/customer operational values when safe identifiers or counts suffice.
`134` — Diagnostic usefulness shall not be used as justification for unrestricted customer-data logging.
`135` — Background-job execution shall keep PST sources read-only.
`136` — Background-job execution shall keep OST sources read-only.
`137` — Retry shall not authorize source mutation.
`138` — Recovery shall not authorize source mutation.
`139` — Cancellation shall not authorize source mutation.
`140` — Job bookkeeping shall not become a second source of domain truth.
`141` — Domain facts accepted by a job shall remain authoritative in their owning domains.
`142` — A job state correction shall not rewrite domain lifecycle evidence produced by successfully committed work.
`143` — A domain rollback shall not be simulated merely by marking the job failed after domain work committed.
`144` — Long-running jobs shall not require the operator to remain on the initiating screen.
`145` — Navigating elsewhere in SOMA shall not cancel a job implicitly.
`146` — Closing a job-status view shall not cancel the job.
`147` — Explicit cancellation shall remain distinct from UI navigation.
`148` — Job execution shall respect the non-overlap/coalescing rules of `0117`.
`149` — A background-job abstraction shall not permit two incompatible jobs to mutate the same governed scope concurrently where invariants require serialization.
`150` — Exact concurrency policy may be refined by LLD while preserving domain invariants and durable coverage correctness.

## `BETA-REQ-0121` — prefix `WF-ISO`

**Governing obligation:** SOMA shall treat communication scanning/backfill/Deep Scan, SR/RFC/WFM imports, Infrastructure workbook exchange, `.msg` generation, orphan housekeeping, and other governed workflows as independently identifiable owners of their invocation, source, staging, jobs, transactions, idempotency, results, provenance, and audit, allowing cooperation only through explicit validated application commands or reviewed proposals without direct cross-workflow state mutation, source modification, or semantic impersonation.

`001` — Ordinary PST/OST Communication Processing shall be an independently identifiable workflow.
`002` — Targeted communication backfill shall be an independently identifiable workflow.
`003` — Deep Scan shall be an independently identifiable workflow.
`004` — Advanced Search Service Request import shall be an independently identifiable workflow.
`005` — Enhanced RFC import shall be an independently identifiable workflow.
`006` — Service Provider WFM import shall be an independently identifiable workflow.
`007` — Infrastructure workbook import shall be an independently identifiable workflow.
`008` — Infrastructure workbook export shall be an independently identifiable workflow.
`009` — `.msg` generation shall be an independently identifiable workflow.
`010` — Orphan housekeeping shall be an independently identifiable workflow.
`011` — Each workflow shall own its supported invocation path.
`012` — Invocation of one workflow shall not silently invoke another workflow unless an explicit accepted orchestration action requires it.
`013` — Workflow invocation shall remain distinguishable from a downstream eligibility change.
`014` — A workflow becoming eligible shall not mean that it has already executed.
`015` — Each scheduled workflow shall own its scheduling configuration.
`016` — Communication Processing cadence shall not become the schedule for unrelated imports.
`017` — Import schedules shall not become Communication Processing schedules.
`018` — `.msg` generation scheduling shall not become Communication Processing scheduling.
`019` — Orphan-housekeeping timing shall remain independent from Communication Processing cadence.
`020` — Disabling one workflow's automatic schedule shall not silently disable another independently scheduled workflow.
`021` — Each workflow shall identify and govern its own source.
`022` — PST/OST workflows shall own communication-source interpretation.
`023` — Advanced Search import shall own interpretation of its supported SR source.
`024` — Enhanced RFC import shall own interpretation of its supported RFC source.
`025` — Service Provider WFM import shall own interpretation of its supported WFM source.
`026` — Infrastructure workbook import shall own interpretation of supported Infrastructure workbooks.
`027` — `.msg` generation shall own its generated artifact rather than treating it as a PST/OST source message.
`028` — One workflow shall not directly modify another workflow's source.
`029` — Communication Processing shall not modify Infrastructure import workbooks.
`030` — Infrastructure import shall not modify PST/OST sources.
`031` — Reporting shall not modify import or communication sources.
`032` — Orphan housekeeping shall not modify external PST/OST content.
`033` — `.msg` generation shall not modify the PST/OST source store.
`034` — A workflow requiring staging shall own its staging representation.
`035` — A workflow requiring operator review shall own the review decision relevant to that workflow.
`036` — One workflow shall not directly alter another workflow's staged rows or proposals.
`037` — Communication proposals shall not mutate workbook-import staging.
`038` — Workbook-import acceptance shall not directly accept communication lifecycle proposals.
`039` — Import staging shall not masquerade as communication-match review.
`040` — Long-running workflows shall own their own background-job identity where background execution applies.
`041` — A job belonging to one workflow shall not be reused as another workflow's job identity.
`042` — Workflow orchestration shall not collapse separately meaningful jobs into one indistinguishable job.
`043` — Failure of one workflow job shall remain attributable to that workflow.
`044` — Success of one workflow job shall not imply success of another workflow.
`045` — Each workflow shall own the transactions for its authoritative mutations.
`046` — One workflow shall not directly commit another workflow's domain decision.
`047` — Workflow cooperation shall occur through accepted application commands, domain services, or reviewed proposals.
`048` — Cooperation shall not bypass the receiving domain's validation.
`049` — Cooperation shall not bypass persistence invariants.
`050` — Each workflow shall define and enforce idempotency for its own repeated execution.
`051` — Communication idempotency shall not substitute for import idempotency.
`052` — Infrastructure workbook idempotency shall not substitute for communication identity rules.
`053` — Reprocessing one workflow shall not duplicate already accepted results belonging to another workflow.
`054` — Each workflow shall produce its own result state.
`055` — Import results shall remain distinct from communication-processing results.
`056` — Communication scan results shall remain distinct from lifecycle proposal outcomes.
`057` — `.msg` generation results shall remain distinct from sending evidence.
`058` — Orphan-housekeeping results shall remain distinct from scan results.
`059` — Each workflow shall expose failure independently.
`060` — Failure of Communication Processing shall not mark Infrastructure import failed.
`061` — Failure of Infrastructure import shall not mark mail scanning failed.
`062` — Failure of `.msg` generation shall not change PST/OST coverage state.
`063` — Orphan purge failure shall not redefine scan high-water state.
`064` — Each workflow shall preserve provenance for the decisions it produces.
`065` — Imported domain facts shall retain import provenance.
`066` — Communication-derived proposals shall retain Communication/source provenance.
`067` — `.msg` artifacts shall retain artifact-generation provenance.
`068` — Orphan purge evidence shall retain housekeeping/purge provenance.
`069` — Provenance shall not be rewritten merely because another workflow later consumes the result.
`070` — Each workflow shall produce applicable audit evidence for its own accepted actions.
`071` — An orchestration layer shall not erase which individual workflow performed each mutation.
`072` — Audit shall distinguish source workflow from downstream domain action where both matter.
`073` — No workflow shall directly write another workflow's source configuration.
`074` — No workflow shall directly write another workflow's source file.
`075` — No workflow shall directly write another workflow's staging state.
`076` — No workflow shall directly write another workflow's job state.
`077` — No workflow shall directly write another workflow's watermark.
`078` — No workflow shall directly write another workflow's coverage state.
`079` — No workflow shall directly write another workflow's review decision.
`080` — No workflow shall directly write another workflow's progress state.
`081` — Workflows may cooperate through explicit application commands.
`082` — Workflows may cooperate through reviewed proposals where the receiving contract supports proposals.
`083` — An application command crossing workflow boundaries shall invoke the receiving workflow/domain through its governed interface.
`084` — Cross-workflow cooperation shall preserve validation.
`085` — Cross-workflow cooperation shall preserve transaction boundaries.
`086` — Cross-workflow cooperation shall preserve provenance and audit.
`087` — Acceptance of the first communication-trackable imported entity may make Communication Processing eligible.
`088` — The importing workflow shall not scan PST/OST content as part of that import.
`089` — The import transaction shall complete independently from any later Communication Processing run.
`090` — Communication eligibility created by import shall be consumed by the Communication Processing pipeline through its normal invocation/schedule.
`091` — Import success shall not imply that communication coverage has advanced.
`092` — Import failure shall not create communication-processing progress.
`093` — Communication Processing shall not behave as Infrastructure workbook synchronization.
`094` — A message mentioning hostname, serial, BOM, IP, Site, Rack, Cloud, or other Infrastructure facts shall not silently update Infrastructure through a workbook-import path.
`095` — Communication-derived Infrastructure-relevant evidence, if ever separately authorized, shall still use the receiving domain's reviewed command/proposal boundary.
`096` — Mail processing shall not write Infrastructure workbook staging.
`097` — Infrastructure workbook discovery shall not start PST/OST scanning.
`098` — Infrastructure workbook staging shall not start PST/OST scanning.
`099` — Infrastructure workbook acceptance shall not execute PST/OST scanning.
`100` — Device Reference promotion or reassignment performed from Infrastructure shall not execute communication scanning.
`101` — Generating a `.msg` artifact shall not prove that a message was sent.
`102` — Saving a `.msg` artifact shall not prove that a message was sent.
`103` — Exporting a `.msg` artifact shall not prove that a message was sent.
`104` — `.msg` generation shall not advance PST/OST communication high-water state.
`105` — `.msg` generation shall not update historical scan coverage.
`106` — `.msg` generation shall not create a retained sent Communication without later governed reconciliation.
`107` — Infrastructure actions shall not directly run Communication Processing.
`108` — Infrastructure actions shall not directly perform orphan-message purge.
`109` — Infrastructure import/export shall not directly modify communication coverage.
`110` — Infrastructure reconciliation shall not directly modify communication high-water state.
`111` — Generating a report shall not initiate PST/OST scanning.
`112` — Viewing a report shall not initiate PST/OST scanning.
`113` — Generating or viewing a report shall not execute orphan purge.
`114` — Reporting shall consume authoritative projections without becoming authority for communication processing state.
`115` — Orphan purge shall remain distinct from Communication Processing.
`116` — Orphan revalidation shall not advance scan high-water.
`117` — Orphan purge shall not expand historical communication coverage.
`118` — Purge shall not inspect unrelated PST/OST messages as part of deletion.
`119` — Scanning shall not be treated as having completed merely because orphan housekeeping completed.
`120` — An explicitly labelled multi-workflow action may orchestrate several workflows.
`121` — Each constituent workflow shall retain its own job identity where jobs apply.
`122` — Each constituent workflow shall retain its own result.
`123` — Each constituent workflow shall retain its own failure state.
`124` — Success of one constituent workflow shall not conceal failure of another.
`125` — Partial multi-workflow success shall remain visible.
`126` — Multi-workflow orchestration shall not merge independent transactions into one ambiguous mutation boundary unless a separately accepted cross-domain transaction explicitly requires that atomicity.
`127` — Advanced Search source files shall remain unmodified unless separate accepted source-writing authority exists.
`128` — RFC import source files shall remain unmodified.
`129` — WFM import source files shall remain unmodified.
`130` — Infrastructure source workbooks shall remain unmodified during import.
`131` — PST/OST source stores shall remain unmodified.
`132` — Generated exports/artifacts shall not be mistaken for authority to mutate their source material.
`133` — Workflow state shall describe execution rather than replace owning domain truth.
`134` — Import success shall not itself define downstream lifecycle state beyond the facts accepted by the import contract.
`135` — Communication-job success shall not itself accept lifecycle proposals.
`136` — Housekeeping-job success shall not redefine ticket or Inventory lifecycle state.
`137` — Each owning domain shall remain authoritative for its accepted business facts.
`138` — Failure in one workflow shall not corrupt another workflow's durable state.
`139` — A failed downstream workflow shall not retroactively mark a successfully committed upstream workflow as uncommitted.
`140` — A successful upstream workflow shall not hide the fact that an explicitly requested downstream workflow failed.
`141` — Retry shall target the failed workflow rather than blindly rerun unrelated successful workflows unless explicitly requested or required for consistency.
`142` — Repeating an explicit multi-workflow action shall preserve each workflow's own idempotency guarantees.
`143` — Repeated orchestration shall not duplicate already accepted imported entities.
`144` — Repeated orchestration shall not duplicate Communications.
`145` — Repeated orchestration shall not duplicate lifecycle proposals.
`146` — Repeated orchestration shall not duplicate purge decisions.
`147` — HLD shall assign each workflow one explicit owning module/service boundary.
`148` — HLD shall identify permitted commands/events/proposals crossing workflow boundaries.
`149` — LLD shall not introduce direct cross-workflow table or state mutation that bypasses the accepted ownership model.
`150` — Shared infrastructure such as job scheduling or persistence utilities shall not transfer business-state ownership between workflows.

## `BETA-REQ-0122` — prefix `COMM-SUM`

**Governing obligation:** Applicable operational detail views shall derive accessible Communication summaries exclusively from accepted canonical links and governed coverage, counting each canonical message once per linked entity and using supported message chronology for direction, last interaction, age, proposals, freshness, and warnings, while `.msg` drafts and rejected/corrected links never inflate current activity and terminal SR/RFC relationships retain only clearly frozen non-reconstructable summaries without body navigation.

`001` — Applicable Service Request detail views shall expose a derived Communication summary.
`002` — Applicable Spare Request detail views shall expose a derived Communication summary.
`003` — Applicable RMA detail views shall expose a derived Communication summary.
`004` — Applicable RFC detail views shall expose a derived Communication summary.
`005` — Applicable WFM Task detail views shall expose a derived Communication summary.
`006` — Applicable Objective detail views shall expose a derived Communication summary.
`007` — Applicable Fault Tag detail views shall expose a derived Communication summary.
`008` — Current Communication summaries shall derive from accepted Communication-to-entity relationships.
`009` — Summary values shall not become an independent authority competing with canonical Communications and links.
`010` — Recalculation of a summary shall not modify underlying Communications.
`011` — Recalculation of a summary shall not modify underlying Communication links.
`012` — Correcting source Communication/link evidence shall cause current summary projection to reflect the accepted correction.
`013` — The summary shall expose accepted received-Communication count where applicable.
`014` — The summary shall expose accepted sent-Communication count where applicable.
`015` — The summary shall expose accepted unknown-direction count where applicable.
`016` — Unknown-direction Communications shall not be forced into received or sent counts.
`017` — Received, sent, and unknown-direction counts shall remain distinguishable.
`018` — Communication direction shall be interpreted relative to the accepted Communication Source Scope.
`019` — `Received` shall mean inbound relative to the applicable source/mailbox context.
`020` — `Sent` shall mean outbound relative to the applicable source/mailbox context.
`021` — Direction shall not be inferred solely from participant names or addresses when source evidence does not support it.
`022` — Ambiguous direction shall remain unknown.
`023` — The summary shall expose the last accepted interaction time when supported.
`024` — Last interaction shall consider only Communications with currently accepted applicable links.
`025` — Rejected links shall not contribute to current last interaction.
`026` — Corrected-away links shall not contribute to current last interaction.
`027` — Last interaction time shall use supported Communication chronology.
`028` — Message received time may support last interaction when applicable and independently known.
`029` — Message sent time may support last interaction when applicable and independently known.
`030` — The applicable accepted final/message chronology shall determine ordering when several supported times exist according to the Communication temporal contract.
`031` — Scan time shall not substitute for last interaction time.
`032` — Discovery time shall not substitute for last interaction time.
`033` — Indexing time shall not substitute for last interaction time.
`034` — Proposal creation time shall not substitute for last interaction time.
`035` — Link-acceptance time shall not substitute for message chronology merely because it is known.
`036` — If no supported Communication time is known, last interaction shall remain unknown.
`037` — Unknown last interaction shall not be replaced with current time.
`038` — Unknown last interaction shall not be replaced with scan/discovery/indexing chronology.
`039` — Where last accepted interaction time is known, the detail view may expose a derived interaction age.
`040` — Interaction age shall derive from the accepted last interaction time rather than be persisted as independent truth.
`041` — Interaction age shall update as time progresses without rewriting the underlying Communication chronology.
`042` — Where last interaction time is unknown, derived age shall also remain unavailable or unknown.
`043` — The summary shall expose the direction of the last accepted interaction where known.
`044` — Last direction shall derive from the same Communication that establishes last accepted interaction.
`045` — Unknown direction of the latest Communication shall remain unknown rather than inherit direction from an earlier message.
`046` — The summary shall expose pending Communication-derived proposals applicable to the entity.
`047` — Pending-proposal count/state shall remain distinct from accepted Communication count.
`048` — A pending lifecycle proposal shall not be represented as an already accepted lifecycle event.
`049` — Rejecting or accepting a proposal shall update the summary projection according to the proposal's resulting state.
`050` — Communication summaries shall expose relevant coverage state.
`051` — Coverage state shall reflect durable communication-processing coverage rather than UI assumptions.
`052` — Historical coverage gaps shall remain visible where they can affect interpretation of the summary.
`053` — Incomplete coverage shall not prevent display of accepted observed counts, but shall qualify their interpretation.
`054` — Communication summaries shall expose relevant freshness state.
`055` — Freshness shall derive from governed scan/coverage state rather than message chronology alone.
`056` — Stale processing state shall remain distinguishable from an entity simply having no recent Communication.
`057` — Material Communication coverage warnings shall remain visible from applicable detail views.
`058` — Source-unavailable warnings shall remain distinguishable from no-match states.
`059` — Historical-coverage warnings shall remain distinguishable from ordinary freshness warnings.
`060` — Warning state shall not silently disappear merely because current accepted counts are nonzero.
`061` — One canonical Communication shall count at most once for any one linked entity's current summary.
`062` — Multiple accepted aliases observed for the same entity in one Communication shall not cause that Communication to count multiple times for that entity.
`063` — Multiple matched identifier occurrences within the same Communication shall not multiply the per-entity Communication count.
`064` — Folder duplicates reconciled to one canonical Communication shall not inflate the entity's count.
`065` — One canonical Communication may count once in the summary of each distinct entity to which it has an accepted link.
`066` — Counting a Communication for one linked entity shall not prevent it from counting for another distinct linked entity.
`067` — Per-entity summaries shall not divide a multi-entity Communication into duplicated stored message records.
`068` — A rejected Communication link shall not contribute to current received count.
`069` — A rejected Communication link shall not contribute to current sent count.
`070` — A rejected Communication link shall not contribute to current unknown-direction count.
`071` — A rejected Communication link shall not establish current last interaction.
`072` — A rejected Communication link may remain visible historically where governed.
`073` — A relationship corrected away from an entity shall not contribute to that entity's current Communication counts.
`074` — A relationship corrected away shall not establish that entity's current last interaction.
`075` — Correction history shall remain explainable without inflating current summary values.
`076` — Correcting one entity link shall not alter another entity's valid summary for the same canonical Communication.
`077` — A generated `.msg` draft shall not count as a sent Communication.
`078` — Saving a `.msg` draft shall not increment sent count.
`079` — Exporting a `.msg` draft shall not increment sent count.
`080` — A `.msg` artifact shall count as Communication activity only after governed reconciliation with an observed sent-store Communication where applicable.
`081` — Reconciliation shall count the canonical observed Communication rather than the artifact as an additional message.
`082` — Communication counts shall describe accepted observed Communications within SOMA's known coverage.
`083` — A count shall not be presented as proof of complete mailbox history.
`084` — A zero count with incomplete coverage shall not be presented as proof that no relevant Communication exists.
`085` — A nonzero count with incomplete coverage shall not imply that no additional relevant Communications exist outside covered ranges.
`086` — Communication body navigation shall resolve through the canonical retained Communication.
`087` — Detail-view summary projections shall not store independent duplicated message bodies.
`088` — Multiple entity links shall resolve to the same canonical Communication body where retention permits body access.
`089` — A summary record alone shall not become an alternate reconstructable Communication store.
`090` — The SR detail/history view shall preserve a frozen terminal Communication summary where applicable.
`091` — The frozen terminal summary shall be non-reconstructable.
`092` — The frozen terminal summary may preserve bounded counts and chronology allowed by the terminal-summary contract.
`093` — The frozen summary shall clearly indicate its terminal/historical nature.
`094` — The frozen terminal summary shall not provide body navigation through the removed SR link.
`095` — Terminal-summary preservation shall not keep a direct active Communication link merely for UI convenience.
`096` — The RFC detail/history view shall preserve a frozen terminal Communication summary where applicable.
`097` — The RFC terminal summary shall be non-reconstructable.
`098` — The terminal RFC summary shall not provide body navigation through its removed direct RFC link.
`099` — Terminal RFC summary shall remain distinct from an active Communication relationship.
`100` — Terminal removal of an SR link shall not remove another entity's valid link to the same Communication.
`101` — Terminal removal of an RFC link shall not remove another entity's valid link to the same Communication.
`102` — Another linked Spare Request may retain body navigation when its Communication dependency remains valid.
`103` — Another linked RMA may retain body navigation when its Communication dependency remains valid.
`104` — Another linked WFM, Objective, or Fault Tag may retain its applicable Communication relationship when still valid.
`105` — Frozen terminal summary shall not prevent the canonical Communication from entering orphan grace when no protected dependency remains.
`106` — The frozen terminal summary itself shall not count as a protected reconstructable dependency.
`107` — Post-purge frozen terminal summary shall remain compatible with the non-reconstructable suppression boundaries of `0116`.
`108` — Terminal summary shall not reconstruct purged body, subject, participants, or attachments.
`109` — Received, sent, unknown, stale, warning, coverage, proposal, and terminal states shall not rely solely on color.
`110` — Communication summary states shall have textual, semantic, iconographic, or equivalent non-color cues.
`111` — Warning meaning shall remain accessible to keyboard and assistive-technology users.
`112` — Terminal frozen-summary state shall be perceivable without relying solely on reduced opacity or color.
`113` — Unknown values shall be explicitly distinguishable from zero values.
`114` — Stale data shall be explicitly distinguishable from current data.
`115` — Current summary projection shall be reproducible from accepted Communication/link/proposal/coverage state.
`116` — Summary recalculation shall be idempotent.
`117` — Rebuilding the summary projection shall not duplicate count contributions.
`118` — Summary projection failure shall not rewrite canonical Communication evidence.
`119` — Summary values shall remain subordinate to the owning Communication and domain facts from which they derive.

## `BETA-REQ-0123` — prefix `UI-NAV`

**Governing obligation:** SOMA shall provide one accessible navigation contract across lists, tables, grids, queues, and workbench navigators that keeps active row, selection, multi-selection, focus, and opened record distinct; uses single-click selection with double-click/Enter/touch-Open equivalence; assigns scroll input to its intended surface without cross-pane leakage; and restores deterministic query, scroll, selection, and focus context on return.

`001` — Shared row-navigation semantics shall apply to SOMA lists.
`002` — Shared row-navigation semantics shall apply to SOMA tables.
`003` — Shared row-navigation semantics shall apply to SOMA grids.
`004` — Shared row-navigation semantics shall apply to search results.
`005` — Shared row-navigation semantics shall apply to review queues.
`006` — Shared row-navigation semantics shall apply to workbench navigators.
`007` — Domain-specific views may add behavior only where they preserve the shared interaction contract.
`008` — Active row shall remain a distinct UI state.
`009` — Single selection shall remain distinct from active-row state where both concepts apply.
`010` — Multi-selection membership shall remain distinct from active-row state.
`011` — Keyboard focus shall remain distinct from selection.
`012` — Opened record shall remain distinct from selection.
`013` — Opening a record shall not be inferred merely because the row became active.
`014` — Selection state shall not be inferred solely from keyboard focus.
`015` — A single primary click on a selectable row shall select that row.
`016` — A single primary click shall not open the row's default destination.
`017` — A single primary click shall establish the clicked row as active where appropriate.
`018` — Single-click selection shall behave consistently across comparable shared list/table components.
`019` — Double-clicking an openable selected or active row shall open its default destination.
`020` — Double-click shall use the same default destination as keyboard `Enter`.
`021` — Double-click shall not invoke an unrelated nested control.
`022` — Rows without an applicable default destination shall not fabricate an open action.
`023` — `Enter` on an openable active/focused row shall open its default destination.
`024` — Keyboard `Enter` and pointer double-click shall resolve to the same default destination.
`025` — `Enter` shall not alter multi-selection membership merely as a side effect of opening.
`026` — `Enter` shall not open a different destination merely because the row was reached through keyboard navigation.
`027` — Arrow keys shall move the active row through eligible rows.
`028` — Arrow navigation shall not open records.
`029` — Arrow navigation shall not silently toggle multi-selection membership.
`030` — Arrow navigation shall preserve the current navigation context.
`031` — The active row shall remain visibly identifiable after keyboard movement.
`032` — Activating a nested row control shall execute only that control's action.
`033` — Activating a nested row control shall not also trigger row opening.
`034` — Activating a nested row control shall not unintentionally change unrelated selection state.
`035` — Nested controls shall remain separately focusable where required for accessibility.
`036` — Pointer-event propagation shall be controlled so nested-action activation cannot accidentally invoke the row's default action.
`037` — Multi-select views shall distinguish active row from membership in the selected set.
`038` — Arrow keys shall move the active row without changing multi-selection membership.
`039` — `Space` shall toggle multi-selection membership for the active row where multi-selection is supported.
`040` — `Space` shall not open the active row.
`041` — Multi-selection membership shall remain visibly distinguishable from the active row.
`042` — A row may be active without belonging to the multi-selection set.
`043` — A selected-set member may remain selected while another row becomes active.
`044` — Wheel input shall apply to the nearest eligible scrollable surface beneath the pointer.
`045` — Trackpad scroll input shall apply to the nearest eligible scrollable surface beneath the pointer.
`046` — Ticket-list scrolling shall follow hovered-surface ownership.
`047` — Communication-preview scrolling shall follow hovered-surface ownership.
`048` — Popup scrolling shall follow hovered-surface ownership.
`049` — Table scrolling shall follow hovered-surface ownership.
`050` — Dialog scrolling shall follow hovered-surface ownership.
`051` — Workbench-pane scrolling shall follow hovered-surface ownership.
`052` — Wheel scrolling shall not change row selection.
`053` — Trackpad scrolling shall not change row selection.
`054` — Wheel scrolling shall not open a record.
`055` — Trackpad scrolling shall not open a record.
`056` — Merely scrolling over a row shall not make that row selected.
`057` — When a hovered scrollable surface reaches its top boundary, continued wheel/trackpad input shall not unexpectedly scroll a separate underlying pane.
`058` — When a hovered scrollable surface reaches its bottom boundary, continued wheel/trackpad input shall not unexpectedly scroll a separate underlying pane.
`059` — Popup scroll boundaries shall not leak scroll into the parent page or workbench pane unexpectedly.
`060` — Dialog scroll boundaries shall not unexpectedly move the underlying workspace.
`061` — Communication-preview boundaries shall not unexpectedly scroll the Ticket navigator.
`062` — Scroll containment shall preserve predictable nested-surface ownership.
`063` — Keyboard scrolling shall belong to the currently focused scrollable surface.
`064` — `Page Up`/`Page Down` or equivalent keyboard scrolling shall not unexpectedly move an unfocused neighboring pane.
`065` — Focus movement between panes shall explicitly transfer keyboard-scroll ownership.
`066` — Keyboard-scroll ownership shall remain perceivable through visible focus.
`067` — Touch scrolling shall apply to the surface where the gesture originated.
`068` — Touch movement inside a scrollable pane shall not trigger row opening.
`069` — A scrolling gesture shall not accidentally trigger deliberate-hold or row-open behavior.
`070` — Touch interfaces shall expose an explicit Open action for openable records.
`071` — Touch users shall not depend on a desktop-style double-click gesture.
`072` — Explicit touch Open shall resolve to the same default destination as desktop double-click and keyboard `Enter`.
`073` — Each openable row type shall have one governed default destination.
`074` — Pointer double-click shall use that destination.
`075` — Keyboard `Enter` shall use that destination.
`076` — Touch Open shall use that destination.
`077` — The shared interaction method shall not produce device-specific destination differences.
`078` — Return navigation shall restore the applicable prior query where still valid.
`079` — Return navigation shall restore the applicable prior filter state.
`080` — Return navigation shall restore applicable scroll position.
`081` — Return navigation shall restore applicable selection.
`082` — Return navigation shall restore applicable active row.
`083` — Return navigation shall restore applicable keyboard focus.
`084` — Restoration shall not reopen the previous record automatically merely because it was previously selected.
`085` — Opening and returning from a workbench shall not unnecessarily reset the operator to the beginning of a result set.
`086` — Navigation restoration shall remain scoped to the originating view.
`087` — Returning to one list shall not restore stale context belonging to another list.
`088` — Return navigation shall detect when the former row is no longer present in the restored result set.
`089` — Stale-result recovery shall use a deterministic fallback.
`090` — Stale-result fallback shall not fabricate the removed row into the current query.
`091` — Stale-result fallback shall preserve the restored query/filter state where still valid.
`092` — The exact nearest-row/focus fallback algorithm may be defined by shared UI LLD.
`093` — Equivalent stale-result conditions shall resolve consistently.
`094` — Keyboard focus shall always have a visible indication.
`095` — Focus indication shall remain distinguishable from selection.
`096` — Focus indication shall remain distinguishable from hover.
`097` — Focus indication shall remain visible in both Light and Dark appearance.
`098` — Focus indication shall satisfy the governed accessible-theme contract.
`099` — Active-row state shall not rely on color alone.
`100` — Selection shall not rely on color alone.
`101` — Multi-selection membership shall not rely on color alone.
`102` — Keyboard focus shall not rely on color alone where an additional visual/semantic cue is required for accessibility.
`103` — Opened/current-record context shall not rely on color alone.
`104` — Shared list/table navigation shall expose appropriate semantic roles.
`105` — Selection state shall be exposed semantically to assistive technology where applicable.
`106` — Multi-selection state shall be exposed semantically where supported.
`107` — Active/focused elements shall have meaningful accessible identification.
`108` — Nested controls shall expose their own accessible names and states.
`109` — Every primary row-opening workflow shall have a keyboard-accessible equivalent.
`110` — Every supported selection action shall have a keyboard-accessible equivalent.
`111` — Multi-selection membership control shall be keyboard-accessible.
`112` — Nested row actions shall be keyboard-accessible.
`113` — Keyboard operation shall not require pointer hover.
`114` — Opening the same record through pointer or keyboard shall yield equivalent application state.
`115` — Selecting a row through pointer or keyboard shall yield equivalent selection semantics.
`116` — Interaction modality shall not change domain mutation semantics.
`117` — Navigation actions shall not themselves execute destructive or domain-mutating actions.
`118` — Arrow movement shall never be interpreted as domain confirmation.
`119` — Scroll input shall never be interpreted as domain confirmation.
`120` — Merely focusing a nested action shall never execute it.
`121` — Comparable SOMA list/table/grid views shall use shared interaction primitives or behaviorally equivalent shared contracts.
`122` — Domain workbenches shall not independently redefine single-click versus double-click semantics without separate accepted authority.
`123` — Review queues shall not invent conflicting keyboard navigation conventions.
`124` — Shared components shall preserve these behaviors under responsive layout changes.
`125` — Restorable query/scroll/selection/focus state is presentation/navigation state rather than business-domain truth.
`126` — Loss of ephemeral navigation state shall not modify domain records.
`127` — Restoration mechanics shall not require writing false domain history.
`128` — The LLD may choose session/local persistence appropriate to the navigation contract without transferring business-state authority.

## `BETA-REQ-0124` — prefix `UI-AUTO`

**Governing obligation:** SOMA shall use one accessible bounded autocomplete/chooser contract in which deliberate thresholded input or explicit bounded disclosure retrieves cancellable current results, popup scrolling remains locally owned, all loading/empty/partial/stale/warning/error states remain distinct, keyboard/pointer/touch acceptance is equivalent, and typed or highlighted text never creates an entity or relationship because missing-record creation is an explicitly labelled domain action.

`001` — Shared autocomplete behavior shall apply to autocomplete controls.
`002` — Shared autocomplete behavior shall apply to searchable relationship selectors.
`003` — Shared autocomplete behavior shall apply to bounded choosers where search is supported.
`004` — Comparable selectors shall use shared interaction primitives or behaviorally equivalent contracts.
`005` — Autocomplete surfaces shall use shared semantic theme tokens.
`006` — Autocomplete surfaces shall adapt to supported responsive layouts.
`007` — Theme changes shall not alter selector semantics.
`008` — Searchable selectors shall expose appropriate combobox semantics.
`009` — Result collections shall expose appropriate listbox semantics.
`010` — Active option state shall be exposed semantically.
`011` — Selected/accepted value shall be exposed semantically.
`012` — Loading, disabled, invalid, and warning states shall be accessible to assistive technology.
`013` — Search shall begin only after deliberate operator input reaches the domain's configured minimum threshold.
`014` — Merely focusing the control shall not initiate an unbounded search.
`015` — Empty input shall not enumerate an unbounded population.
`016` — The search threshold may vary by domain.
`017` — Exact threshold values may be defined by the owning domain or LLD without weakening the deliberate-input rule.
`018` — A selector may expose an explicit disclosure action for a bounded eligible set.
`019` — Explicit disclosure shall remain distinguishable from free-text search.
`020` — Disclosure shall not enumerate an unbounded population.
`021` — If the eligible set is too large to load safely, SOMA shall require search rather than silently loading everything.
`022` — Loaded search results shall be bounded.
`023` — A selector shall not load an arbitrarily large eligible population in one response.
`024` — Result limits shall preserve enough metadata to distinguish partial results from complete results.
`025` — Additional results shall remain retrievable through an explicit governed mechanism where applicable.
`026` — The popup's visible height shall be bounded.
`027` — Excess results shall scroll inside the popup.
`028` — Popup growth shall not extend indefinitely beyond the usable viewport.
`029` — Wheel input over the popup shall scroll the popup.
`030` — Trackpad input over the popup shall scroll the popup.
`031` — Popup scrolling shall not change the underlying list/table selection.
`032` — Popup scroll boundaries shall not leak unexpectedly into the underlying pane.
`033` — Reaching the popup's top boundary shall not unexpectedly scroll the parent workspace.
`034` — Reaching the popup's bottom boundary shall not unexpectedly scroll the parent workspace.
`035` — New search input shall supersede stale pending search work.
`036` — Where supported, stale pending search work shall be cancelled.
`037` — Results from an older query shall not replace newer-query results after they arrive late.
`038` — Query/result association shall be deterministic.
`039` — Stale result sets shall not remain presented as current matches.
`040` — Loading state shall be distinct from minimum-input state.
`041` — Loading state shall be distinct from no-match state.
`042` — Loading shall not be represented as an empty result set.
`043` — Minimum-input state shall indicate that more deliberate input is required.
`044` — Minimum-input state shall not be presented as no matches.
`045` — No-match state shall mean the completed current search returned no eligible matches within its governed scope.
`046` — No-match state shall remain distinct from an empty eligible domain.
`047` — Empty-state shall represent a genuinely empty bounded eligible set where known.
`048` — Empty-state shall not imply search failure.
`049` — Partial results shall be explicitly distinguishable from complete results.
`050` — Additional-results-available state shall be visible where result truncation applies.
`051` — A user shall not be led to believe that a bounded result page contains every possible eligible match when it does not.
`052` — Stale results shall remain distinct from current results.
`053` — A relationship whose eligibility changed after results loaded shall be revalidated before acceptance.
`054` — Materially exceptional but potentially selectable options shall carry a visible warning state.
`055` — Warning state shall not rely solely on color.
`056` — Search failure shall remain distinct from no-match state.
`057` — Search failure shall expose a bounded recoverable error state where applicable.
`058` — An error shall not silently clear a previously accepted relationship.
`059` — Arrow keys shall move the active option within the popup.
`060` — Moving the active option shall not accept it automatically.
`061` — Active-option position shall remain visible.
`062` — `Enter` shall accept the active eligible option.
`063` — `Enter` shall not accept an ineligible option.
`064` — Acceptance shall use the exact underlying entity/relationship identity represented by the option.
`065` — `Escape` shall close the popup without accepting the active option.
`066` — Closing with `Escape` shall preserve the previously accepted value.
`067` — Pointer selection of an option shall produce the same relationship result as keyboard acceptance.
`068` — Touch selection shall produce the same relationship result.
`069` — Input modality shall not alter domain validation.
`070` — Typing text into a selector shall not create an entity.
`071` — Typing text shall not create a relationship.
`072` — Leaving typed text in the control shall not implicitly accept a non-existent record.
`073` — Highlighting a candidate shall not create a relationship.
`074` — Merely navigating to a candidate shall not create a relationship.
`075` — Missing-entity creation shall be exposed as a separate labelled action where the owning domain permits creation.
`076` — Creation shall use the owning domain's validation and confirmation rules.
`077` — Creating a missing entity shall not be disguised as choosing an autocomplete result.
`078` — After creation, relationship establishment shall remain explicit or governed by the creating workflow.
`079` — Ineligible options shall remain distinguishable from eligible options.
`080` — An ineligible option shall expose a reason where useful.
`081` — An archived or otherwise ineligible entity shall not become selectable merely because it matches typed text.
`082` — Keyboard/pointer navigation may expose an ineligible option for explanation where appropriate but shall not permit invalid acceptance.
`083` — Exceptional options that remain valid only after warning/confirmation shall be clearly identified.
`084` — Selecting an exceptional option shall invoke the owning domain's required review/confirmation semantics.
`085` — The selector shall not silently downgrade an exception into ordinary acceptance.
`086` — The popup shall remain within the usable viewport.
`087` — The popup may reposition above/below the control as needed.
`088` — The popup shall not make its active option inaccessible beyond an unrecoverable viewport boundary.
`089` — Popup positioning shall remain usable under supported zoom and text enlargement.
`090` — Opening a popup shall establish predictable keyboard focus/active-option behavior.
`091` — Closing the popup shall return focus to an appropriate selector control or subsequent governed destination.
`092` — Focus indication shall remain visible.
`093` — Pointer interaction shall not destroy keyboard accessibility.
`094` — Searching shall not clear an already accepted relationship.
`095` — A failed search shall not clear an accepted relationship.
`096` — Cancelling popup interaction shall not clear an accepted relationship.
`097` — Replacement of an accepted relationship shall require explicit acceptance of the new option.
`098` — Option acceptance shall revalidate current eligibility before authoritative mutation.
`099` — A stale option becoming archived/ineligible before acceptance shall be rejected or require the applicable exception path.
`100` — Search-result freshness shall not bypass domain constraints.
`101` — Option labels shall remain descriptive presentation rather than relational identity.
`102` — Selection shall persist the governed internal entity identity or relationship target, not the display label alone.
`103` — Two identical display labels shall remain independently selectable where they represent different entities.
`104` — Ambiguous equal-label results shall expose enough context for operator distinction.
`105` — Active option shall not rely solely on color.
`106` — Selected option shall not rely solely on color.
`107` — Warning/ineligible/error states shall not rely solely on color.
`108` — Minimum-input/loading/no-match states shall be semantically announced where appropriate.
`109` — Responsive reflow shall preserve the selector's accepted value.
`110` — Responsive reflow shall not create or remove relationships.
`111` — Popup repositioning shall not change option ordering or acceptance semantics.
`112` — Touch presentation may differ visually while preserving the same eligible set and relationship semantics.
`113` — Autocomplete query state shall remain presentation state rather than domain truth.
`114` — Search-result caching shall not make stale eligibility authoritative.
`115` — Autocomplete implementation shall not write domain relationships before accepted selection.
`116` — Relationship mutation shall occur through the owning application/domain service.

## `BETA-REQ-0125` — prefix `UI-RESP`

**Governing obligation:** Every SOMA surface shall responsively preserve capabilities, material facts, warnings, evidence, actions, and interaction context under changing viewport, zoom, and text size, while accessible icon actions and split/overflow surfaces remain usable and deliberate three-second hold confirmation is restricted to an approved allowlist—including new Device Reference promotion—with safe pointer, touch, and keyboard semantics and without imposing ritual friction on ordinary reversible actions.

`001` — Responsive behavior shall apply to every SOMA workspace.
`002` — Responsive behavior shall apply to every workbench.
`003` — Responsive behavior shall apply to dialogs.
`004` — Responsive behavior shall apply to forms.
`005` — Responsive behavior shall apply to tables and grids.
`006` — Responsive behavior shall apply to Communication panels.
`007` — Responsive behavior shall apply to action surfaces.
`008` — Reduced viewport or container size shall not remove a supported business capability.
`009` — Responsive reflow shall not hide a required action without an accessible alternative route.
`010` — Responsive layout shall not remove material operational facts.
`011` — Responsive layout shall not remove material warnings.
`012` — Responsive layout shall not remove required evidence.
`013` — Responsive layout shall not change domain acceptance logic.
`014` — Controls shall reflow deterministically according to available space.
`015` — Equivalent viewport conditions shall yield equivalent layout behavior.
`016` — Reflow shall not randomly reorder actions between renders.
`017` — Reflow shall preserve meaningful reading and action order.
`018` — Responsive behavior shall be based on usable container/viewport space rather than unsupported fixed-device assumptions.
`019` — Split workbenches shall preserve access to the operational pane.
`020` — Split workbenches shall preserve access to the Communication pane.
`021` — Narrow layouts may stack, collapse, tab, or otherwise reflow panes while preserving both capabilities.
`022` — Reflow shall not permanently discard one pane's state.
`023` — Moving between responsive pane layouts shall preserve the current workbench record.
`024` — Communication access shall remain available even when simultaneous side-by-side presentation is impossible.
`025` — Wide comparison tables shall remain bounded within their owning region.
`026` — Wide tables may use horizontal scrolling when all columns cannot fit.
`027` — Horizontal table scrolling shall not expand the entire application viewport uncontrollably.
`028` — Horizontal scrolling shall preserve row/column context as far as practical.
`029` — Material comparison data shall not simply disappear to avoid horizontal overflow.
`030` — Empty states shall be positioned within their owning region.
`031` — Empty-state centering shall not displace unrelated surrounding surfaces.
`032` — Split-pane empty states shall remain scoped to the empty pane rather than the entire application.
`033` — Empty states shall remain usable at narrow dimensions.
`034` — Text shall remain within usable viewport/container bounds.
`035` — Menus shall remain viewport-safe.
`036` — Dialogs shall remain viewport-safe.
`037` — Autocomplete popups shall remain viewport-safe.
`038` — Required action controls shall remain viewport-accessible.
`039` — Responsive surfaces shall avoid unreachable off-screen required controls.
`040` — Supported text enlargement shall not remove functionality.
`041` — Supported browser/application zoom shall not remove functionality.
`042` — Enlarged text shall not conceal required warnings.
`043` — Enlarged text shall not make dialogs impossible to operate.
`044` — Enlarged text shall not make confirmation controls unreachable.
`045` — Zoomed layouts may reflow rather than preserve desktop geometry.
`046` — Every icon-only action shall expose an accessible name.
`047` — The accessible name shall describe the action rather than merely the icon appearance.
`048` — Icon-only actions shall not depend on visual recognition alone.
`049` — Keyboard-operable icon actions shall be focusable.
`050` — Focus shall remain visibly perceivable.
`051` — Focus appearance shall not rely solely on color.
`052` — Enabled/disabled icon state shall be semantically available.
`053` — Selected/toggled icon state shall be accessible where applicable.
`054` — Warning/destructive icon state shall not depend solely on color.
`055` — Icon-only actions shall provide supplemental pointer tooltip text.
`056` — Icon-only actions shall provide equivalent supplemental information on keyboard focus where appropriate.
`057` — Tooltip text shall supplement rather than replace the accessible name.
`058` — Critical instructions shall not exist only inside a transient tooltip.
`059` — Touch-oriented presentation shall provide a labelled form of icon-only actions where necessary for usability.
`060` — Touch users shall not be required to discover an action through hover.
`061` — Touch-labelled actions shall execute the same domain command as their desktop equivalents.
`062` — Responsive changes shall preserve the active pane.
`063` — Responsive changes shall preserve filters.
`064` — Responsive changes shall preserve unsaved drafts where the owning workflow supports draft preservation.
`065` — Responsive changes shall preserve row selection.
`066` — Responsive changes shall preserve multi-selection membership where applicable.
`067` — Responsive changes shall preserve workbench/navigation context.
`068` — Responsive changes shall preserve current record identity.
`069` — Layout reflow shall not silently submit or cancel drafts.
`070` — Deliberate-hold actions shall belong to a governed allowlist.
`071` — A developer shall not add hold-to-confirm behavior arbitrarily to ordinary actions.
`072` — Every allowlisted hold action shall have an accepted confirmation tier or product authority.
`073` — The standard deliberate-hold duration shall be three seconds.
`074` — An allowlisted three-second hold shall require continuous valid activation for the duration.
`075` — The action shall not execute before completion of the hold.
`076` — The three-second value shall not silently vary among equivalent deliberate-hold controls.
`077` — A deliberate hold shall expose visible progress.
`078` — Progress shall communicate that continued activation is required.
`079` — Hold progress shall not rely only on color.
`080` — Hold completion shall have a perceivable semantic state.
`081` — Reduced-motion presentation shall preserve progress meaning without requiring motion.
`082` — Pointer input shall support continuous deliberate hold.
`083` — Pointer release before completion shall cancel the pending hold.
`084` — Pointer movement into an invalid activation condition shall reset or cancel according to the shared hold contract.
`085` — Touch input shall support an equivalent deliberate-hold action.
`086` — Touch release before completion shall cancel the pending hold.
`087` — Touch movement recognized as scrolling shall not trigger the hold action.
`088` — Touch scrolling and deliberate hold shall remain distinguishable.
`089` — Keyboard users shall have an equivalent deliberate-hold mechanism.
`090` — Keyboard activation shall require continuous valid activation equivalent to the three-second confirmation.
`091` — Releasing the relevant keyboard activation before completion shall cancel/reset the hold.
`092` — Keyboard deliberate hold shall not require pointer interaction.
`093` — Explicit cancellation shall reset hold progress.
`094` — Invalid activation shall reset hold progress.
`095` — Premature release shall reset hold progress.
`096` — Navigating away before completion shall not execute the action.
`097` — A cancelled hold shall cause no domain mutation.
`098` — Wheel scrolling shall not trigger deliberate hold.
`099` — Trackpad scrolling shall not trigger deliberate hold.
`100` — Touch scrolling shall not trigger deliberate hold.
`101` — Reaching a scroll boundary shall not accidentally complete a hold action.
`102` — Deliberate promotion of a provisional/external Device Reference into a newly registered Infrastructure Network Element shall retain the three-second hold behavior.
`103` — Device Reference promotion shall provide visible semantic hold progress.
`104` — Cancelling the Device Reference promotion hold shall create no Network Element.
`105` — Scrolling over the Device Reference promotion control shall not create a Network Element.
`106` — Pointer, touch, and keyboard promotion shall apply equivalent domain validation.
`107` — Correcting or resolving a provisional Device Reference to an already-existing Network Element shall remain distinguishable from promotion that creates a new Network Element.
`108` — The existence of the three-second creation/promotion hold shall not prevent later reviewed reassignment to an existing Network Element after a related SR becomes terminal.
`109` — Such reassignment shall preserve the Device Reference and Network Element identities and applicable historical correction evidence.
`110` — Reassignment from Infrastructure shall not reopen or rewrite the related terminal SR.
`111` — Ordinary reversible actions shall not require deliberate hold merely for visual drama.
`112` — Simple navigation shall not require deliberate hold.
`113` — Ordinary selection shall not require deliberate hold.
`114` — Easily reversible local presentation changes shall not require deliberate hold.
`115` — Confirmation friction shall be proportional to mistake consequence.
`116` — Complex actions shall retain their separately required confirmation or review behavior.
`117` — Multi-target actions shall retain required impact preview where governed.
`118` — Destructive actions shall retain required impact preview.
`119` — A deliberate hold shall not replace required impact preview.
`120` — Impact preview shall not replace a hold when an approved confirmation tier independently requires both.
`121` — Hold confirmation shall be used only when an approved tier determines that sustained intentional activation meaningfully interrupts accidental execution.
`122` — Exact action-to-tier mapping shall be governed through a deliberate-confirmation registry.
`123` — Confirmation-tier design shall distinguish reversible, corrective, destructive, and high-mistake-cost actions.
`124` — Confirmation tiers shall not change domain authorization or validation rules.
`125` — Responsive reflow shall preserve keyboard operability.
`126` — Responsive reflow shall preserve assistive-technology semantics.
`127` — Required actions shall remain reachable in logical focus order.
`128` — Hold progress shall be perceivable without depending exclusively on animation.
`129` — Icon actions shall remain understandable without color or hover alone.
`130` — Responsive layout changes shall not create domain mutations.
`131` — Changing orientation or container dimensions shall not submit a form.
`132` — Changing orientation or container dimensions shall not clear an accepted relationship.
`133` — Changing orientation or container dimensions shall not execute a deliberate-hold action.
`134` — Reflow shall preserve current validation/warning state.
`135` — Responsive behavior shall be implemented through shared layout primitives or behaviorally equivalent contracts.
`136` — Deliberate-hold behavior shall use a shared governed interaction primitive.
`137` — Domain screens shall not implement materially inconsistent hold timers or cancellation semantics.
`138` — Icon-only actions shall use shared accessibility expectations.

## `BETA-REQ-0126` — prefix `UI-THEME`

**Governing obligation:** SOMA shall use one versioned semantic-token system across a governed set of built-in skins and independent Light, Dark, or System appearance modes, permitting visual variation without changing layout, information architecture, workflow, commands, density, confirmation, state/severity semantics, accessibility, or acceptance logic, while every operational state remains distinguishable through redundant accessible cues and any terminal/game-inspired presentation remains subordinate to canonical domain terminology and truth.

`001` — SOMA shall use one governed semantic design-token system.
`002` — The semantic token system shall be versioned.
`003` — Built-in skins shall consume the shared semantic-token system rather than redefine independent application semantics.
`004` — Shared components shall derive their semantic presentation from governed tokens.
`005` — Domain screens shall not hard-code competing semantic meanings outside the governed token system without separately accepted authority.
`006` — Tokens shall represent semantic roles rather than depend solely on raw palette names.
`007` — Business logic shall not derive state meaning from the rendered color value.
`008` — Changing a skin's palette shall not change domain state.
`009` — Beta 1.0 shall provide only a small governed set of built-in skins.
`010` — Available skins shall be explicitly defined by SOMA rather than arbitrary external stylesheets.
`011` — Each built-in skin shall have stable identity/version information sufficient for compatibility and migration.
`012` — Adding a new built-in skin shall require compliance with the full semantic/accessibility contract.
`013` — Beta 1.0 shall not support arbitrary user-supplied CSS.
`014` — Beta 1.0 shall not support imported third-party themes.
`015` — Beta 1.0 shall not permit theme packages to redefine application workflow or semantics.
`016` — Theme customization shall remain bounded to supported SOMA controls.
`017` — Appearance mode shall be independently configurable from skin selection.
`018` — SOMA shall support Light appearance.
`019` — SOMA shall support Dark appearance.
`020` — SOMA shall support System appearance.
`021` — System appearance shall follow the applicable operating/browser environment preference.
`022` — Changing appearance mode shall not change selected skin identity.
`023` — Changing skin shall not silently change Light/Dark/System preference.
`024` — Every built-in skin shall support Light presentation.
`025` — Every built-in skin shall support Dark presentation.
`026` — Every built-in skin shall remain operable under System appearance.
`027` — A skin shall not be considered valid if its semantics only work in one appearance mode.
`028` — Every built-in skin shall remain operable under supported high-contrast presentation.
`029` — High-contrast adaptation shall preserve state meaning.
`030` — High-contrast adaptation shall preserve action discoverability.
`031` — High-contrast mode shall not remove critical boundaries or focus indicators merely because decorative styling is suppressed.
`032` — Every built-in skin shall remain usable under forced-color presentation.
`033` — Forced-color overrides shall not make selection indistinguishable from unselected state.
`034` — Forced-color overrides shall not make focus undiscoverable.
`035` — Forced-color presentation shall preserve destructive/warning meaning through non-color semantics.
`036` — Every skin shall preserve equivalent meaning and operability under supported zoom.
`037` — Zoom shall not cause themed decoration to displace required actions.
`038` — Skin-specific visual treatment shall remain subordinate to responsive-layout requirements from `0125`.
`039` — Every skin shall preserve equivalent operability with supported enlarged text.
`040` — Typography accents shall not prevent text reflow.
`041` — Decorative typography shall not make critical information unreadable at enlarged sizes.
`042` — Required labels shall not be replaced by illegible decorative glyph treatment.
`043` — Every skin shall remain operable under reduced-motion presentation.
`044` — Motion shall not carry unique operational meaning.
`045` — Animations may be reduced or removed without losing state or progress meaning.
`046` — The deliberate-hold progress contract shall remain understandable under reduced-motion settings.
`047` — A skin may alter its palette.
`048` — Palette changes shall preserve semantic contrast and state distinctions.
`049` — Palette changes shall not redefine severity hierarchy.
`050` — A skin may alter approved typography accents.
`051` — Typography accents shall not replace the application's governed readable body/interface typography where doing so would reduce usability.
`052` — Typography changes shall not alter information hierarchy semantics inconsistently.
`053` — A skin may alter border treatment.
`054` — Border changes shall preserve required structural and focus distinctions.
`055` — A skin may alter approved corner-radius treatment.
`056` — Radius changes shall not alter interaction hit targets or action semantics.
`057` — A skin may alter elevation/shadow treatment.
`058` — Elevation changes shall not become the only cue distinguishing modal, popup, or layering semantics.
`059` — A skin may use restrained texture.
`060` — Texture shall remain decorative.
`061` — Texture shall not reduce readability or obscure state cues.
`062` — Texture shall not become a substitute for information or warning semantics.
`063` — Skins may alter governed chart hues.
`064` — Chart-series or state meaning shall not rely solely on hue.
`065` — Equivalent chart semantics shall remain distinguishable under color-vision and forced-color constraints where applicable.
`066` — Skin selection shall not alter application layout.
`067` — Skin selection shall not change workspace placement.
`068` — Skin selection shall not change workbench pane organization.
`069` — Skin selection shall not add or remove business panels.
`070` — Skin selection shall not rename or reorganize canonical workspaces.
`071` — Skin selection shall not move domain functionality between workspaces.
`072` — Skin selection shall not alter navigation hierarchy.
`073` — Skin selection shall not alter workflow steps.
`074` — Skin selection shall not add workflow requirements.
`075` — Skin selection shall not remove workflow requirements.
`076` — Skin selection shall not change whether review/confirmation is required.
`077` — Built-in skins shall expose equivalent supported commands.
`078` — A skin shall not hide a command merely as a stylistic choice.
`079` — A skin shall not introduce unique domain commands.
`080` — Skin selection shall not materially alter information density.
`081` — Compact/comfortable density shall not secretly become a skin-specific workflow difference.
`082` — If density customization is ever supported, it shall be governed separately from skin identity.
`083` — The meaning of informational state shall remain the same across skins.
`084` — Warning severity shall remain semantically equivalent across skins.
`085` — Error/severe state shall remain semantically equivalent across skins.
`086` — Destructive state shall remain semantically equivalent across skins.
`087` — Historical/provisional/stale/unknown semantics shall not change with appearance.
`088` — Skin selection shall not alter confirmation tiers.
`089` — Skin selection shall not alter the three-second deliberate-hold duration.
`090` — Skin selection shall not remove an impact preview.
`091` — Skin selection shall not add ritual confirmation to ordinary reversible actions.
`092` — Skin selection shall not weaken accessibility semantics.
`093` — Skin selection shall not remove keyboard operability.
`094` — Skin selection shall not remove assistive-technology labels.
`095` — Skin selection shall not remove visible focus.
`096` — Skin selection shall not make state distinctions color-only.
`097` — Skin selection shall not alter validation rules.
`098` — Skin selection shall not alter eligibility rules.
`099` — Skin selection shall not alter import acceptance.
`100` — Skin selection shall not alter proposal acceptance.
`101` — Skin selection shall not alter destructive-action eligibility.
`102` — Operational state shall not depend solely on color.
`103` — Operational state shall not depend solely on motion.
`104` — Operational state shall not depend solely on position.
`105` — Operational state shall not depend solely on iconography without accessible semantics.
`106` — Material state shall use redundant semantic cues appropriate to the context.
`107` — Selection state shall remain distinct.
`108` — Hover state shall remain distinct.
`109` — Keyboard focus state shall remain distinct.
`110` — Multi-selection membership state shall remain distinct.
`111` — Disabled state shall remain distinct.
`112` — Provisional state shall remain distinct.
`113` — Destructive state shall remain distinct.
`114` — Historical state shall remain distinct.
`115` — Stale state shall remain distinct.
`116` — Unknown state shall remain distinct.
`117` — Distinct states shall not collapse into one generic muted presentation.
`118` — Focus appearance shall follow the shared accessible-interaction contract.
`119` — Focus shall remain visible in every skin and supported appearance.
`120` — Focus shall remain distinguishable from hover and selection.
`121` — Decorative skin elements shall not obscure focus indication.
`122` — Dialog presentation shall follow the shared accessible-interaction contract.
`123` — Skin styling shall not alter modal/dialog focus behavior.
`124` — Skin styling shall not make required dialog actions unreachable or visually ambiguous.
`125` — Dialog hierarchy shall remain understandable across appearance modes.
`126` — SOMA may use terminal-inspired language or presentation accents.
`127` — SOMA may use game-inspired language or presentation accents.
`128` — Such language may strengthen hierarchy, consequence, status, or operator engagement.
`129` — Game/terminal presentation shall remain subordinate to canonical domain terminology.
`130` — A decorative label shall not replace a canonical entity name where doing so would obscure meaning.
`131` — Game-inspired language shall not reinterpret authoritative state.
`132` — Terminal-inspired visual presentation shall not fabricate operational certainty.
`133` — Decorative severity language shall not contradict governed severity/state meaning.
`134` — The underlying canonical domain value shall remain available wherever presentation terminology could otherwise introduce ambiguity.
`135` — Selected skin shall be persistable as operator presentation configuration.
`136` — Light/Dark/System appearance preference shall be persistable independently.
`137` — Changing either presentation setting shall not modify operational/domain records.
`138` — First-run selection of skin/appearance shall remain presentation configuration rather than product-data mutation.
`139` — Semantic token schema shall be versionable.
`140` — Token evolution shall preserve semantic intent across supported skins.
`141` — A skin incompatible with the active token version shall fail boundedly rather than produce undefined semantic presentation.
`142` — Skin migration shall not change domain state.
`143` — Appearance migration/default changes shall not rewrite operational records.
`144` — Every built-in skin shall be acceptance-tested in Light mode.
`145` — Every built-in skin shall be acceptance-tested in Dark mode.
`146` — Shared semantic states shall be tested under high-contrast/forced-color conditions applicable to the supported platform.
`147` — Focus, state distinction, text enlargement, zoom, and reduced-motion behavior shall be tested against the same semantic expectations across skins.
`148` — No skin may receive release acceptance while materially failing the shared accessibility/semantic-state contract.

## `BETA-REQ-0127` — prefix `UI-DRAFT`

**Governing obligation:** Every editable SOMA workflow shall keep accepted revisions, unsaved operator working copies, and persistent domain Draft states distinct, permit only clearly scoped and transactionally valid save/discard operations, preserve safe input across validation/failure and recoverable abandonment, resolve stale revisions through reviewed comparison rather than last-write-wins, limit Undo to revalidated safe inverses while using governed lifecycle correction for accepted evidence, and ensure unsaved values never affect authoritative projections or behavior.

`001` — Every editable workflow shall distinguish authoritative accepted state from unsaved UI working state.
`002` — Every editable workflow shall distinguish an unsaved UI working copy from a persistent domain entity whose accepted lifecycle state is `Draft`.
`003` — The term `Draft` as a domain lifecycle state shall not imply that the entity is unsaved.
`004` — An accepted persistent Draft entity shall have ordinary persistent identity.
`005` — Unsaved UI working state shall not become a second domain entity merely because it contains modified values.
`006` — Every editable persistent target shall have an identifiable last accepted revision or equivalent concurrency baseline.
`007` — The working copy shall identify the accepted revision from which it originated.
`008` — Saving an edit shall validate against the applicable current accepted revision.
`009` — Accepted revision identity shall remain distinct from lifecycle state.
`010` — A persistent entity may remain in lifecycle state `Draft` across several accepted revisions.
`011` — Editing shall occur against an operator working copy until an applicable save/accept action succeeds.
`012` — Working-copy values shall remain distinguishable from currently accepted values.
`013` — A working copy may contain values that have not yet passed final domain validation.
`014` — Merely typing or selecting a new value shall not constitute authoritative persistence.
`015` — UI state shall not masquerade as committed domain state.
`016` — The UI shall make modified state identifiable.
`017` — Modified fields shall be identifiable where field-level editing applies.
`018` — Modified sections shall be identifiable where section-level editing applies.
`019` — Changed-state presentation shall distinguish modified from invalid.
`020` — Changed-state presentation shall distinguish modified from stale/conflicted.
`021` — A full Save shall have an explicit scope.
`022` — Save shall attempt to persist only the governed editable scope represented by that action.
`023` — Successful Save shall create a new accepted revision or equivalent authoritative update.
`024` — Successful Save shall not silently include unrelated unsaved edits outside its stated scope.
`025` — Selective Save may be supported for individually governable fields or sections.
`026` — Selective Save shall clearly identify which modifications will be accepted.
`027` — Selective Save shall leave excluded unsaved modifications in the working copy.
`028` — Selective Save shall not accidentally discard unrelated unsaved changes.
`029` — Partial Save shall be permitted only when the selected subset forms a complete valid transaction.
`030` — Partial Save shall satisfy all required persistence invariants.
`031` — Partial Save shall satisfy all domain-dependent validation rules applicable to the selected transaction.
`032` — Partial Save shall not persist an internally inconsistent intermediate state.
`033` — SOMA shall detect when a requested selective save requires additional dependent changes.
`034` — SOMA shall not silently widen a selective-save transaction without explaining the required dependency.
`035` — When a selected change cannot stand alone, SOMA shall identify the additional field/section scope required.
`036` — The operator shall be able to review the required dependent scope before acceptance.
`037` — Discard shall have an explicit scope.
`038` — Full Discard shall restore the applicable working copy to the last accepted revision.
`039` — Discard shall not delete the persistent domain entity.
`040` — Discarding UI changes to a persistent `Draft` entity shall not cancel/delete that Draft entity.
`041` — Selective Discard may restore chosen modified fields or sections to the applicable accepted values.
`042` — Selective Discard shall not reset unrelated modified fields.
`043` — Selective Discard shall clearly identify its target scope.
`044` — Discarding dependent values shall preserve internal working-copy consistency or explain required additional discard scope.
`045` — Validation failure shall not silently discard safe operator input.
`046` — Validation failure shall leave the working copy available for correction.
`047` — Actionable validation errors shall receive focus or equivalent direct navigation.
`048` — Validation error presentation shall identify the affected field/section or dependency where possible.
`049` — Validation failure shall not create a new accepted revision.
`050` — Detection of stale accepted state shall preserve the operator's safe working copy.
`051` — Stale-data detection shall not use last-write-wins silently.
`052` — Stale-data state shall be visibly distinguishable from ordinary validation failure.
`053` — The operator shall be shown enough comparison context to resolve the conflict safely.
`054` — Permission or authorization failure shall not silently discard the operator's safe working copy.
`055` — Permission failure shall not commit partial unauthorized changes.
`056` — The UI shall expose an actionable or bounded reason for denied save where applicable.
`057` — Transaction failure shall preserve safe operator input.
`058` — Transaction failure shall not claim that changes were accepted.
`059` — Transaction rollback shall leave the last accepted domain revision unchanged.
`060` — Retry shall revalidate current accepted state before committing preserved working-copy changes.
`061` — Material edits shall not silently autosave into authoritative state.
`062` — Typing into a material field shall not automatically commit the change.
`063` — Changing a material relationship selector shall not automatically commit unless explicitly authorized by its owning requirement.
`064` — Moving between fields shall not imply authoritative acceptance.
`065` — Losing browser focus shall not imply authoritative acceptance.
`066` — An owning requirement may explicitly authorize a specific safe autosave class.
`067` — Authorization for one autosave class shall not generalize to unrelated material edits.
`068` — Autosave authority shall identify the exact affected state and safety semantics.
`069` — Unspecified material fields shall follow explicit-save semantics.
`070` — SOMA may preserve secure recoverable working copies for supported edit workflows.
`071` — A recoverable working copy shall identify its target entity or edit target.
`072` — A recoverable working copy shall identify the base accepted revision.
`073` — A recoverable working copy shall preserve working-copy chronology.
`074` — A recoverable working copy shall preserve sufficient information to determine staleness.
`075` — Recoverable working-copy persistence shall minimize sensitive data consistent with safe recovery.
`076` — Recoverable working copies shall receive protection appropriate to local SOMA operational data.
`077` — Recovery storage shall not become an unencrypted bypass around governed data protection.
`078` — Working copies shall not persist prohibited reusable secrets.
`079` — Recovery storage shall remain distinct from export/backup semantics.
`080` — Restoring a recoverable working copy shall restore editable UI state only.
`081` — Restoration shall not itself create an accepted revision.
`082` — Restored values shall remain unsaved until an applicable Save succeeds.
`083` — Restoration shall revalidate the working copy against current accepted state.
`084` — Restoration shall not bypass stale/conflict handling.
`085` — Navigation that would abandon unsaved material changes shall warn the operator.
`086` — Reload that would abandon unrecoverable unsaved material changes shall warn the operator.
`087` — Window/tab/application closure shall warn before abandoning unrecoverable material changes where technically supported.
`088` — Warning shall distinguish safe recoverable working-copy state from changes that would truly be lost where appropriate.
`089` — Abandonment confirmation shall not silently save changes.
`090` — Switching tabs within the same edit workflow shall preserve the current working copy.
`091` — Responsive pane changes within the same edit workflow shall preserve the working copy.
`092` — Opening/closing a Communication preview within the same edit flow shall preserve the working copy.
`093` — Interacting with nested controls within the same edit flow shall preserve unrelated draft changes.
`094` — Resizing/reflow shall preserve the working copy.
`095` — Same-flow UI interaction shall not generate repeated abandonment warnings unnecessarily.
`096` — A recoverable working copy based on an older accepted revision shall be recognized as stale when authoritative state has advanced.
`097` — An older working copy shall not silently overwrite newer accepted facts.
`098` — Restoring an old working copy shall not reset the target entity to its old accepted revision.
`099` — The base revision shall remain available for conflict comparison.
`100` — Concurrent/stale conflicts shall receive reviewed comparison.
`101` — SOMA shall not use unconditional last-write-wins for material edits.
`102` — Conflict review shall distinguish the base accepted value.
`103` — Conflict review shall distinguish the newer accepted value.
`104` — Conflict review shall distinguish the operator's working-copy value.
`105` — Conflict resolution shall revalidate the chosen result before commit.
`106` — Nonconflicting working-copy changes may be eligible for reviewed merge into newer accepted state.
`107` — Materially conflicting fields shall not be silently resolved from recency alone.
`108` — Merge outcome shall preserve the accepted revision/history required by the owning domain.
`109` — Exact merge UI may be defined by LLD while preserving reviewed comparison semantics.
`110` — Undo shall be offered only where a bounded safe inverse exists.
`111` — An Undo action shall identify the exact accepted action it proposes to reverse.
`112` — Undo availability shall be revalidated at invocation time.
`113` — Undo shall not execute if later dependencies make the inverse unsafe.
`114` — Undo shall remain bounded rather than reconstructing arbitrary historical state.
`115` — Successful Undo shall preserve history of the original accepted action.
`116` — Successful Undo shall preserve evidence that the inverse was later accepted.
`117` — Undo shall not physically erase audited accepted history merely to make state appear unchanged.
`118` — Accepted lifecycle evidence shall not use generic UI Undo when its owning domain requires correction.
`119` — Correction shall remain distinct from Undo.
`120` — Cancellation shall remain distinct from Undo.
`121` — Supersession shall remain distinct from Undo.
`122` — Replacement shall remain distinct from Undo.
`123` — Resend shall remain distinct from Undo.
`124` — Restoration shall remain distinct from Undo.
`125` — Unsaved working-copy values shall not affect authoritative aggregate counts.
`126` — Unsaved additions shall not increment authoritative counts.
`127` — Unsaved removals shall not decrement authoritative counts.
`128` — Unsaved values shall not alter authoritative SLA classification.
`129` — Unsaved values shall not alter authoritative SLA calculations.
`130` — Unsaved chronology edits shall not change SLA until accepted.
`131` — Unsaved values shall not suppress authoritative warnings.
`132` — Unsaved values shall not create authoritative warnings as though accepted.
`133` — Edit UI may preview validation consequences without changing authoritative warning state.
`134` — Unsaved values shall not alter authoritative Stock availability.
`135` — Unsaved scheduling values shall not reserve Objective/Task availability or time windows as though accepted.
`136` — Unsaved allocations shall not consume physical Inventory availability.
`137` — Unsaved relationship changes shall not become authoritative relationships.
`138` — An unsaved SR↔RFC relationship shall not appear as accepted outside the edit context.
`139` — An unsaved Device Reference↔Network Element reassignment shall not change authoritative Infrastructure resolution.
`140` — An unsaved Task-to-Spare-Part allocation shall not affect Inventory truth.
`141` — Unsaved identifier changes shall not enter the active Communication tracking registry.
`142` — Unsaved entity relationships shall not activate Communication Processing.
`143` — Unsaved aliases shall not become authoritative matching identities.
`144` — Communication matching shall consume accepted identity state only.
`145` — Reports shall not consume unsaved working-copy values as authoritative truth.
`146` — Dashboard projections shall not consume unsaved values.
`147` — Exported authoritative operational data shall not silently include unsaved working-copy values.
`148` — If a dedicated preview/export-of-unsaved-draft capability is ever provided, it shall be explicitly labelled as non-authoritative.
`149` — Current domain projections shall derive only from accepted facts.
`150` — Working-copy preview calculations shall remain presentation-only until Save.
`151` — Preview values shall be visually distinguishable where confusion with accepted truth is possible.
`152` — Save shall validate the target revision immediately before authoritative commit.
`153` — Save shall validate required domain invariants immediately before commit.
`154` — Successful commit shall atomically establish the accepted revision and applicable audit evidence.
`155` — Failed commit shall leave the previous accepted state authoritative.
`156` — After successful Save, saved fields shall no longer be marked unsaved.
`157` — Any deliberately excluded selective-save fields shall remain unsaved.
`158` — The working copy's base revision shall advance to the newly accepted revision after successful applicable save.
`159` — Post-save UI shall reflect the accepted domain response rather than assume every attempted value was accepted unchanged.
`160` — Other views shall continue to display the last accepted state until Save succeeds.
`161` — Opening the same entity elsewhere shall not expose another editor's unsaved working copy as accepted truth.
`162` — Shared authoritative projections shall update only after accepted mutation.
`163` — A domain entity in accepted lifecycle state `Draft` shall participate in domain rules applicable to persistent Draft entities.
`164` — Saving edits to a persistent Draft shall not necessarily transition it out of Draft.
`165` — Transition from persistent `Draft` to another lifecycle state shall require the owning domain's explicit transition authority.
`166` — Discarding unsaved edits shall not itself cancel a persistent Draft entity.
`167` — Unsaved keystrokes/field changes shall not automatically become domain audit history merely because they occurred in the UI.
`168` — Accepted Save/correction/conflict-resolution actions shall generate the applicable governed audit evidence.
`169` — Recoverable working-copy metadata shall remain distinguishable from authoritative domain audit.
`170` — Modified fields/sections shall not be identified solely by color.
`171` — Validation errors shall be associated semantically with their relevant controls.
`172` — Conflict comparison shall be keyboard operable.
`173` — Save, selective save, discard, selective discard, recovery, and conflict actions shall have accessible names.
`174` — Abandonment warnings shall be accessible and keyboard operable.
`175` — Comparable editors shall use shared Save/Discard/dirty-state semantics.
`176` — Domain editors shall not redefine `Draft`, `Unsaved`, `Saved`, or `Conflict` inconsistently.
`177` — Exact editor presentation may vary while preserving this common state model.
