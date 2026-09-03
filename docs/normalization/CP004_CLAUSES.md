# SOMA Beta Normalization CP-004 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0078`–`BETA-REQ-0102`.  
Clause identities are stable normative references. Under each requirement, the displayed prefix plus the three-digit suffix forms the full clause ID.

## `BETA-REQ-0078` — prefix `ADMIN-SETUP`

**Governing obligation:** Each SOMA Beta installation shall bootstrap one stable Local Administrator through minimal password-only authentication and progressive configuration while keeping administrator identity, Contacts, scheduling settings, authentication credentials, live-data encryption, portable-backup recovery, and managed-backup rotation as separately governed authorities.

`001` — Each installation shall maintain exactly one Local Administrator actor.
`002` — The Local Administrator shall receive an automatically generated internal identity.
`003` — The Local Administrator internal identity shall remain stable.
`004` — Initial authentication setup shall require a password.
`005` — Initial authentication setup shall require password confirmation.
`006` — Initial setup shall not require a username.
`007` — Login shall not require a username.
`008` — The display name shall default to `Local Administrator`.
`009` — A username-like label may be stored as optional display metadata.
`010` — A username-like display label shall not become authentication identity.
`011` — Email shall not be required on the Local Administrator profile.
`012` — Phone shall not be required on the Local Administrator profile.
`013` — Operational email and phone channels shall belong to reusable Contacts.
`014` — Cryptographic key metadata shall be managed internally.
`015` — Cryptographic key metadata shall never be entered as Local Administrator profile setup.
`016` — First run shall require selection of Light, Dark, or System appearance.
`017` — First run shall require selection of a built-in skin.
`018` — First run shall confirm the Objective/Task scheduling timezone.
`019` — The scheduling timezone default shall use a detected supported IANA value when available.
`020` — `America/Guayaquil` shall be the scheduling-timezone fallback when no supported detected value is available.
`021` — The configurable scheduling timezone shall apply only to Objective/Task scheduling and presentation under the accepted scheduling contract.
`022` — The scheduling-timezone setting shall not reinterpret source timestamps or ordinary/SLA timezone authority.
`023` — Onboarding readiness shall include Customer configuration.
`024` — Onboarding readiness shall include Contract configuration.
`025` — Onboarding readiness shall include Contract Product Line configuration.
`026` — Onboarding readiness shall include Contact configuration.
`027` — Onboarding readiness shall include Dispatch Location configuration.
`028` — Onboarding readiness shall include Infrastructure configuration.
`029` — The readiness checklist shall be skippable.
`030` — The readiness checklist shall be reopenable.
`031` — Missing setup shall block only the action that requires the missing configuration.
`032` — Incomplete readiness shall not create a global application-use gate.
`033` — A Service Request with unresolved setup dependencies shall remain usable where its current workflow does not require them.
`034` — A Service Request lacking valid SLA classification inputs shall remain SLA-unclassified.
`035` — SOMA shall not fabricate an IT or other fallback SLA classification for an unresolved Service Request.
`036` — Local Administrator profile edits shall be audited independently.
`037` — Local Administrator password changes shall be audited independently.
`038` — Password verification shall use an approved salted memory-hard verifier.
`039` — The password shall not derive operational encryption keys.
`040` — The password shall not encrypt or wrap operational encryption keys.
`041` — The password shall not derive portable-backup recovery keys or secrets.
`042` — The password shall not encrypt or wrap portable-backup recovery keys or secrets.
`043` — Automatic login may be offered as an optional capability.
`044` — Automatic login shall use Windows-protected material.
`045` — Automatic login shall never store the Local Administrator password.
`046` — Protected live data shall use authenticated encryption.
`047` — Live-data encryption shall use an independently generated random key.
`048` — The live-data encryption key shall provide at least 256 bits of key strength.
`049` — The live-data encryption key shall be protected through an approved Windows mechanism.
`050` — Portable-backup recovery shall use a secret independent from the authentication password and live-data key.
`051` — The portable-backup recovery secret shall be generated rather than chosen as the login password.
`052` — The portable-backup recovery secret shall provide at least 128 bits of entropy.
`053` — Seven random words, or an equivalently strong generated representation, shall be the recommended portable recovery-secret form.
`054` — Managed backups shall default to retaining five verified backups.
`055` — A new managed backup shall be authenticated before older managed backups are pruned.
`056` — A new managed backup shall pass integrity checking before older managed backups are pruned.
`057` — A new managed backup shall pass structural verification before older managed backups are pruned.
`058` — Failed authentication, integrity, or structural verification shall prevent pruning caused by that backup attempt.
`059` — Managed rotation shall never delete the last verified restorable backup.
`060` — Managed rotation shall not delete operator-exported portable backups.
`061` — Exact cryptographic algorithms shall be resolved in the Security LLD after threat review.
`062` — Exact cryptographic parameters shall be resolved in the Security LLD after threat review.
`063` — Exact protected-data and backup formats shall be resolved in the Security LLD after threat review.
`064` — Password-reset and recovery authorization mechanics shall be resolved in the Security LLD after threat review.
`065` — Key and recovery-secret rotation mechanics shall be resolved in the Security LLD after threat review.
`066` — Restore and recovery behavior shall be resolved in the Security LLD after threat review.
`067` — Custom cryptographic primitives or home-grown cryptographic constructions are prohibited.

## `BETA-REQ-0079` — prefix `SPNEED`

**Governing obligation:** A Spare Need shall persist as one Service-Request-level part-demand aggregate whose contributing Device Part Units, derived contributor count, and operator-governed planning quantities remain distinct from subsequent Stock or Spare Request fulfillment activity.

`001` — A Spare Need shall be a persistent planning record.
`002` — Each Spare Need shall belong to exactly one Service Request.
`003` — A Spare Need shall not be owned by one Device.
`004` — Spare Needs shall aggregate demand by Part Number/BOM code within their owning Service Request.
`005` — A Spare Need shall preserve the applicable part description.
`006` — A Spare Need shall preserve the operator-governed required or planned quantity.
`007` — Matching Device Part Units from any Device under the same Service Request shall contribute to the same applicable Spare Need.
`008` — Matching Device Part Units from different Service Requests shall not be merged into one Spare Need merely because their BOM matches.
`009` — The relationships from a Spare Need to its contributing Device Part Units shall be preserved.
`010` — Contributor relationships shall retain the applicable Device context.
`011` — SOMA shall derive the contributor count from accepted contributor relationships.
`012` — The derived contributor count shall remain distinct from operator-confirmed planned quantity.
`013` — The derived contributor count shall remain distinct from quantities selected for Spare Request attempts.
`014` — Editing an operator-governed planned quantity shall not rewrite contributor relationships.
`015` — A change in contributor relationships shall not silently rewrite an operator-confirmed planning quantity.
`016` — Creating a Spare Request from a Spare Need shall not consume that Need.
`017` — Associating a Spare Need with a Spare Request shall not rewrite the Need's original planning meaning.
`018` — Use of a Spare Need in fulfillment shall not replace its identity.
`019` — A Spare Need shall persist independently from individual fulfillment attempts.
`020` — The Spare Need shall remain the planning-demand authority for its Service Request and part aggregate.
`021` — Stock allocations and Spare Request allocations shall remain separate fulfillment evidence rather than become the Spare Need itself.

## `BETA-REQ-0080` — prefix `DEV-PART`

**Governing obligation:** Each Device Part Unit shall preserve one Device-scoped physical component and its fault evidence, contribute matching demand to the applicable SR-level Spare Need, and allow the operator to choose local, external, or mixed fulfillment after non-binding compatible-Stock suggestions.

`001` — A Device Part Unit shall represent one actual physical component.
`002` — Each Device Part Unit shall belong to one operational Device context.
`003` — A Device Part Unit may represent a component currently installed in the Device.
`004` — A Device Part Unit may represent a component removed from the Device.
`005` — A Device Part Unit may represent a component diagnosed under the Device.
`006` — A Device Part Unit shall reference one slot when that slot is known.
`007` — Unknown slot information shall not invalidate an otherwise valid Device Part Unit.
`008` — Recording a faulty Device Part Unit shall preserve its actual Part Number/BOM code.
`009` — Recording a faulty Device Part Unit shall preserve its manufacturer serial when available.
`010` — Recording a faulty Device Part Unit shall preserve its physical condition.
`011` — Recording a faulty Device Part Unit shall preserve applicable fault chronology.
`012` — A faulty Device Part Unit shall create or contribute to the matching Spare Need under the applicable Service Request.
`013` — The applicable Spare Need shall belong to the Service Request governing the operational fault context.
`014` — Matching part demand within the same Service Request shall aggregate according to the Spare Need contract.
`015` — The contributor relationship from the Device Part Unit to the Spare Need shall remain preserved.
`016` — Before an external Spare Request is prepared, SOMA shall show compatible available Stock relevant to the Spare Need.
`017` — Stock suggestions shall account for the affected Device context where compatibility depends on it.
`018` — Only units currently eligible as available Stock shall be suggested as available fulfillment.
`019` — The operator may fulfill the need from local Stock.
`020` — The operator may request fulfillment externally.
`021` — The operator may combine local Stock and external requesting by quantity.
`022` — The operator may deliberately request externally even when compatible local Stock is available.
`023` — A Stock suggestion shall not automatically reserve a physical unit.
`024` — A Stock suggestion shall not automatically consume a physical unit.
`025` — Merely viewing or refreshing Stock suggestions shall remain side-effect free.
`026` — Local Stock reservation shall require an explicit governed allocation action.
`027` — Local Stock consumption or installation shall require the applicable accepted lifecycle action rather than a suggestion.
`028` — External-request selection shall not silently change physical Stock state.
`029` — Fulfillment choice shall preserve the underlying Spare Need and Device Part Unit identities.

## `BETA-REQ-0081` — prefix `SPNEED-LIFE`

**Governing obligation:** A Spare Need shall remain reusable across repeated local and external fulfillment attempts until explicitly transitioned, while every allocation and lifecycle change remains historical and deletion is restricted by active requests and protected operational evidence.

`001` — An active Spare Need shall remain selectable for repeated fulfillment attempts.
`002` — An active Spare Need may participate in multiple Spare Requests.
`003` — An active Spare Need may participate in multiple local-Stock fulfillment decisions.
`004` — Prior participation shall not consume the Spare Need automatically.
`005` — Prior participation shall remain visible historically.
`006` — Every Need-to-request allocation shall preserve the selected Spare Need identity.
`007` — Every Need-to-request allocation shall preserve the selected Spare Request identity.
`008` — Every Need-to-request allocation shall preserve the selected quantity.
`009` — Allocation history shall be append-oriented rather than overwritten by later attempts.
`010` — The operator may explicitly resolve a Spare Need.
`011` — Resolving a Spare Need shall record a reason and audit evidence.
`012` — The operator may explicitly cancel a Spare Need.
`013` — Cancelling a Spare Need shall record a reason and audit evidence.
`014` — The operator may explicitly reactivate an eligible Spare Need.
`015` — Reactivation shall record a reason and audit evidence.
`016` — Removal shall be blocked while any associated Spare Request remains nonterminal.
`017` — Removal eligibility shall evaluate all associated Spare Requests rather than only the newest request.
`018` — History-preserving removal may occur only after every associated request is confirmed cancelled or rejected under the applicable lifecycle contract.
`019` — History-preserving removal shall preserve prior allocation and request history.
`020` — Hard deletion shall be limited to an untouched manually created Spare Need.
`021` — Any contributor relationship shall block hard deletion.
`022` — Any fulfillment allocation shall block hard deletion.
`023` — Imported or adopted evidence shall block hard deletion.
`024` — Any protected operational dependency shall block hard deletion.
`025` — Hard deletion shall not be used to correct accepted operational history.
`026` — Deletion and removal actions shall follow the general destructive-action safeguards.
`027` — A removed or cancelled Need's historical identity shall not be reused for a new Need.

## `BETA-REQ-0082` — prefix `SPREQ-CTX`

**Governing obligation:** A Spare Request shall persist as one locally identified tracking container derived from one Service Request's selected Spare Needs, while receiver and logistics context remain explicit operator-confirmed choices and temporary tracking remains usable for correspondence reconciliation without becoming the record's internal identity.

`001` — Every Spare Request shall be represented by a locally persisted entity.
`002` — Every Spare Request shall have an opaque immutable internal SOMA identity.
`003` — Every Spare Request shall have an immutable temporary tracking identifier.
`004` — The temporary tracking identifier shall not serve as the relational identity of the Spare Request.
`005` — The temporary tracking identifier shall survive assignment or correction of later official identifiers.
`006` — A Spare Request shall select at least one Spare Need before submission.
`007` — All selected Spare Needs shall belong to the same Service Request.
`008` — A Spare Request shall not combine Needs from different Service Requests.
`009` — Each selected Spare Need identity shall remain preserved through request allocation relationships.
`010` — The Spare Request's Service Request shall be derived from its selected Need allocations.
`011` — SOMA shall not persist a contradictory independently selected Service Request on the Spare Request.
`012` — Allocation changes while draft shall revalidate the single-Service-Request invariant.
`013` — The applicable Customer Organization shall derive from the governing Service Request.
`014` — SOMA shall not persist a contradictory independently selected Customer Organization on the request.
`015` — If Customer Organization resolution is incomplete, SOMA shall preserve that incompleteness rather than fabricate a customer.
`016` — The Service Request's current customer ticket owner may be proposed as the receiver Contact.
`017` — The proposed Contact shall remain a suggestion rather than a silently fixed choice.
`018` — The operator may select another eligible Contact when the workflow permits it.
`019` — A later change to the ticket owner's current Contact shall not rewrite a receiver already frozen as submission evidence.
`020` — Before request-draft generation, the operator shall choose the applicable logistics mode.
`021` — The supported request-draft logistics modes shall distinguish delivery and self-pickup.
`022` — Before request-draft generation, the operator shall select the intended receiver.
`023` — Before request-draft generation, the operator shall select the applicable dispatch, delivery, or pickup location required by the chosen logistics mode.
`024` — Logistics-location semantics shall follow the accepted Dispatch Location and submission-snapshot contracts.
`025` — A Dispatch Location shall not acquire Customer Organization ownership merely because it is selected for a request.
`026` — The generated request communication subject shall include the temporary tracking identifier.
`027` — The temporary tracking identifier shall support later communication reconciliation.
`028` — Omission of the temporary identifier from later correspondence shall not make reconciliation impossible.
`029` — The operator shall be able to reconcile later correspondence manually to the exact Spare Request.
`030` — Manual reconciliation shall preserve the same Spare Request identity.
`031` — Weak similarity in subjects, names, BOM values, or other display facts shall not silently merge requests.
`032` — Receiver and logistics context shall remain explicit governed facts rather than inferred identity.

