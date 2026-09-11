# SOMA Beta Normalization CP-002 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0028`–`BETA-REQ-0052`.  
Clause identities are stable normative references. They preserve the detailed mechanics removed from compact governing obligations.

## `BETA-REQ-0028`

**Governing obligation:** Every Contact shall retain an independent SOMA identity that cannot be established, merged, or selected solely from descriptive or matching attributes.

- **`CONTACT-ID-001`** — Every Contact shall retain an immutable opaque internal SOMA identifier as its relational identity.
- **`CONTACT-ID-002`** — A Contact name shall be descriptive data rather than relational identity.
- **`CONTACT-ID-003`** — Multiple Contacts may legitimately have equal names.
- **`CONTACT-ID-004`** — A normalized email address shall be matching evidence rather than Contact identity.
- **`CONTACT-ID-005`** — Email matching shall occur only within the applicable Customer Organization affiliation scope or the unbound Contact scope.
- **`CONTACT-ID-006`** — Equal normalized email addresses shall not impose a universal global Contact uniqueness rule.
- **`CONTACT-ID-007`** — When available evidence matches multiple Contacts, the candidate set shall remain ambiguous.
- **`CONTACT-ID-008`** — Ambiguous Contact matching shall require operator review before selecting, linking, or merging a Contact.
- **`CONTACT-ID-009`** — SOMA shall not automatically merge Contacts solely from descriptive or matching evidence.

## `BETA-REQ-0029`

**Governing obligation:** A Contact shall preserve one continuous identity independently of Customer Organization affiliation, while affiliation changes and operational organization context remain explicit historical relationships.

- **`CONTACT-AFF-001`** — Contact identity shall remain independent of Customer Organization affiliation.
- **`CONTACT-AFF-002`** — A Contact may have no current Customer Organization affiliation or at most one current affiliation.
- **`CONTACT-AFF-003`** — Changing affiliation shall preserve the same Contact identity.
- **`CONTACT-AFF-004`** — An affiliation change shall close the previous affiliation as historical evidence.
- **`CONTACT-AFF-005`** — An affiliation change shall establish the reviewed new current affiliation.
- **`CONTACT-AFF-006`** — Affiliation changes shall be recorded in audit/lifecycle evidence.
- **`CONTACT-AFF-007`** — Equal names shall not establish shared Contact identity or authorize an affiliation change.
- **`CONTACT-AFF-008`** — Changing an existing Contact's affiliation shall require explicit operator identification using stronger accepted evidence than equal names alone.
- **`CONTACT-AFF-009`** — Operational records shall preserve both the Contact reference and Customer Organization context effective when the relationship was recorded.
- **`CONTACT-AFF-010`** — When a selected Contact's current affiliation differs from a Service Request's Customer Organization, SOMA shall warn the operator.
- **`CONTACT-AFF-011`** — That mismatch shall not silently reassign the Contact.
- **`CONTACT-AFF-012`** — That mismatch shall not silently duplicate the Contact.
- **`CONTACT-AFF-013`** — An otherwise valid imported Service Request shall not be rejected solely because of a Contact-affiliation mismatch.
- **`CONTACT-AFF-014`** — The mismatch shall require reviewed confirmation, correction, or reconciliation.

## `BETA-REQ-0030`

**Governing obligation:** SOMA Beta shall reconcile reference candidates through deterministic, scope-aware exact matching and shall preserve ambiguity rather than infer identity from approximate similarity.

- **`MATCH-001`** — Advanced Search reference candidate matching shall use deterministic exact governed normalized keys.
- **`MATCH-002`** — Matching normalization shall apply Unicode NFKC compatibility normalization.
- **`MATCH-003`** — Matching normalization shall collapse surrounding and internal Unicode whitespace.
- **`MATCH-004`** — Matching normalization shall apply Unicode case folding.
- **`MATCH-005`** — Matching normalization shall preserve accents.
- **`MATCH-006`** — Matching normalization shall preserve punctuation.
- **`MATCH-007`** — SOMA shall not use fuzzy, similarity, or phonetic matching to establish reference identity.
- **`MATCH-008`** — Candidate comparison shall occur within the applicable governed scope.
- **`MATCH-009`** — If more than one active record in that scope produces the same exact key, the result shall be ambiguous.
- **`MATCH-010`** — An ambiguous result shall not trigger guessed selection, merge, or mutation.
- **`MATCH-011`** — Ambiguity shall require operator review or stronger governed identity evidence before resolution.

## `BETA-REQ-0031`

**Governing obligation:** Contact lifecycle operations shall preserve affiliation history, prevent archival from stranding active dependencies, and require explicit reactivation before renewed operational use.

