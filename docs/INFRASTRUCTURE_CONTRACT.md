# SOMA Beta Infrastructure Contract

Status: **Foundation review v0.1**  
Target: **SOMA Beta 1.0.0**, with explicit 1.x connectivity/SSH deferrals  
Authority: `BETA-REQ-0102`–`0110`, Decisions D-076–D-084, and confirmed product-owner Infrastructure workbook decision.

## 1. Purpose

This contract defines canonical Infrastructure terminology, identity, placement, IP inventory, containment, Cloud assignment, credential exclusion, persistence authority, and the SOMA-generated workbook exchange. It is normative for Product, use-case, HLD, LLD, UI, import/export, and acceptance work.

## 2. Canonical terminology and boundaries

- **Infrastructure** is the top-level workspace. `Device Manager` is not a canonical workspace name.
- **Managed Element** is retired as a Beta domain type. Legacy labels may be mapped for source/history only.
- **Device Reference** is an operationally involved device identity used across Tickets, Tasks, Objectives, and Inventory. It may remain unregistered/external.
- **Network Element** is one registered Infrastructure device instance.
- **Network Element Model** is reusable across instances and customers.
- **Component** is a BOM-compatible or historically installed physical part, not another spelling of a Network Element.
- **Cloud Type** is reusable logical classification. **Cloud Deployment** is one Site-bound occurrence.
- Containment, physical placement, Cloud assignment, IP inventory, Component installation, and connectivity are independent relationship families.

## 3. Device Reference promotion and Network Element identity

- A Device Reference remains valid through the full supported operational workflow without Infrastructure registration.
- Deliberate three-second pointer/touch/keyboard promotion creates or links exactly one Network Element and preserves/repoints existing relationships transactionally.
- Promotion cannot duplicate the operational device or infer equality solely from name, serial, IP, Model, Site, or other descriptive values.
- Every Network Element has immutable opaque internal identity, nonblank operational name, and exactly one physical Site.
- Model, serial, Rack/U, Cloud Deployment, IP addresses, containment, and other optional facts may be completed progressively.
- Manufacturer serial and every imported/exported descriptive value are evidence and matching candidates, not relational identity.

## 4. Physical placement, Models, Notes, Components, and history

- A Site belongs to one Customer Organization; Network Element ownership derives through Site.
- A Network Element may be site-level/unracked, placed in exactly one Rack belonging to its Site, or participate in compatible compound containment.
- Rack implies its Room and Site. Contradictory independently selected Site/Room/Rack facts are invalid.
- Rack-unit position is optional unless the applicable placement requires it; represented position must satisfy range and occupancy rules assigned to the LLD.
- Model is an optional relationship to one reusable Network Element Model, never competing free text.
- Notes use the standard historically preserved Notes capability rather than a destructively overwritten blob.
- Devices of the same Model may have different Components.
- Model/BOM compatibility and actual per-instance installation history are distinct. Installation/replacement events preserve unit identity, slot/position, chronology, applicable SR/Objective/Task, and correction history.

## 5. IP-address inventory

- One Network Element may have zero or many stored IP addresses and at most one accepted primary.
- No Device Reference, Network Element, Cloud Type, Cloud Deployment, or organizational/logical record is required to have an IP address.
- SOMA never fabricates an address.
- IP is optional descriptive inventory and candidate matching evidence, not primary/foreign identity.
- IP inventory in 1.0 does not create interfaces, ports, discovery, reachability, connectivity, topology, or SSH.
- Normalization, IPv4/IPv6 validation, duplicate scopes, primary reassignment, chronology, and correction behavior belong in the LLD and acceptance scenarios without weakening these product rules.

## 6. Compound containment

- Network Element/compound-sub-element containment is an acyclic parent/child forest.
- One parent may contain zero-many children; each child has at most one direct parent.
- Self-containment, direct cycles, indirect cycles, and multiple direct parents are invalid.
- Containment is distinct from Site/Room/Rack placement, Cloud assignment, Model/Component compatibility, and connectivity.
- Accepted movement/correction preserves prior relationship history and cannot silently rewrite operational evidence.

## 7. Cloud Type and Cloud Deployment

- One Cloud Type may appear at many Sites.
- One Site may contain many Cloud Deployments.
- Each Cloud Deployment belongs to exactly one Cloud Type and exactly one Site.
- A Network Element may use at most one Cloud Deployment, and it must belong to the Network Element's Site.
- Direct Network-Element-to-Cloud-Type assignment does not substitute for a Deployment.
- Cross-Site Deployment assignment is invalid.
- Unregistered/external Device References require no Site, Cloud Type, Deployment, or Customer Organization.

## 8. Connectivity/topology boundary

- Connectivity never derives from shared Site/Rack, Cloud Deployment, address/subnet pattern, Model, Ticket/Task/Objective, communication, workbook batch, or containment.
- Beta 1.0 exposes no canonical connectivity edge, interface/port topology, automated discovery, path calculation, reachability, or SSH.
- Structured connectivity is deferred to 1.x.0.
- A future accepted edge preserves immutable relationship identity, exact endpoints, physical/logical type, direction when meaningful, interfaces/ports when known, provenance, recording chronology, independently known effective interval, reviewed confidence/verification, and targeted correction.
- Unknown endpoints, ports, direction, or times remain unknown. A future projection cannot rewrite placement, containment, Cloud assignment, IP inventory, or source evidence.

## 9. Credential and secret exclusion