## `BETA-REQ-0083` — prefix `SPREQ-SUBMIT`

**Governing obligation:** A Spare Request shall remain editable until actual submission is evidenced, at which point its exact request allocations, requested part facts, recipient, logistics, and temporary tracking context shall freeze as immutable submission evidence while all later provider responses and corrections append separately.

`001` — Every Spare Request shall contain at least one Need-to-request allocation before submission.
`002` — Every request allocation quantity shall be a positive whole-unit quantity.
`003` — All request allocations shall satisfy the single-Service-Request invariant.
`004` — Draft request allocations shall remain editable before accepted submission.
`005` — Draft review shall show planned quantity relevant to the selected Spare Need.
`006` — Draft review shall show local-Stock fulfillment quantity where applicable.
`007` — Draft review shall show externally requested quantity.
`008` — SOMA shall compare planned, local, and requested quantities before submission.
`009` — Material quantity discrepancies shall be presented explicitly.
`010` — A discrepancy warning shall not silently rewrite any of the compared quantities.
`011` — Indexed sent communication may provide evidence that submission occurred.
`012` — The operator may explicitly confirm submission manually.
`013` — Manual submission confirmation shall remain auditable.
`014` — Accepted submission shall identify the exact Spare Request being submitted.
`015` — Accepted submission shall freeze submitted Spare Need membership.
`016` — Accepted submission shall freeze submitted allocation quantities.
`017` — Accepted submission shall freeze the requested BOM values represented in the request.
`018` — Accepted submission shall freeze the intended receiver.
`019` — Accepted submission shall freeze the delivery or pickup choice.
`020` — Accepted submission shall freeze the applicable logistics snapshot.
`021` — Accepted submission shall freeze the temporary tracking identity used for the submission.
`022` — Current master-data changes may later differ from the immutable submission snapshot.
`023` — The submission snapshot shall remain historical evidence rather than a duplicate source of current master-data authority.
`024` — Generating a `.msg` draft shall not prove submission.
`025` — Exporting a `.msg` draft shall not prove submission.
`026` — Generating or exporting a `.msg` draft shall not freeze the submission snapshot.
`027` — Generating or exporting a `.msg` draft shall not start the response-warning timer.
`028` — Later assignment of an official SR7 shall append lifecycle evidence.
`029` — Later partial acknowledgement shall append lifecycle evidence.
`030` — Later provider substitutions shall append lifecycle evidence rather than rewrite requested part facts.
`031` — Later corrections shall follow the applicable append-oriented correction contract.
`032` — A partial acknowledgement shall not rewrite the originally submitted requested quantity.
`033` — Later provider evidence shall remain distinguishable from original submitted intent.
`034` — Accepted submission evidence shall remain reproducible historically.
`035` — The request shall retain the same internal identity across draft, submission, acknowledgement, substitution, and correction.
`036` — No later lifecycle fact shall silently overwrite the accepted submitted version.

## `BETA-REQ-0084` — prefix `RMA-BRIDGE`

**Governing obligation:** Each RMA shall persist as one independently identified provider obligation linking at most one compatible target, one later direct inbound physical unit, and one separately reviewed return unit, with deterministic but redistributable assignment and history-preserving distinction between identifier correction and new authorization.

`001` — Each RMA shall be a first-class persistent entity.
`002` — Each RMA shall belong to exactly one officially identified Spare Request.
`003` — Each RMA shall have its own immutable internal SOMA identity.
`004` — Each RMA shall represent exactly one promised inbound item.
`005` — An RMA shall not represent a quantity container for several promised items.
`006` — An RMA shall not be a physical-unit child record.
`007` — An RMA may exist before its promised inbound physical unit is received.
`008` — The RMA shall preserve the provider-promised BOM separately from later observed physical-unit BOM evidence.
`009` — An RMA may be preassigned to at most one target Device Part Unit.
`010` — A preassigned target shall satisfy the applicable compatibility or accepted-substitute rules.
`011` — A target shall be unassigned to a contradictory RMA assignment when automatic preassignment occurs.
`012` — Automatic target preassignment shall use stable Device Part Unit creation order.
`013` — Automatic target preassignment shall use preserved accepted-response RMA order.
`014` — Later partial RMA batches shall continue assignment from remaining eligible compatible targets.
`015` — The operator may redistribute proposed RMA-to-target assignments for operational priority.
`016` — A manual reassignment shall satisfy the applicable compatibility or substitute rules.
`017` — Every reassignment shall be audited.
`018` — Reassignment shall preserve the original proposal evidence rather than rewrite it.
`019` — Each RMA may reference at most one direct inbound Spare Part Unit after receipt.
`020` — The direct inbound Spare Part Unit shall retain its own immutable physical identity.
`021` — The direct inbound unit's actual BOM and serial evidence shall remain independent from the RMA's promised BOM.
`022` — No placeholder physical Spare Part Unit shall be fabricated before actual receipt.
`023` — The RMA shall reference its current return unit separately from its target and inbound unit.
`024` — Return-unit selection shall occur only from reviewed maintenance-outcome authority.
`025` — The inbound unit shall not automatically become the return unit merely because it originated from the RMA.
`026` — The target Device Part Unit shall not automatically become the return unit before the applicable physical outcome is known.
`027` — The current return-unit relationship shall remain independently reviewable and correctable.
`028` — An official C10 correction shall preserve the RMA's internal identity.
`029` — The former C10 shall be retained as immutable alias evidence after correction.
`030` — A former C10 alias shall not be reusable for another RMA.
`031` — The corrected current C10 shall remain distinguishable from historical aliases.
`032` — A genuinely new provider authorization shall create a separate RMA.
`033` — A genuine replacement authorization shall create a separate RMA when it represents a distinct provider obligation.
`034` — A new authorization shall not masquerade as an identifier correction to an existing RMA.
`035` — Correcting an RMA identifier shall not replace its target relationship automatically.
`036` — Correcting an RMA identifier shall not replace its inbound physical unit automatically.
`037` — Correcting an RMA identifier shall not replace its return-unit relationship automatically.
`038` — RMA identity, target identity, inbound-unit identity, and return-unit identity shall remain distinct.
`039` — RMA history shall preserve assignment, receipt, return-selection, identifier-correction, and authorization chronology.

## `BETA-REQ-0085` — prefix `SPUNIT-PHYS`

**Governing obligation:** Device Part Units and Spare Part Units shall remain independently identified physical entities whose actual state and provenance survive receipt, dismantling, installation, and return, while requested, promised, inbound, installed, and returned part/serial evidence remains role-specific and reviewable rather than overwritten.

`001` — Device Part Units and Spare Part Units shall be separate entity types.
`002` — Installing a Spare Part Unit shall not convert it into the identity of a Device Part Unit.
`003` — Removing a Device Part Unit shall not convert it into the identity of a Spare Part Unit automatically.
`004` — Every Spare Part Unit shall retain immutable SOMA identity.
`005` — A Spare Part Unit shall preserve its actual Part Number/BOM code.
`006` — A Spare Part Unit shall preserve its manufacturer serial when available.
`007` — A Spare Part Unit shall preserve its physical condition.
`008` — A Spare Part Unit shall preserve its current physical location or custody through governed lifecycle state.
`009` — A Spare Part Unit shall preserve its physical lifecycle history.
`010` — C10 shall remain optional origin provenance for a Spare Part Unit rather than physical identity.
`011` — SR7 shall remain optional origin provenance for a Spare Part Unit rather than physical identity.
`012` — A Spare Part Unit shall remain valid without an official SR7 or C10 where the applicable registration contract permits it.
`013` — One RMA may reference at most one direct inbound Spare Part Unit.
`014` — Each Spare Part Unit may reference at most one origin RMA as its direct origin provenance.
`015` — Origin-RMA provenance shall not replace the physical unit's SOMA identity.
`016` — A received assembly shall remain the direct inbound fulfillment unit when it is later dismantled.
`017` — Components extracted from a received assembly shall receive separate Spare Part Unit identities.
`018` — Extracted units may share origin-RMA provenance through the received parent assembly where applicable.
`019` — Dismantling shall preserve parent-to-extracted-unit lineage.
`020` — Dismantling shall not erase the parent assembly's receipt history.
`021` — Requested BOM evidence shall remain distinct from promised RMA BOM evidence.
`022` — Promised RMA BOM evidence shall remain distinct from actual inbound-unit BOM evidence.
`023` — Provider substitution shall not rewrite the originally requested BOM.
`024` — Installed-part BOM evidence shall remain distinct from requested and inbound evidence.
`025` — Installed-part serial evidence shall remain distinct from requested and inbound evidence.
`026` — Returned-part BOM evidence shall remain distinct from requested, promised, inbound, and installed evidence.
`027` — Returned-part serial evidence shall remain distinct from requested, promised, inbound, and installed evidence.
`028` — Contradictory BOM evidence shall be preserved for review rather than silently normalized.
`029` — Contradictory serial evidence shall be preserved for review rather than silently overwritten.
`030` — Requested, promised, inbound, installed, and returned evidence shall remain reproducible by role.
`031` — A successful installation shall preserve the installed Spare Part Unit's original physical identity.
`032` — A later removal shall preserve the same physical-unit identity through its changed state.
`033` — Condition changes shall append physical lifecycle evidence rather than create a replacement identity.
`034` — Location changes shall append physical lifecycle evidence rather than create a replacement identity.
`035` — Return activity shall not collapse a Device Part Unit and Spare Part Unit into one identity.
`036` — Physical state shall remain owned by the physical-unit lifecycle rather than by copied request fields.
`037` — Inventory shall consume reviewed Task outcome effects without becoming owner of Task execution or review facts.
`038` — Historical physical relationships shall remain resolvable after current state changes.
`039` — Physical-unit provenance shall remain separate from official identifier aliases.
`040` — No role-specific BOM or serial fact shall silently overwrite another role's accepted evidence.

## `BETA-REQ-0086` — prefix `SPUNIT-REG`

**Governing obligation:** A Spare Part Unit shall be manually registrable with stable SOMA/LSU identity independently of official provenance or manufacturer serial, while origin, custody, condition, disposition, and later provenance remain separate historical facts and Stock eligibility derives only from its accepted physical lifecycle state.

`001` — SOMA shall permit manual registration of a local Spare Part Unit.
`002` — SOMA shall permit manual registration of a legacy Spare Part Unit.
`003` — SOMA shall permit manual registration of an installed Spare Part Unit.
`004` — SOMA shall permit manual registration of a removed Spare Part Unit.
`005` — SOMA shall permit manual registration of an extracted Spare Part Unit.
`006` — SOMA shall permit manual registration of a scrapped Spare Part Unit.
`007` — Manual registration shall not require an SR7.
`008` — Manual registration shall not require a C10.
`009` — Manual registration shall not require a manufacturer serial.
`010` — Missing official provenance shall not invalidate a permitted manual unit.
`011` — Every manually registered unit shall receive an immutable internal SOMA identity.
`012` — Every manually registered unit shall receive the next non-reusable `LSU-########` identifier under the accepted sequence contract.
`013` — Later provenance attachment shall not replace the internal identity.
`014` — Later provenance attachment shall not replace the LSU identity.
`015` — BOM plus manufacturer serial shall be duplicate-candidate evidence rather than relational identity.
`016` — Matching BOM and serial shall not authorize silent physical-unit merging.
`017` — Origin shall remain a fact distinct from current location or custody.
`018` — Current location or custody shall remain distinct from physical condition.
`019` — Physical condition shall remain distinct from disposition.
`020` — Disposition shall remain distinct from origin provenance.
`021` — Later reviewed origin-RMA provenance may be attached to an existing unit.
`022` — Later reviewed origin-RMA provenance shall preserve LSU and prior history.
`023` — A scrapped unit shall not appear as eligible Stock.
`024` — A returned unit that is not currently available shall not appear as eligible Stock.
`025` — A quarantined unit shall not appear as eligible Stock.
`026` — A dismantled parent or otherwise unavailable dismantled unit shall not appear as eligible Stock.
`027` — An installed unit shall not appear as eligible Stock.
`028` — An actively reserved unit shall not appear as eligible Stock.
`029` — Any other lifecycle state declared unavailable shall exclude the unit from eligible Stock.
`030` — A unit shall become available Stock only through an accepted lifecycle transition establishing availability.
`031` — Manual registration by itself shall not imply Stock availability.
`032` — Stock shall be a projection of accepted physical-unit lifecycle state rather than a second physical-unit identity.
`033` — Eligibility changes shall preserve the same Spare Part Unit identity.
`034` — Duplicate review shall not rewrite origin, condition, custody, or disposition evidence silently.
`035` — A manually registered installed or removed unit shall remain valid even without provider provenance.
`036` — Stock selection shall always re-evaluate current accepted availability before allocation.

## `BETA-REQ-0087` — prefix `SPUNIT-ALLOC`

**Governing obligation:** Physical Spare Part Units shall be allocated exclusively through Tasks, with reviewed maintenance outcomes preserving the actual target and spare-unit physical consequences and deterministically establishing the applicable RMA return unit without transferring Task-outcome authority to Inventory.