- **`CONTACT-LIFE-001`** — A Contact may be created with no Customer Organization affiliation or exactly one active affiliation.
- **`CONTACT-LIFE-002`** — Contact affiliation, reassignment, and removal shall follow the governed historical-affiliation rules.
- **`CONTACT-LIFE-003`** — Archived Contacts and other archived master records governed by the shared reference lifecycle shall remain visible where required to interpret historical evidence.
- **`CONTACT-LIFE-004`** — Archived Contacts and other archived master records governed by that lifecycle shall not receive new active operational relationships.
- **`CONTACT-LIFE-005`** — Contact archival shall be blocked when it would strand an active dependent record.
- **`CONTACT-LIFE-006`** — A blocking dependency shall first be completed, cancelled, reassigned, or otherwise resolved through an authorized workflow.
- **`CONTACT-LIFE-007`** — Reactivation of an archived Contact shall require an explicit action.
- **`CONTACT-LIFE-008`** — Reactivation shall preserve audit/lifecycle evidence.
- **`CONTACT-LIFE-009`** — Contact archival and reactivation shall conform to the shared history-preserving reference-record lifecycle rather than define a competing archival model.

## `BETA-REQ-0032`

**Governing obligation:** Every Spare Request shall preserve its requester as a reusable Contact relationship governed by Contact lifecycle and historical-evidence rules.

- **`REQUESTER-001`** — A Spare Request requester shall reference a reusable Contact rather than a request-private person identity.
- **`REQUESTER-002`** — Requester shall be a contextual role of the Contact and shall not redefine Contact identity.
- **`REQUESTER-003`** — An archived Contact shall not be selectable as requester for a new Spare Request.
- **`REQUESTER-004`** — A Contact shall not be archived while serving as requester for an active nonterminal Spare Request.
- **`REQUESTER-005`** — A terminal Spare Request shall retain its historical requester Contact relationship.
- **`REQUESTER-006`** — Terminal Spare Request history shall preserve requester evidence effective for that request so later Contact or affiliation changes do not rewrite it.

## `BETA-REQ-0033`

**Governing obligation:** A Site shall preserve stable Customer Organization ownership and history-safe lifecycle behavior once it participates in operational Infrastructure.

- **`SITE-LIFE-001`** — A Site's Customer Organization ownership shall be stable and shall not be transferable through ordinary editing.
- **`SITE-LIFE-002`** — Changing Site ownership shall be permitted only as an explicitly reasoned correction of erroneous initial ownership.
- **`SITE-LIFE-003`** — Such an ownership correction shall be permitted only before the Site, any Cloud Deployment at the Site, or any placed Network Element has acquired operational history.
- **`SITE-LIFE-004`** — Operational history associated with any Cloud Deployment at the Site shall block an ownership correction.
- **`SITE-LIFE-005`** — Operational history associated with any placed Network Element at the Site shall block an ownership correction.
- **`SITE-LIFE-006`** — An authorized Site ownership correction shall preserve its reason and audited lifecycle evidence.
- **`SITE-LIFE-007`** — Site archival shall be blocked while it would strand active or unfinished dependent operational relationships.
- **`SITE-LIFE-008`** — Blocking dependencies include active Cloud Deployments, Rooms, Racks, Network Elements, Tasks, Objectives, Spare Needs, Spare Requests, and other unfinished operational relationships.
- **`SITE-LIFE-009`** — Blocking dependencies shall be resolved through their authorized lifecycle workflows before Site archival may proceed.
- **`SITE-LIFE-010`** — Archiving a Site shall preserve its dedicated Dispatch Location unless a separately reviewed lifecycle action explicitly authorizes another result.
- **`SITE-LIFE-011`** — Site archival shall preserve protected historical evidence unless a separately reviewed lifecycle action explicitly authorizes another result.

## `BETA-REQ-0034`

**Governing obligation:** Dispatch Location lifecycle shall preserve customer neutrality and historical evidence while preventing archival or active reuse that conflicts with Site or unfinished logistics dependencies.

- **`DISPATCH-LIFE-001`** — Dispatch Locations shall not maintain Customer Organization availability or preference relationships.
- **`DISPATCH-LIFE-002`** — An archived Dispatch Location shall remain visible where required to interpret historical evidence.
- **`DISPATCH-LIFE-003`** — An archived Dispatch Location shall not be selectable for new Spare Request, dispatch, pickup, or Fault Tag operations.
- **`DISPATCH-LIFE-004`** — A Dispatch Location linked as the dedicated location of an active Site shall not be independently eligible for archival.
- **`DISPATCH-LIFE-005`** — A Dispatch Location shall not be archived while referenced by an unfinished logistics operation.
- **`DISPATCH-LIFE-006`** — A Site-dedicated Dispatch Location shall not be archived independently of a reviewed Site lifecycle action.
- **`DISPATCH-LIFE-007`** — Reactivation of an archived Dispatch Location shall require an explicit action.
- **`DISPATCH-LIFE-008`** — Dispatch Location reactivation shall preserve audit/lifecycle evidence.

## `BETA-REQ-0035`

