# SOMA Beta Normalization CP-003 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0053`–`BETA-REQ-0077`.  
Clause identities are stable normative references. Under each requirement, the displayed prefix plus the three-digit suffix forms the full clause ID (for example, under prefix `SR-MANUAL`, `001` means `SR-MANUAL-001`).

## `BETA-REQ-0053` — prefix `SR-MANUAL`

**Governing obligation:** SOMA Beta shall support manual Service Request creation and reviewed adoption or exact-source reconciliation of official SR identity without replacing the record's immutable identity or SOMA-owned operational state.

`001` — An operator shall be able to create a Service Request manually.
`002` — When the official external identifier is known at creation, the Service Request shall use the canonical eight-digit SR identity.
`003` — When the official external identifier is unknown at creation, SOMA shall assign the next non-reusable `LSR-########` identifier.
`004` — Local SR allocation shall follow the accepted `BETA-REQ-0011` sequence and identity rules.
`005` — A later Advanced Search observation matching an existing official SR identity shall reconcile into that same Service Request.
`006` — Exact-source reconciliation shall preserve the Service Request's immutable internal SOMA identity.
`007` — Exact-source reconciliation shall preserve existing governed relationships.
`008` — Exact-source reconciliation shall preserve Working Notes.
`009` — Exact-source reconciliation shall preserve Task links.
`010` — Exact-source reconciliation shall preserve Inventory context.
`011` — Exact-source reconciliation shall preserve review state and audit history.
`012` — Attaching an official SR identity to an existing LSR shall require an explicit reviewed operator action.
`013` — The proposed official identifier shall satisfy canonical SR validation and shall not already belong to another Service Request.
`014` — Accepted attachment of an official SR identity shall not replace the Service Request record or erase its local identity/history.
`015` — SOMA shall never infer LSR-to-official-SR linkage from similar summaries, Contacts, Devices, names, or other approximate evidence.

## `BETA-REQ-0054` — prefix `AS-DISC`

**Governing obligation:** SOMA Beta shall provide controlled manual and automatic Advanced Search workbook discovery that deterministically selects eligible source evidence into staging without mutating operational data before authorized acceptance.

`001` — The operator shall be able to configure an Advanced Search inbox directory.
`002` — The operator shall be able to select an Advanced Search workbook manually.
`003` — Automatic discovery shall inspect only direct files within the configured inbox.
`004` — Automatic discovery shall consider only stable regular files.
`005` — Eligible automatic-discovery filenames shall match `Advanced Search(Service Request)YYYYMMDDHHMMSS.xlsx`.
`006` — The embedded filename timestamp shall be interpreted under the accepted Advanced Search source-file timezone rule.
`007` — Automatic discovery shall select the newest eligible candidate according to accepted source chronology.
`008` — Discovery shall create a staged import preview rather than mutate operational data.
`009` — Operational mutation shall wait for the applicable reviewed acceptance or configured safe-auto-accept decision.
`010` — A candidate older than the latest accepted source chronology shall not be accepted as a new authoritative population.
`011` — An older-than-latest candidate shall produce an actionable result rather than silently falling back or mutating state.
`012` — Directory traversal outside the configured inbox shall be excluded.
`013` — Symbolic links, Windows reparse links, or equivalent link traversal shall be excluded from automatic discovery.
`014` — Partial or unstable files shall be excluded.
`015` — Unrelated or nonmatching workbooks shall be excluded.
`016` — Discovery eligibility alone shall not confer safe-auto-accept authority.

## `BETA-REQ-0055` — prefix `AS-PARSE`

**Governing obligation:** Advanced Search workbooks shall be fully and safely interpreted in staging through identity-based, order-independent validation before any operational mutation, with incomplete, invalid, duplicate, conflicting, and unallowlisted source evidence handled explicitly and non-destructively.

`001` — Advanced Search discovery shall complete before operational mutation.
`002` — File-stability validation shall complete in staging before operational mutation.
`003` — Safe XLSX opening shall complete in staging before operational mutation.
`004` — Source identification shall complete in staging before operational mutation.
`005` — Header normalization shall complete in staging before operational mutation.
`006` — Row parsing shall complete in staging before operational mutation.
`007` — Workbook and row validation shall complete in staging before operational mutation.
`008` — An unreadable workbook shall be rejected with an actionable result and no operational mutation.
`009` — A malformed workbook shall be rejected with an actionable result and no operational mutation.
`010` — An unsafe workbook shall be rejected with an actionable result and no operational mutation.
`011` — An unrecognizable workbook shall be rejected with an actionable result and no operational mutation.
`012` — A workbook lacking the required `SRNo` identity column shall be rejected with an actionable result.
`013` — Rejection of the newest candidate shall not silently fall back to an older workbook as a substitute population.
`014` — Missing allowlisted nonidentity columns shall produce coverage warnings rather than reject an otherwise valid workbook.
`015` — Missing allowlisted nonidentity columns shall preserve previously accepted values rather than erase them.
`016` — Allowlisted fields shall be resolved by normalized header identity.
`017` — Accepted header aliases may resolve allowlisted fields.
`018` — Column position shall not define field meaning.
`019` — User-configured column reordering shall not change workbook interpretation.
`020` — An operational row without a usable canonical SR identity shall be reported as invalid.
`021` — Exact duplicate observations may be collapsed when accompanied by a warning.
`022` — Conflicting rows for the same canonical SR identity shall block acceptance until reviewed and resolved.
`023` — Unallowlisted columns shall be discarded after staging.
`024` — Unallowlisted columns shall not participate in logical identity.
`025` — Unallowlisted columns shall not participate in reconciliation.

## `BETA-REQ-0056` — prefix `IMPORT-FP`

**Governing obligation:** All governed workbook imports shall derive deterministic logical fingerprints from canonical allowlisted content and use them with source chronology to make replay idempotent without fabricating operational changes.

`001` — Every official governed workbook import shall compute a SHA-256 logical-content fingerprint.
`002` — The fingerprint shall derive from validated allowlisted logical content.
`003` — Raw XLSX bytes shall not define the logical fingerprint.
`004` — Workbook package layout shall not define the logical fingerprint.
`005` — Filesystem metadata shall not define the logical fingerprint.
`006` — Formula expressions shall not contribute as authoritative logical content.
`007` — Discarded columns shall not contribute to the logical fingerprint.
`008` — Physical row order shall not change the fingerprint when canonical logical ordering is unchanged.
`009` — Physical column order shall not change the fingerprint when canonical field identity is unchanged.
`010` — Canonical field identities shall determine deterministic serialization.
`011` — Canonical business identifiers shall determine deterministic record ordering.
`012` — Source-family identity shall participate in replay identity.
`013` — Import-contract version shall participate in replay identity.
`014` — Accepted source chronology shall participate in replay identity.
`015` — The logical fingerprint shall participate in replay identity.
`016` — Reprocessing the same source family, contract version, source chronology, and logical fingerprint shall be a no-op.
`017` — A newer source observation with identical accepted logical content may record bounded import/check recency provenance.
`018` — Such a replay shall not create duplicate per-record source observations.
`019` — Such a replay shall not create duplicate relationship changes or operational mutations.
`020` — Such a replay shall not fabricate duplicate change-audit events.
`021` — The fingerprint/replay contract shall apply to Advanced Search SR, Enhanced Excel RFC, and Service Provider WFM imports.

## `BETA-REQ-0057` — prefix `SR-PERSIST`