`001` — Reservation of a physical Spare Part Unit shall occur through a Task-to-unit allocation.
`002` — A Spare Part Unit shall not be reserved through direct Objective ownership.
`003` — Objective presentation of reserved units shall derive through its Tasks.
`004` — A Spare Part Unit may have multiple historical Task allocations.
`005` — A Spare Part Unit shall have at most one active Task allocation at a time.
`006` — Allocation shall revalidate current unit availability before acceptance.
`007` — Historical allocations shall not block future allocation after the applicable prior allocation is no longer active.
`008` — A physical unit shall not have contradictory concurrent installation state.
`009` — Task allocation alone shall not constitute physical installation.
`010` — Physical installation shall require the applicable accepted maintenance outcome.
`011` — After maintenance, the operator shall record the outcome for each applicable target.
`012` — After maintenance, the operator shall record the outcome for each allocated Spare Part Unit.
`013` — After maintenance, the operator shall record the outcome for each applicable inbound Spare Part Unit.
`014` — Target and spare-unit physical consequences shall be independently representable.
`015` — A successful replacement shall link the removed Device Part Unit to the accepted maintenance outcome.
`016` — A successful replacement shall link the installed Spare Part Unit to the accepted maintenance outcome.
`017` — A successful replacement shall update the removed target's physical lifecycle state through accepted outcome consequences.
`018` — A successful replacement shall update the installed spare's physical lifecycle state through accepted outcome consequences.
`019` — An unused outcome shall preserve the physical unit's actual unused state.
`020` — A faulty inbound outcome shall preserve the physical unit's actual faulty state.
`021` — An incompatible outcome shall preserve the physical unit's actual incompatible state.
`022` — A dismantled outcome shall preserve the applicable parent and extracted-unit physical state.
`023` — Other accepted outcomes shall preserve their actual physical consequences rather than force replacement semantics.
`024` — An RMA's return unit shall derive from the reviewed maintenance outcome.
`025` — After a successful replacement, the removed target shall normally become the RMA return unit when the return contract requires it.
`026` — No RMA return unit shall be finalized before the applicable reviewed outcome establishes it.
`027` — An unused inbound unit may become the RMA return unit when the return contract requires it.
`028` — A faulty or incompatible inbound unit may become the RMA return unit when the return contract requires it.
`029` — A parent inbound assembly may become the RMA return unit after dismantling when the return obligation applies to that parent.
`030` — Extracted child units shall not silently replace a parent's return obligation.
`031` — An RMA shall have at most one current selected return unit.
`032` — Return-unit selection shall remain reviewable and correctable.
`033` — Correction of return-unit selection shall preserve prior selection evidence.
`034` — Objectives/Task lifecycle shall remain authoritative for Task execution, outcome, review, correction, and retry facts.
`035` — Inventory shall own Task-to-unit allocation, reservation consequences, physical relationships/state, and RMA return-unit derivation from reviewed outcomes.
`036` — Inventory shall not create a competing Task-outcome authority while consuming reviewed maintenance consequences.

## `BETA-REQ-0088` — prefix `INV-EVENT`

**Governing obligation:** Inventory lifecycle authority shall be preserved through independently addressable append-oriented events whose corrections, cross-request return grouping, warehouse loops, and transactional projections preserve original evidence while making current physical and obligation state reproducible.

`001` — Spare Need lifecycle evidence shall be append-oriented where accepted history exists.
`002` — Need-to-request allocation lifecycle evidence shall be append-oriented.
`003` — Spare Request lifecycle evidence shall be append-oriented.
`004` — RMA lifecycle evidence shall be append-oriented.
`005` — Device Part Unit lifecycle evidence shall be append-oriented.
`006` — Spare Part Unit lifecycle evidence shall be append-oriented.
`007` — Task-to-unit allocation lifecycle evidence shall be append-oriented.
`008` — Reviewed replacement physical-effect evidence shall be append-oriented.
`009` — Fault Tag lifecycle evidence shall be append-oriented.
`010` — Warehouse-decision evidence shall be append-oriented.
`011` — A Fault Tag may group eligible return obligations from different Service Requests.
`012` — A Fault Tag may group eligible return obligations from different Spare Requests.
`013` — A Fault Tag may group members associated with different temporary tracking identifiers.
`014` — A Fault Tag may group members from different RMAs.
`015` — Cross-request grouping shall not merge the independent identities of grouped obligations or units.
`016` — Warehouse receipt shall be a lifecycle milestone distinct from final warehouse acceptance.
`017` — Warehouse receipt shall be a lifecycle milestone distinct from final warehouse rejection.
`018` — Every accepted lifecycle event shall identify its exact target.
`019` — Every accepted lifecycle event shall identify its event type.
`020` — Every accepted lifecycle event shall identify its actor or accepted source.
`021` — Every accepted lifecycle event shall preserve recording time.
`022` — Every accepted lifecycle event shall preserve effective time when independently known.
`023` — Unknown effective time shall remain unknown rather than be fabricated.
`024` — Every accepted lifecycle event shall preserve its reason or material facts where applicable.
`025` — Every accepted lifecycle event may preserve an optional evidence reference.
`026` — A permitted manual event shall remain valid without an evidence reference.
`027` — An erroneous accepted automatic event may be corrected by targeting that exact event.
`028` — An erroneous accepted manual event may be corrected by targeting that exact event.
`029` — A correction shall append a new decision rather than mutate the original event.
`030` — The original erroneous event shall remain preserved.
`031` — The original event's source or actor shall remain preserved.
`032` — The original event's chronology shall remain preserved.
`033` — The original event's evidence reference shall remain preserved when present.
`034` — A genuine warehouse rejection after receipt shall be a new lifecycle event rather than correction of the receipt.
`035` — A return of a rejected unit to the operator shall be new operational history.
`036` — Explanation or reconciliation work after rejection shall not erase prior receipt or rejection.
`037` — A later resend shall be recorded as a new operational loop.
`038` — Resend shall not delete or rewrite the earlier receipt.
`039` — Resend shall not delete or rewrite the earlier rejection.
`040` — Current Inventory state shall be a reproducible projection of accepted lifecycle evidence.
`041` — Given the same accepted evidence and correction decisions, the same current projection shall be reproducible.
`042` — Acceptance of an event and its required projection consequences shall commit transactionally.
`043` — A lifecycle event shall not commit while its required authoritative projection is left inconsistent.
`044` — An authoritative projection shall not change without accepted event or relationship authority.
`045` — Projection rebuild shall preserve immutable event identities.
`046` — Cross-request grouping, correction, and resend shall remain independently auditable.
`047` — Append-oriented Inventory evidence shall not transfer Task execution/outcome authority away from Objectives/Task lifecycle.

## `BETA-REQ-0089` — prefix `INV-COMM`

**Governing obligation:** Read-only indexed communications may produce idempotent, source-linked proposals for Spare Request and Inventory lifecycle facts, but authoritative mutation shall occur only through reviewed acceptance or an equivalent permitted manual action, while Beta 1.0 supports optional evidence references internally without exposing manual attachment or upload controls.

`001` — Configured PST sources shall be indexed read-only.
`002` — Configured OST sources shall be indexed read-only.
`003` — SOMA shall not modify the configured PST or OST source as part of indexing.
`004` — Indexed communication may propose that a Spare Request was submitted.
`005` — Detected submission shall not mutate authoritative request state before acceptance.
`006` — Indexed communication may propose assignment of an official SR7.
`007` — A proposed SR7 shall satisfy canonical identifier validation before acceptance.
`008` — A proposed SR7 shall not replace the Spare Request's internal identity.
`009` — Indexed communication may propose zero or more newly observed C10 RMAs.
`010` — RMA proposals may arrive incrementally across later communications.
`011` — A proposed RMA shall preserve the promised BOM represented by the accepted provider evidence.
`012` — Partial RMA acknowledgement shall preserve the still-pending requested quantity.
`013` — Later RMA batches shall append provider-obligation evidence rather than rewrite earlier accepted RMAs.
`014` — Indexed communication may propose dispatch as a lifecycle milestone.
`015` — Dispatch shall remain distinct from provider acknowledgement or RMA assignment.
`016` — Indexed communication may propose later supported lifecycle milestones.
`017` — Every communication-derived proposal shall reference the exact indexed communication that supports it.
`018` — Every proposal shall identify its exact proposed target or targets.
`019` — Every proposal shall remain inspectable before acceptance.
`020` — Rejecting a proposal shall not mutate the authoritative Inventory lifecycle as though it had been accepted.
`021` — Accepting a proposal shall use the same governed lifecycle rules as the equivalent manual action.
`022` — Reindexing the same source communication shall be idempotent.
`023` — Reindexing shall not create duplicate proposals for the same exact source fact and target.
`024` — Reindexing shall not reapply an already accepted lifecycle mutation.
`025` — Missing required provider identifiers shall keep the Spare Request waiting rather than fabricate an identifier.
`026` — Missing required provider identifiers shall produce an actionable warning.
`027` — Later valid identifier evidence shall reconcile to the same surviving request or obligation.
`028` — The operator may enter an official identifier manually where the applicable lifecycle permits it.
`029` — The operator may confirm a permitted lifecycle milestone manually.
`030` — Manual identifier or lifecycle confirmation shall follow the same identity and validation rules as communication-derived acceptance.
`031` — Manual lifecycle confirmation shall remain valid without evidence.
`032` — Persistence shall support an optional evidence reference on governed Inventory events and relationships where applicable.
`033` — Application services shall accept optional evidence references where the governed command permits them.
`034` — Indexed communication evidence may satisfy an optional evidence reference.
`035` — Beta 1.0 shall expose no manual attachment control for Inventory evidence.
`036` — Beta 1.0 shall expose no manual upload control for Inventory evidence.
`037` — Backend evidence-reference support shall not imply an exposed attachment workflow.
`038` — Lack of uploaded evidence shall not block a permitted manual lifecycle action.
`039` — Communication-derived proposals shall not create competing entity identities from display facts.
`040` — Exact source communication identity shall be preserved independently from the Inventory entity identity.
`041` — Proposal review shall preserve accepted and rejected decision history where required by the audit contract.
`042` — Communication indexing shall remain a proposal source rather than an authoritative Inventory writer.
`043` — Manual and communication-assisted paths shall converge on the same authoritative lifecycle model.
`044` — No communication proposal shall silently rewrite previously accepted submission or lifecycle evidence.

## `BETA-REQ-0090` — prefix `INV-MANUAL`

**Governing obligation:** Every supported Inventory lifecycle transition shall remain manually executable, while communication proposals and optional bulk actions remain reviewed conveniences that preserve per-target event identity, transactional mutation, append-only correction, reproducible projections, and the immutable identities of all participating records.

`001` — Every Inventory lifecycle transition supported by Beta 1.0 shall have an explicit manual action.
`002` — A manual action shall remain available when communication-derived detection is absent.
`003` — A manual action shall remain available when communication-derived detection is incomplete.
`004` — A manual action shall remain available when communication-derived detection is delayed.
`005` — A manual action shall remain available when communication-derived detection is incorrect.
`006` — Manual confirmation shall identify the exact lifecycle target.
`007` — Manual confirmation shall identify the operator.
`008` — Manual confirmation shall preserve recording time.
`009` — Manual confirmation shall preserve effective time when independently known.
`010` — Unknown effective time shall remain unknown rather than be fabricated during manual confirmation.
`011` — Manual confirmation shall preserve a reason or relevant facts where applicable.
`012` — A permitted manual transition shall remain valid without uploaded evidence.
`013` — Beta 1.0 shall expose no manual evidence-attachment control for Inventory lifecycle actions.
`014` — Beta 1.0 shall expose no manual evidence-upload control for Inventory lifecycle actions.
`015` — PST/OST communication indexing used by Inventory shall remain read-only.
`016` — Indexed communication may create a reviewed lifecycle proposal.
`017` — A communication-derived proposal shall identify the exact indexed communication.
`018` — A communication-derived proposal shall identify the exact proposed target or targets.
`019` — Reindexing the same communication shall be idempotent.
`020` — A communication-derived proposal shall not mutate Inventory before acceptance.
`021` — The operator shall be able to accept an individual proposal.
`022` — The operator shall be able to reject an individual proposal.
`023` — SOMA may provide a bulk lifecycle action as an optional convenience.
`024` — One bulk lifecycle action shall target only entities compatible with the same transition.
`025` — One bulk lifecycle action shall target only entities satisfying the applicable common prerequisites.
`026` — Before confirmation, a bulk action shall show eligible targets.
`027` — Before confirmation, a bulk action shall show excluded targets.
`028` — Before confirmation, a bulk action shall show conflicting targets.
`029` — Before confirmation, a bulk action shall show the resulting states for affected targets.
`030` — Before confirmation, a bulk action shall show applicable warnings.
`031` — Before confirmation, a bulk action shall show material dependencies.
`032` — Acceptance of a bulk lifecycle action shall execute transactionally.
`033` — A bulk lifecycle action shall append one independently addressable lifecycle event per affected target.
`034` — Per-target events created by one bulk action shall be associated through a common batch identifier.
`035` — A common batch identifier shall not replace each event's own identity.
`036` — A bulk action shall not collapse multiple physical units or obligations into one shared mutable status record.
`037` — An erroneous accepted manual lifecycle event may be corrected.
`038` — An erroneous accepted communication-derived lifecycle event may be corrected.
`039` — A correction shall target the exact disputed accepted event.
`040` — A correction shall append a correcting decision.
`041` — The original event shall remain preserved.
`042` — The original source shall remain preserved when applicable.
`043` — The original actor shall remain preserved when applicable.
`044` — The original chronology shall remain preserved.
`045` — The original batch membership shall remain preserved when applicable.
`046` — Current state shall be recalculated reproducibly after accepted correction.
`047` — Accepted correction shall not rewrite the original event in place.
`048` — One member of a prior bulk action may be corrected independently.
`049` — Correcting one batch member shall not require reversal of unaffected batch members.
`050` — A genuine later lifecycle development shall not be represented as correction merely because it changes current state.
`051` — Warehouse rejection after receipt shall be recorded as a new lifecycle development.
`052` — Return of a unit to the operator after rejection shall be new operational history.
`053` — Explanation or reconciliation work shall not erase prior accepted events.
`054` — A later resend shall be a new operational transition.
`055` — A genuine resend loop shall remain distinguishable from correction or rollback.
`056` — Spare Request identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`057` — RMA identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`058` — Device Part Unit identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`059` — Spare Part Unit identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`060` — Fault Tag identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`061` — Warehouse-decision identity shall not be silently reassigned or replaced through manual, proposed, bulk, or correction actions.
`062` — Correcting a relationship shall supersede or replace that relationship explicitly rather than replacing either participating entity.