**Governing obligation:** The singleton Local User Profile shall provide local administrator authentication without allowing its credentials or profile data to become operational-data encryption authority.

- **`AUTH-001`** — Each SOMA Beta installation shall maintain exactly one authenticating Local User Profile.
- **`AUTH-002`** — The singleton Local User Profile shall be configured once as the installation's authentication profile rather than recreated as additional authentication profiles.
- **`AUTH-003`** — The Local User Profile password shall be used only to authenticate the local administrator.
- **`AUTH-004`** — SOMA shall persist the password only as a salted, memory-hard verifier rather than a recoverable copy of the password.
- **`AUTH-005`** — The password, username, and other Local User Profile fields shall not constitute or derive operational-data encryption keys.
- **`AUTH-006`** — Changing authentication credentials shall not by itself re-encrypt, invalidate, or endanger independently protected operational data.
- **`AUTH-007`** — Automatic login shall be optional.
- **`AUTH-008`** — Automatic login shall use Windows-protected authentication material.
- **`AUTH-009`** — Automatic login shall not store the reusable Local User Profile password.
- **`AUTH-010`** — Local User Profile metadata shall remain separate from Contact identity and shall not acquire encryption-key authority.

## `BETA-REQ-0036`

**Governing obligation:** SOMA Beta shall protect live operational data with authenticated encryption under an independently generated Windows-protected data-encryption key whose lifecycle is separate from administrator authentication credentials.

- **`DATA-CRYPT-001`** — Protected local SOMA data shall be encrypted using authenticated encryption.
- **`DATA-CRYPT-002`** — Live protected data shall use a cryptographically random data-encryption key generated independently of Local User Profile authentication credentials.
- **`DATA-CRYPT-003`** — The live data-encryption key shall contain at least 256 bits of cryptographically generated key material.
- **`DATA-CRYPT-004`** — The live data-encryption key shall not be derived from the application password, username, or other reusable Local User Profile credential or field.
- **`DATA-CRYPT-005`** — The live data-encryption key shall itself be protected using an approved Windows-bound secure-storage mechanism.
- **`DATA-CRYPT-006`** — Changing the application password shall not require re-encryption of protected operational data.
- **`DATA-CRYPT-007`** — Resetting or replacing authentication credentials shall not invalidate the live data-encryption key or endanger correctly protected operational data.
- **`DATA-CRYPT-008`** — Authentication-credential lifecycle and live-data key lifecycle shall remain separately governed security concerns.
- **`DATA-CRYPT-009`** — Exact authenticated-encryption, Windows key-protection, rotation, recovery, and related cryptographic mechanics shall be resolved in the accepted Security LLD without weakening these product constraints.

## `BETA-REQ-0037`

**Governing obligation:** SOMA Beta shall export each portable backup as an independently encrypted, self-verifiable backup set with high-entropy recovery and required detached integrity/authenticity artifacts, and shall successfully validate that set before restore may modify live data.

- **`BACKUP-CRYPT-001`** — Every exportable backup containing protected SOMA data shall be protected with authenticated encryption.
- **`BACKUP-CRYPT-002`** — Each protected exportable backup shall use an independently generated cryptographically random backup-encryption key.
- **`BACKUP-CRYPT-003`** — Backup protection shall remain independent from Local User Profile authentication credentials and from the Windows-bound live-data key protection boundary.
- **`BACKUP-CRYPT-004`** — Portable recovery shall use a generated high-entropy recovery secret capable of recovering the protected backup independently of the originating installation's authentication credentials.
- **`BACKUP-CRYPT-005`** — The portable recovery secret shall provide at least 128 bits of entropy.
- **`BACKUP-CRYPT-006`** — Where represented as words for operator custody, seven randomly selected words or an equivalent representation meeting the required entropy boundary is the recommended form.
- **`BACKUP-CRYPT-007`** — The accepted seven-word recovery concept shall not be implemented or presented as a seven-character password.
- **`BACKUP-CRYPT-008`** — Cryptographic hashes may verify integrity but shall not substitute for encryption.
- **`BACKUP-CRYPT-009`** — Restore shall authenticate the protected backup before modifying authoritative live data.
- **`BACKUP-CRYPT-010`** — Restore shall complete required integrity verification before modifying authoritative live data.
- **`BACKUP-CRYPT-011`** — A backup that fails required authentication or verification shall not partially alter the live datastore.
- **`BACKUP-CRYPT-012`** — Exact backup encryption, backup-key protection, recovery-secret representation, detached-artifact format, and restore mechanics shall be resolved by the Security LLD without weakening the accepted independence, entropy, or pre-mutation verification constraints.
- **`BACKUP-CRYPT-013`** — A successful portable-backup export shall produce a complete backup set containing the encrypted payload and the required detached integrity/authenticity companion artifacts.
- **`BACKUP-CRYPT-014`** — The backup set shall include a detached digest or manifest companion artifact, such as the requested MDA-style sidecar or an equivalently governed mechanism, bound to the exported backup payload.
- **`BACKUP-CRYPT-015`** — The backup set shall include a detached PKCS#7/CMS signature artifact or an equivalently governed authenticity mechanism.
- **`BACKUP-CRYPT-016`** — Required companion artifacts shall be bound to the exact backup they accompany and shall not be validly reusable as verification evidence for a different backup payload.
- **`BACKUP-CRYPT-017`** — Missing, malformed, mismatched, or invalid required companion artifacts shall cause restore validation to fail before authoritative live data is modified.
- **`BACKUP-CRYPT-018`** — A portable-backup export shall not report successful completion until its encrypted payload and required companion verification artifacts have been produced as a complete backup set.