**Governing obligation:** Accepted Advanced Search observations shall update only governed source-owned Service Request facts while SOMA preserves accumulated identity, relationships, review evidence, and operational history; source disappearance or ambiguous status shall never silently destroy or reverse that authority.

`001` — SOMA persistence shall remain authoritative for accumulated SOMA-owned Service Request state, relationships, and history.
`002` — Absence of a previously imported SR from the newest accepted Advanced Search population shall not delete it.
`003` — Source absence shall not archive the Service Request automatically.
`004` — Source absence shall not terminate or finalize the Service Request automatically.
`005` — Applicable source absence shall be staged as a high-risk source-disappearance warning for review.
`006` — A later accepted valid reappearance may clear the source-disappearance warning.
`007` — Reappearance shall reconcile to the same surviving Service Request rather than recreate it.
`008` — A recognized imported `Closed` status shall establish the corresponding terminal presentation.
`009` — A recognized imported `Resolved` status shall establish the corresponding terminal presentation.
`010` — A recognized imported `Cancelled` status shall establish the corresponding terminal presentation.
`011` — Terminal SRs shall remain muted but visible for the configured Daily, Weekly, or Monthly main-view period.
`012` — After that presentation period, the same terminal SR shall remain available through Historical view.
`013` — A missing Status shall not erase recognized terminal evidence.
`014` — A blank Status shall not erase recognized terminal evidence.
`015` — An unknown Status shall not erase recognized terminal evidence.
`016` — An apparent terminal-to-nonterminal reversal shall require explicit high-risk confirmation.
`017` — Accepted or rejected terminal-reversal review shall remain auditable.
`018` — Import processing shall not overwrite SOMA-owned relationships.
`019` — Import processing shall not overwrite Working Notes or Tasks.
`020` — Import processing shall not overwrite Objectives or Inventory context.
`021` — Import processing shall not overwrite Infrastructure context.
`022` — Import processing shall not overwrite review evidence or audit history.
`023` — Import processing shall never purge operational history.
`024` — Beta 1.0 shall perform no general operational-history purge.

## `BETA-REQ-0058` — prefix `AS-REF`

**Governing obligation:** Advanced Search customer reference data shall drive reviewed, deterministic reconciliation without becoming relational identity or blocking otherwise valid Service Request imports when Customer Organization or Contact identity remains unresolved.

`001` — Advanced Search Customer Organization labels shall be reconciliation candidates rather than relational identity.
`002` — Advanced Search Customer Contact labels shall be reconciliation candidates rather than relational identity.
`003` — A valid `Customer Account Code` shall be the preferred stable external key for Customer Organization reconciliation.
`004` — `Customer Account Code` shall remain distinct from SOMA's internal Customer Organization identifier.
`005` — A conflicting account code claim shall require operator review.
`006` — A multiply claimed account code shall require operator review.
`007` — An unknown Customer Organization shall not block an otherwise valid SR import.
`008` — An ambiguous Customer Organization shall not block an otherwise valid SR import.
`009` — An unknown Contact shall not block an otherwise valid SR import.
`010` — An ambiguous Contact shall not block an otherwise valid SR import.
`011` — SOMA shall stage a reviewed existing-record match proposal where evidence supports one.
`012` — SOMA may stage a reviewed minimal-record creation proposal when no governed match exists.
`013` — A display name alone shall never establish Customer Organization or Contact identity.
`014` — Equal display names shall not trigger silent merge.
`015` — A Contact name shall not be treated as proof that two observations identify the same person.
`016` — Unresolved reference reconciliation shall remain explicit without fabricating relational identity.

## `BETA-REQ-0059` — prefix `XLSX-SEC`

**Governing obligation:** All SOMA Beta XLSX adapters shall treat workbooks as untrusted bounded offline input, prohibit active-content execution and external fetching, and fail safely before operational mutation whenever filesystem, archive, content, or resource constraints are violated.

`001` — Every SOMA Beta XLSX adapter shall treat workbook input as untrusted.
`002` — Workbook processing shall remain offline.
`003` — Automatic discovery shall enumerate direct regular files only.
`004` — Automatic discovery shall reject symbolic links.
`005` — Automatic discovery shall reject Windows reparse traversal.
`006` — Automatic discovery shall reject unstable files.
`007` — Automatic discovery shall reject unsupported containers.
`008` — Automatic discovery shall reject path escapes.
`009` — Parsing shall enforce a reviewed maximum compressed archive size.
`010` — Parsing shall enforce a reviewed maximum expanded archive size.
`011` — Parsing shall enforce reviewed limits on workbook parts.
`012` — Parsing shall enforce reviewed limits on worksheets.
`013` — Parsing shall enforce reviewed limits on rows.
`014` — Parsing shall enforce reviewed limits on columns.
`015` — Parsing shall enforce reviewed limits on shared strings.
`016` — Parsing shall enforce reviewed limits on cell text.
`017` — Parsing shall enforce reviewed limits on formula content.
`018` — Parsing shall enforce bounded total processing resources.
`019` — SOMA shall never execute workbook formulas.
`020` — SOMA shall never execute workbook macros or scripts.
`021` — SOMA shall never execute workbook data connections.
`022` — SOMA shall never execute embedded executables or other active content.
`023` — SOMA shall never fetch external workbook resources.
`024` — Unsupported content shall fail safely before operational mutation.
`025` — Resource-limit violations shall fail safely before operational mutation.
`026` — Unsafe archive paths or partial parsing shall fail safely before operational mutation.
`027` — Failure shall produce a bounded actionable result.
`028` — This security boundary shall apply to Advanced Search SR, Enhanced Excel RFC, and Service Provider WFM workbooks.

## `BETA-REQ-0060` — prefix `AS-FIELD`

**Governing obligation:** The Advanced Search adapter shall retain only explicitly allowlisted source fields, distinguish active Beta 1.0 facts from future-use provenance, and prevent all other columns from acquiring operational authority.

`001` — The Advanced Search active Beta 1.0 source-field allowlist shall be exactly: `SRNo`, `Problem Summary`, `Report Date`, `Customer Contact`, `Customer Severity`, `Current Handler`, `Status`, `Customer Org.`, `Customer Account Code`, `Suspend Planned End Date`, `Suspension Duration`, and `Last Update`.
`002` — The Advanced Search future-use provenance allowlist shall be exactly: `ResolveBy`, `Resolve By Suspend`, `Owner`, `L2 Assignee`, `L3 Assignee`, `Related SR`, `Authorization No.`, `Escalation No`, and `Pr Number`.
`003` — Future-use fields shall drive no Beta 1.0 workflow unless another accepted requirement explicitly activates them.
`004` — `SRNo` shall be the only universally required usable row identity.
`005` — Missing, blank, malformed, or absent nonidentity fields shall follow their field-specific non-destructive rules.
`006` — Every other Advanced Search column shall be discarded after staging.
`007` — Discarded columns shall not influence identity.
`008` — Discarded columns shall not influence relationships.
`009` — Discarded columns shall not influence SLA behavior.
`010` — Discarded columns shall not influence Infrastructure behavior.
`011` — Discarded columns shall not influence Inventory behavior.
`012` — Discarded columns shall not influence UI behavior.

## `BETA-REQ-0061` — prefix `SRC-SEM`

**Governing obligation:** SOMA Beta shall interpret timestamps and controlled source values through versioned source-family semantics while keeping source, ordinary/SLA, and Objective scheduling-time authorities distinct and preserving unrecognized evidence non-destructively.