## `BETA-REQ-0091` — prefix `SPREQ-ORIGIN`

**Governing obligation:** A Spare Request shall retain one canonical identity whether initiated inside or outside SOMA, with draft generation remaining distinct from evidenced submission, accepted submission facts freezing immutably, and later official identifiers or communication evidence enriching the same reviewed request rather than silently duplicating, merging, or rewriting it.

`001` — Saving a Spare Request draft shall remain distinct from generating its email draft.
`002` — Generating a Spare Request email draft shall remain distinct from actual submission.
`003` — Registration of a Spare Request prepared or submitted outside SOMA shall be a supported workflow distinct from local draft preparation.
`004` — Saving a new Spare Request draft shall create its canonical local Spare Request record.
`005` — The saved Spare Request shall receive its immutable internal SOMA identity.
`006` — The saved Spare Request shall receive its immutable temporary tracking identifier.
`007` — Draft Spare Need allocations shall remain editable under governed validation.
`008` — Draft receiver and logistics context shall remain editable until the accepted submission boundary.
`009` — Generating an email draft shall operate on an already-created Spare Request rather than create a competing request identity.
`010` — The generated `.msg` subject shall include the Spare Request's temporary tracking identifier.
`011` — SOMA Beta 1.0 shall not send email.
`012` — Creating a `.msg` draft shall not prove Spare Request submission.
`013` — Exporting a `.msg` draft shall not prove Spare Request submission.
`014` — Saving a `.msg` draft shall not prove Spare Request submission.
`015` — Opening a `.msg` draft shall not prove Spare Request submission.
`016` — Local `.msg` actions shall not prove that email was sent.
`017` — Local `.msg` actions shall not prove delivery to the recipient.
`018` — Local `.msg` actions shall not prove recipient receipt or processing.
`019` — Local `.msg` actions shall not prove provider acceptance of the Spare Request.
`020` — Generating or manipulating the `.msg` draft shall not mark the Spare Request submitted.
`021` — Generating or manipulating the `.msg` draft shall not freeze the submission snapshot.
`022` — Generating or manipulating the `.msg` draft shall not start the response-warning timer.
`023` — A corresponding indexed sent-mail message may establish a submission proposal through the governed review path.
`024` — A detected sent communication shall not become accepted submission evidence before operator acceptance.
`025` — The operator may explicitly confirm Spare Request submission manually.
`026` — Manual submission confirmation shall remain valid without uploaded evidence.
`027` — Accepted submission shall preserve submitted Spare Need membership.
`028` — Accepted submission shall preserve submitted quantities.
`029` — Accepted submission shall preserve submitted/requested BOM values.
`030` — Accepted submission shall preserve the intended receiver.
`031` — Accepted submission shall preserve the delivery or pickup choice.
`032` — Accepted submission shall preserve the logistics snapshot.
`033` — Accepted submission shall preserve recipient context.
`034` — Accepted submission shall preserve the temporary tracking identity.
`035` — Accepted submission shall preserve known submission chronology.
`036` — Accepted submission evidence shall remain immutable against later provider responses, master-data edits, or communication discovery.
`037` — The operator may register a Spare Request prepared outside SOMA.
`038` — The operator may register a Spare Request already submitted outside SOMA.
`039` — An externally initiated request shall become the same canonical Spare Request entity type used for SOMA-originated requests.
`040` — An externally initiated request shall receive an immutable SOMA internal identity.
`041` — An externally initiated request shall receive the normal immutable temporary tracking identifier.
`042` — The request shall preserve that its origin was externally initiated.
`043` — External origin shall not weaken the canonical Spare Request lifecycle and identity rules.
`044` — An externally initiated Spare Request shall reconcile to exactly one Service Request.
`045` — External-registration Service Request reconciliation shall require review rather than silent inference.
`046` — An externally initiated Spare Request shall reconcile to one or more Spare Needs.
`047` — Every reconciled Spare Need shall belong to the reconciled Service Request.
`048` — External registration shall not bypass the cross-Service-Request Need prohibition.
`049` — A missing Spare Need may be created during reviewed external registration when necessary to faithfully represent the request.
`050` — A Spare Need created during external registration shall preserve the submitted BOM context.
`051` — A Spare Need created during external registration shall preserve the submitted quantity context.
`052` — Missing-Need creation shall occur as an explicit reviewed part of reconciliation rather than silent inference.
`053` — An externally initiated Spare Request may record a known official SR7.
`054` — A known SR7 shall satisfy canonical identifier validation before acceptance.
`055` — A known SR7 shall satisfy uniqueness and reconciliation validation before acceptance.
`056` — A known official SR7 shall remain an external business identifier rather than replace internal identity.
`057` — Later exact communication evidence may be appended to the already registered Spare Request.
`058` — Later communication discovery shall preserve the existing Spare Request identity.
`059` — Later communication discovery shall not rewrite previously accepted submission facts.
`060` — Later communication shall enrich evidence/history rather than recreate the Spare Request lifecycle.
`061` — SOMA shall detect credible duplicate candidates between manually registered Spare Requests and communication-derived proposals.
`062` — A plausible duplicate candidate shall not blindly create a second Spare Request.
`063` — A plausible duplicate candidate shall not be silently merged into an existing Spare Request.
`064` — Duplicate candidates shall require reviewed reconciliation.
`065` — When reviewed evidence establishes the same real Spare Request, the existing canonical identity shall survive and new evidence shall attach to it.
`066` — A genuinely different real Spare Request shall retain or receive its own distinct internal identity.

## `BETA-REQ-0092` — prefix `INV-ID`

**Governing obligation:** Every Inventory entity, relationship, and accepted lifecycle event shall retain immutable internal identity, with duplicate matching, official-identifier correction, relationship correction, and bulk-action correction operating through reviewed append-only supersession rather than silent merging, reassignment, identity replacement, or deletion of accepted history.

`001` — Every Spare Need shall have immutable internal identity.
`002` — Every Need-to-request allocation shall have immutable internal identity.
`003` — Every Spare Request shall have immutable internal identity.
`004` — Every RMA shall have immutable internal identity.
`005` — Every Device Part Unit shall have immutable internal identity.
`006` — Every Spare Part Unit shall have immutable internal identity.
`007` — Every Task-to-unit allocation shall have immutable internal identity.
`008` — Every accepted replacement-outcome relationship or record shall have immutable internal identity.
`009` — Every Fault Tag shall have immutable internal identity.
`010` — Every warehouse decision shall have immutable internal identity.
`011` — Every accepted Inventory lifecycle event shall have immutable internal identity.
`012` — A display label shall not replace internal identity.
`013` — An official or operator-visible identifier shall not replace internal identity.
`014` — A BOM value shall not replace internal identity.
`015` — A manufacturer serial shall not replace internal identity.
`016` — A communication reference shall not replace internal identity.
`017` — A relationship target shall not replace the identity of the relationship itself.
`018` — Matching external facts may create duplicate or reconciliation candidates only.
`019` — Matching external facts shall not authorize silent entity merging.
`020` — Matching external facts shall not authorize silent relationship reassignment.
`021` — Matching external facts shall not authorize identity replacement.
`022` — A lifecycle correction shall target the exact accepted event or relationship being disputed.
`023` — A superseding decision shall identify exactly which prior meaning it supersedes.
`024` — The original accepted event or relationship shall remain preserved.
`025` — The original target shall remain preserved.
`026` — The original actor or source shall remain preserved.
`027` — The original chronology shall remain preserved.
`028` — The original evidence reference shall remain preserved when present.
`029` — The original batch membership shall remain preserved when applicable.
`030` — A correcting decision shall append as new accepted evidence.
`031` — Original accepted evidence shall not be rewritten in place.
`032` — Original accepted evidence shall not be deleted as the correction mechanism.
`033` — Current projections shall be recalculated reproducibly after correction.
`034` — Correcting a relationship shall preserve both participating entities.
`035` — The disputed relationship shall be explicitly closed, invalidated, or superseded.
`036` — The reviewed replacement relationship shall be established independently.
`037` — An erroneous RMA assignment shall be correctable through relationship supersession.
`038` — An erroneous Task allocation shall be correctable through relationship supersession.
`039` — An erroneous receipt link shall be correctable through relationship supersession.
`040` — An erroneous installation relationship shall be correctable through relationship supersession.
`041` — An erroneous removal relationship shall be correctable through relationship supersession.
`042` — An erroneous return-unit selection shall be correctable through relationship supersession.
`043` — An erroneous Fault Tag membership shall be correctable through relationship supersession or the governed replacement workflow.
`044` — An erroneous warehouse-decision relationship shall be correctable through exact-event or relationship supersession.
`045` — Audit presentation shall identify the previous relationship.
`046` — Audit presentation shall identify the corrected relationship.
`047` — Audit presentation shall identify the correcting operator or accepted source.
`048` — Audit presentation shall identify the correction reason.
`049` — Audit presentation shall identify resulting lifecycle consequences.
`050` — Correcting an official SR7 shall preserve the Spare Request's internal identity.
`051` — A former corrected SR7 shall be retained as alias evidence.
`052` — A former SR7 alias shall be immutable.
`053` — A former SR7 alias shall be non-reusable.
`054` — Correcting an official C10 shall preserve the RMA's internal identity.
`055` — A former corrected C10 shall be retained as alias evidence.
`056` — A former C10 alias shall be immutable.
`057` — A former C10 alias shall be non-reusable.
`058` — A genuinely different Spare Request shall receive a different internal identity.
`059` — A genuinely different provider authorization shall receive a different RMA internal identity.
`060` — A genuinely new entity shall not be represented by overwriting another entity's official identifier.
`061` — A correction to one target within a prior bulk action shall remain isolated to that target unless an explicit dependency requires more.
`062` — Unaffected members of the prior bulk action shall remain preserved.
`063` — Hard deletion shall not be used as the ordinary mechanism for correcting accepted Inventory history.
`064` — Accepted Inventory history shall be corrected through governed append-only correction or supersession rather than destructive erasure.

## `BETA-REQ-0093` — prefix `INV-LOG`

**Governing obligation:** Submitted logistics intent and actual physical fulfillment shall remain independently preserved, with partial and multi-unit logistics recorded per addressable obligation or physical unit, historical location evidence frozen against later master-data changes, and local or dismantled units never receiving fabricated external-delivery history.

`001` — Accepted Spare Request submission shall preserve an immutable submission-logistics snapshot.
`002` — The snapshot shall preserve the requested delivery or self-pickup mode.
`003` — The snapshot shall preserve the intended receiver.
`004` — The snapshot shall preserve the selected logistics location applicable to the submitted workflow.
`005` — The snapshot shall preserve the effective location name used in the submitted request.
`006` — The snapshot shall preserve the effective submitted address.
`007` — The snapshot shall preserve recipient context represented in the submitted request.
`008` — The snapshot shall preserve other material logistics facts actually represented in the submitted request.
`009` — The submission-logistics snapshot shall represent requested logistics intent.
`010` — The submission snapshot shall not prove actual dispatch.
`011` — The submission snapshot shall not prove actual pickup.
`012` — The submission snapshot shall not prove actual delivery.
`013` — The submission snapshot shall not prove physical receipt.
`014` — Actual dispatch shall be recorded independently from submitted intent.
`015` — Actual pickup shall be recorded independently from submitted intent.
`016` — Actual delivery shall be recorded independently from submitted intent.
`017` — Actual receipt shall be recorded independently from submitted intent.
`018` — Later custody and location changes shall remain separate lifecycle evidence.
`019` — Each direct inbound Spare Part Unit shall link to the actual logistics events applicable to that unit.
`020` — Actual effective location or custody shall be preserved for applicable milestones.
`021` — The actual receiver shall be preserved when known.
`022` — Actual dispatch, pickup, delivery, receipt, and custody chronology shall be preserved.
`023` — Physical condition shall be recorded at applicable receipt or logistics milestones where known.
`024` — Applicable communication evidence may be referenced optionally.
`025` — Permitted manual logistics confirmation shall remain valid without uploaded evidence.
`026` — One logistics event may cover multiple RMAs.
`027` — One logistics event may cover multiple physical Spare Part Units.
`028` — Every participating RMA shall remain independently addressable.
`029` — Every participating physical unit shall remain independently addressable.
`030` — Every participant shall remain independently reviewable.
`031` — Every participant shall remain independently correctable.
`032` — SOMA shall support partial dispatch.
`033` — SOMA shall support partial receipt.
`034` — Different RMAs may progress through logistics independently.
`035` — Different physical units may progress through logistics independently.
`036` — Unresolved requested quantity shall remain explicitly pending.
`037` — Unassigned requested quantity shall remain distinguishable from an assigned but undispatched RMA obligation.
`038` — Undispatched shall remain distinguishable from dispatched-but-unreceived.
`039` — Actual logistics may differ from submitted intent.
`040` — Actual divergence shall not rewrite the submitted logistics snapshot.
`041` — Actual logistics facts shall be preserved separately.
`042` — Material differences between submitted intent and actual logistics shall be presented for review.
`043` — Later Contact edits shall not rewrite historical recipient or receiver logistics evidence.
`044` — Later Dispatch Location edits shall not rewrite historical logistics evidence.
`045` — Later linked Infrastructure Site edits shall not rewrite historical logistics evidence.
`046` — A current address change shall not rewrite a prior frozen logistics address.
`047` — Dispatch Location shall remain the applicable logistics-location entity under its accepted role semantics.
`048` — Infrastructure Site shall remain a separate entity from Dispatch Location.
`049` — A linked Dispatch Location may supply the effective logistics address for its Site where the accepted relation applies.
`050` — Linking Site and Dispatch Location shall not merge their identities.
`051` — A local Spare Part Unit with no external request shall not receive fabricated Spare Request provenance.
`052` — A local Spare Part Unit with no external delivery shall not receive fabricated external dispatch evidence.
`053` — A local Spare Part Unit with no external delivery shall not receive fabricated external receipt evidence.
`054` — A dismantled received parent assembly shall retain the direct receipt relationship.
`055` — A dismantled received parent assembly shall retain its original logistics relationship.
`056` — Extracted components shall receive separate Spare Part Unit identities.
`057` — Extracted units may inherit origin provenance through the received parent assembly.
`058` — Extracted units may inherit receipt provenance through the received parent assembly.
`059` — Extracted units shall not receive fabricated independent delivery events.
`060` — Later location changes of extracted units shall be recorded through their own append-oriented lifecycle events.
`061` — Later custody changes of extracted units shall be recorded through their own append-oriented lifecycle events.