## `BETA-REQ-0038`

**Governing obligation:** Service Requests shall provide pivotal operational context without becoming universal parents, while each related domain entity retains its explicitly governed ownership and relationship path.

- **`SR-HUB-001`** — A Service Request shall act as a pivotal operational connector when applicable.
- **`SR-HUB-002`** — A Service Request shall not be the universal persistence or lifecycle parent of SOMA operational entities.
- **`SR-HUB-003`** — An RFC may exist without a Service Request where its own creation rules permit.
- **`SR-HUB-004`** — A Local Task may exist without a Service Request where its own creation rules permit.
- **`SR-HUB-005`** — An Objective may exist without a Service Request when its constituent Tasks carry no Service Request relationship.
- **`SR-HUB-006`** — Infrastructure records may exist without a Service Request.
- **`SR-HUB-007`** — Standalone Inventory stock and Local Spare Units may exist without a Service Request where their own rules permit.
- **`SR-HUB-008`** — Every WFM shall belong to exactly one RFC.
- **`SR-HUB-009`** — Every Spare Need shall belong to exactly one Service Request.
- **`SR-HUB-010`** — An officially identified Spare Request shall derive exactly one Service Request relationship through its selected Spare Needs.
- **`SR-HUB-011`** — All Spare Needs selected into one governed Spare Request shall belong to the same Service Request.
- **`SR-HUB-012`** — Each RMA under an official Spare Request shall derive the same exactly one Service Request relationship through that Spare Request's selected Spare Needs and shall not maintain an independently contradictory Service Request relationship.
- **`SR-HUB-013`** — An Objective shall relate to a Service Request only through one or more constituent Tasks.
- **`SR-HUB-014`** — An Objective shall not persist an independently authoritative direct Service Request relationship.

## `BETA-REQ-0039`

**Governing obligation:** Direct Service Request relationships shall terminate at master RFCs, with subordinate RFCs inheriting Service Request context exclusively through their master hierarchy.

- **`SR-RFC-001`** — The direct Service Request-to-RFC relationship shall be many-to-many.
- **`SR-RFC-002`** — A direct Service Request-to-RFC relationship shall target only a master RFC.
- **`SR-RFC-003`** — A subordinate RFC shall not receive an independently authoritative direct Service Request relationship.
- **`SR-RFC-004`** — A subordinate RFC shall derive its applicable Service Request context through its owning master RFC.
- **`SR-RFC-005`** — Service Request workbench visibility of subordinate RFC context shall be inherited through the linked master RFC branch.
- **`SR-RFC-006`** — Adding or removing an SR-to-master-RFC relationship shall change inherited subordinate context without changing subordinate RFC identity.
- **`SR-RFC-007`** — SOMA shall not persist a duplicate subordinate-level relationship merely to reproduce context already derived through the master RFC.

## `BETA-REQ-0040`

**Governing obligation:** RFCs shall form a strict two-level acyclic master/subordinate hierarchy whose corrections preserve identity, protected history, and inherited operational context.

- **`RFC-HIER-001`** — Every RFC shall be either a master RFC or a subordinate RFC.
- **`RFC-HIER-002`** — A master RFC may own zero or more subordinate RFCs.
- **`RFC-HIER-003`** — A subordinate RFC shall belong to exactly one master RFC.
- **`RFC-HIER-004`** — A subordinate RFC shall never own subordinate RFCs.
- **`RFC-HIER-005`** — RFC hierarchy shall not exceed the accepted two levels.
- **`RFC-HIER-006`** — Hierarchy creation or correction shall not introduce cycles.
- **`RFC-HIER-007`** — Hierarchy changes shall not detach or rewrite protected operational history associated with an RFC or its branch.
- **`RFC-HIER-008`** — Hierarchy changes shall not silently alter inherited Service Request context; any resulting inherited-context recalculation or change shall be explicit and governed.
- **`RFC-HIER-009`** — An authorized hierarchy correction shall preserve the identities of affected RFCs.

## `BETA-REQ-0041`

**Governing obligation:** Every WFM shall retain exactly one RFC owner and at most one Objective membership, with unscheduled state and regrouping handled without duplicating WFM identity.

