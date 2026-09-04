# P1A-W5 — Infrastructure Use Cases

Status: **Draft catalogue; UC-053..UC-061 pending owner review**

## UC-053 — Create a Site and its dedicated Dispatch Location
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Register one physical Datacenter Site under one Customer Organization with its required dedicated Dispatch Location.
- **Trigger/preconditions:** Customer Organization exists; new Site is needed.
- **Main flow:** create Site with immutable identity and one Customer owner; capture current physical address; create/link exactly one dedicated Dispatch Location in the governed Site operation; derive the location's current address from the Site.
- **Alternates/failures:** equal Site names/city codes across Customers remain distinct; ordinary editing cannot transfer Site ownership once protected history exists; Dispatch Location itself does not become customer-owned.
- **Postconditions/evidence:** Site + dedicated location identities/history and valid Customer relationship.
- **Authority:** `BETA-REQ-0023..0027`, `0033..0034`, Infrastructure Contract.

## UC-054 — Manage Cloud Types and site-bound Cloud Deployments
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Reuse a Cloud Type across Sites through distinct Cloud Deployments without copying conflicting ownership truth.
- **Trigger/preconditions:** Site exists; Cloud context needed.
- **Main flow:** create/select reusable Cloud Type; create Cloud Deployment bound to exactly one Site; maintain allowed metadata; assign eligible Network Elements through the Deployment.
- **Alternates/failures:** same Cloud Type may appear at many Sites; NE Cloud Deployment must belong to the NE physical Site; archive/reactivation respects active dependencies.
- **Postconditions/evidence:** stable Cloud Type/Deployment identities and relationships.
- **Authority:** `BETA-REQ-0027`, `0076..0080`, `0103..0110`.

## UC-055 — Manage Rooms and Racks within a Site
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Maintain the physical placement hierarchy used by registered Network Elements.
- **Trigger/preconditions:** Site exists.
- **Main flow:** create/manage Room; create/manage Rack/row/column context under valid Site hierarchy; use placement references for Network Elements; archive/reactivate when safe.
- **Alternates/failures:** hierarchy cannot contradict owning Site; archival cannot strand active placed elements/operational dependencies; placement history remains interpretable.
- **Postconditions/evidence:** stable physical-location reference hierarchy.
- **Authority:** `BETA-REQ-0027`, `0033`, `0077`, Infrastructure Contract.

## UC-056 — Promote an unregistered Device Reference into a new Network Element
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Regularize an operational Device Reference by creating a new registered Network Element without duplicating or replacing the Device Reference identity/history.
- **Trigger/preconditions:** Device Reference exists and is not resolved to a Network Element; operator chooses promotion.
- **Main flow:** inspect current Device Reference and relationships; invoke mandatory deliberate three-second hold; provide minimum required NE registration facts including Site/name; revalidate; create new NE; resolve Device Reference to that NE while preserving existing operational links/history.
- **Alternates/failures:** cancelled/interrupted hold creates nothing; existing matching NE should use resolution flow instead; historical ticket/device evidence is not rewritten.
- **Postconditions/evidence:** one new NE plus persistent Device Reference→NE resolution relation and promotion audit.
- **Authority:** `BETA-REQ-0049`, `0076..0078`, `0110`, UI/Infrastructure contracts.

## UC-057 — Resolve a Device Reference to an existing Network Element
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Regularize an unregistered operational Device Reference against an already existing Network Element without creating a duplicate.
- **Trigger/preconditions:** Device Reference and compatible target NE exist.
- **Main flow:** select Device Reference; search/choose exact existing NE; review identity/context/relationship impact; confirm resolution; preserve all valid historical relationships and bind the reference to exactly one NE.
- **Alternates/failures:** weak name/IP/model similarity never silently resolves identity; resolution after SR terminal state is still allowed and does not reopen ticket; no generic history repointing.
- **Postconditions/evidence:** stable reference and NE identities with one accepted resolution relation.
- **Authority:** `BETA-REQ-0049`, `0076`, `0110`.

## UC-058 — Maintain Network Element facts, IP inventory, placement, containment, and components
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Progressively complete a registered Network Element's descriptive/physical structure while preserving distinct ownership dimensions.
- **Trigger/preconditions:** Registered NE exists.
- **Main flow:** maintain model/serial/name; manage zero-many IPs with max one primary; place in Site/Room/Rack/U; assign Site-compatible Cloud Deployment; maintain acyclic compound containment; manage component/BOM installation history.
- **Alternates/failures:** IP is descriptive/matching evidence, not identity/connectivity; placement ≠ containment ≠ Cloud ≠ components; containment cycles prohibited; topology/interfaces/SSH unavailable in 1.0; derived Customer/Cloud truth is not independently copied/editable.
- **Postconditions/evidence:** current NE projection plus append-oriented placement/component/history.
- **Authority:** `BETA-REQ-0076..0080`, `0103..0110`; Infrastructure Contract.

## UC-059 — Export a versioned Infrastructure workbook
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Produce an approved Infrastructure workbook for empty registration, discovery/readable current-device export, or round-trip update without making the file authoritative by itself.
- **Trigger/preconditions:** Operator requests supported export.
- **Main flow:** choose supported workbook purpose/scope; generate versioned structure with installation identity/provenance as required; include current governed Infrastructure facts; verify artifact; present/export.
- **Alternates/failures:** export failure changes no Infrastructure state; workbook does not create external authority over SOMA; sensitive/unsupported topology/credential data excluded.
- **Postconditions/evidence:** verified export artifact plus export history.
- **Authority:** `BETA-REQ-0103..0110`, `0137..0139`; Infrastructure/Runtime contracts.

## UC-060 — Import and reconcile an Infrastructure workbook
Status: **Draft — pending owner review**
- **Actor:** Local Administrator / System.
- **Goal:** Safely apply reviewed workbook changes to Infrastructure while preserving installation-scoped identity and nondestructive absence behavior.
- **Trigger/preconditions:** Versioned Infrastructure workbook discovered from configured source directory or selected through supported workflow.
- **Main flow:** validate version/installation/source structure; match exact records; stage every mutation with diffs; classify ambiguity/foreign installation/duplicates/malformed rows; review/accept safe scope; apply accepted changes transactionally.
- **Alternates/failures:** absence is nondestructive; foreign-installation identity cannot silently update local records; ambiguity remains review; malformed/modified files fail safely; workbook never overrides protected hierarchy/history by similarity.
- **Postconditions/evidence:** accepted Infrastructure changes plus import/review/provenance history.
- **Authority:** `BETA-REQ-0103..0110`, `0137`, Infrastructure Contract.

## UC-061 — Archive or reactivate Infrastructure references safely
Status: **Draft — pending owner review**
- **Actor:** Local Administrator.
- **Goal:** Remove eligible Infrastructure/reference entities from active selection while preserving historical interpretation and preventing stranded dependencies.
- **Trigger/preconditions:** Site/Dispatch/Cloud/Room/Rack/NE/reference record is eligible for lifecycle action.
- **Main flow:** choose archive/reactivate; inspect active dependencies; block unsafe archival; accept eligible transition; preserve historical links and make archived records unavailable for new active relationships unless lifecycle explicitly permits.
- **Alternates/failures:** active Site-linked Dispatch Location cannot be independently archived; active Tasks/Objectives/logistics/placements block applicable archival; reactivation is deliberate and preserves identity/history.
- **Postconditions/evidence:** correct active/archive state and history.
- **Authority:** `BETA-REQ-0025`, `0033..0034`, `0076..0080`, Infrastructure Contract.