- Passwords, private keys, tokens, recovery codes, and reusable authentication secrets never enter ordinary domain tables, Device/IP fields, Notes, evidence, audit payloads, logs, imports, or exports.
- Beta 1.0 exposes no device username/password/credential controls.
- A future accepted capability may store only an opaque reference to an approved external or operating-system provider plus strictly non-secret resolution metadata.
- A reference never contains or reversibly encodes the credential.
- Missing, inaccessible, invalid, or revoked references produce a bounded unavailable state and never prompt ordinary persistence of the secret.
- Local authentication, encryption keys, and backup recovery remain governed by separate security contracts.

## 10. SQLite authority and possible graph projection

- SQLite is authoritative for every 1.0 Infrastructure entity, relationship, invariant, event, projection, import decision, and audit record.
- All Infrastructure behavior is enforceable and queryable without a graph database or separately administered server.
- Graph shape alone is not justification for another database.
- A later graph engine requires representative measurements demonstrating an accepted need not adequately met by reviewed SQLite schema, constraints, indexes, recursive queries, and services.
- Any graph is derived, rebuildable, versioned, disposable, and owns no unique facts.
- It accepts no independent authoritative writes and cannot weaken relational constraints.
- Absence, failure, or staleness of the graph never blocks authoritative operation or changes meaning.

## 11. SOMA-generated workbook family

SOMA generates one versioned, macro-free `.xlsx` family:

1. **Empty registration template** — operator populates new devices.
2. **Current-device discovery export** — human-readable inventory that others can inspect in ordinary spreadsheet software without SOMA.
3. **Round-trip update export** — current records plus stable same-installation targeting data for reviewed bulk updates.

Every generated workbook declares its version, mode, source-installation scope, generation chronology, and export filter/scope. Export never mutates Infrastructure.

## 12. Import directory and export destination

- Settings owns exactly one configurable Infrastructure Import Directory.
- **Check now** discovers supported SOMA workbooks only in that directory.
- Discovery is nonrecursive and never falls back to broader filesystem scanning.
- Exports are written to an operator-selected destination and may be shared independently.
- SOMA never automatically deletes, renames, moves, overwrites, or edits operator workbooks.
- Inaccessible directories and locked/corrupt/unsupported files produce bounded errors.

## 13. Workbook data boundary

The workbook may represent current Network Element name, Model, serial, Site, same-Site Cloud Deployment, Room/Rack/U, zero-many IP addresses and primary selection, compound parent, and permitted notes/import comments.

It contains no credential, secret, opaque credential-provider reference, interface/port, connectivity edge, topology, path, discovery result, or reachability fact. Co-occurrence in a workbook establishes no relationship beyond explicitly represented and validated supported fields.

Exact sheets, headers, types, cell limits, formula policy, validation lists, and template-version migration belong in the LLD. They must remain deterministic, documented, dependency-auditable, and usable with sanitized fixtures.

## 14. Import identity, staging, review, and transaction

- A valid same-installation round-trip identity may target exactly one existing record/relationship.
- Foreign-installation identities are bounded provenance and candidate evidence only. They never authorize overwrite of a local record.
- Names, hostnames, serials, Models, IPs, and labels never prove identity.
- New accepted records receive new immutable local identity.
- Unknown related master data requires explicit resolution or reviewed creation; it is never silently invented.
- Parsing changes no domain state and produces a review separating creations, updates, unchanged rows, ambiguity/duplicates, unknown references, invalid relationships, skips, and warnings.
- Site/Rack/Cloud/primary-IP/containment/archival/dependency invariants use the same application services as manual actions.
- Material placement, Cloud, containment, identity, or relationship change is independently visible.
- Acceptance commits the reviewed batch transactionally or rolls it back.
- Identical accepted content is idempotent.

## 15. Nondestructive absence, blank, and provenance rules

- Missing rows never mean deletion, archival, movement, unlinking, clearing, or disappearance.
- Blank/unusable optional cells preserve prior valid values unless a future explicit clearing operation is accepted.
- Unsupported/invalid rows cannot partially mutate their targets.
- SOMA retains bounded workbook/content identity, version, source-installation scope, row decisions, actor, chronology, results, and warnings—not unnecessary full copies or secrets.
- Exported discovery content is a point-in-time snapshot, not live truth, authority over another installation, or proof of network reachability.

## 16. Required use cases and acceptance coverage

Before 1.0 release, accepted use cases, responsive UI states, LLD contracts, and automated scenarios cover:

- generate each workbook mode;
- choose export scope and open the result outside SOMA;
- configure/validate import-directory access and Check now;
- create, update, unchanged, ambiguous, duplicate, unknown-reference, cross-Site, invalid-Rack/U, multiple-primary-IP, and containment-cycle rows;
- same-installation round-trip and foreign-installation import;
- mixed valid/invalid batches and transactional rollback;
- idempotent replay;
- blank/missing nondestructive behavior;
- locked/corrupt/unsupported files;
- credential/topology column rejection;
- source-file preservation and import/export history; and
- accessible review, keyboard/pointer operation, responsive layouts, empty/loading/error states.

## 17. LLD responsibilities

LLD defines exact normalized schema, constraints/indexes, Network Element name/serial/IP candidate matching, Site/Model/Rack/Deployment resolution, U occupancy, containment cycle checks, workbook sheets/headers/versioning, installation-scope token, formulas/macros policy, file stabilization, fingerprints, import limits, concurrency, transaction/idempotency keys, errors, export filters, and sanitized golden fixtures. Those choices may not weaken this contract.