- **`WFM-REL-001`** — Every WFM shall belong to exactly one RFC.
- **`WFM-REL-002`** — A WFM shall belong to at most one Objective at a time.
- **`WFM-REL-003`** — A WFM without an accepted timeframe may remain valid and unscheduled.
- **`WFM-REL-004`** — Absence of an accepted timeframe shall not fabricate Objective membership.
- **`WFM-REL-005`** — When reviewed regrouping changes a WFM's Objective membership, the existing WFM shall move between Objectives.
- **`WFM-REL-006`** — Regrouping shall not create duplicate WFM entities or simultaneous Objective memberships merely to represent a scheduling change.
- **`WFM-REL-007`** — Moving or removing Objective membership shall preserve the WFM's immutable identity and owning RFC relationship.

## `BETA-REQ-0042`

**Governing obligation:** Distinct WFM identities shall remain independent attempts, and potentially competing attempts shall be explicitly reviewed without identity collapse or overlapping-Objective workarounds.

- **`WFM-ATTEMPT-001`** — Every WFM attempt shall use a distinct canonical `TK##############` identity.
- **`WFM-ATTEMPT-002`** — One WFM attempt shall never overwrite another WFM identity or its protected evidence.
- **`WFM-ATTEMPT-003`** — Distinct WFM identifiers shall not be collapsed into one WFM merely because descriptive facts appear similar.
- **`WFM-ATTEMPT-004`** — A later attempt shall not reactivate an earlier WFM by reusing or mutating that earlier identity.
- **`WFM-ATTEMPT-005`** — Multiple WFMs owned by the same RFC may belong to one Objective when reviewed as genuinely distinct activities.
- **`WFM-ATTEMPT-006`** — More than one active WFM attempt representing the same activity lineage in the same overlapping period shall be treated as a conflict.
- **`WFM-ATTEMPT-007`** — That conflict shall require reviewed classification as distinct work, retry lineage, cancellation, source error, or unresolved evidence.
- **`WFM-ATTEMPT-008`** — While such a conflict remains unresolved, every involved WFM identity and its evidence shall remain preserved.
- **`WFM-ATTEMPT-009`** — SOMA shall not create overlapping Objectives merely to evade the competing-attempt conflict.
- **`WFM-ATTEMPT-010`** — Multiple Local Tasks may relate to the same RFC according to their own workflow and shall not inherit the WFM-specific attempt restriction solely from sharing that RFC.

## `BETA-REQ-0043`

**Governing obligation:** A persisted Objective shall be a first-class operational entity with one accepted timeframe and at least one Task, without requiring unrelated SR, RFC, Inventory, or Infrastructure context.

- **`OBJ-EXIST-001`** — A Maintenance Window Objective shall be a first-class persistent operational entity with its own immutable SOMA identity.
- **`OBJ-EXIST-002`** — A persisted Objective shall have one accepted timeframe.
- **`OBJ-EXIST-003`** — A persisted Objective shall contain at least one Task.
- **`OBJ-EXIST-004`** — An Objective shall not require a Service Request merely to exist.
- **`OBJ-EXIST-005`** — An Objective shall not require an RFC or WFM when its constituent Tasks do not carry those relationships.
- **`OBJ-EXIST-006`** — An Objective shall not require a Spare Request or Spare Part Unit merely to exist.
- **`OBJ-EXIST-007`** — An Objective shall not require a Network Element merely to exist.
- **`OBJ-EXIST-008`** — An unfinished UI creation draft may temporarily contain zero Tasks before persistence is attempted.
- **`OBJ-EXIST-009`** — A zero-Task UI draft shall not become an authoritative persisted Objective.
- **`OBJ-EXIST-010`** — Objective creation shall remain transient or fail persistence until at least one eligible Task is attached and required Objective invariants are satisfied.

## `BETA-REQ-0044`

**Governing obligation:** An Objective shall derive all Service Request context exclusively through its constituent Tasks and shall expose that relationship provenance without maintaining independent Objective-level SR authority.

- **`OBJ-SR-001`** — An Objective shall not persist an independently authoritative direct Service Request relationship.
- **`OBJ-SR-002`** — Every Service Request associated with an Objective shall be derived through one or more constituent Tasks.
- **`OBJ-SR-003`** — For a Local Task, Objective Service Request context shall derive from the Task's direct Service Request relationships.
- **`OBJ-SR-004`** — For a WFM Task, Objective Service Request context shall derive through its owning RFC and applicable master-RFC Service Request relationships.
- **`OBJ-SR-005`** — If multiple constituent Tasks derive the same Service Request, the Objective may present it once while preserving all contributing provenance.
- **`OBJ-SR-006`** — Adding or removing Service Request context from an Objective workflow shall modify the appropriate Task or RFC-authoritative relationship rather than create an Objective-level relationship.
- **`OBJ-SR-007`** — Changes to authoritative Task or RFC Service Request relationships shall update the Objective's derived Service Request context.
- **`OBJ-SR-008`** — The Objective UI shall expose how each displayed Service Request is derived.
- **`OBJ-SR-009`** — Where relevant, provenance shall distinguish direct Local Task linkage from WFM-to-RFC-to-master-RFC-derived linkage.
- **`OBJ-SR-010`** — Persistence shall not maintain a shadow Objective-to-Service-Request relation as competing authority for the derived view.