`001` — A source timestamp carrying an explicit UTC offset shall be interpreted using that offset.
`002` — An operational workbook timestamp lacking an explicit offset shall use the configured timezone for its source family.
`003` — Accepted Beta operational source families shall default to `America/Guayaquil` where their profile does not override that default.
`004` — Interpreted operational source instants shall be normalized to canonical UTC.
`005` — The Advanced Search filename timestamp shall retain its separately accepted China Standard Time interpretation.
`006` — Source-family timezone authority shall remain distinct from ordinary/SLA operational timezone authority.
`007` — Source-family timezone authority shall remain distinct from Objective scheduling timezone authority.
`008` — The fixed ordinary/SLA operational timezone shall remain distinct from the separately selectable Objective scheduling timezone.
`009` — Status values shall use a source-family-specific versioned vocabulary.
`010` — Severity values shall use a source-family-specific versioned vocabulary.
`011` — Risk Level values shall use a source-family-specific versioned vocabulary where applicable.
`012` — Dispatch Progress values shall use a source-family-specific versioned vocabulary where applicable.
`013` — Other controlled source values shall use source-family-specific versioned vocabularies.
`014` — An unknown nonblank controlled value shall produce a reviewed warning.
`015` — An unknown nonblank value shall not overwrite the last recognized canonical value.
`016` — Blank handling shall remain field-specific rather than being globally treated as unknown.

## `BETA-REQ-0062` — prefix `AS-HANDLER`

**Governing obligation:** Advanced Search `Product` shall have no Beta 1.0 operational authority, while `Current Handler` shall remain a source-owned current-assignment fact that may support reviewed Contact reconciliation without creating competing local handler state or mutating Contact identity.

`001` — Advanced Search `Product` shall be discarded.
`002` — `Product` shall not create or select a Contract.
`003` — `Product` shall not create or select a reusable Product Line.
`004` — `Product` shall not create or select a Contract Product Line.
`005` — `Product` shall not create or select a product family.
`006` — `Product` shall not create or select a Network Element.
`007` — `Product` shall not create or select a Device Reference.
`008` — `Product` shall not create or select an SLA policy.
`009` — `Product` shall not create or select an Inventory relationship.
`010` — `Current Handler` shall remain a source-owned current-assignment fact.
`011` — The newest accepted usable Advanced Search observation shall govern the current `Current Handler` source assignment.
`012` — `Current Handler` may propose reviewed Contact reconciliation.
`013` — `Current Handler` shall not silently create a Contact.
`014` — `Current Handler` shall not silently merge Contacts.
`015` — An accepted blank `Current Handler` may clear the current source-assignment display.
`016` — Clearing the source-assignment display shall not delete, archive, or modify the underlying Contact.
`017` — SOMA shall not maintain a competing locally authoritative `Current Handler` value.
`018` — Local operational context shall instead remain in governed relationships, Tasks, and Working Notes.
`019` — Audit history shall preserve relevant local/source assignment changes without creating a second handler authority.

## `BETA-REQ-0063` — prefix `SR-SUSP`

**Governing obligation:** Advanced Search Resolve and suspension fields shall influence Beta 1.0 only through explicitly authorized suspension semantics, while future-use deadlines remain non-operational and cumulative suspension history remains source-reported, non-inferred, and non-destructive.

`001` — `ResolveBy` shall be retained with source provenance for future use.
`002` — `Resolve By Suspend` shall be retained with source provenance for future use.
`003` — `ResolveBy` and `Resolve By Suspend` shall not determine Beta 1.0 SLA behavior.
`004` — They shall not determine Beta 1.0 risk behavior.
`005` — They shall not determine Beta 1.0 expiration behavior.
`006` — They shall not determine Beta 1.0 notification behavior.
`007` — They shall not determine Beta 1.0 workflow behavior.
`008` — Their presence shall not create a synthetic effective deadline.
`009` — `Suspend Planned End Date` shall represent an active suspension only when accepted Status is `Customer Agreed Suspend`.
`010` — An active suspension additionally requires a valid future `Suspend Planned End Date`.
`011` — Otherwise `Suspend Planned End Date` shall not pause SLA behavior.
`012` — Otherwise it shall not represent an active suspension.
`013` — `Suspension Duration` shall represent cumulative source-reported suspension duration.
`014` — Cumulative suspension duration shall never be inferred between exports.
`015` — A blank `Suspension Duration` shall mean zero cumulative suspension and that the source reports no suspension history.
`016` — A new blank value contradicting previously accepted nonzero suspension evidence shall require review before erasure.
`017` — A new zero value contradicting previously accepted nonzero suspension evidence shall require review before erasure.
`018` — Contradictory blank/zero evidence shall not silently erase previously accepted nonzero suspension history.
`019` — An SR lacking active suspension or usable future Resolve fields shall remain fully trackable.

## `BETA-REQ-0064` — prefix `SLA-POLICY`

**Governing obligation:** Each customer-specific Contract Product Line shall own an independently governed tiered SLA policy whose templates, custom thresholds, Non-fault derivation, cohort eligibility, revisions, and historical-report effects follow the accepted SLA contract.

`001` — Each Contract shall belong to exactly one Customer Organization.
`002` — A reusable Product Line may appear in Contracts belonging to multiple Customer Organizations.
`003` — Each occurrence of a reusable Product Line in a Contract shall be represented by a distinct Contract Product Line.
`004` — Different Contract Product Lines for the same reusable Product Line may carry different customer-specific SLA policies.
`005` — Each SLA policy shall belong to exactly one Contract Product Line.
`006` — Each SLA policy shall define one or more cohort-compliance tiers for every supported severity.
`007` — Each SLA tier shall define a validated required percentage of eligible Service Requests.
`008` — Each SLA tier shall define a maximum inclusive elapsed duration.
`009` — An eligible SR whose elapsed duration equals the tier maximum shall satisfy that duration threshold.
`010` — A 100% tier shall require every eligible cohort member to satisfy its duration threshold.
`011` — A percentage tier such as 85% shall require at least that configured percentage of eligible cohort members to satisfy its duration threshold.
`012` — The default IT Critical template shall be 100% within 7 days.
`013` — The default IT Major template shall include 85% within 15 days and 100% within 30 days.
`014` — The default IT Minor template shall include 85% within 45 days and 100% within 60 days.
`015` — The default NFV Critical template shall be 100% within 3 days.
`016` — The default NFV Major template shall be 100% within 15 days.
`017` — The default NFV Minor template shall be 100% within 90 days.
`018` — Template definitions shall not operate as global SLA policy.
`019` — A template shall become operational only through a customer Contract Product Line.
`020` — A custom SLA policy may define one or more supported validated percentages.
`021` — A custom SLA policy shall not be forced into an 85%/100% pair.
`022` — Non-fault inquiry shall derive from the corresponding configured Minor policy.
`023` — Non-fault inquiry shall multiply every configured Minor duration by exactly 1.5.
`024` — Non-fault derivation shall preserve the Minor policy's tier percentages and tier structure.
`025` — Exact fractional-day results shall be retained without forced whole-day rounding.
`026` — Default IT Non-fault inquiry shall therefore include 85% within 67.5 days and 100% within 90 days.
`027` — Default NFV Non-fault inquiry shall therefore require 100% within 135 days.
`028` — An accepted SLA policy revision shall become the current policy authority for its Contract Product Line.
`029` — Every existing Service Request currently classified under that Contract Product Line shall be recalculated under the accepted revision.
`030` — Report Date shall not exempt an existing classified SR from current-policy recalculation.
`031` — Service Request creation date shall not exempt it from current-policy recalculation.
`032` — Terminal state shall not exempt a classified SR from current-policy recalculation.
`033` — Completed report snapshots shall retain the policy revision and calculation results captured when they completed.
`034` — A later policy revision shall not rewrite completed report snapshots.
`035` — All subsequent current views, warnings, calculations, and reports shall use the revised current policy.
`036` — Policy revisions and their prior values shall remain auditable.
`037` — Cancelled Service Requests shall be excluded from SLA cohorts.
`038` — Alpha's global age-risk severity schedule shall not control Beta 1.0 SLA behavior.
`039` — Alpha's suspension-KPI severity schedule shall not control Beta 1.0 SLA behavior.
`040` — Configurable Weekly and Monthly reports shall evaluate each applicable reporting cohort against the SLA tiers of its Contract Product Line.
`041` — Each such report shall expose the actual eligible count or percentage satisfying each configured maximum duration together with the required percentage and duration.
`042` — When an SLA policy contains multiple tiers, the report shall evaluate and expose each tier independently.
`043` — Under the default IT Major policy, Weekly or Monthly reporting shall make observable whether at least 85% of eligible Major SRs satisfy the governed 15-day threshold and whether 100% satisfy the governed 30-day threshold.
`044` — A completed report snapshot shall preserve the SLA policy revision and cohort-compliance result used when that report completed.

