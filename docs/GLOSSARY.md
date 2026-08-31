# SOMA Beta Domain Glossary

This glossary is normative product language. UI copy, schemas, imports, and documentation should use these terms consistently.

| Term | Contract definition |
|---|---|
| Local User Profile | The sole authenticating local administrator profile for one SOMA installation. |
| Registered Person | A business/contact record. It is not a login account. |
| Customer Organization | The customer boundary that owns Product Lines and Clouds. |
| Product | Descriptive source text on operational records; it never silently selects a Product Line. |
| Product Line | Operator-controlled classification within one Customer Organization that selects the SLA policy. |
| Service Request (SR) | A pivotal Ticket that connects service work, RFCs, spares, and infrastructure evidence. Official identity: exactly 8 digits; manual local identity: `LSR-` + 8 digits. |
| Request for Change (RFC) | A change Ticket that owns WFM Tasks. Official identity: `NC` + 14 digits. RFC hierarchy is exactly two levels. |
| Master RFC | An RFC that may own direct subordinate RFCs and receive direct SR/Local Task links. |
| Subordinate RFC | An RFC owned by exactly one master RFC. It cannot own another RFC or act as a master. |
| Task | A first-class unit of work with its own identity, classified as either a Local Task or WFM Task and belonging to at most one Objective. |
| Local Task | A manually registered Task whose only required user-supplied field is Task Name. It may link to zero or many SRs, master or subordinate RFCs, Spare Part Units, and Network Elements. |
| WFM Task | A Huawei-generated Task subtype imported or registered with external identity `TK` + 14 digits; it belongs to exactly one RFC. |
| Master WFM | The WFM owned by a master RFC for an operational branch/timeframe. The role is derived, not independently assigned. |
| Subordinate WFM | A WFM owned by a subordinate RFC; its master/SR context is derived through the RFC hierarchy. |
| Objective | A Maintenance Window with one reviewed planned timeframe and at least one Task from creation. |
| Device Reference | An involved device identity used by Tickets, Tasks, and Inventory. It may resolve to Infrastructure or remain unregistered. |
| Unregistered Device Reference | A valid Device Reference not yet promoted to an Infrastructure Network Element. It remains usable throughout the workflow. |
| Spare Need | The device-level planning step before a Spare Request, always linked to one open or registered SR and recording BOM, description, and quantity. It remains reusable. |
| Fault Part | The actual failed or removed device component. It may differ from the Spare Need and may link to zero or one received replacement unit. |
| Stock | The Inventory view of physical Spare Part Units grouped by BOM and state while retaining unit serial/history. |
| Spare Request | The official `SR` + 7 logistics request linked to one Service Request. Requested quantity `N` may yield `M ≤ N` accepted C10 RMA positions; every rejected/unfulfilled position retains a reason. |
| RMA | One accepted ordered BOM position within exactly one Spare Request. Identity: `C` + 10 digits. It is not a quantity container and becomes associated with exactly one received physical unit at receipt. |
| Fault Tag | The return-lifecycle record grouping physical units for pickup, warehouse confirmation, and terminal closure. |
| Part Number / BOM code | The catalog, compatibility, and inventory grouping identifier for a type of component. |
| Spare Part Unit | One physical component tracked by immutable SOMA local identity, BOM, condition, location, and lifecycle history; manufacturer serial is optional. |
| Infrastructure | Installed organizational, physical, device, and component structure plus its history. |
| Cloud | A logical platform belonging to a Customer Organization that may span Sites. |
| Site | A customer-neutral physical datacenter. It may host Clouds from multiple Customer Organizations and automatically has one exclusive Dispatch Location. |
| Dispatch Location | A physical logistics address. A standalone location owns its address; a site-bound location inherits the Site address. |
| Network Element Model | A reusable device type/model definition. |
| Network Element | A specific device instance whose components may differ from other instances of the same model. |
| Component | A BOM-compatible or historically installed part associated with a Network Element or compound sub-element. |
| Population | Updating source-owned fields on an identity-matched record while preserving SOMA-owned meaning and history. |
| Import Review | Operator acceptance, rejection, or conflict resolution for proposed source changes. |
| Workbench | The focused split ticket view with a tabbed working area and local communication-evidence preview. |
| Historical View | The retained view for records outside the configured Daily, Weekly, or Monthly main period. |
| SLA State | A derived status calculated from Product Line policy, severity, effective Report Date, suspension, and endpoint facts. |

## Identifier rules

| Record | Official format | Local identity allowed? |
|---|---:|---|
| Service Request | 8 digits | `LSR-` + 8 digits, starting locally at `LSR-00000001`; later official mapping is explicit and reviewed |
| Request for Change | `NC` + 14 digits | Provisional RFC may be created by manual WFM registration |
| WFM Task | `TK` + 14 digits | No; a manual task without this identity is a Local Task |
| Spare Request | `SR` + 7 digits | Inventory records may otherwise be registered manually, but are not official Spare Requests |
| RMA | `C` + 10 digits | No official RMA without its external identity |
| Local Task | SOMA-generated | Always generated; never inherited from its Objective |

Identity is not a mutable descriptive field. Corrections use explicit reconciliation so references and audit history remain intelligible.
