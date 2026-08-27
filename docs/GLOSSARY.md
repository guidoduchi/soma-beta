# SOMA Beta Domain Glossary

This glossary is normative product language. UI copy, schemas, imports, and documentation should use these terms consistently.

| Term | Contract definition |
|---|---|
| Local User Profile | The sole authenticating local administrator profile for one SOMA installation. |
| Registered Person | A business/contact record. It is not a login account. |
| Customer Organization | The customer boundary that owns Product Lines and Clouds. |
| Product | Descriptive source text on operational records; it never silently selects a Product Line. |
| Product Line | Operator-controlled classification within one Customer Organization that selects the SLA policy. |
| Service Request (SR) | A pivotal Ticket that connects service work, RFCs, spares, and infrastructure evidence. Official identity: exactly 8 digits. |
| Request for Change (RFC) | A change Ticket that owns WFM Tasks and may participate in master/subordinate structure. Official identity: `NC` + 14 digits. |
| Task | A first-class unit of work with its own identity, optionally linked to Tickets, Inventory, Infrastructure, and at most one Objective. |
| Local Task | A manually registered Task. Task Name is its only required user-supplied field. It is not a WFM. |
| WFM Task | A Huawei-generated Task subtype imported or registered with external identity `TK` + 14 digits; it belongs to exactly one RFC. |
| Objective | A Maintenance Window with one reviewed timeframe and one or more Tasks when non-draft. |
| Spare Need | A need for a replacement/part, always linked to an open or registered Service Request. |
| Spare Request | The logistics order grouping one or more RMAs. Official identity: `SR` + 7 digits; always linked to a Service Request. |
| RMA | One ordered BOM position within exactly one Spare Request. Identity: `C` + 10 digits. It becomes associated with exactly one received serial at receipt. |
| Part Number / BOM code | The catalog, compatibility, and inventory grouping identifier for a type of component. |
| Spare Part Unit | One physical component tracked by serial number, condition, location, and lifecycle history. |
| Infrastructure | Installed organizational, physical, device, and component structure plus its history. |
| Cloud | A logical platform belonging to a Customer Organization that may span Sites. |
| Site | A datacenter. It may host multiple Clouds and automatically has one exclusive Dispatch Location. |
| Dispatch Location | A physical logistics address. A standalone location owns its address; a site-bound location inherits the Site address. |
| Network Element Model | A reusable device type/model definition. |
| Network Element | A specific device instance whose components may differ from other instances of the same model. |
| Component | A BOM-compatible or historically installed part associated with a Network Element or compound sub-element. |
| Population | Updating source-owned fields on an identity-matched record while preserving SOMA-owned meaning and history. |
| Import Review | Operator acceptance, rejection, or conflict resolution for proposed source changes. |
| SLA State | A derived status calculated from Product Line policy, severity, effective Report Date, suspension, and endpoint facts. |

## Identifier rules

| Record | Official format | Local identity allowed? |
|---|---:|---|
| Service Request | 8 digits | Yes; later mapping to an official ID is explicit and reviewed |
| Request for Change | `NC` + 14 digits | Provisional RFC may be created by manual WFM registration |
| WFM Task | `TK` + 14 digits | No; a manual task without this identity is a Local Task |
| Spare Request | `SR` + 7 digits | Inventory records may otherwise be registered manually, but are not official Spare Requests |
| RMA | `C` + 10 digits | No official RMA without its external identity |
| Local Task | SOMA-generated | Always generated; never inherited from its Objective |

Identity is not a mutable descriptive field. Corrections use explicit reconciliation so references and audit history remain intelligible.