## `BETA-REQ-0065` — prefix `SR-SLA-CLASS`

**Governing obligation:** Each Service Request shall have at most one customer-consistent Contract Product Line classification, established only through deterministic trusted mapping or explicit reviewed selection, with classification changes recalculating current SLA results without rewriting completed report evidence.

`001` — A Service Request shall have zero or one active Contract Product Line classification.
`002` — The active classification shall reference the customer-specific Contract Product Line rather than only the reusable Product Line.
`003` — The selected Contract Product Line's Contract shall belong to the SR's resolved Customer Organization.
`004` — Import reconciliation may assign a Contract Product Line automatically only through an accepted deterministic configured mapping.
`005` — Automatic classification shall use trusted allowlisted source evidence.
`006` — A valid `Customer Account Code` may participate as deterministic mapping evidence.
`007` — Discarded Advanced Search `Product` text shall not classify an SR into a Contract Product Line.
`008` — If the Customer Organization remains unresolved, SOMA shall not fabricate a Contract Product Line classification.
`009` — If no configured mapping applies, the SR shall remain SLA-unclassified.
`010` — If multiple mappings apply, SOMA shall not choose between them automatically.
`011` — A proposed Contract Product Line belonging to another Customer Organization shall not be accepted as the SR classification.
`012` — Unresolved, absent, ambiguous, or incompatible classification shall require review rather than a fabricated default.
`013` — SOMA shall not assign a generic IT, NFV, Product Line, template, or other default merely because classification is unresolved.
`014` — The operator may explicitly reclassify an individual SR.
`015` — The selected reclassification target shall be an active Contract Product Line eligible for selection.
`016` — Manual reclassification shall be limited to Contract Product Lines belonging to the SR's resolved Customer Organization.
`017` — Changing or correcting an SR's Customer Organization shall revalidate its existing Contract Product Line classification.
`018` — An incompatible existing classification shall be invalidated or explicitly reviewed through the governed correction workflow.
`019` — An accepted classification change shall be auditable and preserve prior classification evidence.
`020` — Accepted reclassification shall recalculate the SR's current SLA results under the newly applicable policy.
`021` — Subsequent current Weekly/Monthly cohort calculations shall evaluate the SR under its accepted current classification when otherwise eligible.
`022` — Reclassification shall not retroactively alter a completed report snapshot.
`023` — Subsequent reports shall use the then-current accepted classification and applicable SLA policy.

## `BETA-REQ-0066` — prefix `SR-SRC-HIST`

**Governing obligation:** SOMA Beta shall derive each current source-owned Service Request field from its newest accepted usable field observation while preserving compact, provenance-rich historical deltas instead of redundant workbook snapshots or purgeable source-history copies.

`001` — Each source-owned Service Request field shall derive its current value independently from its newest accepted usable observation.
`002` — Selection of the current source value shall follow governed source chronology.
`003` — Observation usability shall follow the field's accepted missing, blank, malformed, and unknown-value semantics.
`004` — A newer source row shall not automatically replace every source-owned field merely because the row is newer.
`005` — Historical source evidence shall use compact delta observations rather than complete repeated source records.
`006` — A delta observation shall retain only allowlisted values meaningfully observed or changed under the applicable field contract.
`007` — Necessary source-family, import-run, chronology, and other governed provenance shall remain attached to historical observations.
`008` — Applicable validation findings, ambiguity warnings, or review decisions shall remain associated with relevant source evidence.
`009` — SOMA shall not preserve full imported workbook copies as generic historical SR evidence.
`010` — Fields excluded from the accepted allowlist, including Advanced Search `Product`, shall not survive merely because history is recorded.
`011` — An unchanged Problem Summary shall not be redundantly copied into every historical observation.
`012` — Unchanged Customer Organization labels shall not be redundantly copied into every observation.
`013` — Unchanged Contact labels shall not be redundantly copied into every observation.
`014` — Unchanged source contact-channel evidence shall not be redundantly replicated into every observation.
`015` — The current accepted Problem Summary shall remain directly available on the Service Request.
`016` — Each accepted Problem Summary revision shall preserve enough prior-value and provenance evidence to remain auditable.
`017` — Beta 1.0 shall not create Alpha's separate terminated-Service-Request snapshot model.
`018` — Beta 1.0 shall not purge accepted source history merely because an SR becomes terminal or old.
`019` — Historical presentation shall remain based on the surviving Service Request identity.
`020` — Historical view shall derive its explanation from the surviving SR, compact source observations, and applicable audit/history evidence.

## `BETA-REQ-0067` — prefix `CONTACT-COMM`

**Governing obligation:** Contact communication channels shall remain optional until a specific workflow requires a recipient, at which point SOMA shall validate or resolve the needed channel without invalidating the underlying operational record and shall preserve the recipient evidence used for any generated communication artifact.

`001` — A Contact may exist without an email address or other supported communication channel.
`002` — Missing Contact communication channels shall not prevent Service Request import.
`003` — They shall not prevent creation of an otherwise valid Service Request or RFC.
`004` — They shall not prevent normal review of Tickets or related operational records.
`005` — They shall not prevent Task or Objective scheduling.
`006` — They shall not prevent Task or Objective execution.
`007` — They shall not prevent historical viewing of Service Requests, RFCs, Tasks, or Objectives.
`008` — A workflow action that actually requires a recipient shall validate the applicable communication channel when that action is invoked.
`009` — Generation of a Spare Request `.msg` draft shall perform just-in-time recipient validation.
`010` — When the selected Contact lacks a usable required channel, the operator shall be able to select another eligible Contact where the workflow permits.
`011` — The operator shall be able to register the missing required address through the governed Contact workflow and then continue the communication action.
`012` — Failure to provide a usable recipient shall block only the communication-dependent action.
`013` — Recipient failure shall not invalidate or block the underlying Ticket.
`014` — It shall not invalidate or block the underlying Task.
`015` — It shall not invalidate or block the underlying Objective.
`016` — It shall not invalidate or block the underlying Spare Need.
`017` — It shall not invalidate or block the underlying Spare Request.
`018` — A generated communication artifact shall preserve the recipient Contact identity effective when the artifact was created.
`019` — The artifact/evidence shall preserve the communication address actually used at creation time.
`020` — Subsequent Contact communication-channel edits shall not retroactively alter recipient evidence for an already generated artifact.
`021` — Historical recipient snapshots shall not prevent later legitimate edits to the Contact's current communication details.