## `BETA-REQ-0094` — prefix `FT-SCOPE`

**Governing obligation:** Fault Tags and their complete physical-return lifecycle shall be mandatory first-class Inventory capabilities in Beta 1.0.0, preserving independently identified cross-request return members through reviewed manual or communication-assisted submission, warehouse decision, rejection, correction, and resend workflows whose full use-case, responsive-UI, LLD, and automated-acceptance coverage is required for release.

`001` — Fault Tags shall be a mandatory SOMA Beta 1.0.0 capability.
`002` — The governed physical-return lifecycle associated with Fault Tags shall be mandatory in Beta 1.0.0.
`003` — Fault Tags shall not be deferred to a later Beta release.
`004` — Essential physical-return lifecycle behavior required by this contract shall not be deferred independently from Fault Tags.
`005` — Fault Tags shall be one of the Inventory workspace's primary views.
`006` — Stock shall remain a peer primary Inventory view.
`007` — Spare Requests shall remain a peer primary Inventory view.
`008` — Fault Tag availability shall not depend on future manual-evidence upload functionality.
`009` — The physical-return lifecycle shall remain operable without manual evidence uploads.
`010` — SOMA shall support determination of the actual physical return unit from the accepted reviewed maintenance outcome.
`011` — Return-unit determination shall preserve the selected physical unit's immutable identity.
`012` — The applicable physical return unit shall be determined or reviewed before governed Fault Tag membership is accepted.
`013` — Fault Tags shall support grouping eligible RMA return obligations.
`014` — Fault Tags shall represent the physical units selected to satisfy those obligations through memberships.
`015` — Fault Tag grouping shall not create duplicate physical-unit identity.
`016` — One Fault Tag may contain eligible members originating from different Service Requests.
`017` — One Fault Tag may contain eligible members originating from different Spare Requests.
`018` — Grouped members may be associated with different temporary tracking identifiers.
`019` — One Fault Tag may contain eligible members belonging to different RMAs.
`020` — Each Fault Tag member shall retain independent identity.
`021` — Each Fault Tag member shall retain independent origin or provenance.
`022` — Each Fault Tag member shall retain an independently addressable lifecycle.
`023` — Each Fault Tag member shall retain its own correction history.
`024` — Fault Tag grouping shall not merge independent return obligations.
`025` — Fault Tag grouping shall not merge independent physical units.
`026` — Beta 1.0 shall support recording a Fault Tag's first actual submission.
`027` — Communication-draft activity shall not constitute first submission except through the separately governed submission authority.
`028` — Beta 1.0 shall support warehouse receipt for submitted Fault Tag members.
`029` — Warehouse receipt shall remain distinct from final warehouse acceptance.
`030` — Warehouse receipt shall remain distinct from final warehouse rejection.
`031` — Beta 1.0 shall support final warehouse acceptance.
`032` — Beta 1.0 shall support final warehouse rejection.
`033` — Warehouse rejection shall not erase or terminate prior Fault Tag history merely because the first return attempt failed.
`034` — SOMA shall support applicable explanation or reconciliation work after warehouse rejection.
`035` — SOMA shall support a later resend when a rejected return requires another attempt.
`036` — A resend shall preserve prior submission, receipt, and rejection history.
`037` — Every supported Fault Tag lifecycle transition shall remain available through a governed manual action.
`038` — Lack of communication-derived detection shall not prevent a permitted Fault Tag transition.
`039` — A permitted manual Fault Tag action shall remain valid without uploaded evidence.
`040` — Read-only indexed communication may propose a supported Fault Tag lifecycle transition.
`041` — A communication-derived Fault Tag proposal shall remain reviewed before authoritative mutation.
`042` — Equivalent manual and communication-derived transitions shall converge on the same governed Fault Tag lifecycle model.
`043` — Beta 1.0 shall expose no manual evidence-attachment control in the Fault Tag workflow.
`044` — Beta 1.0 shall expose no manual evidence-upload control in the Fault Tag workflow.
`045` — Absence of manual upload functionality shall not make the required Fault Tag workflow incomplete.
`046` — Fault Tag creation workflow shall be covered before Beta 1.0.0 release.
`047` — Fault Tag membership workflow shall be covered before Beta 1.0.0 release.
`048` — Fault Tag submission workflow shall be covered before Beta 1.0.0 release.
`049` — Fault Tag receipt workflow shall be covered before Beta 1.0.0 release.
`050` — Fault Tag acceptance workflow shall be covered before Beta 1.0.0 release.
`051` — Fault Tag rejection workflow shall be covered before Beta 1.0.0 release.
`052` — Fault Tag correction workflow shall be covered before Beta 1.0.0 release.
`053` — Fault Tag replacement workflow shall be covered before Beta 1.0.0 release.
`054` — Fault Tag archival workflow shall be covered before Beta 1.0.0 release.
`055` — Fault Tag resend workflow shall be covered before Beta 1.0.0 release.
`056` — Fault Tag warning states shall be covered before Beta 1.0.0 release.
`057` — Fault Tag empty states shall be covered before Beta 1.0.0 release.
`058` — Fault Tag error states shall be covered before Beta 1.0.0 release.
`059` — Fault Tag historical workflows and states shall be covered before Beta 1.0.0 release.
`060` — Every required Fault Tag workflow/state category shall have accepted business-use-case coverage before release.
`061` — Every required Fault Tag workflow and material state shall have accepted responsive-UI coverage before release.
`062` — Every required Fault Tag workflow shall have sufficient accepted LLD contract coverage before release.
`063` — Every required Fault Tag workflow/state category shall have automated acceptance-scenario coverage before release.
`064` — Beta 1.0.0 shall not satisfy this product requirement while any mandated Fault Tag workflow category lacks required use-case, responsive-UI, LLD, or automated-acceptance coverage.

## `BETA-REQ-0095` — prefix `FT-ID`

**Governing obligation:** Each Fault Tag shall retain immutable internal and operator-visible identities and derive its current state from append-oriented lifecycle events, while first submission freezes its exact membership and applicable pickup-origin logistics evidence without conflating pickup origin, destination, communication drafts, or later corrections.

`001` — Every Fault Tag shall receive an immutable opaque internal SOMA identity.
`002` — The internal identity shall be assigned when the Fault Tag draft is created.
`003` — Every Fault Tag shall receive an operator-visible tracking identifier.
`004` — The operator-visible tracking identifier shall be immutable.
`005` — The operator-visible tracking identifier shall be non-reusable.
`006` — The operator-visible tracking identifier shall be assigned when the Fault Tag draft is created.
`007` — Fault Tag membership shall not substitute for Fault Tag identity.
`008` — Service Request identifiers shall not substitute for Fault Tag identity.
`009` — Spare Request identifiers shall not substitute for Fault Tag identity.
`010` — RMA identifiers shall not substitute for Fault Tag identity.
`011` — BOM values shall not substitute for Fault Tag identity.
`012` — Manufacturer serial values shall not substitute for Fault Tag identity.
`013` — Filenames shall not substitute for Fault Tag identity.
`014` — Communication subjects shall not substitute for Fault Tag identity.
`015` — Matching or similar external facts shall not silently merge or replace Fault Tag identity.
`016` — Every Fault Tag draft shall record its intended return method.
`017` — Return method shall remain distinct from lifecycle state.
`018` — A pickup return method shall reference exactly one reusable Dispatch Location in the pickup-origin role when pickup information is required.
`019` — The pickup-origin Dispatch Location shall identify where return units are dispatched or collected from.
`020` — The pickup-origin Dispatch Location shall not represent the warehouse destination.
`021` — The applicable pickup Contact may be linked where known or required.
`022` — Pickup origin shall reference the reusable Dispatch Location entity rather than create one-off location identity.
`023` — Accepted first submission shall preserve the effective pickup-origin name.
`024` — Accepted first submission shall preserve the effective pickup-origin address.
`025` — Accepted first submission shall preserve the pickup Contact when applicable.
`026` — Accepted first submission shall preserve applicable pickup context.
`027` — The submitted pickup-origin snapshot shall remain immutable historical evidence.
`028` — A separately known warehouse destination may be recorded independently.
`029` — Recording a destination shall not redefine the pickup-origin role.
`030` — Pickup origin and destination shall remain distinct logistics facts.
`031` — A Fault Tag draft may temporarily omit pickup information when the selected method or current draft stage does not yet require it.
`032` — Pickup information shall become required at the point where the selected return method or submission action depends on it.
`033` — A non-pickup return method shall not fabricate a pickup Dispatch Location.
`034` — A non-pickup return method shall not fabricate a pickup-origin snapshot.
`035` — The Fault Tag's current state shall derive from accepted lifecycle events.
`036` — Given the same accepted lifecycle history, the same current Fault Tag state shall be reproducible.
`037` — Fault Tag current state shall not be governed by an independently editable status label that can contradict lifecycle history.
`038` — Draft creation shall remain a distinguishable lifecycle event.
`039` — First submission shall remain a distinguishable lifecycle event.
`040` — Warehouse receipt shall remain a distinguishable lifecycle event.
`041` — Final acceptance shall remain a distinguishable lifecycle event.
`042` — Rejection shall remain a distinguishable lifecycle event.
`043` — Resend shall remain a distinguishable lifecycle event.
`044` — Cancellation shall remain a distinguishable lifecycle event.
`045` — Replacement shall remain a distinguishable lifecycle event.
`046` — Archival shall remain a distinguishable lifecycle event.
`047` — Correction shall remain a distinguishable lifecycle event.
`048` — Distinct lifecycle events shall not be collapsed into generic mutable status history.
`049` — Generating a Fault Tag communication draft shall not prove sending.
`050` — Saving a Fault Tag communication draft shall not prove sending.
`051` — Exporting a Fault Tag communication draft shall not prove sending.
`052` — Communication-draft activity shall not constitute first submission.
`053` — Corresponding indexed sent communication may establish a first-submission proposal.
`054` — Communication-derived first submission shall require operator acceptance before becoming authoritative.
`055` — The operator may confirm first submission explicitly without indexed communication.
`056` — Manual first-submission confirmation shall remain valid without uploaded evidence.
`057` — When first submission is supported by indexed communication, the accepted event shall preserve the exact indexed message reference.
`058` — Lack of communication evidence shall not invalidate a permitted manually confirmed first submission.
`059` — The accepted first-submission event shall preserve the Fault Tag identities.
`060` — The accepted first-submission event shall preserve the exact submitted membership snapshot.
`061` — The accepted first-submission event shall preserve the submitted return method.
`062` — The accepted first-submission event shall preserve the pickup-origin snapshot when applicable.
`063` — The accepted first-submission event shall preserve the recipient snapshot when applicable.
`064` — The accepted first-submission event shall preserve its source or operator.
`065` — The accepted first-submission event shall preserve recording time.
`066` — The accepted first-submission event shall preserve effective time when independently known.
`067` — The accepted first-submission event shall preserve its reason or material facts.
`068` — The accepted first-submission event shall remain immutable.
`069` — A correction shall target the exact original first-submission event.
`070` — The original first-submission event shall remain preserved.
`071` — The correcting decision shall append as separate accepted evidence.
`072` — The Fault Tag's current projection shall be recalculated reproducibly after correction.
`073` — Correction shall not silently mutate the original first-submission snapshot.

## `BETA-REQ-0096` — prefix `FT-MEMBER`

**Governing obligation:** Each Fault Tag membership shall pair exactly one open RMA return obligation with one reviewed physical return unit derived from the accepted maintenance outcome, preserving both identities and selection evidence while enforcing active-submission exclusivity and treating any later warehouse-rejection resend as a new historical return attempt.

