# SOMA Beta Inventory Lifecycle Contract

Status: **Foundation review v0.3**  
Target: **SOMA Beta 1.0.0**

## 1. Operational chain

The principal chain is:

**Service Request → involved device reference → Spare Need → Spare Request → RMA position → received Spare Part Unit → installation/return outcome → Fault Tag**

Not every workflow uses every step. Manual Stock units, unregistered device references, and manually confirmed installation are valid under the warnings defined here.

## 2. Device references, Spare Needs, and Fault Parts

- An SR may have multiple involved device references.
- A reference may resolve to an Infrastructure Network Element or remain unregistered throughout the workflow.
- Each involved device may have zero or more Spare Needs and zero or more Fault Parts.
- A Spare Need is the planning step before a Spare Request. It belongs to one SR and one involved device and records BOM/Part Number, description, and quantity.
- A Fault Part represents the actual removed or diagnosed device component. It may be prefilled from a Spare Need, but the link is optional because the actual failed part may differ from the requested one.
- The original Spare Need is preserved when the actual Fault Part has a different BOM; SOMA records the reviewed discrepancy rather than rewriting history.

## 3. Spare Need and Spare Request cardinality

- A single Spare Request may use one or more Spare Needs, but all selected Needs must belong to the same SR.
- A Spare Need may feed zero or many Spare Requests and remains eligible after its first use.
- The workbench shows previous requests and compares planned, already requested, accepted, and remaining quantities.
- Submitted quantities may differ from Need quantities only after a warning and explicit confirmation.
- A Spare Need with no request history may be removed under the normal audited manual-record rule.
- Once linked to a Spare Request, it cannot be removed while any associated request remains active or otherwise nonrejected.
- Removal becomes available only when every associated request relevant to that Need has been explicitly confirmed by the operator as cancelled or rejected. The UI previews consequences and preserves the cancelled/rejected request evidence and the Need's prior values in audit history.

## 4. Spare Requests and RMA positions

- Every Spare Request originates locally from one or more selected Spare Needs and immediately receives an immutable, non-reusable temporary tracking identity.
- All selected Needs must belong to the same registered Service Request; the Spare Request derives and retains exactly that one SR relationship even when the Service Request currently has only an `LSR-########` identity.
- Huawei may later assign the official Spare Request identity, `SR` followed by seven digits, to the existing request. This never replaces its internal identity or temporary tracking identity.
- A requested quantity `N` may yield `M` C10 RMA positions where `M ≤ N`.
- Every missing position records a reviewed rejection/unfulfilled outcome such as EOS, unavailable, incompatible, or another explicit status.
- One RMA identity is `C` followed by ten digits, belongs to exactly one Spare Request, and represents one accepted ordered position.
- An RMA has one requested BOM and, after receipt, exactly one received physical unit. The actual received BOM may differ and is recorded separately.
- Before receipt an RMA has no received serial. On receipt, the resulting unit normally arrives with condition `new`.
- A locally registered Spare Part Unit may optionally record the official parent Spare Request and RMA from which it originated.

## 5. Physical identity and components without serial labels

Every Spare Part Unit has a SOMA-generated immutable local physical-unit identity. Manufacturer serial number is authoritative when available but is not mandatory, because components such as CPUs may have no serial label.

Units without manufacturer serials remain individually traceable through their local identity, BOM, origin, device/slot installation events, removal events, and disposition. SOMA never fabricates a serial value.

## 6. Replacement linkage

- A Fault Part may link to zero or one received Spare Part Unit.
- A received Spare Part Unit may link to zero or one Fault Part as its direct replacement counterpart.
- The one-to-one link records which actual component was replaced by which actual received unit, on which device and, when known, slot.
- Installation/removal is recorded per device even when the received item was a larger assembly that was dismantled into subcomponents.
- Extracted subcomponents are registered as individual local Spare Part Units. Each can record its parent Spare Request and RMA and can be installed against a device Fault Part independently.

## 7. Reviewed receipt and maintenance outcomes

| Scenario | Required Beta behavior |
|---|---|
| Requested unit arrives as needed | Record actual BOM/serial or local identity, then install or retain in Stock |
| Different but valid compatible unit arrives | Preserve requested BOM; record actual BOM and operator compatibility acceptance before use |
| Different invalid unit arrives | Quarantine/reject it, prevent installation, and preserve return evidence |
| Removed site part differs from original Need | Register the actual Fault Part and discrepancy; do not rewrite the Need |
| Mixed result across positions | Review and resolve every RMA position independently |
| Received unit is unused | Return the same unit as `new`; no Fault Part replacement link exists |
| Request is cancelled/rejected, including EOS | Preserve the terminal request/position reasons; no missing RMA is fabricated |
| Received assembly is dismantled/scrapped | Register extracted components individually; the parent assembly is dispositioned as dismantled/scrapped and returned as faulty under its own identity |

For a normal replacement, the received unit becomes installed and the linked Fault Part becomes the unit returned as faulty. Its return serial is the actual removed serial when available; otherwise SOMA records an unknown serial with a reason.

For an unused return, rejected incompatible unit, dead-on-arrival unit, or dismantled parent assembly, the returned unit is the received unit itself, so its return serial—when it has one—is the received serial. Lack of a serial uses the immutable local unit identity; it never causes a copied or invented serial.

## 8. Confirmation warning

Creating and managing a Spare Request does not require its requester or related Contacts to already have email or phone data. Generating a Spare Request `.msg` draft validates a usable recipient address just in time and may collect the missing address or use another eligible Contact. Missing recipient data blocks only draft generation and does not invalidate the Spare Request or its Needs. The generated artifact/evidence preserves the recipient identity and address used at creation.

After outgoing Spare Request communication has verifiable sent evidence, SOMA expects a confirmation response. If no matching response evidence has been indexed or manually registered within **24 hours**, the request becomes a Needs Attention warning. Generating an MSG draft alone does not start this timer because it is not evidence of sending.

## 9. Fault Tags

- A Fault Tag uses the resolved return/disposition information of linked Fault Parts and received units to construct the return-to-warehouse list.
- It preserves SR, Spare Need, Spare Request, RMA, device, BOM, unit, and return-identity context through references rather than copied mutable truth.
- Mixed outcomes are allowed; only units actually requiring return appear in the return membership.
- Sending locks membership and identity. Corrections cancel/replace the sent tag rather than rewriting it.
- Warehouse confirmation requires evidence plus explicit operator confirmation.

## 10. Manual installation and retention

- A manually registered unit may be confirmed installed, including on an unregistered device reference, after an explicit provenance warning.
- Installation without an SR is permitted for manual Stock units after acknowledgment; official SR7/C10 flows retain their required SR chain.
- Beta 1.0.0 performs no automatic or operator-triggered purge of operational inventory history. New purge policies are deferred to Beta 1.1.0.