## `BETA-REQ-0068` — prefix `AS-SCHED`

**Governing obligation:** SOMA Beta shall provide configurable daily Advanced Search checking in the fixed operational timezone, with bounded startup catch-up and manual invocation, while routing every check through the same staged, review-governed, replay-safe import pipeline.

`001` — Automatic Advanced Search scheduling shall be available only after an Advanced Search inbox is configured.
`002` — The automatic daily check shall be enabled by default.
`003` — Its default execution boundary shall be 10:00.
`004` — The scheduled boundary shall be interpreted in `America/Guayaquil`.
`005` — The operator may configure another valid whole-minute clock time.
`006` — The operator may disable automatic checking.
`007` — Changing the Objective scheduling timezone shall not reinterpret the Advanced Search schedule boundary.
`008` — At application startup, SOMA shall recognize an enabled scheduled boundary that was missed.
`009` — Startup shall trigger at most one catch-up check for outstanding missed schedule boundaries.
`010` — SOMA shall not replay one catch-up check for every missed day merely because the application was offline.
`011` — `Check now` shall remain available whether automatic scheduling is enabled or disabled.
`012` — A manual check shall enter the same governed discovery/staging/reconciliation boundary rather than a privileged mutation path.
`013` — An automatic scheduled check shall not open a manual file-selection dialog.
`014` — An automatic check shall discover the newest eligible stable workbook under the accepted discovery rules.
`015` — A discovered candidate shall produce a staged import result before operational mutation.
`016` — Scheduled invocation shall not bypass required operator review.
`017` — Scheduled invocation shall not expand or bypass the configured safe-auto-accept policy.
`018` — SOMA shall persist enough schedule-boundary state to distinguish satisfied from missed checks across restarts.
`019` — Recording a schedule boundary as satisfied shall not itself imply workbook acceptance into operational state.
`020` — Scheduled and manual checking shall use the governed logical import fingerprint for replay recognition.
`021` — Repeated checking of already-processed equivalent evidence shall not create duplicate domain mutations.
`022` — Replay shall not fabricate duplicate change-audit or per-record operational history.

## `BETA-REQ-0069` — prefix `SR-NOTIFY`

**Governing obligation:** Recognized terminal Service Request states shall suppress active-work and live SLA-risk notifications while preserving terminal evidence and governed cohort eligibility, with supplemental alerts throttled persistently and suspected reversals handled as high-risk review.

`001` — An accepted `Resolved` status shall immediately suppress active-work reminders for that SR.
`002` — An accepted `Closed` status shall immediately suppress active-work reminders.
`003` — An accepted `Cancelled` status shall immediately suppress active-work reminders.
`004` — Recognized terminal status shall suppress ongoing live SLA-risk notifications for that SR.
`005` — Resolved SRs shall retain their effective terminal-duration, SLA, source, and audit evidence.
`006` — Closed SRs shall retain the same governed historical evidence.
`007` — A Resolved SR shall remain eligible for applicable Contract Product Line cohorts when it otherwise satisfies cohort rules.
`008` — A Closed SR shall likewise remain eligible for applicable cohorts.
`009` — Cancelled SRs shall preserve source, lifecycle, and audit evidence.
`010` — Cancelled SRs shall not contribute to Contract Product Line SLA cohorts.
`011` — Persistent active conditions shall be surfaced primarily through Overview.
`012` — Needs Attention shall be a primary presentation surface for actionable ongoing conditions.
`013` — In-app or tray notifications may supplement but shall not replace persistent Overview/Needs Attention presentation.
`014` — For the same SR and same condition, a supplemental local notification shall occur at most once per operator-local calendar day.
`015` — Application restart shall not permit another notification for the same SR/condition within that same operator-local calendar day.
`016` — Enough bounded state shall persist to enforce the daily notification limit across restarts.
`017` — An apparent terminal-to-nonterminal source transition shall remain a distinct high-risk review condition.
`018` — The reversal warning itself shall not silently reactivate ordinary active-work notifications before acceptance.
`019` — `ResolveBy` shall not generate Beta 1.0 expiration notifications.
`020` — `Resolve By Suspend` shall not generate Beta 1.0 expiration notifications.

## `BETA-REQ-0070` — prefix `SR-WARN`

**Governing obligation:** SOMA Beta shall present suspension-ending-soon as a distinct noncontractual warning state, preserve its semantic separation from SLA, cohort, source, retention, and lifecycle concepts, and ensure every governed state remains distinguishable without relying on color alone.

`001` — A suspension-ending-soon warning shall apply only when accepted SR Status is `Customer Agreed Suspend`.
`002` — The SR shall also have a valid future `Suspend Planned End Date`.
`003` — The warning shall become active when the suspension end enters the configured warning threshold.
`004` — The suspension-ending-soon threshold shall remain a noncontractual operational warning preference.
`005` — Suspension ending soon shall be represented as a distinct warning state.
`006` — It shall not be treated as an SLA milestone state.
`007` — It shall remain distinct from individual elapsed-duration evidence.
`008` — It shall remain distinct from Contract Product Line cohort-compliance results.
`009` — It shall remain distinct from `ResolveBy` and `Resolve By Suspend` source guidance.
`010` — It shall remain distinct from cumulative source-reported `Suspension Duration`.
`011` — It shall not control retention, archival, or historical-record behavior.
`012` — It shall not alter source-import authority or source-handling behavior.
`013` — It shall not imply any terminal lifecycle transition.
`014` — SOMA shall not collapse suspension end, Resolve guidance, SLA thresholds, or other temporal states into one generic deadline state.
`015` — Distinct governed time-related conditions shall not be represented as one undifferentiated risk state.
`016` — An individual SR crossing a configured SLA duration shall constitute evidence about that SR's performance against the applicable tier.
`017` — One individual SR exceeding a duration threshold shall not by itself establish failure of a percentage-based cohort tier.
`018` — No governed warning or state shall rely exclusively on color.
`019` — Every governed state shall include text, iconography, or both in addition to any color treatment.

## `BETA-REQ-0071` — prefix `REPORT-SNAP`

**Governing obligation:** Daily, Weekly, and Monthly reports shall become immutable, reproducible historical evidence only after successful artifact verification, using one consistent accepted-state snapshot with sufficient scope, membership, SLA-policy, classification, and calculation provenance while remaining strictly non-destructive to operational data.