`001` — Every Fault Tag membership shall reference exactly one RMA return obligation.
`002` — The referenced RMA return obligation shall be open and eligible when the membership is accepted.
`003` — Every Fault Tag membership shall reference exactly one physical unit selected to satisfy that obligation.
`004` — A Fault Tag membership shall represent one specific RMA-return-obligation-to-physical-unit pairing rather than a quantity or generic grouping record.
`005` — SOMA shall derive or propose the applicable physical return unit from the accepted reviewed maintenance outcome.
`006` — A derived or proposed return unit shall not be added to a Fault Tag automatically.
`007` — The operator shall review the proposed obligation/unit pairing before Fault Tag membership acceptance.
`008` — A removed Device Part Unit after successful replacement may be an eligible return unit.
`009` — An unused inbound Spare Part Unit may be an eligible return unit when the return contract requires it.
`010` — An inbound Spare Part Unit found faulty may be an eligible return unit when the return contract requires it.
`011` — An inbound Spare Part Unit found incompatible may be an eligible return unit when the return contract requires it.
`012` — The parent inbound assembly may be an eligible return unit after dismantling when the return obligation applies to the parent.
`013` — Other physical outcomes may qualify only when explicitly permitted by the RMA return contract and reviewed.
`014` — The selected return unit shall preserve its actual physical identity.
`015` — The selected return unit shall preserve its actual BOM.
`016` — The selected return unit shall preserve its manufacturer serial when available.
`017` — The selected return unit shall preserve its physical condition.
`018` — The selected return unit shall preserve its origin or provenance.
`019` — The selected return unit shall preserve its existing physical lifecycle.
`020` — Fault Tag membership shall not transform or replace the selected unit's physical identity.
`021` — A condition label alone shall not establish Fault Tag eligibility.
`022` — Apparent newness alone shall not establish Fault Tag eligibility.
`023` — BOM equality alone shall not establish Fault Tag eligibility or compatibility.
`024` — Manufacturer serial equality alone shall not establish Fault Tag eligibility.
`025` — RMA provenance alone shall not establish Fault Tag eligibility.
`026` — Eligibility requires the physical unit to be the currently selected return for an applicable open RMA obligation.
`027` — A unit currently installed and still serving in equipment shall not be eligible for contradictory active return.
`028` — An unrelated faulty component without the applicable RMA return obligation shall not be eligible merely because it is faulty.
`029` — A physical unit selected for another contradictory active return shall not be eligible for a second conflicting membership.
`030` — A closed or already satisfied RMA return obligation shall not be accepted as a new active membership unless later accepted authority creates or reopens an obligation.
`031` — Creating Fault Tag membership shall not create a duplicate physical-unit record.
`032` — Fault Tag membership shall reference the RMA rather than duplicate RMA identity.
`033` — RMA-owned facts shall not be copied into independently mutable membership fields as competing operational truth.
`034` — Membership-specific facts such as selection reason and chronology may remain authoritative on the membership where appropriate.
`035` — Membership shall preserve the exact RMA obligation selected.
`036` — Membership shall preserve the exact physical unit selected.
`037` — Membership shall preserve the accepted maintenance outcome supporting the return selection.
`038` — Membership shall preserve the return reason.
`039` — Membership shall preserve the operator or accepted source responsible for selection.
`040` — Membership shall preserve the effective selection chronology.
`041` — Later lifecycle changes shall not rewrite which obligation, unit, outcome, and reason were accepted when membership was selected.
`042` — One open RMA return obligation shall participate in at most one active submitted Fault Tag membership at a time.
`043` — One physical unit shall participate in at most one contradictory active submitted Fault Tag membership at a time.
`044` — Draft candidacy alone shall not necessarily activate submitted-membership exclusivity.
`045` — First submission or equivalent activation shall revalidate active-membership exclusivity.
`046` — Genuine warehouse rejection shall preserve prior submitted membership history.
`047` — A genuine rejection may make the same unresolved RMA obligation eligible for a later return attempt.
`048` — The same physical unit may be eligible for a later resend/replacement return attempt when it remains the governed return unit.
`049` — A later return attempt shall receive a new independently identified Fault Tag membership.
`050` — The previous Fault Tag shall remain preserved.
`051` — The previous membership shall remain preserved.
`052` — The previous warehouse receipt shall remain preserved.
`053` — The previous warehouse rejection shall remain preserved.
`054` — The previous attempt chronology shall remain preserved.
`055` — Fault Tag members may originate from different Service Requests.
`056` — Fault Tag members may originate from different Spare Requests.
`057` — Fault Tag members may carry different temporary tracking identifiers.
`058` — Fault Tag members may belong to different RMAs.
`059` — Every cross-request Fault Tag membership shall independently satisfy eligibility.
`060` — Exact BOM equality shall not be required for valid replacement or return when an accepted substitute relationship exists.
`061` — When the faulty Device Part Unit, corresponding Spare Need, and submitted Spare Request consistently identify the same BOM, that BOM shall establish the original requested or target part context for substitution review.
`062` — When an accepted RMA for that request results in an inbound unit with a different actual BOM, SOMA may recognize the difference as provider-approved substitute evidence rather than treat BOM mismatch alone as incompatibility.
`063` — Recognizing a provider-approved substitute shall not rewrite the target, Spare Need, submitted-request, or other historical requested BOM evidence.
`064` — A substitute physical unit shall retain its actual observed BOM identity.
`065` — The operator may explicitly select or register a different-BOM physical unit as a substitute where the workflow permits it.
`066` — When no accepted substitute authority already exists, a BOM mismatch between the selected physical unit and applicable target/request context shall produce a material warning rather than automatic rejection solely for mismatch.
`067` — The operator may explicitly confirm a mismatching physical unit as an accepted or safe substitute.
`068` — Manual substitute approval shall preserve the operator, original BOM, substitute BOM, chronology, and applicable reason or context.
`069` — Once an accepted substitute relationship exists, BOM mismatch alone shall not prevent otherwise valid replacement, RMA-return, or Fault Tag eligibility.
`070` — Substitute approval shall not bypass identity, active-allocation, open-RMA, installation-state, contradictory-return, condition, or other governed lifecycle prerequisites.

## `BETA-REQ-0097` — prefix `FT-REL`

**Governing obligation:** Each Fault Tag membership shall retain immutable identity and reference its Fault Tag, open RMA return obligation, and selected physical unit through their internal identities, deriving ticket and Device context from authoritative relationships while keeping current facts at their owning entities and preserving only data-minimized immutable submission-time display evidence.

`001` — Every Fault Tag membership shall receive its own immutable internal SOMA identity.
`002` — Membership identity shall remain distinct from its parent Fault Tag identity.
`003` — Changes to display identifiers, conditions, locations, or derived context shall not replace membership identity.
`004` — Each membership shall reference exactly one Fault Tag.
`005` — Each membership shall reference exactly one RMA return obligation.
`006` — The referenced RMA return obligation shall satisfy applicable open-obligation eligibility when membership is accepted.
`007` — Each membership shall reference exactly one selected physical unit.
`008` — Membership shall represent the exact relationship without duplicating participating entities.
`009` — The Fault Tag shall be referenced by immutable internal identity.
`010` — The RMA shall be referenced by immutable internal identity.
`011` — The physical unit shall be referenced by immutable internal identity.
`012` — C10 shall not serve as relationship identity.
`013` — SR7 shall not serve as relationship identity.
`014` — BOM shall not serve as relationship identity.
`015` — Manufacturer serial shall not serve as relationship identity.
`016` — Names shall not serve as relationship identity.
`017` — Display labels shall not serve as relationship identity.
`018` — The membership's Spare Request shall derive through its RMA.
`019` — Membership shall not persist an independently authoritative Spare Request relationship that can contradict the RMA's parent request.
`020` — Governed RMA relationship correction shall cause current Spare Request context to resolve through the accepted relationship rather than copied SR7 values.
`021` — The applicable Service Request shall derive through the RMA's parent Spare Request.
`022` — Service Request derivation shall respect the Spare Request's accepted Need allocations.
`023` — Fault Tag membership shall preserve the single-Service-Request invariant of the Spare Request's accepted Need allocations.
`024` — Membership shall not maintain a contradictory independently selected Service Request.
`025` — RMA target assignment may contribute applicable Device context.
`026` — Reviewed maintenance outcome shall contribute actual Device context where relevant.
`027` — Selected physical return-unit history may contribute applicable Device context.
`028` — Operational Device context shall resolve through applicable Device Reference relationships.
`029` — Device-context authorities shall be reconciled rather than selected arbitrarily from conflicting labels.
`030` — A Device Reference may resolve to one registered Infrastructure Network Element.
`031` — A Device Reference may remain provisional.
`032` — A Device Reference may remain external or unregistered.
`033` — Lack of a registered Network Element shall not invalidate otherwise legitimate operational return history.
`034` — SOMA shall reject an independently selected Service Request that contradicts the authoritative relationship chain.
`035` — SOMA shall reject an independently selected Spare Request that contradicts the authoritative relationship chain.
`036` — SOMA shall reject an independently selected RMA that contradicts the authoritative relationship chain.
`037` — SOMA shall reject an independently selected Device Reference that contradicts the authoritative relationship chain.
`038` — SOMA shall reject an independently selected physical unit that contradicts the authoritative relationship chain.
`039` — Equal external identifiers shall not authorize silent reassignment.
`040` — Similar external identifiers shall not authorize silent reassignment.
`041` — Equal BOM values shall not authorize silent reassignment.
`042` — Different BOM values shall not by themselves invalidate an otherwise valid relationship when an accepted provider- or operator-approved substitute relationship exists.
`043` — Serial similarity shall not authorize silent reassignment.
`044` — Device-name similarity shall not authorize silent reassignment.
`045` — Label similarity shall not authorize silent reassignment.
`046` — Similarity may create reviewed reconciliation candidates but shall not silently create duplicate relationships.
`047` — An accepted substitute relationship shall not rewrite faulty Device Part Unit, Spare Need, submitted Spare Request, RMA promise, or physical-unit BOM evidence.
`048` — The physical unit shall remain authoritative for its actual observed BOM.
`049` — Submitted request evidence shall remain authoritative for the BOM that was requested.
`050` — RMA/provider evidence shall remain authoritative for promised part context represented by that response.
`051` — Provider- or operator-approved substitution shall be represented as governed compatibility/substitution evidence connecting distinct part facts.
`052` — Fault Tag membership shall not maintain independently mutable original/substitute BOM current-truth copies when those facts resolve from owning entities and relationships.
`053` — Membership shall not persist a mutable copy of the RMA's C10 as competing current truth.
`054` — Membership shall not persist a mutable copy of the parent Spare Request's SR7 as competing current truth.
`055` — Membership shall not persist a mutable copy of the physical unit's BOM as competing current truth.
`056` — Membership shall not persist a mutable copy of the physical unit's manufacturer serial as competing current truth.
`057` — Membership shall not persist a mutable copy of current physical condition as competing current truth.
`058` — Membership shall not persist a mutable copy of current physical location as competing current truth.
`059` — Membership shall not persist mutable derived ticket relationships as competing operational truth.
`060` — Membership shall not persist mutable derived Device relationships as competing operational truth.
`061` — Current C10 display shall resolve from the RMA's owning current facts.
`062` — Current SR7 display shall resolve from the Spare Request's owning current facts.
`063` — Current physical BOM and serial display shall resolve from the physical-unit owner.
`064` — Current condition shall resolve from accepted physical lifecycle state.
`065` — Current location shall resolve from accepted physical lifecycle state.
`066` — Current ticket context shall resolve through governing relationships.
`067` — Current Device context shall resolve through governing relationships.
`068` — Current display shall distinguish current facts from historical submitted facts when they differ.
`069` — A first-submission membership snapshot shall be data-minimized.
`070` — Identifiers actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`071` — BOM values actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`072` — Serial information actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`073` — Device context actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`074` — Return reason actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`075` — Other display facts actually represented in the submitted Fault Tag or communication may be frozen in the submission snapshot.
`076` — Unrepresented facts shall not be copied gratuitously into the historical snapshot.
`077` — The first-submission membership snapshot shall be immutable.
`078` — The snapshot shall represent submission-time evidence.
`079` — Historical snapshot values shall not replace current owning-entity facts.
`080` — Later current-fact changes shall not rewrite the historical submission snapshot.
`081` — The historical snapshot shall not become current relationship authority.
`082` — RMA official-identifier correction shall preserve Fault Tag identity.
`083` — RMA official-identifier correction shall preserve Fault Tag membership identity.
`084` — RMA official-identifier correction shall preserve RMA internal identity.
`085` — RMA official-identifier correction shall preserve physical-unit identity.
`086` — RMA official-identifier correction shall leave the submitted snapshot unchanged.
`087` — A former C10 shall remain preserved as alias evidence.
`088` — Current views may display the corrected current C10.
`089` — UI/history views shall distinguish the current C10 from the C10 value submitted historically when they differ.
`090` — A relationship correction shall target the exact disputed membership or source relationship.
`091` — Fault Tag identity shall remain preserved where correction does not require the material replacement workflow.
`092` — Membership identity shall remain preserved unless its submitted meaning requires governed supersession or replacement.
`093` — RMA identity shall remain preserved through relationship correction.
`094` — Physical-unit identity shall remain preserved through relationship correction.
`095` — Relationship correction shall append audit history.
`096` — Original relationship evidence shall remain preserved.
`097` — Current derived context shall be recalculated from the accepted corrected relationship chain.

## `BETA-REQ-0098` — prefix `FT-REPLACE`

**Governing obligation:** Fault Tag membership shall remain editable until actual first submission, after which submitted membership is immutable: false submission may be corrected on the same Fault Tag, material changes to a real submission require a transactionally linked linear replacement lineage, and genuine warehouse resend remains separate operational history.

