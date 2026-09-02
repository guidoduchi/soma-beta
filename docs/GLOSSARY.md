# SOMA Beta Domain Glossary

This glossary is normative product language. UI copy, schemas, imports, and documentation should use these terms consistently.

| Term | Contract definition |
|---|---|
| Local User Profile | The sole authenticating local administrator profile for one SOMA installation. |
| Registered Person | A business/contact record. It is not a login account. |
| Customer Organization | The customer boundary that owns Contracts and Datacenter Sites. Equal names or city labels do not merge different organizations or physical locations. |
| Contract | A service agreement belonging to exactly one Customer Organization under which one or more Contract Product Lines and their SLA policies are configured. One Customer Organization may have multiple Contracts. |
| Product | An untrusted Advanced Search source column discarded by Beta 1.0; it cannot classify an SR or create operational relationships. |
| Product Line | A reusable service or technology classification, such as IT or NFV. It does not own SLA policy outside a Contract. |
| Contract Product Line | One occurrence of a reusable Product Line inside one Contract. It owns that Contract-specific SLA cohort policy. Different Customer Organizations may configure different policies for the same Product Line. |
| Service Request (SR) | A pivotal Ticket that connects service work, RFCs, spares, and infrastructure evidence. Official identity: exactly 8 digits; manual local identity: `LSR-` + 8 digits. |
| Request for Change (RFC) | A change Ticket that owns WFM Tasks. Official identity: `NC` + 14 digits. RFC hierarchy is exactly two levels. |
| Master RFC | An RFC that may own direct subordinate RFCs and receive direct SR/Local Task links. |
| Subordinate RFC | An RFC owned by exactly one master RFC. It cannot own another RFC or act as a master. |
| Task | A first-class unit of work with its own identity, classified as either a Local Task or WFM Task and belonging to at most one Objective. |
| Local Task | A manually registered Task whose only required user-supplied field is Task Name. It may link to zero or many SRs, master or subordinate RFCs, Spare Part Units, and Network Elements. |
| WFM Task | An externally generated Task subtype imported or registered with external identity `TK` + 14 digits; it belongs to exactly one RFC. |
| Master WFM | The WFM owned by a master RFC for an operational branch/timeframe. The role is derived, not independently assigned. |
| Subordinate WFM | A WFM owned by a subordinate RFC; its master/SR context is derived through the RFC hierarchy. |
| Objective | A Maintenance Window with one reviewed planned timeframe and at least one Task from creation. |
| Device Reference | An involved device identity used by Tickets, Tasks, and Inventory. It may resolve to Infrastructure or remain unregistered. |
| Unregistered Device Reference | A valid Device Reference not yet promoted to an Infrastructure Network Element. It remains usable throughout the workflow. |
| Spare Need | The Service-Request-level planning record aggregated by BOM across contributing Device Part Units from any relevant Device under that SR. It records description and quantity, preserves contributor links, remains reusable, and is not consumed by a request attempt. |
| Device Part Unit | One actual component installed in, removed from, or diagnosed under one Device and, when known, one slot. It owns its actual BOM, optional manufacturer serial, condition, fault state, and installation/removal history. |
| Fault Part | The operational role of a Device Part Unit that is diagnosed faulty, removed, or selected as a return candidate; it is not a second physical-unit record. |
| Stock | The Inventory view of physical Spare Part Units grouped by BOM and eligibility while retaining unit identity, condition, location, origin, reservation, and history. |
| Spare Request | A request and tracking container with immutable SOMA and temporary identities. It normally begins as a local draft from SR-level Needs, while a request prepared or submitted outside SOMA is registered into the same model through reviewed reconciliation. Draft generation never proves sending. It records requested receiver and delivery/self-pickup logistics and may later receive its official `SR` + 7 identifier. Requested quantity `N` may yield incremental `M ≤ N` C10 RMAs while pending or unfulfilled quantity remains explainable. |
| RMA | One C10 two-sided obligation under exactly one official Spare Request: first a promise of one inbound replacement and later an obligation to return one selected physical unit. It may target one Device Part Unit, link to at most one direct inbound Spare Part Unit, and reference its return unit separately. It is neither a quantity container nor a physical unit. |
| Fault Tag | An identified physical-return attempt containing independently identified memberships for open RMA return obligations and their selected physical units. It may span different Service Requests and Spare Requests and preserves submission, pickup-origin, warehouse, correction-replacement, resend, and archival history. |
| Fault Tag membership | An immutable relationship within one Fault Tag referencing exactly one open RMA return obligation and exactly one selected physical return unit. Ticket and Device context is derived rather than independently copied. |
| Fault Tag correction replacement | A new Fault Tag with new identities that supersedes one materially wrong actual submission through linear `corrects/replaces` lineage. It is distinct from an operational resend. |
| Fault Tag resend | A later return attempt following genuine warehouse rejection, linked through `resend of` lineage and carrying its own submission and pickup-origin snapshot. |
| Part Number / BOM code | The catalog, compatibility, and inventory grouping identifier for a type of component. |
| Spare Part Unit | One physical Inventory component tracked by immutable SOMA identity, BOM, optional manufacturer serial, condition, location, and lifecycle. It may have zero or one origin RMA and remains distinct from Device Part Units, RMA obligations, and return relationships. |
| Submission-logistics snapshot | Immutable evidence of the requested delivery or self-pickup mode, intended receiver, dispatch or pickup location, effective address, and recipient context accepted with a Spare Request submission. It is intent, not proof of dispatch or receipt. |
| Actual logistics event | An append-oriented record of dispatch, pickup, delivery, receipt, location, custody, receiver, chronology, or observed condition. One event may cover several RMAs or units while each participant remains independently addressable. |
| Inventory correction | An append-only decision targeting one exact accepted lifecycle event or relationship. It preserves the original evidence and entity identities while recalculating the current projection. A genuine later rejection or resend is new history, not a correction. |
| Infrastructure | Installed organizational, physical, device, and component structure plus its history. |
| Cloud Type | A reusable logical platform classification such as PRV, B2B, AMS, BES, or NFV. The same type may be deployed at many Sites. |
| Cloud Deployment | One occurrence of a Cloud Type at exactly one Site. It is distinct from deployments of the same type at other Sites. |
| Site | One physical Datacenter belonging to exactly one Customer Organization. Site names and city codes may repeat across organizations, but each physical location is a distinct Site and automatically has one exclusive Dispatch Location. |
| Dispatch Location | A reusable physical logistics address whose role is operation-specific. A Spare Request may use it for delivery or self-pickup; a Fault Tag may use it as the pickup origin from which return units are dispatched or collected. The pickup origin is not the warehouse destination. A site-bound location inherits the Site address. |
| Network Element Model | A reusable device type/model definition. |
| Network Element | A registered device instance with immutable SOMA identity, nonblank operational name, and one physical Site. Model, serial, precise placement, Cloud Deployment, and IP inventory may be completed progressively. |
| Network Element IP Address | An optional stored address belonging to one Network Element. It is descriptive inventory and matching evidence, not relational identity or proof of connectivity. One address per Network Element may be primary. |
| Compound containment | The acyclic parent/child forest among Network Elements or compound sub-elements, distinct from physical placement, Component installation, and connectivity. |
| Component | A BOM-compatible or historically installed part associated with a Network Element or compound sub-element. |
| Infrastructure Workbook | A versioned SOMA-generated `.xlsx` family used for empty device registration, human-readable current-device discovery export, and reviewed round-trip updates. Import identities are authoritative only within their source installation. |
| Population | Updating source-owned fields on an identity-matched record while preserving SOMA-owned meaning and history. |
| Import Review | Operator acceptance, rejection, or conflict resolution for proposed source changes. |
| Workbench | The focused split ticket view with a tabbed working area and local communication-evidence preview. |
| Historical View | The retained view for records outside the configured Daily, Weekly, or Monthly main period. |
| SLA Cohort Tier | A Contract Product Line rule requiring a percentage of eligible SRs of one severity to resolve or close within an inclusive duration. |
| SLA Result | A derived individual-duration or cohort-compliance result calculated from Contract Product Line policy, severity, effective Report Date, suspension, endpoint, and reporting-period facts. |

## Identifier rules

| Record | Official format | Local identity allowed? |
|---|---:|---|
| Service Request | 8 digits | `LSR-` + 8 digits, starting locally at `LSR-00000001`; later official mapping is explicit and reviewed |
| Request for Change | `NC` + 14 digits | Provisional RFC may be created by manual WFM registration |
| WFM Task | `TK` + 14 digits | No; a manual task without this identity is a Local Task |
| Spare Request | `SR` + 7 digits when assigned externally | Always originates with an immutable SOMA temporary tracking identifier; the official identifier is attached later without replacing it |
| RMA | `C` + 10 digits | The business identifier belongs to the obligation record; target, inbound, return, and physical-unit identities remain separate |
| Spare Part Unit | Manufacturer serial when available | `LSU-` + 8 digits, starting locally at `LSU-00000001`; official Spare Request and RMA references are optional |
| Local Task | SOMA-generated | Always generated; never inherited from its Objective |

Identity is not a mutable descriptive field. Corrections use explicit reconciliation so references and audit history remain intelligible.