`001` — Every Daily, Weekly, or Monthly report shall be calculated from one internally consistent snapshot of accepted operational state.
`002` — A report shall not combine facts from mutually inconsistent revisions merely because operational data changed during generation.
`003` — A report may be scoped to one Customer Organization.
`004` — A report may alternatively include all eligible Customer Organizations.
`005` — The completed report shall retain the exact scope used for its calculation.
`006` — Completed evidence shall identify the exact reporting period.
`007` — Completed evidence shall identify the timezone governing that reporting period.
`008` — Reporting period and timezone evidence shall be sufficient to reproduce report-window membership.
`009` — Completed evidence shall identify included operational members at the minimum granularity required for reproducibility.
`010` — The report snapshot shall preserve its calculated results.
`011` — Where SLA tiers are evaluated, the snapshot shall preserve cohort counts, percentages, thresholds, and PASS/FAIL results necessary to explain the report.
`012` — The applicable Contract Product Line identity/revision context shall remain part of completed evidence.
`013` — The exact SLA-policy revision used for each applicable calculation shall be preserved.
`014` — The report shall retain the minimum accepted source provenance needed to reproduce or explain results.
`015` — Where Contract Product Line classification affects the result, relevant accepted classification provenance shall be retained.
`016` — Report-time Customer Organization, Contact, Status, Problem Summary, and similar display values shall be captured only when included or necessary to interpret the report.
`017` — Completed report snapshots shall not duplicate entire source-observation histories.
`018` — Communications shall not be copied into report evidence merely because they relate to reported entities.
`019` — Working Notes shall not be duplicated into the report snapshot absent separately accepted reporting authority.
`020` — Discarded source fields shall not re-enter persistence through report snapshots.
`021` — Personal data unrelated to interpreting or reproducing the report shall not be copied into durable report evidence.
`022` — A report shall not become Completed until its output artifact has been written successfully.
`023` — The artifact shall pass the governed verification step before completed-report evidence is committed.
`024` — Only a successfully written and verified artifact may produce a Completed report snapshot.
`025` — A failed generation shall not create completed-report evidence.
`026` — A cancelled generation shall not create completed-report evidence.
`027` — Failed or cancelled report generation shall not mutate operational domain records.
`028` — Failed or cancelled report generation shall not initiate operational-data cleanup.
`029` — A failed or cancelled attempt may preserve bounded diagnostic/audit evidence sufficient to explain the attempt.
`030` — Later source observations shall not alter a completed report snapshot.
`031` — Later Contact edits shall not rewrite report-time evidence.
`032` — Later Customer Organization reconciliation shall not rewrite completed report evidence.
`033` — Later SLA-policy revisions shall not recalculate or mutate a completed report snapshot.
`034` — Later Contract Product Line reclassification shall not rewrite completed report membership or results.
`035` — Subsequent operational change shall not mark an otherwise valid completed report for cleanup.
`036` — Subsequently generated reports shall use the then-current accepted operational state and policy/classification authority.
`037` — Generating or completing a report shall not finalize operational records.
`038` — Report generation shall not minimize authoritative operational history.
`039` — Report generation shall not archive domain records.
`040` — Report generation shall not delete or purge operational records.
`041` — Beta 1.0 shall expose no report workflow action that performs post-export operational cleanup.

## `BETA-REQ-0072` — prefix `RETENTION`

**Governing obligation:** SOMA Beta 1.0 shall preserve surviving operational records and their governed history independently of reporting, terminal status, source disappearance, age, inactivity, or presentation state, permitting destructive minimization only through explicitly accepted narrow domain rules.

`001` — Completing a report shall not finalize, minimize, anonymize, archive, delete, or purge operational domain records.
`002` — Resolved, Closed, Cancelled, or another terminal state shall not independently authorize destructive retention behavior.
`003` — A record disappearing from an external source shall not authorize deletion or archival.
`004` — The age of source evidence shall not independently authorize destructive retention.
`005` — Operational inactivity shall not independently authorize archival or deletion.
`006` — Beta 1.0 shall contain no general operational-history purge based solely on elapsed retention time.
`007` — Moving a terminal SR out of Daily, Weekly, or Monthly primary views shall be a presentation/query transition.
`008` — Historical view shall represent the same surviving Service Request rather than a replacement archival entity or snapshot.
`009` — Accepted Customer Organization context shall remain governed by its domain history rules.
`010` — Contact relationships and historical context shall remain intact.
`011` — Working Notes and their history shall survive movement into Historical view.
`012` — RFC relationships and hierarchy evidence shall remain intact.
`013` — Task identities, outcomes, attempts, and relationships shall remain intact.
`014` — Objective membership and execution/review evidence shall remain intact.
`015` — Inventory relationships and lifecycle evidence shall remain intact.
`016` — Infrastructure relationships and regularization history shall remain intact.
`017` — Accepted compact source observations shall remain according to their source-history contract.
`018` — Historical report-membership evidence shall remain intact.
`019` — Applicable audit history shall remain intact.
`020` — Communications required by the Communications Contract shall remain according to that contract.
`021` — Beta 1.0 shall not create Alpha's terminated-episode record as a replacement for the surviving SR.
`022` — Beta 1.0 shall not collapse the SR into Alpha's 27-field final snapshot.
`023` — Beta 1.0 shall not implement Alpha's 180-day operational-data purge timer.
`024` — Compact source observations shall not substitute for the surviving operational record.
`025` — Completed report snapshots shall not replace operational entities.
`026` — Terminal communication summaries shall remain separate from domain-record identity and history.
`027` — Audit history shall not substitute for retaining the operational record it explains.
`028` — Hard deletion or dependent cleanup shall occur only where an accepted domain-specific rule explicitly permits it.
`029` — The orphaned-communication content-minimization rule under `BETA-REQ-0116` shall not broaden into general operational-record purge authority.
`030` — A governed destructive/corrective action shall satisfy its applicable impact-preview or due-housekeeping visibility rule.
`031` — Execution shall require governed confirmation or explicitly accepted automatic-housekeeping authority.
`032` — Eligibility shall be revalidated transactionally at execution time.
`033` — The applicable destructive/corrective operation shall preserve required audit evidence.
`034` — Rebuildable technical cache reconstruction/removal shall remain outside operational-history retention authority.
`035` — Temporary import/reconciliation staging cleanup shall remain separate from accepted operational history.
`036` — Diagnostic-log rotation shall not authorize domain-history deletion.
`037` — Verified backup rotation shall not define operational-record retention.
`038` — Any broader operational purge shall require Beta 1.1 or later product authority.
`039` — Such a future capability shall require explicit new product authority.
`040` — It shall require dedicated threat and privacy analysis.
`041` — It shall require accepted use cases and low-level design.
`042` — Introducing future purge behavior shall include an explicit migration/compatibility plan.
`043` — No future Beta retention period shall become authoritative merely because Alpha previously used it.

## `BETA-REQ-0073` — prefix `MIG-LINEAGE`

**Governing obligation:** SOMA Beta shall maintain an independent protected migration lineage in which candidates remain revisable only until acceptance, accepted migrations become individually immutable, and all later schema evolution proceeds through atomic forward migration or governed recovery without inheriting Alpha database history.

`001` — SOMA Beta shall maintain its own clean schema and migration lineage.
`002` — Alpha migration filenames shall not form part of Beta migration history.
`003` — Alpha migration sequence numbers shall not define Beta migration order or identity.
`004` — Alpha migration-ledger state shall not be imported as Beta migration authority.
`005` — Alpha table/layout history may inform review but shall not constitute executable Beta ancestry.
`006` — Alpha migration checksums shall not be accepted as Beta lineage evidence.
`007` — A Beta migration candidate may be revised until its protected-lineage acceptance.
`008` — Once accepted, the migration's identity shall freeze.
`009` — Once accepted, the migration's name shall freeze.
`010` — Once accepted, its accepted ordering position shall freeze.
`011` — Once accepted, its canonical migration content shall freeze.
`012` — Once accepted, its checksum shall freeze.
`013` — Once accepted, its corresponding manifest entry shall freeze.
`014` — A later correction shall not silently modify an already accepted migration.
`015` — A correction after acceptance shall be represented through a new forward migration.
`016` — Application of schema mutation and governed migration-ledger evidence shall commit atomically.
`017` — SOMA shall not leave schema mutation committed without required lineage evidence or lineage evidence claiming an unapplied schema change.
`018` — A development database may be destroyed and recreated after candidate changes only when explicitly classified as disposable.
`019` — A database containing non-disposable data shall not be discarded merely because migration development changed.
`020` — Non-disposable data shall receive an accepted supported forward-migration path where applicable.
`021` — Where migration cannot safely continue, the supported recovery contract may provide the applicable restoration path.
`022` — SOMA shall not promise compatibility with abandoned pre-acceptance development migration checksums.
`023` — An abandoned development origin becomes supported only when an explicit migration/recovery rule accepts that origin.
`024` — SOMA Beta shall not automatically treat an Alpha database as a Beta migration starting point.
`025` — Any future supported Alpha-data transition shall require an explicitly governed migration/import/recovery mechanism rather than implicit schema upgrade.