`001` — Fault Tag membership shall remain editable while the Fault Tag is an unsubmitted draft.
`002` — Eligible membership may be added before accepted first submission.
`003` — Draft membership may be removed before accepted first submission under ordinary draft-integrity rules.
`004` — Draft obligation/unit selection may be revised before accepted first submission.
`005` — Generating a communication draft shall not lock Fault Tag membership.
`006` — Saving a communication draft shall not lock Fault Tag membership.
`007` — Exporting a communication draft shall not lock Fault Tag membership.
`008` — Existence of a communication artifact shall not itself make submitted membership immutable.
`009` — Exact submitted membership identities shall become immutable only when first submission is accepted.
`010` — The first-submission snapshot shall become immutable at the same accepted boundary.
`011` — A sent-message-derived first submission shall require operator acceptance before the immutable boundary applies.
`012` — Explicit manual confirmation may establish accepted first submission without communication evidence.
`013` — If an accepted first-submission event was erroneous and no real external submission occurred, SOMA may append a correction or suppression.
`014` — A false-submission correction shall target the exact disputed accepted event.
`015` — The erroneous submission event shall remain preserved.
`016` — The original source or operator shall remain preserved.
`017` — The original chronology shall remain preserved.
`018` — The correction reason shall remain preserved.
`019` — Accepted false-submission correction may recalculate the same Fault Tag to Draft.
`020` — Returning to Draft after false-submission correction shall preserve the same Fault Tag identity.
`021` — Returning to Draft after false-submission correction shall preserve the same tracking identifier.
`022` — Draft membership may unlock again because no real external submission occurred.
`023` — Membership of a genuinely submitted Fault Tag shall never be edited in place.
`024` — Membership of a genuinely submitted Fault Tag shall never be removed in place.
`025` — Membership of a genuinely submitted Fault Tag shall never be reassigned in place.
`026` — Membership of a genuinely submitted Fault Tag shall never be overwritten in place.
`027` — Submitted membership shall remain historical evidence of what was actually submitted.
`028` — A correction requiring a different submitted RMA obligation shall be material.
`029` — A correction requiring a different submitted physical unit shall be material.
`030` — A material correction shall not edit the original submitted Fault Tag in place.
`031` — The original submitted Fault Tag shall undergo the applicable supersession or cancellation transition.
`032` — A material correction shall create one explicit replacement Fault Tag.
`033` — A replacement Fault Tag shall receive a new immutable internal identity.
`034` — A replacement Fault Tag shall receive a new immutable tracking identifier.
`035` — A replacement Fault Tag shall reference exactly one direct correction predecessor.
`036` — The correction lineage relationship shall be typed `corrects/replaces`.
`037` — Replacement lineage shall preserve the reason.
`038` — Replacement lineage shall preserve the operator or accepted source.
`039` — Replacement lineage shall preserve chronology.
`040` — Replacement lineage shall preserve material differences from the predecessor.
`041` — Every replacement membership shall receive a new immutable membership identity.
`042` — Every replacement membership shall revalidate the current open RMA obligation.
`043` — Every replacement membership shall revalidate the current selected physical return unit.
`044` — Every replacement membership shall revalidate active-membership constraints.
`045` — Accepted provider- or operator-approved substitute authority shall be revalidated when the replacement membership depends on substitution.
`046` — Superseding or cancelling the predecessor and creating the replacement shall commit transactionally.
`047` — Failure to create the replacement shall not leave the predecessor successfully superseded as though a valid replacement exists.
`048` — A replacement shall not become authoritative while the predecessor remains in a contradictory uncorrected state.
`049` — Each Fault Tag shall have at most one direct `corrects/replaces` successor.
`050` — Each replacement Fault Tag shall have at most one direct correction predecessor.
`051` — A later material correction shall extend the lineage from the current correction-head Fault Tag.
`052` — Correction lineage shall be acyclic.
`053` — Correction lineage shall be linear rather than branching.
`054` — Cancellation, supersession, or replacement shall preserve the original Fault Tag identity.
`055` — Cancellation, supersession, or replacement shall preserve the original tracking identifier.
`056` — Cancellation, supersession, or replacement shall preserve the original submitted membership.
`057` — Cancellation, supersession, or replacement shall preserve original communication or manual evidence.
`058` — Cancellation, supersession, or replacement shall preserve the original pickup-origin snapshot.
`059` — Cancellation, supersession, or replacement shall preserve original lifecycle history.
`060` — A replacement shall not erase predecessor evidence.
`061` — Archival may alter default presentation after the applicable terminal transition.
`062` — Archival shall not erase replacement lineage.
`063` — Archival shall not substitute for the `corrects/replaces` relationship.
`064` — Historical predecessors shall remain resolvable after archival.
`065` — Alias-preserving correction of an RMA/C10 identifier shall not by itself require replacement when the RMA internal identity and submitted meaning are unchanged.
`066` — Correction of a derived current display may be non-material when it does not change what was actually submitted.
`067` — The existing Fault Tag shall be preserved for a non-material correction.
`068` — The submitted snapshot shall remain unchanged for a non-material correction.
`069` — A replacement Fault Tag shall not be created unnecessarily for a correction that does not change submitted meaning.
`070` — Genuine warehouse rejection shall be later operational lifecycle rather than correction of the original submission.
`071` — Return of a rejected unit to the operator shall be later operational lifecycle.
`072` — A later resend shall be later operational lifecycle.
`073` — Warehouse rejection, return, and resend shall not invalidate the fact that the original submission occurred.
`074` — A later resend attempt may use a new Fault Tag.
`075` — A resend Fault Tag shall explicitly reference the earlier attempt.
`076` — The resend lineage relationship shall be typed `resend of`.
`077` — `resend of` shall remain semantically distinct from `corrects/replaces`.
`078` — A genuine resend shall not enter the correction chain as the canonical replacement of the earlier Fault Tag.

## `BETA-REQ-0099` — prefix `FT-WH`

**Governing obligation:** Each submitted Fault Tag membership shall progress independently through distinct warehouse-receipt and explicitly confirmed final-disposition stages, where acceptance closes its RMA return obligation, rejection preserves that obligation for further action, and all partial, corrected, and resend history remains immutable and independently reproducible.

`001` — Warehouse receipt and final warehouse disposition shall be modeled as separate confirmation stages.
`002` — Warehouse stages shall be tracked independently for each submitted Fault Tag membership.
`003` — `Warehouse Received` shall mean that physical possession of the selected return unit was acknowledged.
`004` — Warehouse receipt shall not imply final inspection acceptance.
`005` — Warehouse receipt shall not imply final rejection.
`006` — Warehouse receipt alone shall not close the RMA return obligation.
`007` — A later governed warehouse decision shall record final disposition after applicable inspection or review.
`008` — Final `Accepted` disposition shall be supported.
`009` — Final `Rejected` disposition shall be supported.
`010` — One final warehouse decision shall not represent both Accepted and Rejected simultaneously.
`011` — Final warehouse acceptance shall close the corresponding RMA return obligation.
`012` — Closure shall apply to the exact RMA obligation associated with the accepted membership.
`013` — Acceptance of one membership shall not close unrelated RMA obligations in the same Fault Tag.
`014` — Final warehouse rejection shall not close the corresponding RMA return obligation.
`015` — Final rejection shall preserve the submitted Fault Tag.
`016` — Final rejection shall preserve the membership.
`017` — Final rejection shall preserve the physical-unit identity.
`018` — Final rejection shall preserve the warehouse-receipt event.
`019` — Final rejection shall preserve the inspection decision.
`020` — Final rejection shall preserve the rejection reason.
`021` — Final rejection shall preserve chronology.
`022` — Final rejection shall preserve evidence when available.
`023` — A rejected return obligation shall remain visible as requiring further action.
`024` — A rejected unresolved obligation may later participate in an explicitly linked resend Fault Tag where applicable.
`025` — Further action after rejection shall not reopen or rewrite the original submitted Fault Tag attempt.
`026` — Indexed communication may propose warehouse receipt.
`027` — Indexed communication may propose final warehouse disposition.
`028` — A warehouse proposal may target one membership.
`029` — A warehouse proposal may target several memberships.
`030` — A warehouse proposal may target all applicable memberships in one Fault Tag.
`031` — Every proposed membership target shall remain independently reviewable.
`032` — Every proposed warehouse outcome shall remain independently reviewable.
`033` — No communication proposal shall mutate Inventory before operator acceptance.
`034` — Final warehouse acceptance shall always require explicit operator confirmation.
`035` — Final warehouse rejection shall always require explicit operator confirmation.
`036` — Communication evidence shall not silently finalize a return obligation without operator confirmation.
`037` — Memberships in the same submitted Fault Tag may progress independently through warehouse stages.
`038` — Partial warehouse receipt shall be supported.
`039` — Partial final-disposition processing shall be supported.
`040` — One communication or manual action may process only a subset of memberships.
`041` — Unprocessed memberships shall remain pending.
`042` — One membership outcome shall not fabricate or infer another member's outcome.
`043` — One membership outcome shall not force another member's outcome.
`044` — Communication evidence shall be linked to an accepted warehouse event when available and applicable.
`045` — Communication evidence shall not be mandatory for an otherwise permitted warehouse event.
`046` — The operator may confirm warehouse receipt manually.
`047` — The operator may confirm final warehouse acceptance manually.
`048` — The operator may confirm final warehouse rejection manually.
`049` — Permitted manual warehouse actions shall remain valid without uploaded evidence.
`050` — Beta 1.0 shall expose no manual attachment control for warehouse evidence.
`051` — Beta 1.0 shall expose no manual upload control for warehouse evidence.
`052` — Every accepted receipt or final-decision event shall preserve the exact Fault Tag membership.
`053` — Every accepted receipt or final-decision event shall preserve the exact RMA obligation.
`054` — Every accepted receipt or final-decision event shall preserve the exact physical unit.
`055` — Every accepted receipt or final-decision event shall preserve the operator or accepted source.
`056` — Every accepted receipt or final-decision event shall preserve recording time.
`057` — Every accepted receipt or final-decision event shall preserve independently supported effective time when known.
`058` — Every accepted receipt or final-decision event shall preserve the applicable decision or event type.
`059` — Every accepted receipt or final-decision event shall preserve its reason or material facts.
`060` — Every accepted receipt or final-decision event may preserve an optional evidence reference.
`061` — An unknown external effective time shall remain unknown.
`062` — Discovery time shall not be substituted for unknown external effective time.
`063` — Indexing time shall not be substituted for unknown external effective time.
`064` — Current-clock time shall not be substituted for unknown external effective time.
`065` — Recording time shall remain separately preserved even when effective time is unknown.
`066` — An accepted warehouse event shall remain immutable evidence.
`067` — Accepted event timestamp evidence shall remain immutable.
`068` — Later current-state changes shall not rewrite accepted warehouse events.
`069` — An erroneously recorded warehouse receipt may be corrected.
`070` — An erroneously recorded final acceptance may be corrected.
`071` — An erroneously recorded final rejection may be corrected.
`072` — A warehouse correction shall target the exact disputed accepted event.
`073` — A warehouse correction shall append a new decision.
`074` — The original warehouse event shall remain preserved.
`075` — The original warehouse evidence shall remain preserved.
`076` — Membership projection shall be recalculated after accepted correction.
`077` — Fault Tag projection shall be recalculated after accepted correction.
`078` — Physical-unit projection shall be recalculated after accepted correction.
`079` — RMA return-obligation projection shall be recalculated after accepted correction.
`080` — Projection recalculation shall be reproducible.
`081` — A submitted Fault Tag attempt shall reach an aggregate terminal state only when every submitted membership has a final decision, cancellation, or supersession applicable to that attempt.
`082` — A rejected membership counts as having a final decision for completion of the Fault Tag attempt even though its RMA obligation remains open.
`083` — Cancellation may satisfy completion of a membership for the submitted attempt where applicable.
`084` — Supersession may satisfy completion of a membership for the submitted attempt where applicable.
`085` — A terminal aggregate Fault Tag attempt shall not imply that every RMA return obligation was accepted and closed.
`086` — A rejected membership shall remain an unresolved RMA return obligation.
`087` — Rejected unresolved obligations shall remain visible after the prior Fault Tag attempt becomes terminal.
`088` — A genuine resend shall use a later Fault Tag.
`089` — The resend Fault Tag shall explicitly link to the earlier attempt.
`090` — Genuine resend shall not reopen the original submitted Fault Tag.
`091` — Genuine resend shall not rewrite the original submitted Fault Tag.
`092` — Earlier receipt and rejection history shall remain preserved through resend.

## `BETA-REQ-0100` — prefix `FT-REMOVE`

**Governing obligation:** Fault Tag removal shall use lifecycle-specific cancellation, replacement, archival, resend, or narrowly eligible draft hard deletion according to preserved operational dependencies, with explicit impact preview, non-cascading entity protection, transactional audit, and no destructive control over previously exported artifacts.