## `BETA-REQ-0045`

**Governing obligation:** A Service Request shall not require fabricated operational work and may participate in zero or multiple Objectives solely through its Tasks, subject to the global Task scheduling and grouping rules.

- **`SR-WORK-001`** — A Service Request may validly have zero Tasks.
- **`SR-WORK-002`** — A Service Request may validly have zero Objective context.
- **`SR-WORK-003`** — SOMA shall not create, require, or infer a Task or Objective solely to permit completion of a Service Request.
- **`SR-WORK-004`** — Customer-resolved, informational, Non-fault, and other legitimately completed cases requiring no planned maintenance may remain Task-free and Objective-free.
- **`SR-WORK-005`** — When a Service Request participates in Objectives, that context shall derive only through related Tasks.
- **`SR-WORK-006`** — A Service Request may retain Task-derived relationships to any number of terminal Objectives.
- **`SR-WORK-007`** — A Service Request may participate in multiple unfinished Objectives when the accepted timeframes of its participating Tasks do not overlap across those Objectives.
- **`SR-WORK-008`** — SOMA shall not impose an arbitrary one-unfinished-Objective-per-Service-Request rule.
- **`SR-WORK-009`** — Scheduling conflict shall be determined from accepted Task timeframes under the global grouping contract rather than merely from shared Service Request identity.
- **`SR-WORK-010`** — Overlapping Tasks shall follow the global Objective grouping contract rather than an SR-specific limit.

## `BETA-REQ-0046`

**Governing obligation:** Retries shall create new Task attempts linked through immutable predecessor lineage, while Objective retry context and membership shall remain derived from the participating Tasks and normal scheduling rules.

- **`TASK-RETRY-001`** — Retrying work shall create a new Task attempt with a new immutable Task identity.
- **`TASK-RETRY-002`** — The earlier Task attempt and its protected evidence shall remain unchanged when a retry is created.
- **`TASK-RETRY-003`** — Every retry Task shall reference exactly one immediate predecessor Task.
- **`TASK-RETRY-004`** — A Task attempt shall have at most one direct retry successor.
- **`TASK-RETRY-005`** — Longer retry history shall be represented through successive immediate predecessor/successor links rather than by rewriting earlier lineage.
- **`TASK-RETRY-006`** — A Local Task retry shall begin from a reviewed copy of the selected predecessor's applicable operational relationships.
- **`TASK-RETRY-007`** — The cloned Local Task retry relationships shall be reviewed rather than silently propagated as unquestioned current truth.
- **`TASK-RETRY-008`** — A Local Task retry shall receive its own new accepted timeframe.
- **`TASK-RETRY-009`** — A WFM retry shall require a distinct canonical `TK##############` identifier.
- **`TASK-RETRY-010`** — A prior WFM shall not be reopened, overwritten, or reactivated to represent a retry attempt.
- **`TASK-RETRY-011`** — A retry Task shall be assigned to an Objective through the normal accepted timeframe-overlap algorithm.
- **`TASK-RETRY-012`** — A retry Task shall not automatically inherit the predecessor Task's Objective membership solely because it is a retry.
- **`TASK-RETRY-013`** — Objective-level predecessor or supersession context shall derive from the retry relationships of constituent Tasks.
- **`TASK-RETRY-014`** — SOMA shall not enforce a one-to-one Objective retry chain.
- **`TASK-RETRY-015`** — One Objective may derive retry context from multiple earlier Objectives when its constituent retry Tasks have different predecessors.

## `BETA-REQ-0047`

**Governing obligation:** Scheduled Objectives and Tasks shall use valid accepted temporal intervals without rounding or invented timestamps, and Objective membership shall require an accepted Task timeframe.

- **`OBJ-TIME-001`** — Every scheduled Objective shall have a valid accepted start and end stored as canonical UTC instants.
- **`OBJ-TIME-002`** — Canonical Objective instants shall preserve whole-second precision under the shared temporal contract.
- **`OBJ-TIME-003`** — An Objective's accepted end shall be strictly later than its accepted start.
- **`OBJ-TIME-004`** — Objective boundaries may occur at any valid minute.
- **`OBJ-TIME-005`** — SOMA shall not silently round, snap, or coerce Objective boundaries to predefined increments such as `:00` or `:30`.
- **`OBJ-TIME-006`** — A Task without an accepted timeframe shall remain unscheduled and shall not receive synthetic start or end timestamps.
- **`OBJ-TIME-007`** — An unscheduled Task shall not become a member of an Objective until an accepted timeframe exists.
- **`OBJ-TIME-008`** — Once a Task receives an accepted timeframe, Objective membership shall be determined through the normal grouping rules rather than fabricated retroactively.