## `BETA-REQ-0074` — prefix `IMPORT-REVIEW`

**Governing obligation:** Every official workbook import shall expose an exact staged impact review before mutation, infer absence only from declared authoritative populations, and permit safe auto-accept solely for explicitly approved low-risk changes while preserving all high-risk and destructive cases for reviewed decision.

`001` — Every official workbook import shall produce a staged impact summary before operational mutation.
`002` — The impact summary shall derive from the exact validated logical source proposed for acceptance.
`003` — The summary shall distinguish proposed record creation.
`004` — It shall distinguish proposed updates.
`005` — It shall expose unchanged observations separately from actual mutations.
`006` — Skipped source records shall remain identifiable.
`007` — Invalid rows shall be distinguished from valid proposals.
`008` — Warnings shall be represented explicitly.
`009` — High-risk conflicts shall be clearly distinguished from low-risk proposals.
`010` — Identity conflicts shall be separately identifiable where applicable.
`011` — Customer Organization reconciliation changes shall be separately identifiable.
`012` — Proposed RFC hierarchy changes shall be visible independently.
`013` — Proposed WFM ownership changes shall be visible independently.
`014` — Task scheduling/timeframe conflicts shall be explicitly surfaced.
`015` — Governed source disappearance shall be separately visible.
`016` — A missing record may be interpreted as source disappearance only when the source profile declares authoritative-population semantics for a known scope.
`017` — Partial, filtered, or otherwise nonauthoritative exports shall not create missing-record proposals merely from absence.
`018` — A partial/non-authoritative RFC workbook shall not fabricate RFC disappearance.
`019` — A partial/non-authoritative WFM workbook shall not fabricate WFM disappearance.
`020` — A structurally valid empty authoritative population shall be high-risk when prior accepted in-scope records exist.
`021` — Such an empty authoritative import shall never qualify for automatic acceptance.
`022` — Acceptance shall require explicit high-risk operator confirmation.
`023` — Confirmation shall be bound to the exact source family.
`024` — Confirmation shall be bound to the proposed source chronology.
`025` — Confirmation shall be bound to the validated logical-content fingerprint.
`026` — Confirmation shall be bound to the declared authoritative scope.
`027` — Confirmation shall apply to the exact displayed impact summary.
`028` — An accepted import may record reviewed disappearance evidence.
`029` — Acceptance of disappearance evidence shall not delete existing records.
`030` — It shall not automatically archive existing records.
`031` — It shall not terminate or finalize existing operational state.
`032` — It shall not minimize or purge operational history.
`033` — Configured safe auto-accept may apply only to change classes explicitly approved as low-risk.
`034` — Safe auto-accept shall not bypass an empty authoritative population requiring high-risk confirmation.
`035` — Identity conflicts shall not safe-auto-accept.
`036` — RFC hierarchy changes shall not safe-auto-accept.
`037` — WFM ownership changes shall not safe-auto-accept.
`038` — Task timeframe conflicts shall not safe-auto-accept.
`039` — Terminal-to-nonterminal reversal proposals shall not safe-auto-accept.
`040` — Contradictory hardware serial evidence shall not safe-auto-accept.
`041` — Source-disappearance proposals shall not safe-auto-accept.
`042` — Where meaningful, the staged result shall expose the current candidate population count.
`043` — It shall expose the previous accepted comparable population count.
`044` — Where meaningful, Customer Organization distribution changes shall be visible for comparison.
`045` — Beta 1.0 shall not automatically accept or reject a nonempty import solely because its population count crosses an unvalidated numeric threshold.
`046` — A Customer Organization distribution change shall not become automatic rejection/acceptance authority without an accepted policy.
`047` — Any later numeric anomaly threshold shall require separately accepted product policy.
`048` — Such a future policy shall require representative operational evidence sufficient to justify its threshold behavior.

## `BETA-REQ-0075` — prefix `SR-INCOMPLETE`

**Governing obligation:** An Advanced Search Service Request with valid canonical identity shall remain persistable, visible, and trackable despite incomplete nonidentity source facts, while SOMA preserves missing information explicitly, never fabricates Report Date or SLA inputs, and validates required facts only at the workflows that actually depend on them.

`001` — A recognized `SRNo` header shall be the only universally required Advanced Search structural identity column.
`002` — Every row representing operational SR data shall contain a usable canonical Service Request identifier.
`003` — Missing allowlisted nonidentity headers shall produce coverage warnings.
`004` — Such missing headers shall not alone invalidate an otherwise acceptable workbook.
`005` — An accepted usable source value shall update its corresponding source-owned fact according to governed field precedence.
`006` — Missing values shall follow field-specific rules.
`007` — Blank values shall follow field-specific rules.
`008` — Malformed values shall follow field-specific rules.
`009` — Unknown controlled values shall follow source-family/field-specific rules.
`010` — None of those conditions shall erase a previously accepted valid value unless that field's accepted contract explicitly permits clearing.
`011` — A newly discovered SR with canonical identity may be persisted when some nonidentity source facts are unavailable.
`012` — An incomplete SR shall remain visible.
`013` — An incomplete SR shall remain usable in workflows that do not require the missing fact.
`014` — SOMA shall not synthesize `Report Date` from workbook discovery time.
`015` — SOMA shall not synthesize `Report Date` from import execution/capture time.
`016` — SOMA shall not synthesize `Report Date` from filesystem timestamps.
`017` — SOMA shall not synthesize `Report Date` from filename chronology.
`018` — SOMA shall not synthesize `Report Date` from the current system clock.
`019` — Import capture time shall remain separate provenance.
`020` — Import capture time shall not participate in Service Request age calculation.
`021` — Import capture time shall not substitute for Report Date in Contract Product Line SLA calculation.
`022` — Until a valid Report Date is accepted, calculations requiring it shall remain unavailable.
`023` — The SR shall visibly communicate the applicable incomplete or SLA-unclassified state rather than a fabricated result.
`024` — A later accepted valid Report Date shall populate the missing source fact on the existing SR.
`025` — That enrichment shall not change immutable SR identity.
`026` — Prior incomplete observations and import provenance shall remain intact.
`027` — Missing Problem Summary shall not prevent identity-preserving import.
`028` — Missing or not-yet-recognized Severity shall not prevent identity-preserving import.
`029` — Unresolved Customer Organization shall not prevent the SR from existing.
`030` — Missing or unresolved Contact shall not prevent the SR from existing.
`031` — Missing `Current Handler` shall not prevent import.
`032` — A workflow that genuinely requires a missing fact shall validate that prerequisite when the action is attempted.
`033` — The operator shall receive a reviewed way to supply, reconcile, or resolve that required fact where supported.
`034` — A missing field shall not disable unrelated SR capabilities merely because another workflow needs it.
`035` — An incomplete SR within a report's defined scope shall not be silently omitted solely because it lacks one or more calculation inputs.
`036` — The report shall represent unavailable/incomplete calculation state explicitly.
`037` — Advanced Search `Product` shall remain discarded.
`038` — `Current Handler` shall remain optional and source-owned.
`039` — Beta 1.0 shall not require an SR to become complete merely so reporting may finalize or preserve it.
`040` — Report generation shall not fabricate missing facts or modify the SR to satisfy a report completeness condition.