`001` — Fault Tag destructive and removal actions shall reflect actual lifecycle and dependencies rather than one generic deletion meaning.
`002` — Hard deletion shall remain distinct from other Fault Tag lifecycle actions.
`003` — Cancellation shall remain distinct from hard deletion.
`004` — Supersession shall remain distinct from hard deletion.
`005` — Replacement shall remain distinct from hard deletion.
`006` — Archival shall remain distinct from hard deletion.
`007` — Creation of a resend attempt shall remain distinct from hard deletion.
`008` — SOMA shall expose only lifecycle actions valid for the Fault Tag's current state and dependencies.
`009` — Physical hard deletion shall be limited to a manually created Fault Tag draft.
`010` — Any actual external first submission shall permanently disqualify that Fault Tag from hard deletion.
`011` — An active accepted first-submission event shall block hard deletion.
`012` — Corrected first-submission history shall remain protected unless the general deletion contract establishes that no protected history remains.
`013` — Protected communication-generation history shall block hard deletion where preservation is required by the deletion contract.
`014` — Associated indexed communication shall block hard deletion.
`015` — A reviewed proposal shall block hard deletion.
`016` — A warehouse event shall block hard deletion.
`017` — Protected correction history shall block hard deletion.
`018` — Replacement lineage shall block hard deletion.
`019` — Predecessor lineage shall block hard deletion.
`020` — Successor lineage shall block hard deletion.
`021` — A resend relationship shall block hard deletion.
`022` — Any other protected operational dependency shall block hard deletion.
`023` — A falsely recorded first submission shall first be resolved through the exact-event correction mechanism before deletion eligibility is evaluated.
`024` — Accepted false-submission correction may restore Draft projection when no real submission occurred.
`025` — Draft state alone shall not establish hard-deletion eligibility after false-submission correction.
`026` — A corrected draft may be hard-deleted only when no protected history or dependency remains under the general deletion contract.
`027` — Eligible untouched draft memberships may be physically deleted with their eligible draft parent.
`028` — Eligible draft-membership deletion shall be transactional with parent hard deletion.
`029` — Submitted or otherwise protected membership shall not be physically deleted through the untouched-draft path.
`030` — Fault Tag hard deletion shall never cascade-delete an RMA.
`031` — Fault Tag hard deletion shall never cascade-delete an RMA return obligation.
`032` — Fault Tag hard deletion shall never cascade-delete a Device Part Unit.
`033` — Fault Tag hard deletion shall never cascade-delete a Spare Part Unit.
`034` — Fault Tag hard deletion shall never cascade-delete a Service Request.
`035` — Fault Tag hard deletion shall never cascade-delete a Spare Request.
`036` — Fault Tag hard deletion shall never cascade-delete a Device Reference.
`037` — Fault Tag hard deletion shall never cascade-delete a Contact.
`038` — Fault Tag hard deletion shall never cascade-delete a Dispatch Location.
`039` — Fault Tag hard deletion shall never cascade-delete an indexed communication.
`040` — Fault Tag hard deletion shall never cascade-delete any other independently surviving entity.
`041` — Hard deletion shall remove only the eligible Fault Tag and Fault-Tag-owned draft records explicitly permitted by the deletion contract.
`042` — A submitted Fault Tag shall not be hard-deletable.
`043` — A communication-linked Fault Tag with protected history shall not be hard-deletable.
`044` — A proposal-linked Fault Tag shall not be hard-deletable.
`045` — A corrected Fault Tag with protected correction history shall not be hard-deletable.
`046` — A Fault Tag with warehouse history shall not be hard-deletable.
`047` — A replacement-linked Fault Tag shall not be hard-deletable.
`048` — A resend-linked Fault Tag shall not be hard-deletable.
`049` — A Fault Tag with any other protected operational history shall not be hard-deletable.
`050` — Cancellation, supersession, replacement, archival, and resend shall preserve Fault Tag internal identity where applicable to the existing record.
`051` — Cancellation, supersession, replacement, archival, and resend shall preserve the existing Fault Tag tracking identifier historically.
`052` — Non-delete lifecycle actions shall preserve submitted snapshots.
`053` — Non-delete lifecycle actions shall preserve submitted memberships.
`054` — Non-delete lifecycle actions shall preserve pickup-origin evidence.
`055` — Non-delete lifecycle actions shall preserve lifecycle events.
`056` — Non-delete lifecycle actions shall preserve correction, replacement, and resend lineage.
`057` — Non-delete lifecycle actions shall preserve communication/manual evidence.
`058` — Material correction of actually submitted RMA or physical-unit membership shall use the explicit replacement workflow.
`059` — A materially incorrect real submission shall not be hard-deleted as the correction mechanism.
`060` — Genuine warehouse rejection shall remain a real operational lifecycle outcome.
`061` — A later return attempt after genuine rejection shall use the resend workflow.
`062` — Rejection and resend shall not be misrepresented as deletion.
`063` — Genuine resend shall remain distinct from correction lineage when the original submission was valid.
`064` — Archival may affect default presentation after the applicable terminal transition.
`065` — Archival shall not delete historical Fault Tag evidence.
`066` — Archival shall not conceal or strand unresolved RMA return obligations.
`067` — Archival shall preserve correction/replacement lineage.
`068` — Archival shall preserve resend lineage.
`069` — SOMA shall present an impact preview before executing a destructive Fault Tag action.
`070` — The impact preview shall identify the Fault Tag.
`071` — The impact preview shall identify current lifecycle state.
`072` — The impact preview shall identify applicable memberships.
`073` — The impact preview shall identify associated communications.
`074` — The impact preview shall identify associated lifecycle proposals.
`075` — The impact preview shall identify warehouse events.
`076` — The impact preview shall identify correction or replacement lineage.
`077` — The impact preview shall identify resend lineage.
`078` — The impact preview shall identify protected dependencies.
`079` — The impact preview shall identify the exact records that will be removed.
`080` — The impact preview shall identify the exact records that will be preserved.
`081` — A destructive Fault Tag action shall require explicit operator confirmation after impact preview.
`082` — The executed action shall correspond to the reviewed remove/preserve set and lifecycle transition.
`083` — Destructive mutation shall commit transactionally.
`084` — Required audit recording shall commit transactionally.
`085` — Required mutation and audit evidence shall commit together.
`086` — Failure of required mutation or audit recording shall roll back the governed operation.
`087` — SOMA shall not delete or modify a previously exported `.msg` in an operator-selected location merely because the originating Fault Tag changes lifecycle state or is hard-deleted.
`088` — SOMA shall not delete or modify other previously exported artifacts in operator-selected locations merely because the originating Fault Tag changes lifecycle state or is hard-deleted.
`089` — A later SOMA lifecycle action shall not imply destructive authority over an operator-managed exported artifact.

## `BETA-REQ-0101` — prefix `FT-LOG`

**Governing obligation:** Each Fault Tag shall preserve a return-method-specific submission snapshot in which pickup uses exactly one Dispatch Location as the return origin, while actual pickup remains separate lifecycle evidence and false submission, material logistics correction, and genuine resend follow their distinct draft, replacement, and resend paths.

`001` — Every Fault Tag draft shall record its intended return method.
`002` — Required logistics prerequisites shall depend on the selected return method.
`003` — When the return method requires physical pickup, exactly one reusable Dispatch Location shall be selected in the pickup-origin role before first submission can be accepted.
`004` — A pickup-required Fault Tag shall not reach accepted first submission with zero pickup-origin Dispatch Locations.
`005` — A pickup-required Fault Tag shall not reach accepted first submission with multiple competing pickup-origin Dispatch Locations.
`006` — The selected pickup-origin Dispatch Location shall identify where the return units are dispatched or collected from.
`007` — The selected pickup-origin Dispatch Location shall not represent the warehouse destination.
`008` — Any known warehouse destination shall remain a separate fact.
`009` — A known destination shall not reverse or redefine pickup-origin semantics.
`010` — A pickup-origin submission snapshot shall not exist without exactly one selected pickup-origin Dispatch Location.
`011` — SOMA shall not persist an orphan pickup-origin snapshot disconnected from its governing Dispatch Location identity.
`012` — The submitted pickup-origin snapshot shall preserve the Dispatch Location's internal identity.
`013` — The submitted pickup-origin snapshot shall preserve the effective origin name.
`014` — The submitted pickup-origin snapshot shall preserve the effective origin address.
`015` — The submitted pickup-origin snapshot shall preserve the applicable pickup Contact when known.
`016` — The submitted pickup-origin snapshot shall preserve the applicable communication channel when known.
`017` — The submitted pickup-origin snapshot shall preserve pickup instructions when represented.
`018` — The submitted logistics snapshot shall preserve the selected return method.
`019` — The submitted logistics snapshot shall preserve recipient context.
`020` — The submitted logistics snapshot may preserve other represented data-minimized logistics facts.
`021` — The submitted logistics snapshot shall remain data-minimized rather than duplicate unrelated current master data.
`022` — When the selected return method does not require pickup, a pickup-origin Dispatch Location shall not be required.
`023` — A non-pickup return method shall not fabricate a pickup origin.
`024` — A non-pickup return method shall not fabricate a pickup-origin snapshot.
`025` — Accepted non-pickup submission shall preserve its selected return method and applicable represented logistics context.
`026` — Generating a Fault Tag communication draft shall not freeze return method.
`027` — Saving a Fault Tag communication draft shall not freeze pickup origin.
`028` — Exporting a Fault Tag communication draft shall not freeze pickup logistics.
`029` — Draft logistics shall remain editable until accepted first submission.
`030` — The return-method snapshot shall freeze only at accepted first submission.
`031` — The pickup-origin snapshot shall freeze only at accepted first submission.
`032` — Reviewed indexed sent communication may establish the accepted first-submission boundary.
`033` — Explicit manual confirmation may establish the accepted first-submission boundary.
`034` — Later Dispatch Location changes shall not rewrite the submitted snapshot.
`035` — Later linked Infrastructure Site changes shall not rewrite the submitted snapshot.
`036` — Later current address changes shall not rewrite the submitted snapshot.
`037` — Later Contact changes shall not rewrite the submitted snapshot.
`038` — Later communication-channel changes shall not rewrite the submitted snapshot.
`039` — Archived logistics master data referenced historically shall remain resolvable for historical presentation.
`040` — Corrected logistics master data referenced historically shall remain resolvable for historical presentation.
`041` — A logistics master-data value no longer eligible for current use shall become unavailable for incompatible new selections.
`042` — Historical resolvability shall not imply current operational eligibility.
`043` — Actual physical pickup shall be recorded independently from submitted pickup intent.
`044` — Actual pickup shall enter history through append-oriented logistics and custody events.
`045` — Actual pickup shall not mutate the submitted snapshot.
`046` — Actual pickup shall preserve actual pickup location when known.
`047` — Actual pickup shall preserve actual pickup Contact when known.
`048` — Actual pickup shall preserve actual chronology when known.
`049` — Actual pickup shall preserve actual instructions or context when represented.
`050` — Actual pickup shall preserve the applicable custody consequence.
`051` — Actual pickup may differ from submitted pickup intent.
`052` — A difference in actual pickup location shall be preserved.
`053` — A difference in actual pickup Contact shall be preserved.
`054` — A difference in actual chronology shall be preserved.
`055` — A difference in actual pickup instructions shall be preserved.
`056` — Material submitted-versus-actual pickup differences shall be presented for review.
`057` — Actual discrepancy shall not rewrite the submitted pickup snapshot.
`058` — A falsely recorded first submission may be corrected.
`059` — False-submission correction shall target the exact accepted event.
`060` — When no real submission occurred, accepted correction may return the same Fault Tag to Draft.
`061` — Returning to Draft after false-submission correction may make return method editable again.
`062` — Returning to Draft after false-submission correction may make pickup-origin selection editable again.
`063` — The prior erroneous submission event shall remain preserved.
`064` — Materially incorrect pickup instructions in a genuinely submitted Fault Tag shall not cause the original submission to be rewritten.
`065` — A material submitted-logistics correction shall supersede the original Fault Tag.
`066` — A material submitted-logistics correction shall create a replacement Fault Tag.
`067` — The replacement Fault Tag shall receive a new internal identity.
`068` — The replacement Fault Tag shall receive a new tracking identifier.
`069` — The replacement Fault Tag shall receive its own immutable logistics snapshot at its accepted submission.
`070` — A logistics-only replacement may preserve logically equivalent RMA and physical-unit memberships when those memberships remain valid.
`071` — A logistics replacement shall explicitly link to its predecessor through the governed correction/replacement lineage.
`072` — The predecessor's original logistics snapshot shall remain immutable.
`073` — The replacement shall not rewrite predecessor logistics evidence.
`074` — A genuine resend Fault Tag shall select its own return method.
`075` — A genuine resend Fault Tag shall select its own pickup origin when applicable.
`076` — A genuine resend Fault Tag shall create its own submission logistics snapshot.
`077` — A prior Fault Tag's pickup snapshot shall not be inherited as current truth for the resend.
`078` — SOMA may offer prior return-method or pickup-origin values as draft defaults for a resend.
`079` — Prior values offered as resend defaults shall remain reviewable and editable before submission.
`080` — Defaulting prior values into a resend draft shall not establish them as accepted current logistics facts.

## `BETA-REQ-0102` — prefix `INFRA-TERM`

**Governing obligation:** SOMA Beta shall use Infrastructure as the canonical registered-device domain, represent operational devices through persistent Device References that may deliberately resolve to exactly one Network Element without duplication, and keep each Network Element's identity distinct from model, components, compound structure, placement, cloud attributes, and legacy Managed Element terminology.

`001` — The top-level SOMA Beta workspace shall be named `Infrastructure`.
`002` — `Device Manager` shall not be used as the canonical Beta workspace or domain name.
`003` — `Managed Element` shall not be used as the canonical name of a Beta domain entity.
`004` — A device involved in operational workflows shall be represented through a Device Reference.
`005` — A Device Reference may remain valid without a registered Infrastructure Network Element.
`006` — A Device Reference may represent an external or unregistered device while participating in supported workflows.
`007` — Lack of Infrastructure registration shall not invalidate accepted operational relationships.
`008` — A Device Reference may later resolve to a registered Infrastructure Network Element.
`009` — A Device Reference shall resolve to at most one Network Element at a time.
`010` — Device Reference to Network Element resolution shall rely on governed entity identity rather than only hostname, serial, model, or another mutable/display fact.
`011` — Regularizing an unregistered or external Device Reference into Infrastructure shall require an explicit governed promotion or reconciliation action.
`012` — Promotion shall preserve the Device Reference identity.
`013` — Promotion shall preserve existing operational relationships attached to the Device Reference.
`014` — Promotion shall not create a second competing Device Reference for the same operational device relationship.
`015` — Promotion shall not rewrite historical operational records merely because a Network Element later becomes available.
`016` — A Network Element shall represent one specific registered device instance.
`017` — A Network Element shall have an immutable identity distinct from descriptive, model, placement, or cloud attributes.
`018` — A reusable hardware or product Model shall remain distinct from the specific Network Element instance using that Model.
`019` — Components associated with a Network Element shall remain distinct from Network Element identity.
`020` — Compound sub-elements shall remain distinct from parent Network Element identity according to the Infrastructure contract.
`021` — Physical placement shall remain a relationship or attribute distinct from Network Element identity.
`022` — Relocating a Network Element shall preserve its identity.
`023` — Cloud Type shall remain distinct from Network Element identity.
`024` — Cloud Deployment shall remain distinct from Network Element identity.
`025` — Changing cloud context shall not by itself create a new Network Element identity.
`026` — Legacy `Managed Element` labels may be recognized during import or migration mapping.
`027` — Historical source evidence may preserve a legacy `Managed Element` label where it existed.
`028` — Legacy terminology shall not create a distinct Beta `Managed Element` domain type.
`029` — Adopted legacy device data shall reconcile into Device Reference and Network Element semantics according to accepted Beta contracts.
`030` — Matching hostname shall be duplicate or reconciliation candidate evidence only.
`031` — Matching serial shall be duplicate or reconciliation candidate evidence only.
`032` — Matching Model shall be duplicate or reconciliation candidate evidence only.
`033` — Matching labels or device facts shall not silently promote, merge, or reassign Device References or Network Elements.