## `BETA-REQ-0048`

**Governing obligation:** Eligible scheduled Tasks shall create or join Objectives through one uniform overlap algorithm, while RFC hierarchy contributes review context and warnings without fabricating or reclassifying work.

- **`OBJ-GROUP-001`** — Creating, registering, or importing an eligible future Task with an accepted timeframe shall trigger Objective grouping evaluation.
- **`OBJ-GROUP-002`** — A cancelled Task shall not create or join an Objective merely because timeframe evidence exists.
- **`OBJ-GROUP-003`** — The grouping algorithm shall apply whether the eligible Task is Local, a master-RFC WFM, or a subordinate-RFC WFM.
- **`OBJ-GROUP-004`** — An eligible Task shall create a new Objective or join an applicable Objective through the accepted overlap algorithm.
- **`OBJ-GROUP-005`** — When the Task belongs to an RFC hierarchy, SOMA shall resolve and display the relevant master and subordinate RFC context.
- **`OBJ-GROUP-006`** — Relevant sibling RFC context and colliding Tasks shall be visible during grouping/review.
- **`OBJ-GROUP-007`** — Missing same-window WFMs for relevant subordinate RFCs shall be surfaced as warnings.
- **`OBJ-GROUP-008`** — A missing same-window subordinate WFM warning shall not by itself block Objective formation.
- **`OBJ-GROUP-009`** — SOMA shall not fabricate a WFM to complete hierarchy symmetry or silence the warning.
- **`OBJ-GROUP-010`** — The operator may create a Local Task under a master RFC.
- **`OBJ-GROUP-011`** — The operator may create a Local Task under a subordinate RFC.
- **`OBJ-GROUP-012`** — A Local Task created under either RFC role shall remain a Local Task and shall not acquire WFM identity merely from the RFC relationship.

## `BETA-REQ-0049`

**Governing obligation:** Device References shall remain independently usable in operational relationships before Infrastructure regularization, with Objective Device context derived through Tasks and all existing relationships preserved when a Device Reference is promoted.

- **`DEVICE-REF-001`** — A Service Request may relate directly to zero or more affected Device References.
- **`DEVICE-REF-002`** — A Local Task or WFM Task may relate directly to zero or more affected Device References.
- **`DEVICE-REF-003`** — An SR-to-Device or Task-to-Device relationship shall not require a Spare Need, Spare Request, Fault Part/Fault Tag workflow, or Spare Part Unit.
- **`DEVICE-REF-004`** — A Device Reference may remain usable as a provisional or external operational reference without being a registered Infrastructure Network Element.
- **`DEVICE-REF-005`** — A Device Reference may resolve to a registered Infrastructure Network Element.
- **`DEVICE-REF-006`** — SOMA shall not require Infrastructure regularization merely to preserve otherwise valid operational Device relationships.
- **`DEVICE-REF-007`** — An Objective shall derive its affected Device References from its constituent Tasks.
- **`DEVICE-REF-008`** — An Objective shall not maintain an independently authoritative direct Device relationship.
- **`DEVICE-REF-009`** — Where multiple Tasks contribute the same Device Reference, the Objective may present it once while preserving contributing Task provenance.
- **`DEVICE-REF-010`** — Promoting or regularizing a Device Reference shall preserve operational identity continuity rather than replace it with an unrelated operational reference.
- **`DEVICE-REF-011`** — Regularization shall preserve existing Service Request and Task relationships.
- **`DEVICE-REF-012`** — Regularization shall preserve Objective context derived from affected Tasks.
- **`DEVICE-REF-013`** — Regularization shall preserve existing Spare Need relationships associated with the Device Reference.
- **`DEVICE-REF-014`** — Regularization shall preserve protected historical relationships and evidence.

## `BETA-REQ-0050`

**Governing obligation:** Due Objective attempts shall require explicit review while preserving independent Task outcomes, true execution chronology, Inventory fact authority, and the distinction between outcome correction and retry.