## `BETA-REQ-0076` — prefix `SR-CONT`

**Governing obligation:** Each official Service Request identity shall survive terminal state, disappearance, reappearance, and reviewed terminal reversal as one continuous record, while reversal remains explicitly high-risk and workbook validation evidence is never overstated as publisher-authenticity proof.

`001` — Each canonical official `SRNo` shall resolve to one surviving Service Request identity.
`002` — A terminal state shall not create a separate SR episode.
`003` — Source disappearance shall not replace or split SR identity.
`004` — Historical-view placement shall not create a separate archival SR identity.
`005` — Age or elapsed time shall not split an SR into another record.
`006` — An official SR identifier already belonging to a surviving SR shall not be reassigned to another record.
`007` — A later accepted observation for an already terminal SR shall continue reconciling usable allowlisted source facts.
`008` — Such later observations shall preserve their source/import provenance.
`009` — A source observation shall not be ignored solely because the SR is already terminal.
`010` — A valid source reappearance shall reconcile to the same existing SR.
`011` — A valid accepted reappearance may clear the applicable unresolved source-disappearance warning.
`012` — A recognized nonterminal Status observed after accepted `Resolved`, `Closed`, or `Cancelled` shall become a high-risk terminal-reversal proposal.
`013` — A terminal-reversal proposal shall never qualify for safe auto-accept.
`014` — Review shall expose the accepted terminal state/evidence being challenged.
`015` — The proposed nonterminal Status shall be shown explicitly.
`016` — The applicable source chronology shall be shown.
`017` — The validated logical-content fingerprint shall be associated with the review.
`018` — Material effects on current operational presentation shall be visible before confirmation.
`019` — Material effects on current Contract Product Line SLA calculation shall be visible before confirmation.
`020` — The operator may accept a terminal reversal only through explicit reviewed confirmation.
`021` — The workflow shall support legitimate external correction or manually manipulated source evidence without treating it as a new SR.
`022` — Accepted reversal shall update the current lifecycle state of the existing Service Request.
`023` — Acceptance shall not rewrite or delete previous terminal source evidence.
`024` — Previous terminal and reversal-review evidence shall remain auditable.
`025` — Accepted reversal shall recalculate affected current projections, including current SLA state where applicable.
`026` — Accepted reversal shall not modify completed Daily, Weekly, or Monthly report snapshots.
`027` — Rejecting the proposal shall preserve the currently accepted terminal state.
`028` — Enough bounded source/review evidence shall remain to explain the rejected reversal observation.
`029` — A missing Status shall not reopen an SR.
`030` — A blank Status shall not reopen an SR.
`031` — A malformed Status shall not reopen an SR.
`032` — An unrecognized Status shall not reopen an SR.
`033` — Workbook validation shall establish structural/processing validity, not publisher authenticity.
`034` — Source chronology shall not be represented as cryptographic proof of origin.
`035` — The logical-content fingerprint shall prove deterministic content identity/replay semantics, not who authored or published the workbook.
`036` — Passing anomaly checks shall not prove that a source file was not altered by a person.
`037` — Without independently verified digital-signature evidence, SOMA shall not claim cryptographic publisher authenticity, origin authenticity, or proof of absence of human modification.

## `BETA-REQ-0077` — prefix `RET-GOV`

**Governing obligation:** SOMA Beta 1.0 shall have no generalized operational-retention clock or purge schedule; main-view aging shall remain presentation-only, technical housekeeping shall remain isolated from authoritative history, and any future destructive retention policy shall require separately accepted installation-wide governance.

`001` — Beta 1.0 shall not assign domain records a general operational-retention countdown.
`002` — Authoritative domain records shall not receive a generic purge-due timestamp.
`003` — Elapsed age shall not automatically finalize operational records.
`004` — Beta 1.0 shall have no general scheduled process that purges authoritative domain records.
`005` — An SR's `Report Date` shall not start a general retention timer.
`006` — Resolved, Closed, Cancelled, or other terminal state shall not start a general retention timer.
`007` — Moving a record into Historical view shall not start a general retention timer.
`008` — Last activity shall not start a general retention timer.
`009` — Import/source chronology shall not start a general retention timer.
`010` — Inclusion in a Daily, Weekly, or Monthly report shall not start a general retention timer.
`011` — Operational-history retention shall be governed at installation/product-contract level rather than as a Local User preference.
`012` — A Local User setting shall not independently cause authoritative history to expire.
`013` — Beta 1.0 Settings shall not expose Alpha's 180-day operational retention default.
`014` — Beta 1.0 shall not expose a per-user domain-retention period.
`015` — Settings shall not expose Alpha's recurring daily operational purge job.
`016` — Beta 1.0 shall not expose retention-postponement controls on individual tickets.
`017` — Beta 1.0 shall not expose Alpha-style legal-hold controls for a general purge mechanism that does not exist.
`018` — The `BETA-REQ-0116` orphaned-communication grace shall remain the only accepted elapsed-time operational-content minimization exception in Beta 1.0.
`019` — That grace shall be governed installation-wide rather than per Local User.
`020` — Its accepted default shall remain seven exact elapsed days.
`021` — When the grace expires, eligibility shall be revalidated against current dependencies before destructive minimization.
`022` — The governed operation shall preserve the required record that content minimization occurred.
`023` — The required frozen terminal communication summary shall survive content minimization.
`024` — When Daily view is selected/configured, its period shall determine how long applicable terminal records remain in the main operational presentation.
`025` — The Weekly period shall likewise determine main-view presentation duration.
`026` — The Monthly period shall likewise determine main-view presentation duration.
`027` — When the applicable presentation period ends, the terminal record shall remain available through Historical view.
`028` — Moving out of the main view shall preserve the record's governed relationships.
`029` — Required source, audit, report, communication, and domain evidence shall remain intact.
`030` — The Daily/Weekly/Monthly display period shall not be represented as a retention duration.
`031` — Its end shall not be represented as a purge or deletion deadline.
`032` — Verified backup rotation shall use its own bounded technical policy.
`033` — Diagnostic-log rotation shall use its own technical retention policy.
`034` — Temporary staging cleanup shall remain separate from authoritative operational-history retention.
`035` — Cleanup of abandoned/uncommitted generated artifacts may use its own bounded technical policy.
`036` — Rebuildable disposable caches may be reconstructed or removed according to technical policy.
`037` — None of these technical cleanup mechanisms shall acquire authority to delete authoritative operational history.
`038` — Any generalized operational-retention capability shall require Beta 1.1 or later product authority.
`039` — Any such policy shall remain installation-wide unless a future accepted contract explicitly changes that model.
`040` — The future contract shall define exactly which record classes are eligible.
`041` — It shall define what event, if any, starts retention.
`042` — It shall define the applicable temporal basis.
`043` — It shall define treatment of active and terminal records.
`044` — It shall define dependency constraints and shared-evidence implications.
`045` — Any exceptions or hold mechanism shall be explicitly designed rather than inherited.
`046` — The future policy shall define impact-preview requirements.
`047` — It shall define manual or automated confirmation authority.
`048` — It shall define transactional execution/revalidation semantics.
`049` — Recovery expectations shall be explicitly defined.
`050` — Destructive retention operations shall have explicit audit requirements.
`051` — No Alpha retention duration shall automatically become Beta authority.
`052` — The absence or presence of Alpha hold semantics shall provide no implicit Beta authority.