- **`OBJ-REVIEW-001`** — A due completed or incomplete Objective attempt shall be surfaced for explicit operator review.
- **`OBJ-REVIEW-002`** — SOMA shall not silently convert a due completed or incomplete Objective attempt into an accepted reviewed state.
- **`OBJ-REVIEW-003`** — `reviewed_at` shall record when the operator accepted the review.
- **`OBJ-REVIEW-004`** — `reviewed_at` shall not fabricate Task or Objective execution chronology.
- **`OBJ-REVIEW-005`** — Every Task outcome within an Objective shall remain independently reviewable.
- **`OBJ-REVIEW-006`** — Objective review shall preserve distinct constituent Task outcomes rather than replace them with one inferred Objective-level outcome.
- **`OBJ-REVIEW-007`** — Objective success, completion, or review acceptance shall not by itself establish physical spare use.
- **`OBJ-REVIEW-008`** — Any physical spare-use fact shall arise from its separately governed Inventory or Task-outcome evidence rather than from Objective success alone.
- **`OBJ-REVIEW-009`** — An outcome correction shall append against the exact previously accepted outcome being corrected.
- **`OBJ-REVIEW-010`** — Correction shall preserve the earlier accepted outcome and evidence rather than overwrite or erase them.
- **`OBJ-REVIEW-011`** — An authorized outcome correction shall not by itself create a new Task attempt or Task identity.
- **`OBJ-REVIEW-012`** — When work is to be performed again rather than recorded evidence corrected, SOMA shall use Task retry lineage and create a new Task attempt.

## `BETA-REQ-0051`

**Governing obligation:** The Objectives workspace shall expose the governed Objective lifecycle and Task-management actions while preserving Task- and domain-owned relationship authority and protected operational history.

- **`OBJ-UI-001`** — The Objectives workspace shall allow the operator to create an Objective when persistence invariants are satisfied.
- **`OBJ-UI-002`** — Creation of a persisted Objective shall require at least one eligible Task.
- **`OBJ-UI-003`** — The operator shall be able to edit an Objective's reviewed timeframe through the governed scheduling workflow.
- **`OBJ-UI-004`** — The operator shall be able to add eligible Tasks to an Objective subject to governing membership and scheduling rules.
- **`OBJ-UI-005`** — The operator shall be able to remove an eligible Task from an Objective when the resulting state remains valid.
- **`OBJ-UI-006`** — The operator shall be able to manually regroup eligible Tasks through a reviewed action.
- **`OBJ-UI-007`** — The Objectives workspace shall expose the governed controls required to execute an Objective and its Tasks.
- **`OBJ-UI-008`** — The operator shall be able to perform the explicit Objective and Task review actions required by the accepted outcome contract.
- **`OBJ-UI-009`** — The operator shall be able to invoke governed cancellation workflows when lifecycle preconditions are satisfied.
- **`OBJ-UI-010`** — The operator shall be able to archive an eligible Objective while preserving protected operational history.
- **`OBJ-UI-011`** — The Objectives workspace shall allow the operator to initiate retry from an eligible Task rather than treating the Objective as a single retry identity.
- **`OBJ-UI-012`** — Service Request relationships exposed in the Objective workflow shall be managed through the authoritative Task or RFC relationship path.
- **`OBJ-UI-013`** — RFC context shall not be attached to an Objective as independently authoritative Objective-owned relationship merely for UI convenience.
- **`OBJ-UI-014`** — Affected Device context shall derive through constituent Tasks rather than an Objective-owned Device relationship.
- **`OBJ-UI-015`** — Inventory relationships and physical inventory effects shall be managed through the Task or Inventory records that own those facts.
- **`OBJ-UI-016`** — Hard deletion shall not serve as the correction mechanism for executed, reviewed, or otherwise protected Objective history.
- **`OBJ-UI-017`** — Any Objective hard-deletion eligibility shall follow the global and domain-specific deletion rules.
- **`OBJ-UI-018`** — A newly created Objective may legitimately lack Service Request, RFC, WFM, Device, and Inventory context.
- **`OBJ-UI-019`** — A persisted Objective may not lack its required Task.

## `BETA-REQ-0052`

**Governing obligation:** Service Requests and RFCs shall preserve independently editable Working Notes as SOMA-owned historical evidence whose creation facts, edit history, and audited deletion state remain protected from import reconciliation.

- **`NOTE-HIST-001`** — Every Service Request and RFC shall support multiple independent Working Notes.
- **`NOTE-HIST-002`** — Each persistent Working Note shall retain its own immutable SOMA identity.
- **`NOTE-HIST-003`** — A Working Note's creation timestamp shall remain immutable after creation.
- **`NOTE-HIST-004`** — Each Working Note shall preserve its creating Local User Profile.
- **`NOTE-HIST-005`** — The operator may edit Working Note content.
- **`NOTE-HIST-006`** — Editing a Working Note shall not alter its creation timestamp.
- **`NOTE-HIST-007`** — Every edit shall record a modification timestamp.
- **`NOTE-HIST-008`** — Every edit shall preserve the previous note value in audit history.
- **`NOTE-HIST-009`** — Deleting a Working Note shall remove it from the active workbench view.
- **`NOTE-HIST-010`** — Working Note deletion shall preserve an audited deletion record.
- **`NOTE-HIST-011`** — Preserved deletion evidence shall follow the accepted retention policy.
- **`NOTE-HIST-012`** — Imported Service Request or RFC population shall not overwrite, merge, or delete Working Notes.
- **`NOTE-HIST-013`** — Import reconciliation shall preserve Working Note identity, creation facts, edit history, and audited deletion evidence.
