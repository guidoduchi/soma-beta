# SOMA Beta Normalization CP-006 — Normative Clauses

Status: **Accepted**  
Scope: clauses owned by `BETA-REQ-0128`–`BETA-REQ-0152`.  
Clause identities are stable normative references. Under each requirement, the displayed prefix plus the three-digit suffix forms the full clause ID.

## `BETA-REQ-0128` — prefix `VIEW-PROJ`

**Governing obligation:** Service Request and main operational views shall remain derived projections of accepted owning-domain truth: Customer scope, Communication activity, Inventory lifecycle context, Objective association, SLA and chronology presentation, and Historical placement shall resolve from their authoritative identities, relationships, events, and coverage rather than dashboard-owned state; mixed and unknown conditions shall remain explicit, drafts and rejected proposals shall not affect authoritative values, and the permanently discarded `Resolved Status Date` shall neither be represented nor recreated by inference or surrogate timestamp.

`001` — Service Request lists shall derive visible state from accepted owning-domain facts.
`002` — Overview shall derive visible state from accepted owning-domain facts.
`003` — Dashboards shall derive visible state from accepted owning-domain facts.
`004` — Service Request workbenches shall derive visible state from accepted owning-domain facts.
`005` — Operational exports shall derive values from accepted owning-domain facts.
`006` — A dashboard shall not become an independent source of domain truth.
`007` — A card count shall not become an independent source of domain truth.
`008` — A trend value shall not become an independent source of domain truth.
`009` — A warning projection shall not create the condition it reports.
`010` — Projection recomputation shall not mutate authoritative domain state.
`011` — Projection refresh shall not create lifecycle evidence.
`012` — Projection caches, if any, shall remain rebuildable from owning authority.
`013` — Projection cache loss shall not erase authoritative state.
`014` — Projection staleness shall remain distinguishable from authoritative change.
`015` — Unknown projection inputs shall remain unknown rather than guessed.
`016` — Partial projection inputs shall remain distinguishable from complete evidence.
`017` — Unavailable projection inputs shall remain distinguishable from confirmed absence.
`018` — Rejected proposals shall not affect authoritative projection values.
`019` — Draft proposals shall not affect authoritative projection values.
`020` — Unsaved UI working copies shall not affect authoritative projection values.
`021` — Persistent domain Draft state shall be shown according to its owning lifecycle rather than as accepted state.
`022` — Customer filtering shall use immutable Customer Organization identity.
`023` — Customer display name shall not serve as filter identity.
`024` — Customer aliases shall not create duplicate filter identities.
`025` — Customer rename shall preserve filter identity.
`026` — Customer filters shall support an all-Customer scope.
`027` — Customer filters shall support one specific Customer Organization scope.
`028` — Customer filters shall support an unassigned scope where owning data permits no Customer assignment.
`029` — Unassigned shall remain distinct from unknown Customer resolution.
`030` — The active Customer filter shall remain visible to the operator.
`031` — Customer scope shall apply consistently to list rows.
`032` — Customer scope shall apply consistently to summary cards.
`033` — Customer scope shall apply consistently to counts.
`034` — Customer scope shall apply consistently to trends.
`035` — Customer scope shall apply consistently to warnings.
`036` — Customer scope shall apply consistently to applicable exports.
`037` — Customer filtering shall not rewrite entity Customer ownership.
`038` — Filtering an entity out of view shall not archive or delete it.
`039` — Changing Customer filter shall not alter accepted relationships.
`040` — Customer-derived counts shall be recomputed from canonical scoped entities.
`041` — Communication summaries shall derive only from canonical accepted Communication links.
`042` — One canonical Communication shall count once per linked entity.
`043` — Duplicate source observations of one canonical Communication shall not inflate counts.
`044` — Received direction shall derive from supported Communication evidence.
`045` — Sent direction shall derive from supported Communication evidence.
`046` — Unknown direction shall remain explicitly unknown.
`047` — Scan time shall not substitute for message chronology.
`048` — Import time shall not substitute for message chronology.
`049` — Proposal time shall not substitute for message chronology.
`050` — Last interaction shall use the latest independently supported linked Communication chronology.
`051` — Interaction age shall derive from supported last-interaction chronology and current display time.
`052` — Missing supported interaction chronology shall remain unknown rather than zero-age.
`053` — Communication proposal counts shall derive from current governed proposals.
`054` — Rejected Communication proposals shall not inflate current pending counts.
`055` — Corrected Communication links shall not remain counted in the wrong entity summary.
`056` — Communication coverage state shall remain visible where it affects summary completeness.
`057` — Unknown Communication coverage shall not be displayed as zero Communications.
`058` — Partial Communication coverage shall not be displayed as complete coverage.
`059` — `.msg` drafts shall not count as observed sent Communications.
`060` — `.msg` artifact creation shall not update last observed interaction chronology.
`061` — Terminal SR Communication summaries shall use the governed frozen non-reconstructable summary.
`062` — Terminal RFC Communication summaries shall use the governed frozen non-reconstructable summary.
`063` — Frozen terminal summaries shall not preserve duplicate hidden body content.
`064` — Frozen terminal summaries shall remain distinct from live navigable Communication bodies.
`065` — Inventory summaries shall derive from accepted Inventory entities and lifecycle evidence.
`066` — Inventory summary shall not collapse all constituent lifecycle positions into one false completion flag.
`067` — Spare Need state shall remain independently representable in a summary.
`068` — Spare Request state shall remain independently representable in a summary.
`069` — RMA state shall remain independently representable in a summary.
`070` — Inbound Spare Part Unit state shall remain independently representable in a summary.
`071` — Installed or allocated physical-unit state shall remain independently representable in a summary.
`072` — Return-obligation state shall remain independently representable in a summary.
`073` — Fault Tag state shall remain independently representable in a summary.
`074` — Warehouse decision state shall remain independently representable in a summary.
`075` — Action-required Inventory positions shall remain independently visible.
`076` — Mixed Inventory state shall be displayed as mixed rather than forced into one status.
`077` — Missing Inventory evidence shall remain unknown rather than treated as completed.
`078` — Inventory summary shall derive requested and actual BOM facts from their owning entities.
`079` — Approved substitute relationships shall not rewrite the original requested BOM.
`080` — Inventory summary shall preserve official and local identity distinctions.
`081` — Task outcome information shown in Inventory context shall be consumed from accepted Task lifecycle evidence.
`082` — Inventory shall not become the owner of Task execution state.
`083` — Inventory shall not become the owner of Task outcome state.
`084` — Inventory shall not become the owner of Task review state.
`085` — Inventory shall not become the owner of Task correction state.
`086` — Inventory shall not become the owner of Task retry state.
`087` — Reviewed Task outcomes may drive Inventory physical consequences through the owning Inventory contract.
`088` — Pending Task review shall not be displayed as a finalized Inventory physical consequence.
`089` — Corrected Task outcome shall update derived Inventory context without rewriting historical Task evidence.
`090` — Objective context for a Service Request shall derive through accepted Task relationships.
`091` — A Service Request shall not acquire a competing direct SR-to-Objective authority.
`092` — SR-to-Task relationships shall determine applicable Objective membership.
`093` — A Task with no Objective shall not fabricate an Objective association for the SR.
`094` — A Task assigned to an Objective may contribute that Objective context to the SR projection.
`095` — Multiple applicable Tasks may expose multiple relevant Objective contexts where the view supports them.
`096` — Objective identity shall remain distinct from its time frame.
`097` — Maintenance Window presentation shall remain the Objective presentation defined by the owning Objective contract.
`098` — Objective status shall derive from Objective authority rather than SR status.
`099` — Task status shall derive from Task authority rather than Objective status.
`100` — Starting an Objective shall not make every Task appear started.
`101` — SLA presentation shall distinguish individual SR elapsed duration from cohort compliance.
`102` — Individual duration shall derive from the governing temporal/SLA chronology.
`103` — Contract Product Line cohort SLA shall derive from the applicable Customer-specific contract.
`104` — Product Line alone shall not determine a Customer's SLA contract.
`105` — Current SLA policy revisions shall recalculate current classified SR projections where approved.
`106` — Report-time SLA snapshots shall remain immutable once produced under their governing contract.
`107` — Report-time policy evidence shall remain distinguishable from current policy.
`108` — SLA tier percentages shall remain distinct from individual ticket duration.
`109` — SLA suspension state shall remain distinguishable from ordinary elapsed time.
`110` — Missing SLA classification shall remain unknown/inapplicable rather than fabricated.
`111` — Missing SLA chronology shall remain explicit rather than coerced to zero duration.
`112` — Cohort size and compliance denominator shall derive from the governed report scope.
`113` — A dashboard shall not invent a terminal endpoint such as `Closed` when the SLA contract does not establish it.
`114` — Customer filtering shall apply consistently to SLA cohort presentation where the report scope is Customer-scoped.
`115` — Daily main-view timing shall use the accepted configured/local display time zone.
`116` — Weekly main-view timing shall use the accepted configured/local display time zone.
`117` — Monthly main-view timing shall use the accepted configured/local display time zone.
`118` — Canonical stored instants shall remain UTC whole-second authority.
`119` — Display-period boundaries shall not rewrite stored instants.
`120` — Daily/Weekly/Monthly presentation buckets shall remain view projections.
`121` — Moving a row between time-bucket views shall not create lifecycle evidence.
`122` — Historical placement in a view shall derive from accepted lifecycle/status chronology.
`123` — Historical presentation shall not imply purge eligibility.
`124` — Historical presentation shall not imply data retention expiration.
`125` — Historical placement shall not delete relationships.
`126` — Historical placement shall not stop source reconciliation.
`127` — Terminal imported records shall remain available under their historical presentation rules.
`128` — Cancelled imported records shall remain available under their historical presentation rules.
`129` — Closed imported records shall remain available under their historical presentation rules.
`130` — Archived state shall remain distinct from merely historical view placement.
`131` — The discarded `Resolved Status Date` shall not be imported.
`132` — The discarded `Resolved Status Date` shall not be persisted.
`133` — The discarded `Resolved Status Date` shall not be displayed.
`134` — The discarded `Resolved Status Date` shall not be exported as a SOMA field.
`135` — The discarded `Resolved Status Date` shall not be inferred from `Closed` time.
`136` — The discarded `Resolved Status Date` shall not be inferred from `Cancelled` time.
`137` — The discarded `Resolved Status Date` shall not be inferred from last update time.
`138` — The discarded `Resolved Status Date` shall not be inferred from import time.
`139` — The discarded `Resolved Status Date` shall not be inferred from Communication time.
`140` — The discarded `Resolved Status Date` shall not be reconstructed from audit recording time.
`141` — Another timestamp shall not be renamed or repurposed as `Resolved Status Date`.
`142` — Missing legacy `Resolved Status Date` shall require no surrogate value.
`143` — Draft entities shall be visibly distinguishable from accepted entities in applicable projections.
`144` — Rejected proposals shall not affect counts.
`145` — Rejected proposals shall not affect SLA.
`146` — Rejected proposals shall not affect relationship projections.
`147` — Rejected proposals shall not affect action-required counts.
`148` — Loading state shall remain distinguishable from empty state.
`149` — Empty state shall remain distinguishable from filtered-empty state.
`150` — Partial state shall remain distinguishable from complete state.
`151` — Stale state shall remain distinguishable from current state.
`152` — Warning state shall remain distinguishable from error state.
`153` — Unknown and unavailable-evidence states shall remain explicit and accessible without relying only on color.
`154` — All material projection states shall retain accessible semantics, labels, and non-color cues consistent with the shared UI contract.

## `BETA-REQ-0129` — prefix `INV-ACT`

**Governing obligation:** Every Inventory action surface shall derive truthfully labelled commands from accepted lifecycle state, immutable identity, dependencies, relationships, targets, proposals, and correction history rather than editable status labels; material and bulk commands shall revalidate authoritative state, expose impact and complete preflight outcomes, preserve each owning transaction contract, retain manual evidence-independent paths, keep proposals and exports separate from lifecycle acceptance, and ensure every valid nonterminal state offers a governed next action or actionable blocker while correction, replacement, resend, cancellation, archival, deletion, and history remain distinct workflows.

`001` — Spare Need action surfaces shall derive commands from accepted Spare Need lifecycle state.
`002` — Spare Request action surfaces shall derive commands from accepted Spare Request lifecycle state.
`003` — RMA action surfaces shall derive commands from accepted RMA lifecycle state.
`004` — Spare Part Unit action surfaces shall derive commands from accepted unit lifecycle state.
`005` — Device Part Unit action surfaces shall derive commands from accepted unit lifecycle state.
`006` — Fault Tag action surfaces shall derive commands from accepted Fault Tag lifecycle state.
`007` — Membership action surfaces shall derive commands from accepted relationship state.
`008` — Action availability shall not derive from an independently editable status label.
`009` — Action availability shall use immutable entity identity.
`010` — Action availability shall use current accepted dependencies.
`011` — Action availability shall use current accepted relationships.
`012` — Action availability shall use the exact selected target where a command is target-specific.
`013` — Action availability shall consider relevant pending proposals.
`014` — Action availability shall consider accepted correction history where it changes current eligibility.
`015` — Action availability shall not rely on stale UI state alone.
`016` — Action labels shall describe the actual command semantics.
`017` — A lifecycle command shall remain distinct from manual evidence confirmation.
`018` — A lifecycle command shall remain distinct from a Communication proposal.
`019` — A lifecycle command shall remain distinct from artifact generation.
`020` — A lifecycle command shall remain distinct from export.
`021` — Correction shall remain distinct from ordinary progression.
`022` — Replacement shall remain distinct from correction.
`023` — Resend shall remain distinct from replacement.
`024` — Cancellation shall remain distinct from archival.
`025` — Archival shall remain distinct from eligible hard deletion.
`026` — History viewing shall remain distinct from state mutation.
`027` — A generated document shall not imply the represented request was submitted.
`028` — Exporting data shall not imply lifecycle acceptance.
`029` — Predictably unavailable actions should remain discoverable when explaining the blocker is useful.
`030` — A discoverable unavailable action shall expose the governing blocker.
`031` — A discoverable unavailable action shall expose remediation where a governed remediation exists.
`032` — A known-missing prerequisite shall not be exposed as an enabled command that can only fail.
`033` — A permanently inapplicable action need not be shown as enabled.
`034` — Disabled presentation shall remain accessible and explainable.
`035` — Action availability shall update when authoritative prerequisites change.
`036` — Material commands shall revalidate authoritative state immediately before commit.
`037` — Material commands shall not trust the state captured when a menu first opened.
`038` — Material commands shall identify the exact target identity before commit.
`039` — Material commands shall detect stale target revision where applicable.
`040` — Material commands shall reject execution when required state changed incompatibly.
`041` — Material commands shall show applicable impact before confirmation.
`042` — Impact preview shall identify affected entity types.
`043` — Impact preview shall identify affected relationships where material.
`044` — Impact preview shall identify destructive consequences where material.
`045` — Impact preview shall identify irreversible or high-risk consequences where applicable.
`046` — An impact preview shall not itself mutate state.
`047` — Closing an impact preview shall execute no command.
`048` — Consequential commands shall preserve their assigned confirmation tier.
`049` — A deliberate hold shall not replace a required impact preview.
`050` — Ordinary reversible commands shall not receive unnecessary ritual confirmation.
`051` — Bulk selection shall expose only command types supported for multi-target operation.
`052` — A command supporting only one target shall not masquerade as a bulk command.
`053` — Bulk preflight shall inspect every selected target.
`054` — Bulk preflight shall classify every selected target exactly once for that command attempt.
`055` — Bulk preflight shall identify eligible targets.
`056` — Bulk preflight shall identify incompatible targets.
`057` — Bulk preflight shall identify stale targets.
`058` — Bulk preflight shall identify targets missing required input.
`059` — Bulk preflight shall identify targets requiring individual review.
`060` — Bulk preflight shall not silently skip incompatible targets.
`061` — Bulk preflight shall not silently skip stale targets.
`062` — Bulk preflight shall not silently skip missing-input targets.
`063` — Bulk preflight shall not silently coerce an incompatible target into eligibility.
`064` — Bulk preflight shall not silently apply default input where explicit input is required.
`065` — Bulk preflight results shall remain inspectable before commit.
`066` — The operator shall be able to identify why each non-eligible target is blocked.
`067` — Eligible target count shall match the preflight result.
`068` — Incompatible target count shall match the preflight result.
`069` — Stale target count shall match the preflight result.
`070` — Missing-input target count shall match the preflight result.
`071` — Individual-review target count shall match the preflight result.
`072` — Re-running preflight shall use current authoritative state.
`073` — A stale preflight result shall not authorize commit without revalidation.
`074` — Bulk execution shall follow the owning domain's atomic-or-independent transaction contract.
`075` — A domain-defined all-or-nothing batch shall commit all eligible work or roll back it together.
`076` — A domain-defined independent-target batch may commit targets independently.
`077` — UI convenience shall not redefine an owning transaction boundary.
`078` — Partial success shall be reported only when the owning transaction contract permits partial success.
`079` — Partial success shall identify each successful target.
`080` — Partial failure shall identify each failed target.
`081` — A failed target shall preserve its actual pre-command authoritative state unless its own transaction committed a different governed result.
`082` — A batch shall have stable identity when persisted job/batch history is required.
`083` — Each target result shall retain target identity.
`084` — Each target result shall retain command identity.
`085` — Each target result shall retain success/failure classification.
`086` — Retry shall not lose the original target/result history.
`087` — Retrying one failed target shall not automatically repeat already successful targets unless the owning idempotency contract requires it.
`088` — Manual lifecycle paths shall remain available for supported transitions without Communication evidence.
`089` — Manual lifecycle paths shall remain available without manual attachment/upload evidence in Beta 1.0.
`090` — Manual receipt confirmation shall not require a parsed email.
`091` — Manual provider-response recording shall not require a scanned Communication when the owning lifecycle permits manual evidence.
`092` — Manual warehouse decision shall remain available under its owning lifecycle.
`093` — Manual installed-unit confirmation shall remain available with its required warning where applicable.
`094` — Communication-derived proposals shall remain optional assistance rather than the sole mutation path.
`095` — A Communication proposal shall not mutate authoritative state before review.
`096` — Rejecting a Communication proposal shall leave authoritative lifecycle unchanged.
`097` — Accepting a Communication proposal shall execute the owning domain command rather than a special bypass.
`098` — Proposal acceptance shall revalidate current authoritative state.
`099` — Proposal staleness shall prevent blind acceptance.
`100` — Artifact generation shall remain separate from proposal acceptance.
`101` — Export shall remain separate from proposal acceptance.
`102` — Generating a Spare Request artifact shall not assign the external provider identifier.
`103` — Generating a Fault Tag artifact shall not prove physical dispatch.
`104` — Generating a warehouse artifact shall not prove warehouse acceptance.
`105` — External files shall remain operator-managed after generation/export.
`106` — SOMA shall not modify an operator-managed external file merely because it was generated from SOMA.
`107` — Submission outside SOMA shall require independent accepted evidence before lifecycle progression where the lifecycle depends on submission.
`108` — A valid nonterminal Spare Need state shall expose a governed next action or actionable blocker.
`109` — A valid nonterminal Spare Request state shall expose a governed next action or actionable blocker.
`110` — A valid nonterminal RMA state shall expose a governed next action or actionable blocker.
`111` — A valid nonterminal Spare Part Unit state shall expose a governed next action or actionable blocker.
`112` — A valid nonterminal Fault Tag state shall expose a governed next action or actionable blocker.
`113` — A valid nonterminal membership workflow shall expose a governed next action or actionable blocker.
`114` — A blocker shall identify the prerequisite preventing progress.
`115` — A blocker shall distinguish missing data from incompatible lifecycle state.
`116` — A blocker shall distinguish stale review from permanently unsupported action.
`117` — An action surface shall not strand an entity merely because one automated evidence path is unavailable.
`118` — A failed command shall preserve actual authoritative state.
`119` — A failed command shall not be displayed as successful.
`120` — A failed command shall expose safe retry where the owning lifecycle permits retry.
`121` — A failed command shall expose correction where retry would be semantically wrong.
`122` — A retry shall revalidate authoritative state.
`123` — A retry shall preserve command idempotency semantics.
`124` — A correction shall target exact accepted evidence or relationship where required.
`125` — Correction shall append history rather than silently rewriting accepted evidence.
`126` — Correcting a false lifecycle event shall remain distinct from progressing to the next lifecycle state.
`127` — Correcting a false provider response shall remain distinct from recording a later provider response.
`128` — Replacement of an artifact shall remain distinct from correction of domain evidence.
`129` — Resending a warehouse artifact shall remain distinct from creating a new warehouse decision.
`130` — Resend shall preserve the prior send/generation history.
`131` — Cancellation shall preserve prior accepted lifecycle history.
`132` — Archival shall preserve prior accepted lifecycle history.
`133` — Eligible hard deletion shall preserve only the minimized audit evidence required by the deletion contract.
`134` — Hard deletion shall not be exposed when protected dependent history blocks deletion.
`135` — Hard deletion shall not be used as a substitute for cancellation.
`136` — Hard deletion shall not be used as a substitute for archival.
`137` — State-specific removal shall identify exactly what relationship or draft element will be removed.
`138` — Removing a membership relationship shall not delete either endpoint entity unless separately authorized.
`139` — Removing a Spare Need relationship shall obey Spare Request dependency rules.
`140` — A Spare Need used by an active Spare Request shall not be silently deleted.
`141` — Accepted cancelled/rejected Spare Request conditions may enable the separately governed Need-deletion path only with required review.
`142` — RMA removal shall obey official Spare Request and obligation-history rules.
`143` — Unit removal shall obey provenance and operational-history rules.
`144` — Fault Tag removal shall obey return-obligation history rules.
`145` — Selection state shall remain separate from action eligibility.
`146` — Highlighting an action shall not execute it.
`147` — Keyboard and pointer activation shall produce equivalent command semantics.
`148` — Touch activation shall produce equivalent command semantics where supported.
`149` — Action menus shall remain reachable under responsive layouts.
`150` — Overflowing commands shall remain discoverable rather than disappearing.
`151` — Destructive commands shall remain clearly distinguished from ordinary commands.
`152` — Provisional commands shall remain clearly distinguished from accepted-state commands.
`153` — Historical-only actions shall remain clearly distinguished from current lifecycle actions.
`154` — Unavailable-action explanations shall not rely only on color.
`155` — Bulk preflight classifications shall have accessible names/semantics.
`156` — Batch progress shall remain truthful when execution is long-running.
`157` — Cancelling a background batch shall follow its owning transaction-safe cancellation contract.
`158` — A cancelled background batch shall not be reported as completed.
`159` — Recovering a crashed batch shall not duplicate already committed target results.
`160` — Batch diagnostics shall not contain unrestricted Inventory/customer content.
`161` — Manual correction shall not require regenerated external files unless the correction itself owns an artifact consequence.
`162` — Regenerating an artifact shall not silently reapply lifecycle transitions.
`163` — History view shall show the accepted sequence of progression and corrections.
`164` — Current action eligibility shall derive from the corrected current projection rather than the mere existence of old events.
`165` — Pending proposals shall be represented separately from current authoritative action state.
`166` — Multiple pending proposals shall not silently collapse into one accepted decision.
`167` — An accepted proposal result shall retain the proposal identity/provenance where required.
`168` — An action requiring a specific physical unit shall display that unit's immutable identity.
`169` — An action requiring a specific RMA shall display that RMA's immutable identity.
`170` — An action requiring a specific Spare Request shall display that request's immutable identity.
`171` — An action requiring a Dispatch Location shall preserve operation-specific directionality and not relabel pickup origin as warehouse destination.
`172` — Cross-domain commands shall invoke explicit owning application commands rather than mutate another workflow's state directly.
`173` — UI action availability shall not weaken database/domain invariants.
`174` — Import-derived action proposals shall remain subject to the same command validation as manual actions.
`175` — Every accepted material action shall produce its required lifecycle/audit evidence under the owning contract.
`176` — Inventory action surfaces shall remain non-stranding, truthful projections of governed commands rather than editable status-control panels.

## `BETA-REQ-0130` — prefix `UX-REF`

**Governing obligation:** SOMA shall classify external and internal visual/artifact references by explicit authority—directional design reference, approved visual acceptance fixture, or export golden—and shall use vSphere, Wireshark, and terminal conventions only as non-copying inspiration within SOMA's proprietary responsive and accessible design; approved fixtures/goldens shall be versioned, reproducible, sanitized, tolerance- and provenance-defined, normative contracts shall always prevail, baselines shall never be changed merely to hide regressions, and missing required acceptance evidence shall block acceptance rather than authorize design by guesswork.

`001` — Every visual or artifact reference used by SOMA design/acceptance shall have an explicit authority classification.
`002` — A reference shall be classified as directional, visual acceptance fixture, export golden, or another separately approved authority class.
`003` — Directional references shall guide design direction without becoming exact acceptance baselines.
`004` — Visual acceptance fixtures shall be explicitly approved before they become normative acceptance evidence.
`005` — Export goldens shall be explicitly approved before they become normative export acceptance evidence.
`006` — An unclassified screenshot shall not become normative merely because it is available.
`007` — An old prototype shall not become normative merely because it resembles the current UI.
`008` — A third-party UI shall not become normative merely because it inspired SOMA.
`009` — Normative SOMA requirements shall outrank directional references.
`010` — Normative SOMA requirements shall outrank visual fixture guesses.
`011` — Normative SOMA requirements shall outrank export golden assumptions when the golden conflicts with accepted behavior.
`012` — A directional reference shall not define exact pixel positions.
`013` — A directional reference shall not define exact component dimensions.
`014` — A directional reference shall not define exact workflow semantics.
`015` — A directional reference shall not define domain terminology.
`016` — A directional reference shall not define confirmation tiers.
`017` — A directional reference shall not define authoritative state meaning.
`018` — vSphere may inspire contextual explorer organization.
`019` — vSphere may inspire entity header/action organization.
`020` — vSphere may inspire tabbed entity workbench organization.
`021` — vSphere may inspire modular card composition.
`022` — vSphere may inspire progressive disclosure.
`023` — vSphere may inspire independent pane behavior.
`024` — vSphere may inspire activity/history surfaces.
`025` — vSphere inspiration shall remain directional only.
`026` — SOMA shall not copy vSphere branding.
`027` — SOMA shall not copy vSphere logos or proprietary assets.
`028` — SOMA shall not copy vSphere product terminology into unrelated SOMA domain concepts.
`029` — SOMA shall not copy vSphere pixels as an acceptance baseline without explicit fixture approval.
`030` — SOMA shall not imitate vSphere trade dress as a substitute for proprietary SOMA design.
`031` — Wireshark may inspire efficient high-volume list inspection.
`032` — Wireshark may inspire list/detail/evidence navigation patterns.
`033` — Wireshark may inspire keyboard-fluent inspection.
`034` — Wireshark inspiration shall remain directional only.
`035` — SOMA shall not copy Wireshark branding.
`036` — SOMA shall not copy Wireshark proprietary assets.
`037` — SOMA shall not copy Wireshark terminology where it would replace SOMA domain terminology.
`038` — SOMA shall not make packet-analysis interaction assumptions normative for unrelated workflows.
`039` — Terminal interfaces may inspire concise information hierarchy.
`040` — Terminal interfaces may inspire restrained monospace operational accents.
`041` — Terminal interfaces may inspire keyboard fluency.
`042` — Terminal inspiration shall not make SOMA a terminal-only interface.
`043` — Terminal inspiration shall not remove pointer/touch accessibility obligations.
`044` — Terminal inspiration shall not override readable long-form typography.
`045` — SOMA shall combine directional references into a proprietary SOMA interface.
`046` — SOMA's combined interface shall remain responsive.
`047` — SOMA's combined interface shall remain accessible.
`048` — SOMA's combined interface shall preserve shared navigation contracts.
`049` — SOMA's combined interface shall preserve semantic token/skin contracts.
`050` — SOMA's combined interface shall preserve domain terminology.
`051` — SOMA shall not copy third-party brand colors as required identity cues.
`052` — SOMA shall not copy third-party icon assets without explicit proprietary ownership/license authority.
`053` — SOMA shall not copy third-party logos.
`054` — SOMA shall not copy third-party trademarks into SOMA branding.
`055` — SOMA shall not copy third-party screen pixels as ordinary implementation guidance.
`056` — SOMA shall not copy third-party trade dress.
`057` — Directional references may be described in internal design rationale without becoming acceptance fixtures.
`058` — Long-form content shall use readable typography.
`059` — Long-form content shall not be forced into monospace merely because terminal interfaces are directional references.
`060` — Tables/code/identifiers may use approved monospace accents where appropriate.
`061` — Typography shall remain readable under supported zoom/text enlargement.
`062` — Typography shall remain compatible with Light/Dark/System appearance.
`063` — A visual acceptance fixture shall identify the exact product state it represents.
`064` — A visual acceptance fixture shall identify the relevant viewport/container state.
`065` — A visual acceptance fixture shall identify relevant appearance/skin context.
`066` — A visual acceptance fixture shall identify relevant data-state context.
`067` — A visual acceptance fixture shall be versioned.
`068` — Fixture version changes shall be attributable.
`069` — A fixture shall use synthetic or irreversibly sanitized data.
`070` — A fixture shall not contain live customer data.
`071` — A fixture shall not contain credentials or secrets.
`072` — A fixture shall not contain reconstructable Communication bodies unless separately approved and sanitized beyond reconstruction.
`073` — Fixture data shall remain representative enough to exercise the intended state.
`074` — A fixture shall define the environment assumptions needed for reproducibility.
`075` — A fixture shall define the browser/runtime assumptions where they materially affect rendering.
`076` — A fixture shall define the font/rendering assumptions where they materially affect tolerance.
`077` — A fixture shall define the expected tolerance rather than demand undefined pixel identity.
`078` — Tolerance shall not hide material layout or semantic regressions.
`079` — Tolerance shall distinguish anti-aliasing/rendering noise from meaningful regression where possible.
`080` — A fixture shall record provenance explaining who/what approved it.
`081` — Fixture provenance shall identify the normative requirement/state it evidences.
`082` — Fixture provenance shall remain immutable historical evidence for that version.
`083` — An export golden shall identify the exact export family.
`084` — An export golden shall identify the export schema/version.
`085` — An export golden shall use synthetic or irreversibly sanitized data.
`086` — An export golden shall define comparison rules.
`087` — An export golden shall distinguish semantic equality from irrelevant container metadata where the format requires it.
`088` — Export golden differences shall not be ignored merely because a file opens successfully.
`089` — Export golden acceptance shall not overwrite domain requirements.
`090` — A fixture/golden baseline shall not be changed merely to make a failing regression pass.
`091` — A baseline change shall have an explicit reason.
`092` — A baseline change shall identify the requirement/design change that justifies it.
`093` — A baseline change shall be reviewed before becoming acceptance authority.
`094` — A baseline update shall not silently remove coverage of a previously required state.
`095` — A baseline update shall remain historically attributable.
`096` — Missing required visual fixture shall block that acceptance evidence.
`097` — Missing required export golden shall block that acceptance evidence.
`098` — Missing required evidence shall not authorize implementers to guess the intended design.
`099` — Missing required evidence shall be reported as missing rather than passing by omission.
`100` — Directional references may still guide implementation while normative evidence is being completed, but cannot substitute for a required fixture at acceptance.
`101` — An obsolete fixture shall not remain current acceptance authority.
`102` — Fixture supersession shall identify the replacing fixture/version.
`103` — Fixture deletion shall not erase its historical provenance where accepted releases depended on it.
`104` — Visual fixtures shall cover material responsive states where layout meaningfully changes.
`105` — Visual fixtures shall cover material warning/error states where appearance is acceptance-relevant.
`106` — Visual fixtures shall cover focus/selection states where appearance is acceptance-relevant.
`107` — Visual fixtures shall not be the sole accessibility acceptance method.
`108` — Automated/manual semantic accessibility checks shall complement visual fixtures.
`109` — Export goldens shall not be the sole validation of import/export semantics.
`110` — Structural/schema assertions shall complement export golden comparisons.
`111` — Reference catalogue entries shall identify whether they are directional, fixture, or golden.
`112` — Reference catalogue entries shall identify current/superseded status.
`113` — Reference catalogue entries shall identify ownership/provenance.
`114` — Reference catalogue entries shall link to applicable requirement/design authority.
`115` — A third-party screenshot shall default to non-normative unless explicitly classified otherwise with lawful authority.
`116` — User-provided sketches may be directional unless explicitly approved as fixtures.
`117` — Generated mockups may be directional unless explicitly approved as fixtures.
`118` — An AI-generated visual shall not become acceptance authority merely because it looks plausible.
`119` — Acceptance shall test behavior/semantics independently from visual resemblance.
`120` — Responsive reflow may legitimately differ from wide-screen directional references while preserving required capability.
`121` — Accessibility requirements may legitimately require divergence from directional reference visuals.
`122` — SOMA branding requirements may legitimately require divergence from directional reference visuals.
`123` — Domain terminology requirements may legitimately require divergence from directional reference labels.
`124` — Confirmation-tier requirements may legitimately require divergence from directional reference actions.
`125` — No directional reference may weaken non-color state communication.
`126` — No directional reference may weaken keyboard equivalence.
`127` — No directional reference may weaken focus visibility.
`128` — No directional reference may weaken responsive reachability.
`129` — Required fixture comparisons shall run against the versioned approved baseline for the exact acceptance state.
`130` — Fixture comparison failures shall be investigated rather than automatically re-baselined.
`131` — Fixture/golden acceptance evidence shall be reproducible from controlled inputs and environment assumptions.
`132` — Normative SOMA contracts remain final authority whenever a reference, fixture, golden, or directional inspiration conflicts with them.

## `BETA-REQ-0131` — prefix `DB-FK`

**Governing obligation:** Every authoritative SQLite access path shall obtain connections from one SOMA-owned factory that enables and proves foreign-key enforcement before authoritative work, with the same integrity policy applying to application, startup, migration, import, job, test, maintenance, and restore-validation paths; relational actions shall implement rather than redefine owning deletion contracts, normal child-side foreign-key paths shall have genuinely usable leading-prefix indexes, ordinary connections shall never disable enforcement, and any isolated versioned SQLite rebuild exception shall be recovery-tested and pass post-operation foreign-key validation before service.

`001` — Every authoritative SQLite connection shall be obtained through one SOMA-owned connection factory.
`002` — Application request handling shall use the authoritative connection factory.
`003` — Startup validation shall use the authoritative connection factory where authoritative access is required.
`004` — Migration code shall use the governed connection policy.
`005` — Import workflows shall use the governed connection policy.
`006` — Background jobs shall use the governed connection policy.
`007` — Automated tests exercising authoritative behavior shall use the governed connection policy unless explicitly testing a rejected bypass.
`008` — Maintenance operations shall use the governed connection policy.
`009` — Restore validation shall use the governed connection policy.
`010` — Ad hoc application repository code shall not create unmanaged authoritative SQLite connections.
`011` — The connection factory shall enable SQLite foreign-key enforcement before authoritative transactions.
`012` — The connection factory shall verify that foreign-key enforcement is enabled.
`013` — Verification shall occur before authoritative work begins on the connection.
`014` — Failure to enable foreign keys shall fail safely.
`015` — Failure to verify foreign keys shall fail safely.
`016` — A connection with unknown foreign-key enforcement state shall not perform authoritative work.
`017` — Foreign-key enforcement shall not be assumed from SQLite version alone.
`018` — Foreign-key enforcement shall not be assumed from a previous connection.
`019` — Foreign-key enforcement shall be verified per authoritative connection as required by SQLite connection scope.
`020` — Connection pooling/reuse shall preserve verified enforcement.
`021` — Reopened connections shall be reverified as appropriate.
`022` — Read-only authoritative validation paths shall still use the governed integrity policy.
`023` — Foreign-key enforcement policy shall apply consistently across Python 3.13 and 3.14 support targets.
`024` — Foreign-key actions shall implement owning domain deletion/update contracts.
`025` — `CASCADE` shall not be introduced merely for convenience when the owning domain requires protected history.
`026` — `SET NULL` shall not be introduced when the owning relation requires exactly one parent.
`027` — `RESTRICT`/`NO ACTION` behavior shall not be weakened by UI bypass.
`028` — Database actions shall not invent domain deletion semantics absent approved authority.
`029` — Domain-dependent deletion checks shall still execute transactionally where FK syntax alone is insufficient.
`030` — Referential integrity shall remain enforced even when imports attempt invalid relationships.
`031` — Referential integrity shall remain enforced even when jobs attempt invalid relationships.
`032` — Referential integrity shall remain enforced even when migrations transform relationships.
`033` — Referential integrity shall remain enforced after restore validation.
`034` — Every normal child-side foreign-key access path shall have an effective supporting index where used by joins or parent checks.
`035` — An index shall be considered effective only when SQLite can use its leading columns for the FK access path.
`036` — A single-column FK may use a single-column index.
`037` — A single-column FK may use a composite index only when the FK column is the usable leading prefix.
`038` — A composite FK shall use an index whose leading columns match the FK columns in usable order.
`039` — An index containing FK columns only after unrelated leading columns shall not count as the required effective FK index.
`040` — An index with incompatible expression/collation semantics shall not be assumed effective without proof.
`041` — Unique constraints may satisfy indexing only when they provide the required usable access path.
`042` — Primary-key indexes may satisfy indexing only when they provide the required usable access path.
`043` — Redundant duplicate indexes need not be created when an existing effective index already satisfies the path.
`044` — Index verification shall inspect the actual accepted schema.
`045` — Index verification shall not rely only on migration source text.
`046` — Schema tests shall detect missing child-side FK indexes.
`047` — Schema tests shall detect ineffective composite-leading-column order.
`048` — Parent deletion/update checks shall not degrade into avoidable full child scans where an effective index is required.
`049` — Normal joins on FK columns shall have the expected effective index support.
`050` — Index requirements shall not redefine business uniqueness.
`051` — A non-unique FK index may be valid when uniqueness is not a domain invariant.
`052` — A unique index shall not be added merely to satisfy FK performance if duplicates are valid.
`053` — Ordinary authoritative connections shall never disable foreign-key enforcement.
`054` — Application code shall not issue `PRAGMA foreign_keys=OFF` on an ordinary authoritative connection.
`055` — Import code shall not disable foreign keys to accept bad rows.
`056` — Job code shall not disable foreign keys to force progress.
`057` — Test helpers shall not disable foreign keys for tests claiming product acceptance.
`058` — Maintenance code shall not disable foreign keys to simplify cleanup.
`059` — Restore code shall not disable foreign keys and then claim restored data is valid without governed exception/validation.
`060` — Migration code shall not casually disable foreign keys outside an isolated SQLite-required rebuild exception.
`061` — A SQLite-required rebuild exception shall be explicit.
`062` — A rebuild exception shall be versioned as part of a governed migration.
`063` — A rebuild exception shall be narrowly scoped.
`064` — A rebuild exception shall document why ordinary FK-enforced migration cannot perform the required SQLite transformation.
`065` — A rebuild exception shall not become a general connection-factory bypass.
`066` — A rebuild exception shall preserve the last committed version on failure according to migration authority.
`067` — A rebuild exception shall be recovery-tested.
`068` — A rebuild exception shall preserve immutable identities.
`069` — A rebuild exception shall preserve required relationships.
`070` — A rebuild exception shall preserve audit append-only protections where applicable.
`071` — A rebuild exception shall validate row counts/constraints appropriate to the migrated schema.
`072` — A rebuild exception shall run `foreign_key_check` after enforcement is restored.
`073` — Any reported `foreign_key_check` violation shall fail the migration/readiness validation.
`074` — Post-migration validation shall detect FK violations before ordinary service.
`075` — Post-restoration validation shall detect FK violations before ordinary service.
`076` — Startup shall not report ready if required FK validation fails.
`077` — Browser launch shall not turn an FK-invalid data instance into apparent success.
`078` — FK validation failure shall be reported truthfully.
`079` — Diagnostic emission failure shall not convert FK validation failure into success.
`080` — Schema status inspection shall remain observational and not repair FK violations implicitly.
`081` — The factory shall configure any connection settings required for consistent authoritative operation before use.
`082` — Connection configuration shall not silently differ between UI and background-job paths.
`083` — Connection configuration shall not silently differ between import and application paths.
`084` — Connection configuration shall not silently differ between migration verification and restore verification.
`085` — Connection factory behavior shall be deterministically testable.
`086` — Tests shall open an authoritative connection and prove FK enforcement is on.
`087` — Tests shall attempt an invalid child insert and prove rejection.
`088` — Tests shall attempt an invalid parent delete and prove the owning deletion contract is enforced.
`089` — Tests shall attempt an invalid parent update where applicable and prove enforcement.
`090` — Tests shall cover transaction rollback after FK failure.
`091` — Tests shall cover import rollback after FK failure.
`092` — Tests shall cover job rollback after FK failure where applicable.
`093` — Tests shall cover restore validation with deliberately invalid references.
`094` — Tests shall cover migration validation with deliberately invalid references.
`095` — Tests shall verify every declared FK has its intended delete/update action.
`096` — Tests shall verify every required child-side FK path has an effective index.
`097` — Tests shall verify composite indexes use the FK columns as a usable leading prefix.
`098` — Tests shall not count an unrelated composite index as effective merely because it contains the FK later.
`099` — Tests shall cover schema variants from every supported migration origin.
`100` — Tests shall verify no ordinary runtime path disables FK enforcement.
`101` — Tests shall cover the isolated rebuild exception path where such a migration exists.
`102` — Failure injection shall prove rebuild interruption does not expose invalid ready state.
`103` — Recovery tests shall prove retry after rebuild failure is safe.
`104` — Recovery tests shall prove post-rebuild `foreign_key_check` must pass.
`105` — The connection factory shall remain the single policy choke point even if repositories are refactored.
`106` — A new authoritative workflow shall integrate through the factory before acceptance.
`107` — A plugin or future workflow shall not obtain bypass authority without new accepted product/design authority.
`108` — Read-only diagnostics that do not perform authoritative database access need not become relational authority.
`109` — Non-authoritative tooling shall not be allowed to mutate the authoritative database through an unmanaged connection.
`110` — Database corruption or invalid-file conditions shall fail before authoritative transactions.
`111` — FK enforcement shall complement, not replace, higher-level domain validation.
`112` — Higher-level domain validation shall complement, not disable, FK enforcement.
`113` — Foreign keys shall use immutable internal identifiers rather than business identifiers where required by the identity contract.
`114` — External SR/RFC/WFM identifiers shall not become relational FK keys merely for convenience.
`115` — Relationship corrections shall preserve immutable endpoint identities.
`116` — Hard-deletion eligibility shall be checked before database actions that would remove protected parents.
`117` — Cascade behavior shall not erase protected audit history.
`118` — Cache/projection deletion shall not be confused with FK-governed authoritative deletion.
`119` — A successful SQL statement shall not be treated as product-valid if higher-level transaction rules fail.
`120` — A failed SQL constraint shall never be converted into accepted product success by catch-and-ignore behavior.
`121` — Authoritative SQLite integrity behavior shall remain consistent across startup, service, import, jobs, tests, maintenance, migration, and restore validation.
`122` — Ordinary service shall be exposed only after the authoritative connection/integrity policy required for that data instance is proven operational.

## `BETA-REQ-0132` — prefix `DB-MIG`

**Governing obligation:** Every SOMA schema migration shall be a serialized, crash-safe authoritative version transition in which transactional schema/data changes and migration-ledger bookkeeping commit together or roll back together; exactly one migrator shall own a data instance, re-read current schema and ledger after acquiring ownership, preserve the last committed version across cancellation or failure, and support safe retry, while ordinary service remains blocked until migrations and all required ledger, schema, foreign-key, and audit-protection validations pass and any nontransactional step requires separately accepted recovery-aware design.

`001` — Every schema migration shall represent one governed version transition.
`002` — Migration schema mutations shall be coordinated with migration-ledger bookkeeping.
`003` — Transactional schema changes and their ledger record shall commit together.
`004` — Transactional data changes performed by a migration and their ledger record shall commit together.
`005` — Migration-ledger bookkeeping shall not claim a version whose transactional schema/data changes rolled back.
`006` — Schema/data changes shall not commit without the required ledger update in the same atomic boundary where SQLite supports the transaction.
`007` — Migration failure shall preserve the last fully committed version.
`008` — Migration cancellation shall preserve the last fully committed version.
`009` — Storage failure shall preserve the last committed version or expose explicit recovery-required state rather than a false newer version.
`010` — Constraint failure shall preserve the last committed version.
`011` — Ledger-write failure shall roll back the associated transactional migration work.
`012` — Exactly one migrator shall own a canonical data instance at a time.
`013` — Two concurrent startup processes shall not both migrate the same data instance.
`014` — Migration ownership shall be acquired before applying migration work.
`015` — Migration ownership shall be scoped to canonical data-instance identity.
`016` — Alternate path spellings of the same canonical data instance shall not authorize concurrent migrators.
`017` — Port differences shall not authorize concurrent migration of the same data instance.
`018` — Process differences shall not authorize concurrent migration of the same data instance.
`019` — A second migrator shall wait/fail according to governed startup ownership behavior rather than run concurrently.
`020` — After acquiring migration ownership, SOMA shall re-read current schema state.
`021` — After acquiring migration ownership, SOMA shall re-read the migration ledger.
`022` — A migration plan computed before ownership shall not be trusted without the post-ownership re-read.
`023` — Post-ownership re-read shall detect work completed by another process before ownership was obtained.
`024` — Post-ownership re-read shall prevent applying one migration twice.
`025` — Migration ordering shall derive from the accepted migration lineage.
`026` — Migration application shall begin from the actual committed current version.
`027` — Unsupported future version shall not be migrated backward automatically.
`028` — Drifted lineage shall not be migrated as though it were a clean older version.
`029` — Missing accepted migration evidence shall block ordinary migration readiness until reconciled.
`030` — Unknown migration state shall not be guessed.
`031` — Each migration shall validate applicable preconditions before mutation.
`032` — Preconditions shall use current post-ownership schema/ledger state.
`033` — A migration shall not silently skip required work because an individual SQL statement happens to succeed.
`034` — A migration shall not silently mark itself applied because some target objects already exist unexpectedly.
`035` — Unexpected schema state shall produce an explicit failure/conflict.
`036` — Transactional migrations shall use one transaction boundary sufficient to cover required schema/data/ledger work.
`037` — Commit shall occur only after all required migration steps succeed.
`038` — Rollback shall occur when a required migration step fails.
`039` — Rollback shall occur when required ledger bookkeeping fails.
`040` — Rollback shall occur when required post-step transaction validation inside the same boundary fails.
`041` — Crash before commit shall not leave the ledger claiming success.
`042` — Crash after a successful commit shall be recoverable by re-reading committed state.
`043` — Retry after crash shall detect the actual committed version before applying work.
`044` — Retry shall be safe after storage failure once the storage condition is resolved.
`045` — Retry shall be safe after constraint failure once the cause is corrected through a governed path.
`046` — Retry shall be safe after ledger failure once the cause is resolved.
`047` — Retry shall not duplicate data transformations already committed.
`048` — Retry shall not duplicate audit-protection setup already committed.
`049` — Cancellation shall occur only at a safe boundary.
`050` — Cancellation shall not interrupt an indivisible transaction and report it partially successful.
`051` — A cancellation request during a transaction may be deferred until a safe boundary.
`052` — Cancelled migration shall not report the target as current if pending work remains.
`053` — Cancelled migration shall preserve truthful pending state.
`054` — Cancellation shall not silently rewrite the migration ledger.
`055` — Ordinary service shall remain blocked while required migrations are pending.
`056` — Ordinary service shall remain blocked while migration is running.
`057` — Ordinary service shall remain blocked after migration failure.
`058` — Ordinary service shall remain blocked after migration cancellation if required work remains.
`059` — Readiness shall not be reported merely because the database file can be opened.
`060` — Readiness shall not be reported merely because the last migration SQL statement ran.
`061` — Required migration-ledger validation shall pass before readiness.
`062` — Required schema validation shall pass before readiness.
`063` — Required foreign-key validation shall pass before readiness.
`064` — Required audit-protection validation shall pass before readiness.
`065` — Any other accepted integrity gate shall pass before readiness.
`066` — Browser launch shall not precede authenticated readiness.
`067` — A listening local socket shall not substitute for migration readiness.
`068` — Migration diagnostics shall not convert failure into readiness.
`069` — Migration status command shall observe rather than perform pending migration.
`070` — Migration ownership shall integrate with the broader canonical data-instance ownership contract.
`071` — The service shall not release ownership and expose ordinary service before migration/readiness gates complete.
`072` — Migration ownership failure shall produce a truthful startup state.
`073` — A stale runtime registry shall not substitute for migration ownership proof.
`074` — A stale lock/ownership artifact shall be handled according to process/data-instance identity rather than blindly deleted or trusted.
`075` — Exact ownership/lock mechanics remain LLD-defined.
`076` — A nontransactional migration step shall not be introduced implicitly.
`077` — A required nontransactional step shall require separately accepted design authority.
`078` — The accepted design for a nontransactional step shall define failure recovery.
`079` — The accepted design for a nontransactional step shall define restart/retry behavior.
`080` — The accepted design for a nontransactional step shall define how ledger truth remains consistent.
`081` — The accepted design for a nontransactional step shall define readiness blocking behavior.
`082` — A nontransactional exception shall remain isolated rather than weaken all migrations.
`083` — SQLite rebuild exceptions shall also satisfy the FK/recovery rules in `0131`.
`084` — Migration source files accepted into the protected lineage shall satisfy `0133` immutability.
`085` — Migration runner shall reject unsupported missing/unknown lineage conditions rather than invent a path.
`086` — Migration runner shall preserve immutable entity identities during transformations.
`087` — Migration runner shall preserve required historical evidence.
`088` — Migration runner shall preserve accepted audit rows.
`089` — Migration runner shall preserve domain relationships unless a governed migration intentionally transforms them.
`090` — A migration shall not redefine product behavior beyond accepted schema/data transformation authority.
`091` — Supported starting versions shall be explicitly known/tested.
`092` — Clean uninitialized-state migration shall be tested.
`093` — Every supported prior release schema shall have a tested path to current.
`094` — Unsupported origin shall fail visibly rather than be guessed.
`095` — Tests shall cover two concurrent migration attempts on one data instance.
`096` — Tests shall prove only one migrator applies each migration.
`097` — Tests shall prove the second process re-reads state after ownership.
`098` — Failure injection shall cover crash/interruption before commit.
`099` — Failure injection shall cover failure during schema mutation.
`100` — Failure injection shall cover failure during data transformation.
`101` — Failure injection shall cover ledger-write failure.
`102` — Failure injection shall cover constraint failure.
`103` — Failure injection shall cover storage/I/O failure where reproducibly simulatable.
`104` — Failure injection shall prove the ledger never advances past rolled-back work.
`105` — Failure injection shall prove safe retry from the last committed version.
`106` — Tests shall cover cancellation at a safe boundary.
`107` — Tests shall cover cancellation requested during an active transaction.
`108` — Tests shall prove cancellation does not expose partial authoritative success.
`109` — Tests shall verify required schema after migration.
`110` — Tests shall verify migration ledger after migration.
`111` — Tests shall run foreign-key validation after migration.
`112` — Tests shall verify audit append-only protections after migration where applicable.
`113` — Tests shall verify ordinary service stays blocked on failed validation.
`114` — Tests shall verify browser launch stays blocked on failed validation.
`115` — Tests shall verify retry after successful committed migration is a no-op for already applied steps.
`116` — Tests shall verify drifted accepted migration state does not proceed as ordinary migration.
`117` — Tests shall verify unsupported future version remains blocked.
`118` — Tests shall verify a missing accepted migration remains blocked.
`119` — Tests shall verify migration status remains observational.
`120` — Tests shall control time/concurrency/filesystem sufficiently for deterministic failure evidence.
`121` — Migration logs shall use sanitized diagnostics rather than unrestricted SQL/data dumps.
`122` — Migration diagnostics shall identify stable phase/error context without becoming ledger authority.
`123` — Required migration audit/protection setup shall fail closed for readiness even if diagnostics fail open.
`124` — A successful migration shall leave one unambiguous current committed version.
`125` — A failed migration shall leave one unambiguous last committed version or an explicit integrity/recovery failure state.
`126` — Migration/version bookkeeping shall never be repaired silently merely to permit startup.
`127` — Recovery from a failed accepted migration shall occur through safe retry or separately governed repair/forward migration, not history rewriting.
`128` — SOMA shall expose authoritative service only after the serialized migration and complete integrity/readiness contract succeeds for the canonical data instance.

## `BETA-REQ-0133` — prefix `DB-MIGFREEZE`

**Governing obligation:** A migration may be corrected or consolidated only while it remains an unaccepted branch candidate; acceptance into the protected migration lineage shall permanently freeze its identity, filename, order, canonical bytes, checksum, and manifest entry, after which startup shall detect and distinctly report unknown, missing, drifted, misordered, ledger-mismatched, or unsupported-future migration state and block authoritative service rather than rewrite lineage evidence, while accepted defects are corrected only by new forward migrations and checksums serve solely as deterministic drift evidence rather than proof of authorship or malicious tampering.

`001` — A migration that exists only as an unaccepted branch candidate may be corrected before lineage acceptance.
`002` — An unaccepted branch candidate may be consolidated with other unaccepted candidates when repository policy permits.
`003` — Pre-acceptance correction shall not be described as rewriting accepted product history.
`004` — Development databases affected by a pre-acceptance rewrite may be rebuilt/reset under development policy.
`005` — Pre-acceptance rewrite authority ends when the migration is accepted into the protected lineage.
`006` — Acceptance into the protected migration lineage shall freeze the migration's identity.
`007` — Acceptance shall freeze the migration filename.
`008` — Acceptance shall freeze the migration order.
`009` — Acceptance shall freeze the migration content.
`010` — Acceptance shall freeze canonical byte representation used for drift comparison.
`011` — Acceptance shall freeze the migration checksum recorded for that accepted content.
`012` — Acceptance shall freeze the migration manifest entry.
`013` — Accepted migration identity shall not be reused for different content.
`014` — Accepted migration filename shall not be renamed to hide lineage changes.
`015` — Accepted migration order shall not be renumbered/reordered to hide lineage changes.
`016` — Accepted migration SQL/content shall not be edited in place to fix a defect.
`017` — Accepted migration checksum shall not be recomputed and silently replaced after content drift.
`018` — Accepted manifest entries shall not be rewritten merely to make startup pass.
`019` — Canonical encoding for accepted migration drift evidence shall be deterministic.
`020` — Canonical encoding shall define UTF-8 handling.
`021` — Canonical encoding shall define line-ending treatment.
`022` — Canonicalization shall not change accepted migration semantics.
`023` — Repository tooling shall produce the same checksum for the same canonical bytes.
`024` — Startup shall load the accepted migration manifest.
`025` — Startup shall inspect the available migration set.
`026` — Startup shall inspect the applied migration ledger.
`027` — Startup shall compare manifest, files, order, and ledger before authoritative service.
`028` — An unknown migration file/identity shall be reported distinctly.
`029` — Unknown migration state shall not be silently added to the accepted manifest.
`030` — A missing accepted migration file shall be reported distinctly.
`031` — Missing migration state shall not be silently removed from the manifest.
`032` — Drifted migration content/checksum shall be reported distinctly.
`033` — Drift shall not be repaired by replacing the ledger checksum.
`034` — Drift shall not be repaired by replacing the manifest checksum.
`035` — Drift shall not be repaired by editing the accepted migration to match an unexpected checksum.
`036` — Misordered migration files shall be reported distinctly.
`037` — Misorder shall not be repaired silently by changing accepted lineage order.
`038` — Ledger-mismatched migration state shall be reported distinctly.
`039` — Ledger mismatch shall include applied identities absent from expected accepted lineage where applicable.
`040` — Ledger mismatch shall include expected applied identities missing from the ledger where applicable.
`041` — Ledger mismatch shall include inconsistent version/order evidence where applicable.
`042` — Unsupported-future migration/version state shall be reported distinctly.
`043` — A database from a newer unsupported migration lineage shall not be opened for ordinary authoritative service.
`044` — Startup shall distinguish future-version state from corruption where deterministically possible.
`045` — Startup shall distinguish missing migration from content drift.
`046` — Startup shall distinguish drift from misorder.
`047` — Startup shall distinguish ledger mismatch from source-file drift.
`048` — Startup shall block authoritative service on accepted-lineage drift.
`049` — Startup shall block authoritative service on unresolved missing accepted migration.
`050` — Startup shall block authoritative service on unresolved unknown migration where lineage cannot be proven.
`051` — Startup shall block authoritative service on unresolved misorder.
`052` — Startup shall block authoritative service on ledger mismatch.
`053` — Startup shall block authoritative service on unsupported future version.
`054` — Browser launch shall not present a drifted data instance as ready.
`055` — Runtime health shall not report ready before migration-lineage validation succeeds.
`056` — Migration status shall report drift observationally rather than repair it.
`057` — A failed drift check shall preserve the underlying files unchanged.
`058` — Accepted migration defects shall be corrected through a new forward migration.
`059` — A forward corrective migration shall have a new migration identity.
`060` — A forward corrective migration shall preserve the original accepted migration file unchanged.
`061` — A forward corrective migration shall preserve the original manifest evidence unchanged.
`062` — A forward corrective migration shall preserve the original applied ledger history unchanged.
`063` — A forward corrective migration may transform schema/data to repair the defect under migration rules.
`064` — Corrective migration history shall remain inspectable.
`065` — An accepted migration shall not be squashed out of protected history merely to simplify the current schema.
`066` — Accepted migration identities shall remain non-reusable after supersession by later migrations.
`067` — Development-only reset authority shall not be exposed as production/history-rewrite authority.
`068` — A branch candidate rewrite may require local development database reset when prior candidate bytes were already applied.
`069` — Development reset shall not be used on accepted operational data merely because a migration changed unexpectedly.
`070` — Checksums shall provide deterministic drift evidence.
`071` — A checksum match shall mean the compared canonical bytes match the expected digest under the selected algorithm.
`072` — A checksum shall not be described as proof of authorship.
`073` — A checksum shall not be described as a digital signature.
`074` — A checksum shall not be described as cryptographic proof against privileged malicious file replacement.
`075` — A checksum mismatch shall not by itself identify who caused the change.
`076` — A checksum mismatch shall not by itself distinguish accident from malicious tampering.
`077` — Repository access control remains a separate protection boundary.
`078` — Application startup validation remains a separate detection boundary.
`079` — Backup integrity remains a separate protection/recovery concern.
`080` — Migration manifest shall be version-controlled as protected project material.
`081` — Manifest generation/update shall be deterministic.
`082` — Manifest entry shall identify migration identity.
`083` — Manifest entry shall identify filename/order as required.
`084` — Manifest entry shall identify expected checksum.
`085` — Manifest shall not contain operational/customer data.
`086` — Manifest shall not contain secrets.
`087` — A migration file shall not contain operational/customer data.
`088` — A migration file shall not contain secrets.
`089` — Migration acceptance shall occur through repository/protected-lineage governance rather than runtime self-acceptance.
`090` — Runtime shall not modify repository migration files.
`091` — Runtime shall not rewrite the migration manifest.
`092` — Runtime shall not update source-controlled checksums to match local drift.
`093` — Restore validation shall include migration-lineage compatibility before service.
`094` — Backup restore shall preserve the applied migration ledger represented in the backup.
`095` — Restore shall not rewrite accepted migration history to fit the restored database.
`096` — A restored older supported version shall migrate forward normally after lineage validation.
`097` — A restored future unsupported version shall remain blocked.
`098` — A restored drifted ledger/files state shall remain blocked pending governed recovery.
`099` — Tests shall cover branch-candidate correction before acceptance.
`100` — Tests shall cover candidate consolidation before acceptance where supported.
`101` — Tests shall prove accepted migration content is treated as immutable.
`102` — Tests shall deliberately modify one accepted migration byte and detect drift.
`103` — Tests shall deliberately alter line endings contrary to canonical expectations and verify deterministic comparison behavior.
`104` — Tests shall deliberately change an accepted filename and detect missing/unknown lineage as applicable.
`105` — Tests shall deliberately change accepted order and detect misorder.
`106` — Tests shall deliberately remove an accepted file and detect missing state.
`107` — Tests shall add an unexpected migration and detect unknown state.
`108` — Tests shall simulate ledger missing entry and detect mismatch.
`109` — Tests shall simulate ledger unexpected entry and detect mismatch.
`110` — Tests shall simulate unsupported future version and block service.
`111` — Tests shall prove startup does not repair drift automatically.
`112` — Tests shall prove migration status reports drift without mutation.
`113` — Tests shall prove a forward corrective migration can repair an accepted defect without editing the old migration.
`114` — Tests shall prove the original accepted checksum remains unchanged after forward correction.
`115` — Tests shall verify manifest comparison is deterministic across supported Windows/Python environments.
`116` — Tests shall control line endings/encoding to prove canonical-byte behavior.
`117` — Tests shall not assert checksum security properties beyond deterministic drift detection.
`118` — Diagnostics for drift shall identify migration identity/state without dumping sensitive operational data.
`119` — Drift diagnostics shall distinguish expected checksum from observed checksum where safe/useful.
`120` — Drift diagnostics shall not repair or accept the drift.
`121` — An operator-facing error shall explain that accepted migration history cannot be edited in place.
`122` — An operator-facing error shall distinguish development-candidate reset options from operational accepted-lineage recovery.
`123` — A protected-primary acceptance event shall be the conceptual freeze boundary even if exact branch/ruleset mechanics evolve.
`124` — No local runtime flag shall downgrade an accepted migration back to mutable candidate status.
`125` — No database value shall downgrade an accepted migration back to mutable candidate status.
`126` — No manifest rewrite shall retroactively redefine which bytes were accepted without explicit repository-history correction outside normal runtime behavior.
`127` — Migration lineage identity shall remain independent of applied-at runtime timestamps.
`128` — Applied-at timestamps shall not substitute for migration order/identity.
`129` — File mtime shall not define migration acceptance chronology.
`130` — File mtime shall not define migration order.
`131` — Checksum generation time shall not define migration order.
`132` — Migration order shall remain an explicit protected-lineage property.
`133` — Unknown/missing/drifted/misordered/mismatched/future states shall remain mutually distinguishable where evidence permits.
`134` — A generic “database error” shall not be the only operator feedback when a specific migration-lineage state is known.
`135` — Accepted migration-lineage validation shall precede ordinary authoritative service.
`136` — Correction of migration history after acceptance shall always be forward/additive rather than in-place mutation.
`137` — SOMA shall preserve deterministic migration lineage evidence without overstating it as cryptographic provenance.

## `BETA-REQ-0134` — prefix `DB-MIGSTAT`

**Governing obligation:** Migration status shall be a strictly observational operation that reports absence without initializing anything, inspects existing targets only through demonstrably non-mutating access, never migrates, repairs, checkpoints, vacuums, changes database configuration, writes schema or ledger state, or replaces invalid content, prefers the authenticated running-instance status path over unsafe offline interference, truthfully distinguishes current, pending, drifted, future, invalid, integrity-failed, live/locked-limited, and inspection-failed states, and must prove through filesystem-snapshot acceptance tests that the status operation itself produces no side effects.

`001` — Migration status shall be strictly observational.
`002` — Invoking migration status shall not initialize SOMA data.
`003` — Invoking migration status shall not perform migration.
`004` — Invoking migration status shall not perform repair.
`005` — Invoking migration status shall not mutate authoritative domain state.
`006` — For a missing target, status shall report Not initialized or equivalent explicit absence.
`007` — A missing target check shall not create a database file.
`008` — A missing target check shall not create the containing application data directory merely to inspect status.
`009` — A missing target check shall not create SQLite `-wal` sidecars.
`010` — A missing target check shall not create SQLite `-shm` sidecars.
`011` — A missing target check shall not create rollback journals.
`012` — A missing target check shall not create temporary files.
`013` — A missing target check shall not create lock files.
`014` — A missing target check shall not create runtime registry files.
`015` — A missing target check shall not create settings/default records.
`016` — A missing target check shall not persist a default path merely by reading configuration.
`017` — Missing-target inspection shall be possible through filesystem metadata checks that do not initialize state.
`018` — Existing-target inspection shall use explicit non-mutating access.
`019` — Existing SQLite inspection shall use read-only access where supported.
`020` — Existing SQLite inspection shall use query-only safeguards where appropriate.
`021` — Status shall not issue schema writes.
`022` — Status shall not issue migration-ledger writes.
`023` — Status shall not insert default rows.
`024` — Status shall not update settings.
`025` — Status shall not repair indexes.
`026` — Status shall not create missing tables.
`027` — Status shall not create missing triggers.
`028` — Status shall not create missing audit protections.
`029` — Status shall not change `PRAGMA` settings persistently.
`030` — Status shall not disable foreign keys.
`031` — Status shall not enable write-oriented journaling merely to inspect.
`032` — Status shall not run checkpoint operations.
`033` — Status shall not run `VACUUM`.
`034` — Status shall not run optimization that mutates the database.
`035` — Status shall not run recovery that changes the file.
`036` — Status shall not overwrite an invalid database with a new one.
`037` — Status shall not rename an invalid database and initialize another automatically.
`038` — Status shall not truncate invalid content.
`039` — Invalid-file state shall remain inspectable/reportable without replacement.
`040` — If an authenticated SOMA instance is running for the target, status should prefer the authenticated live-instance status path where possible.
`041` — Live-instance status shall verify the exact intended run/data identity.
`042` — Live-instance status shall not trust port occupancy alone.
`043` — Live-instance status shall not follow redirects to another endpoint.
`044` — Live-instance status shall use bounded timeouts.
`045` — Live-instance status shall bypass proxies according to runtime trust rules.
`046` — Failure of the live authenticated path shall not silently fall back to unsafe write-capable offline access.
`047` — Offline inspection shall avoid disturbing a live writer.
`048` — If safe offline inspection cannot be proven while a writer is active/locked, status shall report limited/unavailable.
`049` — Limited live/locked status shall remain distinguishable from corruption.
`050` — Limited live/locked status shall remain distinguishable from migration pending.
`051` — Status shall identify current migration state when all accepted migrations are applied and validated.
`052` — Status shall identify pending migration state when accepted migrations remain unapplied.
`053` — Status shall identify drifted state when accepted migration evidence differs.
`054` — Status shall identify unsupported future-version state.
`055` — Status shall identify invalid-database state.
`056` — Status shall identify integrity-failure state.
`057` — Status shall identify live/locked limitation state.
`058` — Status shall identify inspection-failure state.
`059` — Status shall distinguish Not initialized from invalid database.
`060` — Status shall distinguish pending from drifted.
`061` — Status shall distinguish drifted from future version.
`062` — Status shall distinguish integrity failure from generic inspection failure where known.
`063` — Status shall distinguish authenticated-running status from unverified port conflict.
`064` — Status shall not mark current merely because the latest ledger version number matches.
`065` — Current status shall require applicable schema/ledger/lineage validation.
`066` — Current status shall not require mutating the database to prove it.
`067` — Pending status shall report enough bounded information to identify unapplied migration count/identity where safe.
`068` — Drift status shall report enough bounded information to identify the drift category.
`069` — Future-version status shall report the unsupported version/lineage indicator where safe.
`070` — Invalid-database status shall not expose unrestricted file contents.
`071` — Integrity-failure status shall not attempt silent repair.
`072` — Inspection-failure status shall preserve the original target unchanged.
`073` — Status command exit/result semantics shall distinguish success/current from non-current/failed inspection as defined by CLI design.
`074` — UI status presentation shall distinguish each governed state accessibly.
`075` — A warning state shall not be displayed as success.
`076` — A status check shall not acquire long-lived authoritative migration ownership merely to observe.
`077` — A status check shall not start the application service.
`078` — A status check shall not launch the browser.
`079` — A status check shall not create the runtime registry.
`080` — A status check shall not rotate diagnostics merely as a side effect beyond unavoidable read-only-safe logging policy.
`081` — Status diagnostics shall not change the inspected target.
`082` — File open modes shall be demonstrably non-mutating for acceptance.
`083` — SQLite URI/open options shall be selected to avoid creation where the target is absent.
`084` — A status implementation shall not rely on an API that auto-creates missing SQLite databases.
`085` — If the selected library would auto-create, the implementation shall guard existence before opening.
`086` — Status shall not resolve absence by touching the path.
`087` — Status shall not resolve permissions by changing them automatically.
`088` — Permission-denied shall be reported as inspection limitation/failure rather than “Not initialized.”
`089` — Unsupported file format shall be reported as invalid/inspection failure rather than replaced.
`090` — Filesystem races shall be handled without turning the check into a mutating recovery workflow.
`091` — A target disappearing during inspection shall produce a truthful changed/failed result.
`092` — A target changing during offline inspection shall produce limited/stale/failed evidence rather than false certainty where detectable.
`093` — Tests shall snapshot the relevant filesystem before missing-target status.
`094` — Tests shall snapshot the relevant filesystem after missing-target status.
`095` — Missing-target before/after snapshots shall prove no files/directories/sidecars/temp/locks/settings were created.
`096` — Tests shall snapshot an existing valid target before status.
`097` — Tests shall snapshot the existing valid target after status.
`098` — Existing-target snapshots shall prove database bytes and sidecar state were not changed by status under the controlled test.
`099` — Tests shall cover current state.
`100` — Tests shall cover pending state.
`101` — Tests shall cover drift state.
`102` — Tests shall cover future-version state.
`103` — Tests shall cover invalid-database state.
`104` — Tests shall cover integrity-failure state.
`105` — Tests shall cover live/locked limitation state.
`106` — Tests shall cover inspection-failure state.
`107` — Tests shall cover authenticated running-instance status.
`108` — Tests shall cover redirect rejection on live status.
`109` — Tests shall cover proxy bypass on live status.
`110` — Tests shall cover bounded timeout on unresponsive live status.
`111` — Tests shall prove status never applies a pending migration.
`112` — Tests shall prove status never repairs drift.
`113` — Tests shall prove status never changes migration ledger.
`114` — Tests shall prove status never vacuums/checkpoints/configures the target.
`115` — Tests shall prove invalid file remains unchanged.
`116` — Required status tests shall be deterministic across supported Windows/Python targets.
`117` — Migration status output shall remain observational evidence rather than a source of authoritative lifecycle state.
`118` — Any operation that must mutate the target shall be a separate explicitly named command/workflow rather than hidden inside migration status.

## `BETA-REQ-0135` — prefix `AUD-EVID`

**Governing obligation:** SOMA shall preserve accepted domain lifecycle evidence, application audit, proposal/job history, and technical diagnostics as separate authorities: lifecycle evidence records operational occurrences and independently supported chronology, while audit records meaningful accepted actions through immutable action identity, actor/source, UTC recording time, target, applicable reason and command/correlation references, minimal change evidence, and resulting domain-event references; required domain mutation, lifecycle evidence, and audit shall commit atomically, failures or rejected proposals shall never fabricate accepted state, projection recomputation shall create no lifecycle events, corrections shall append against exact identities, and eligible hard deletion shall leave only minimized non-reconstructable audit evidence while combined History surfaces clearly label each authority.

`001` — Accepted domain lifecycle evidence shall be a distinct record class.
`002` — Application audit shall be a distinct record class.
`003` — Proposal history shall be a distinct record class.
`004` — Background-job history shall be a distinct record class.
`005` — Technical diagnostics shall be a distinct record class.
`006` — Diagnostic records shall not become lifecycle evidence.
`007` — Proposal records shall not become lifecycle evidence before acceptance.
`008` — Job progress records shall not become lifecycle evidence merely because processing occurred.
`009` — Application audit shall not replace domain lifecycle evidence when the domain requires an event.
`010` — Domain lifecycle evidence shall not replace application audit when audit is required.
`011` — Combined History may show several record classes while preserving their labels/authority.
`012` — Lifecycle evidence shall record an operational occurrence.
`013` — Lifecycle evidence shall use independently supported occurrence chronology where available.
`014` — Occurrence chronology shall remain distinct from audit recording time.
`015` — Import time shall not automatically become lifecycle occurrence time.
`016` — Audit recording time shall not automatically become lifecycle occurrence time.
`017` — Communication scan time shall not automatically become lifecycle occurrence time.
`018` — Missing occurrence chronology shall remain unknown when no governing source establishes it.
`019` — Lifecycle event identity shall be immutable.
`020` — Lifecycle event target identity shall be stable.
`021` — Lifecycle event type shall have governed semantics.
`022` — Lifecycle correction shall reference exact prior evidence where required.
`023` — Application audit shall record meaningful accepted commands/decisions/configuration/relationship mutations.
`024` — Audit shall not log every projection read as a meaningful accepted action.
`025` — Audit shall not fabricate an accepted action for a rejected proposal.
`026` — Every audit event shall have immutable opaque action/event identity.
`027` — Audit identity shall remain independent of domain business identifiers.
`028` — Audit shall identify actor or authoritative source.
`029` — Local User actions shall identify the Local User actor/source as governed.
`030` — Import/source-driven actions shall identify the source/workflow where applicable.
`031` — Background/system actions shall identify their governed source rather than impersonating the Local User.
`032` — Audit shall record UTC recording time.
`033` — Audit recording time shall represent when SOMA accepted/recorded the action.
`034` — Audit recording time shall not rewrite source occurrence chronology.
`035` — Audit shall identify the target entity/type.
`036` — Audit target identity shall use immutable internal identity or another governed immutable reference.
`037` — Audit shall preserve a reason category where the owning action requires one.
`038` — Free-form reason text shall not substitute for a required governed reason category.
`039` — Audit may reference the command identity.
`040` — Audit may reference a correlation identity.
`041` — Command/correlation references shall remain purpose-specific rather than sensitive values.
`042` — Audit shall preserve minimal change evidence sufficient to explain the accepted action.
`043` — Minimal change evidence shall not become a full entity snapshot.
`044` — Audit shall reference resulting domain-event identities where the command creates domain events.
`045` — Resulting domain-event references shall preserve the distinction between action recording and occurrence evidence.
`046` — Required domain mutation and required lifecycle event shall commit atomically.
`047` — Required domain mutation and required audit shall commit atomically.
`048` — Required lifecycle event and required audit shall commit atomically when part of the same accepted command.
`049` — Failure to insert required audit shall roll back the uncommitted domain mutation.
`050` — Failure to insert required lifecycle evidence shall roll back the uncommitted domain mutation.
`051` — Failure to mutate the domain shall prevent a successful audit record that claims the mutation succeeded.
`052` — Failure to mutate the domain shall prevent successful lifecycle evidence claiming the occurrence was accepted.
`053` — Transaction rollback shall not leave a false success projection.
`054` — Diagnostic emission failure shall not rescue a failed authoritative transaction.
`055` — A failed command may produce technical diagnostics without producing accepted lifecycle state.
`056` — A rejected proposal may preserve proposal/review history without producing accepted domain mutation.
`057` — A cancelled review may preserve review metadata without producing accepted domain mutation.
`058` — A validation failure shall not create a success lifecycle event.
`059` — An authorization failure shall not create a success lifecycle event.
`060` — An integrity failure shall not create a success lifecycle event.
`061` — A migration failure shall not create domain lifecycle success.
`062` — Projection recomputation shall not create lifecycle events.
`063` — Dashboard refresh shall not create lifecycle events.
`064` — Re-running a report shall not create lifecycle events for the reported entities.
`065` — Rebuilding a cache shall not create lifecycle events.
`066` — Recomputing current state from existing events shall not duplicate events.
`067` — Correction shall target exact immutable evidence identity where possible.
`068` — Correction shall append new evidence rather than mutate original accepted evidence.
`069` — Correction shall preserve the original event.
`070` — Correction shall preserve correction actor/source.
`071` — Correction shall preserve correction recording chronology.
`072` — Correction shall preserve applicable reason.
`073` — Current projection may incorporate correction without erasing original history.
`074` — Reversal shall append evidence.
`075` — Cancellation shall append evidence.
`076` — Restoration shall append evidence.
`077` — Supersession shall append evidence.
`078` — Replacement shall append evidence where it is an accepted meaningful action.
`079` — Resend shall append evidence where it is an accepted meaningful action.
`080` — Archive shall append audit/history rather than rewrite earlier actions.
`081` — Hard deletion eligibility shall be established before deletion.
`082` — Eligible hard deletion shall preserve minimized audit evidence that the action occurred.
`083` — Deletion audit shall not retain a reconstructable whole deleted entity.
`084` — Deletion audit shall not retain unrestricted Notes content.
`085` — Deletion audit shall not retain unrestricted Communication content.
`086` — Deletion audit shall not retain secrets.
`087` — Deletion audit shall preserve action identity.
`088` — Deletion audit shall preserve actor/source.
`089` — Deletion audit shall preserve recording time.
`090` — Deletion audit shall preserve target type and minimized opaque historical reference as permitted.
`091` — Deletion audit may preserve bounded reason category.
`092` — Deleted entity business identifiers shall be minimized according to the owning deletion/audit schema.
`093` — Audit minimization shall not create a shadow tombstone database.
`094` — Combined History shall label lifecycle events as lifecycle evidence.
`095` — Combined History shall label application audit as audit/action evidence.
`096` — Combined History shall label proposal/review history separately.
`097` — Combined History shall label background-job history separately.
`098` — Combined History shall label technical diagnostics separately where surfaced.
`099` — History ordering shall preserve each record class's accepted chronology semantics.
`100` — Audit recording time shall not be displayed as source occurrence time without clear labeling.
`101` — Job start/end time shall not be displayed as domain occurrence time without authority.
`102` — Proposal creation time shall not be displayed as accepted mutation time.
`103` — Communication time shall remain source Communication chronology.
`104` — Import source chronology shall remain source observation chronology.
`105` — Audit target references shall remain resolvable after ordinary archival where required.
`106` — Historical audit shall remain viewable after terminal domain state.
`107` — Diagnostic rotation shall not remove lifecycle evidence.
`108` — Diagnostic rotation shall not remove application audit.
`109` — Proposal cleanup shall not remove required application audit.
`110` — Job cleanup shall not remove required application audit.
`111` — Cache cleanup shall not remove required application audit.
`112` — Projection rebuild shall not remove required application audit.
`113` — Communication orphan purge shall not delete unrelated application audit.
`114` — General source-file cleanup shall not delete audit authority.
`115` — Audit shall use minimal bounded payloads governed by action-specific contracts.
`116` — Audit shall not serialize whole command objects.
`117` — Audit shall not serialize whole domain entities.
`118` — Audit shall not serialize ORM/database objects.
`119` — Audit shall not store arbitrary exceptions.
`120` — Audit shall not store unrestricted provider/import payloads.
`121` — Audit shall not store full Communication bodies.
`122` — Audit shall not store full Notes content.
`123` — Audit shall not store secrets/authentication material.
`124` — Technical exceptions belong in sanitized diagnostics rather than audit payloads.
`125` — Proposal reasoning/evidence shall remain in proposal authority rather than copied wholesale into audit.
`126` — Job counters/progress shall remain in job history rather than copied wholesale into audit.
`127` — Audit may reference proposal/job identities when needed for correlation.
`128` — Audit correlations shall use immutable/purpose-created identifiers.
`129` — Required audit insertion shall use append-only semantics.
`130` — Required audit insertion shall not silently ignore duplicate event identity.
`131` — Command idempotency shall resolve before audit insertion.
`132` — Duplicate action identity shall remain an integrity error rather than ordinary replay success.
`133` — Accepted audit rows shall not be updated.
`134` — Accepted audit rows shall not be deleted.
`135` — Accepted audit rows shall not be replaced.
`136` — Audit corrections shall append.
`137` — Historical audit payload versions shall remain readable.
`138` — Historical audit payload versions shall not be rewritten merely because schemas evolve.
`139` — Audit startup validation shall verify required append-only protections.
`140` — Missing audit protections shall block readiness where authoritative audit integrity would be weakened.
`141` — Backup shall preserve audit rows.
`142` — Restore shall preserve audit rows.
`143` — Migration shall preserve audit rows and protections.
`144` — Application audit append-only protection shall not be described as cryptographic immunity from privileged file replacement.
`145` — Database checksums/digests shall not be used to overclaim audit authenticity.
`146` — Privileged external replacement remains outside the guarantee unless separately protected by a future cryptographic design.
`147` — Tests shall prove occurrence time and audit recording time remain distinct.
`148` — Tests shall prove required audit failure rolls back domain mutation.
`149` — Tests shall prove rejected proposals create no accepted lifecycle mutation.
`150` — Tests shall prove projection recomputation creates no lifecycle event.
`151` — Tests shall prove correction appends while preserving original evidence.
`152` — Tests shall prove eligible deletion leaves only minimized non-reconstructable audit evidence.
`153` — Tests shall prove History labels authority classes distinctly.
`154` — Tests shall prove diagnostics cannot substitute for required audit.
`155` — Tests shall prove audit cannot substitute for required domain event.
`156` — Tests shall prove failed domain mutation cannot leave a success audit/event pair.
`157` — Tests shall prove target/correlation references preserve immutable identity.
`158` — Tests shall prove audit payload minimization rejects prohibited content.
`159` — Tests shall prove backup/restore preserves accepted audit rows.
`160` — Tests shall prove migration preserves audit protections.
`161` — Tests shall prove no ordinary retention/purge path deletes audit.
`162` — Lifecycle, audit, proposal/job history, and diagnostics shall remain separately queryable authorities even when displayed together.
`163` — Current domain projections shall derive from accepted lifecycle/correction authority rather than from audit summary text.
`164` — SOMA History shall explain accepted operational truth without collapsing distinct evidence classes into one ambiguous log stream.

## `BETA-REQ-0136` — prefix `JSON-CONTRACT`

**Governing obligation:** Every persisted JSON document shall belong to an explicitly named and versioned bounded contract whose role remains distinct among UI working copies, persistent domain Drafts, typed local settings, and approved job documents; SOMA shall strictly validate encoding, JSON form, duplicate/nonfinite values, shape, fields, types, required members, semantics, size, depth, collection bounds, and version before persistence, treat database JSON validity only as a backstop, preserve missing/null/empty distinctions and explicit unknown-version/field policies, perform validated version upgrades and setting writes atomically while reads create nothing, and never use JSON as a substitute for normalized authority or as ordinary storage for secrets, unrestricted Communication/provider payloads, or complete domain objects, with canonicalization defined only where specifically required.

`001` — Every persisted JSON document shall have an explicitly named contract.
`002` — Every persisted JSON document shall have an explicit contract version.
`003` — Contract name/version shall identify the expected document semantics.
`004` — Unknown contract name shall not be treated as a known document type.
`005` — Unknown contract version shall not be treated as current.
`006` — UI recoverable working-copy JSON shall remain distinct from persistent domain Draft JSON.
`007` — UI recoverable working-copy JSON shall remain non-authoritative.
`008` — Persistent domain Draft JSON shall follow the owning domain Draft lifecycle.
`009` — Typed local settings JSON shall remain distinct from domain Drafts.
`010` — Approved job-document JSON shall remain distinct from settings and domain Drafts.
`011` — JSON document role shall not be inferred solely from file/table location.
`012` — JSON shall not be used to erase distinctions between document roles.
`013` — JSON encoding shall be valid UTF-8.
`014` — Malformed UTF-8 shall be rejected.
`015` — Truncated Unicode sequences shall be rejected.
`016` — JSON syntax shall be strictly valid for the accepted parser contract.
`017` — Truncated JSON shall be rejected.
`018` — Trailing garbage outside the accepted JSON document shall be rejected.
`019` — Duplicate JSON object keys shall be rejected unless a separately approved contract explicitly defines otherwise; Beta baseline is reject.
`020` — Last-key-wins duplicate handling shall not silently normalize persisted authority.
`021` — First-key-wins duplicate handling shall not silently normalize persisted authority.
`022` — `NaN` shall be rejected.
`023` — Positive infinity shall be rejected.
`024` — Negative infinity shall be rejected.
`025` — Non-standard numeric literals shall be rejected unless explicitly part of a future accepted format.
`026` — Database JSON-valid checks shall serve only as a structural backstop.
`027` — Database JSON validity shall not replace application contract validation.
`028` — Contract validation shall verify top-level shape.
`029` — Contract validation shall verify allowed fields.
`030` — Contract validation shall verify required fields.
`031` — Contract validation shall verify field types.
`032` — Contract validation shall verify semantic constraints.
`033` — Contract validation shall verify total document size.
`034` — Contract validation shall verify maximum nesting depth.
`035` — Contract validation shall verify collection item-count bounds.
`036` — Contract validation shall verify string length bounds where applicable.
`037` — Contract validation shall verify numeric bounds where applicable.
`038` — Contract validation shall verify identifier syntax where applicable.
`039` — Contract validation shall verify referenced enum values where applicable.
`040` — Unknown required semantic state shall fail rather than be guessed.
`041` — Unknown fields shall follow an explicit per-contract policy.
`042` — A contract may explicitly reject unknown fields.
`043` — A contract may explicitly preserve unknown fields for forward-compatible non-authoritative transport where approved.
`044` — A contract may explicitly quarantine unknown fields where approved.
`045` — Unknown-field policy shall not be selected ad hoc by each call site.
`046` — Unknown-field preservation shall not make the unknown field authoritative.
`047` — Unknown-field quarantine shall keep the field from current authoritative use.
`048` — Unknown-version documents shall follow an explicit unsupported/upgrade/quarantine policy.
`049` — Unknown-version documents shall not be parsed as the newest known schema.
`050` — Missing member and explicit `null` shall remain distinguishable where the contract assigns different meaning.
`051` — Missing member and empty string shall remain distinguishable where meaningful.
`052` — Missing member and empty array shall remain distinguishable where meaningful.
`053` — Explicit `null` and empty string shall remain distinguishable where meaningful.
`054` — Explicit `null` and empty collection shall remain distinguishable where meaningful.
`055` — Whitespace-only string shall not automatically become null unless the contract defines normalization.
`056` — Numeric zero shall not automatically become missing.
`057` — Boolean false shall not automatically become missing.
`058` — Empty object shall not automatically become missing.
`059` — Contract-specific normalization shall occur before persistence as explicitly defined.
`060` — Normalization shall not invent absent business facts.
`061` — Normalization shall not collapse meaningful distinctions.
`062` — Canonicalization shall be defined only for documents that require deterministic canonical bytes/logical fingerprints.
`063` — JSON documents shall not all be canonicalized merely for convenience.
`064` — Canonicalization rules shall be versioned when they affect fingerprints/signatures/comparison.
`065` — Version upgrade shall start from a document valid under its declared old contract.
`066` — Version upgrade shall produce a document valid under the target contract.
`067` — Version upgrade shall be explicit and deterministic.
`068` — Version upgrade shall preserve semantic meaning or record an approved transformation.
`069` — Version upgrade shall not silently discard unknown/protected information contrary to policy.
`070` — Version upgrade shall validate before commit.
`071` — Version upgrade shall commit atomically.
`072` — Failed version upgrade shall preserve the last valid persisted document.
`073` — Interrupted version upgrade shall preserve the last committed version.
`074` — Retry after failed upgrade shall be safe.
`075` — Historical audit payload JSON shall not be upgraded in place merely to newest schema.
`076` — Working-copy recovery may migrate its own non-authoritative format only under its own contract.
`077` — Persistent domain Draft upgrades shall not silently accept the Draft as final state.
`078` — Settings reads shall be side-effect free.
`079` — Reading a missing setting shall not persist a default record merely by reading.
`080` — Reading Settings shall not create the settings file/table entry unless an explicit write occurs.
`081` — Default values may be supplied in memory without persistence on read.
`082` — Settings writes shall validate the typed setting contract.
`083` — Settings writes shall commit atomically.
`084` — Failed settings write shall preserve the last valid setting.
`085` — Settings write shall not partially persist a multi-field document when the contract requires atomicity.
`086` — Job documents shall be bounded.
`087` — Job documents shall have immutable job identity references where required.
`088` — Job document state shall remain job authority rather than domain authority.
`089` — Job restart/recovery shall validate the stored job-document version.
`090` — Invalid job document shall not be treated as successful job completion.
`091` — UI working-copy documents shall identify target/base revision where required.
`092` — UI working-copy documents shall identify chronology/staleness where required.
`093` — Working-copy restoration shall not commit authoritative state automatically.
`094` — Working-copy data shall be protected according to applicable local-security design.
`095` — JSON shall not substitute for normalized relational authority.
`096` — Core entity identity shall not be moved into opaque JSON instead of relational fields.
`097` — Core relationships shall not be moved into opaque JSON instead of relational constraints where normalized authority requires relational modeling.
`098` — Lifecycle status/evidence shall not be hidden in generic JSON blobs instead of governed records.
`099` — Audit core fields shall remain relational rather than only JSON.
`100` — Query-critical normalized facts shall remain queryable under their owning data model.
`101` — JSON shall not become a generic “details” dumping ground.
`102` — JSON shall not store whole ORM entities as ordinary persistence.
`103` — JSON shall not store whole domain aggregates as ordinary persistence.
`104` — JSON shall not store arbitrary Python object representations.
`105` — JSON shall not store database connection/session objects.
`106` — JSON shall not store unrestricted exception objects.
`107` — JSON shall not ordinarily store reusable secrets.
`108` — JSON shall not ordinarily store passwords.
`109` — JSON shall not ordinarily store authentication tokens.
`110` — JSON shall not ordinarily store cryptographic keys.
`111` — JSON shall not ordinarily store runtime session/authentication material.
`112` — JSON shall not ordinarily store unrestricted Communication bodies.
`113` — JSON shall not ordinarily store full Notes content outside its owning normalized persistence.
`114` — JSON shall not ordinarily store unrestricted provider payloads.
`115` — JSON shall not ordinarily store whole import rows/workbooks.
`116` — JSON shall not ordinarily store full HTTP requests/responses.
`117` — A sanitized bounded derivative may be stored only when an owning contract explicitly permits it.
`118` — Structured allowlists shall control any sensitive-context derivative.
`119` — Encryption alone shall not authorize prohibited JSON storage.
`120` — Hashing alone shall not authorize prohibited JSON storage.
`121` — Truncation alone shall not authorize prohibited JSON storage.
`122` — Encoding alone shall not authorize prohibited JSON storage.
`123` — JSON validation shall occur before database persistence.
`124` — Database transaction shall roll back if a required JSON document fails validation.
`125` — UI validation shall not be the sole protection.
`126` — Import validation shall not bypass the JSON contract.
`127` — Background jobs shall not bypass the JSON contract.
`128` — Migration code shall validate transformed JSON before accepting it.
`129` — Restore validation shall detect invalid persisted JSON before service where required.
`130` — Tests shall cover valid minimum document.
`131` — Tests shall cover valid maximum bounded document.
`132` — Tests shall cover malformed UTF-8.
`133` — Tests shall cover truncated JSON.
`134` — Tests shall cover duplicate keys.
`135` — Tests shall cover `NaN`.
`136` — Tests shall cover infinities.
`137` — Tests shall cover wrong top-level shape.
`138` — Tests shall cover unknown field under each supported policy.
`139` — Tests shall cover unknown version.
`140` — Tests shall cover missing required member.
`141` — Tests shall cover wrong type.
`142` — Tests shall cover excessive string length.
`143` — Tests shall cover excessive array/object size.
`144` — Tests shall cover excessive nesting depth.
`145` — Tests shall cover missing/null/empty distinctions.
`146` — Tests shall cover atomic version upgrade.
`147` — Failure injection shall prove failed upgrade preserves old valid document.
`148` — Tests shall prove Settings read does not persist defaults.
`149` — Tests shall prove Settings write is atomic.
`150` — Tests shall prove working-copy restore does not accept authoritative state.
`151` — Tests shall prove persistent Draft remains distinct from UI dirty state.
`152` — Tests shall prove job document invalidity cannot fabricate job success.
`153` — Tests shall prove prohibited secret/body/provider whole-object storage is rejected by applicable contracts.
`154` — Tests shall prove database JSON validity alone is insufficient for application acceptance.
`155` — Tests shall prove canonicalization is applied only where the contract explicitly requires it.
`156` — Contract/version metadata shall remain sufficient to choose the correct parser/validator deterministically.
`157` — Persisted JSON shall remain bounded, typed application data rather than an escape hatch around normalized SOMA authority.
`158` — Every JSON-reading/writing workflow shall preserve the owning document role, version, semantics, and authority boundary from creation through upgrade/recovery.

## `BETA-REQ-0137` — prefix `TEST-CONTRACT`

**Governing obligation:** SOMA shall maintain deterministic acceptance verification explicitly traceable to every accepted requirement, stable clause, migration, and use case, covering both permitted and prohibited identity, relationship, lifecycle, correction, recovery, referential-integrity, index, migration, schema, and append-protection behavior; every structured import/export shall use governed fixtures covering normal, round-trip, foreign-identity, duplicate, ambiguous, malformed, modified, partial-failure, and hierarchy cases, tests shall control time, locale, filesystem, ordering, concurrency, customer data, Outlook, and network dependencies, reproducible defects shall gain regression coverage where automatable, and required failures, unexpected skips, or nondeterminism shall block acceptance because code-coverage percentage alone never proves product compliance.

`001` — Every accepted requirement shall map to deterministic acceptance evidence.
`002` — Every stable normative clause shall map to acceptance evidence.
`003` — Every supported migration shall map to migration acceptance evidence.
`004` — Every accepted business use case shall map to acceptance evidence.
`005` — One test may cover multiple requirements only when traceability records every covered authority.
`006` — One requirement may require multiple tests.
`007` — Traceability shall be many-to-many rather than one-test-per-requirement fiction.
`008` — Missing acceptance evidence for a required clause shall remain visible.
`009` — A passing unrelated test shall not satisfy a missing clause mapping.
`010` — Test names alone shall not be the sole traceability mechanism where stable metadata/matrix is required.
`011` — Tests shall cover valid identifier syntax.
`012` — Tests shall cover invalid identifier syntax.
`013` — Tests shall cover immutable internal identity.
`014` — Tests shall prove business identifier correction does not replace internal identity.
`015` — Tests shall cover external/local namespace distinctions.
`016` — Tests shall cover duplicate constrained business identities.
`017` — Tests shall cover exact canonicalization rules for identifiers.
`018` — Tests shall cover malformed source branch artifacts where applicable.
`019` — Tests shall cover relationship cardinalities.
`020` — Tests shall cover required relationships.
`021` — Tests shall cover optional relationships.
`022` — Tests shall cover one-to-many relationships.
`023` — Tests shall cover many-to-many relationships where approved.
`024` — Tests shall cover prohibited duplicate relationships.
`025` — Tests shall cover self-cycle rejection.
`026` — Tests shall cover indirect-cycle rejection.
`027` — Tests shall cover one-parent constraints.
`028` — Tests shall cover two-level hierarchy limits where applicable.
`029` — Tests shall cover derived relationships/context.
`030` — Tests shall prove derived context is not independently editable competing authority.
`031` — Tests shall cover cross-Site/customer consistency rules.
`032` — Tests shall cover unresolved relationship evidence without fabricated ownership.
`033` — Tests shall cover protected immutability.
`034` — Tests shall prove immutable history rows cannot be updated through ordinary paths.
`035` — Tests shall prove immutable history rows cannot be deleted through ordinary paths.
`036` — Tests shall prove correction appends rather than overwrites.
`037` — Tests shall cover archival/history-preservation rules.
`038` — Tests shall cover eligible hard deletion.
`039` — Tests shall cover hard-deletion rejection when protected history exists.
`040` — Tests shall cover every permitted lifecycle transition.
`041` — Tests shall cover every prohibited lifecycle transition.
`042` — Tests shall cover cancellation paths.
`043` — Tests shall cover correction paths.
`044` — Tests shall cover reversal/restoration paths where approved.
`045` — Tests shall cover retry as a new Task/action where required.
`046` — Tests shall cover terminal-state behavior.
`047` — Tests shall cover pending-review behavior.
`048` — Tests shall cover failure preserving actual state.
`049` — Tests shall cover safe retry after failure.
`050` — Tests shall cover stale-proposal rejection/revalidation.
`051` — Tests shall cover crash recovery where persistence/jobs require it.
`052` — Tests shall cover cancellation at transaction-safe boundaries.
`053` — Tests shall cover idempotent replay.
`054` — Tests shall cover duplicate-command handling separately from duplicate-audit identity.
`055` — Tests shall cover referential integrity with foreign keys enabled.
`056` — Tests shall prove invalid child references fail.
`057` — Tests shall prove protected parent delete/update actions fail or follow approved cascade semantics.
`058` — Tests shall verify every required child-side FK index.
`059` — Tests shall verify usable leading-prefix ordering for composite FK indexes.
`060` — Tests shall reject ineffective non-leading composite indexes as satisfying the requirement.
`061` — Tests shall verify schema constraints exactly after migration.
`062` — Tests shall verify exact expected tables/columns/indexes/triggers where those are part of accepted schema.
`063` — Tests shall verify append-only audit protections.
`064` — Tests shall verify audit mutation attempts fail.
`065` — Tests shall verify audit duplicate identity fails explicitly.
`066` — Tests shall verify audit correction appends.
`067` — Tests shall verify audit payload schemas reject unknown/prohibited data.
`068` — Tests shall cover migration from a clean/uninitialized state.
`069` — Tests shall cover migration from every supported prior origin version.
`070` — Tests shall cover unsupported origin rejection.
`071` — Tests shall cover migration concurrency.
`072` — Tests shall cover migration interruption before commit.
`073` — Tests shall cover migration ledger failure.
`074` — Tests shall cover migration constraint failure.
`075` — Tests shall cover safe retry after migration failure.
`076` — Tests shall cover accepted migration drift detection.
`077` — Tests shall cover missing migration detection.
`078` — Tests shall cover unknown migration detection.
`079` — Tests shall cover misordered migration detection.
`080` — Tests shall cover ledger mismatch detection.
`081` — Tests shall cover unsupported future migration state.
`082` — Tests shall prove migration status has no side effects.
`083` — Tests shall compare filesystem snapshots before/after observational status.
`084` — Every structured import/export family shall have governed fixtures.
`085` — Fixture data shall be synthetic or irreversibly sanitized.
`086` — Infrastructure Device workbook template shall have an acceptance fixture.
`087` — Infrastructure discovery export shall have an acceptance fixture.
`088` — Infrastructure same-installation round trip shall be tested.
`089` — Infrastructure foreign-installation identity handling shall be tested.
`090` — Infrastructure duplicate identity handling shall be tested.
`091` — Infrastructure ambiguous descriptive-match handling shall be tested.
`092` — Infrastructure malformed workbook handling shall be tested.
`093` — Infrastructure modified/unsupported-version workbook handling shall be tested.
`094` — Infrastructure partial-failure behavior shall be tested.
`095` — Infrastructure hierarchy preservation shall be tested.
`096` — RFC import normal workbook shall be tested.
`097` — WFM import normal workbook shall be tested.
`098` — RFC/WFM exact replay shall be tested.
`099` — RFC/WFM newer-identical observation shall be tested.
`100` — RFC/WFM equal-chronology different-content conflict shall be tested.
`101` — RFC/WFM older-content recovery gate shall be tested.
`102` — RFC/WFM omission-without-lifecycle-effect shall be tested.
`103` — RFC/WFM adoption of manually registered exact identity shall be tested.
`104` — RFC/WFM similar-label no-adoption shall be tested.
`105` — RFC/WFM status vocabulary shall be tested.
`106` — RFC/WFM hierarchy non-inference shall be tested.
`107` — SR-link candidate extraction shall be tested.
`108` — Strong labelled SR/TT candidate evidence shall be tested.
`109` — Lower-confidence isolated eight-digit evidence shall be tested.
`110` — Date exclusion shall be tested.
`111` — Longer-identifier substring exclusion shall be tested.
`112` — Subordinate-origin SR candidate master targeting shall be tested.
`113` — Export generation shall be tested separately from lifecycle submission/progress.
`114` — `.msg` generation shall be tested separately from sent Communication observation.
`115` — Communication scanner shall be tested with no trackable entities and prove no source read.
`116` — Communication targeted backfill shall be tested independently from ordinary scan.
`117` — Communication Deep Scan confirmation shall be tested.
`118` — Communication canonical identity and collision handling shall be tested.
`119` — Communication orphan-grace behavior shall be tested.
`120` — Communication purge revalidation shall be tested.
`121` — Communication terminal frozen summaries shall be tested.
`122` — Time-dependent tests shall control the clock.
`123` — UTC/local display tests shall control time zone.
`124` — Locale-sensitive tests shall control locale.
`125` — Filename/path tests shall control filesystem conditions.
`126` — File mtime tests shall set deterministic timestamps.
`127` — File discovery ordering tests shall not rely on filesystem enumeration order.
`128` — Concurrency tests shall use deterministic synchronization rather than arbitrary sleeps where practicable.
`129` — Random identities/tokens in tests shall be injectable/deterministically inspectable without weakening production unpredictability.
`130` — Customer data shall not be required for acceptance tests.
`131` — Acceptance fixtures shall use synthetic customer identities/data.
`132` — Outlook/PST/OST dependencies shall be controlled or represented through governed test adapters/fixtures.
`133` — Network dependencies shall be controlled.
`134` — CI shall not require external internet service for core offline acceptance.
`135` — Local HTTP runtime tests shall control ports/process identity.
`136` — Proxy-poisoning tests shall control proxy environment.
`137` — Browser anti-forgery tests shall use controlled origins.
`138` — Diagnostic canary tests shall use synthetic secret values.
`139` — Audit canary tests shall use synthetic prohibited payload values.
`140` — A reproducible defect shall receive a regression test when automatable.
`141` — Regression tests shall preserve the minimal conditions that reproduced the defect.
`142` — Regression tests shall map back to the affected requirement/clause.
`143` — A fixed defect shall not remove coverage of the original failure mode.
`144` — Nondeterministic/flaky required tests shall be treated as acceptance defects rather than ignored indefinitely.
`145` — Required test failure shall block acceptance.
`146` — Unexpected skip of a required test shall block acceptance.
`147` — Missing required test dependency shall not convert the test to pass.
`148` — Allowed-failure/advisory configuration shall not be used for a required acceptance leg.
`149` — Test timeout shall not count as pass.
`150` — Infrastructure failure shall not count as product pass without rerun/current evidence.
`151` — Line coverage percentage alone shall not prove requirements acceptance.
`152` — Branch coverage percentage alone shall not prove lifecycle correctness.
`153` — High coverage shall not excuse missing negative tests.
`154` — Low-level unit coverage shall not excuse missing integration/transaction tests.
`155` — Snapshot tests alone shall not prove semantic behavior.
`156` — End-to-end tests alone shall not replace targeted invariant tests.
`157` — Positive-path tests alone shall not prove prohibited behavior is blocked.
`158` — Negative-path tests alone shall not prove valid workflows succeed.
`159` — Tests shall prove both permitted and prohibited behavior for material invariants.
`160` — Tests shall verify manual evidence-independent paths where automation/proposals exist.
`161` — Tests shall verify proposal review does not mutate before acceptance.
`162` — Tests shall verify unsaved UI state does not affect authoritative projections.
`163` — Tests shall verify persistent Draft remains distinct from unsaved working copy.
`164` — Tests shall verify accessibility/keyboard behavior through manual/automated acceptance as appropriate.
`165` — Tests shall verify wheel/trackpad scroll ownership where automatable and manual acceptance covers platform nuance.
`166` — Tests shall verify deliberate-hold timing/cancellation/one-shot behavior.
`167` — Tests shall verify Device Reference existing-NE reconciliation does not incorrectly require creation-hold semantics.
`168` — Test result evidence shall identify exact code commit/revision where required for release.
`169` — Test result evidence shall identify environment/runtime where material.
`170` — Historical test results shall not substitute for current required revision evidence.
`171` — Acceptance traceability shall remain inspectable as requirements evolve without losing historical mappings.
`172` — SOMA acceptance shall be demonstrated by deterministic requirement/invariant evidence, not inferred from code coverage or incidental green tests.

## `BETA-REQ-0138` — prefix `CI-MATRIX`

**Governing obligation:** SOMA CI shall produce independent current-commit Windows evidence for every supported Python runtime—initially 3.13 and 3.14—allowing draft PRs only a bounded reduced validation set while every ready-for-review revision, protected-primary result, and release requires the complete governed matrix; stale, cancelled, timed-out, missing, infrastructure-failed, or advisory/allowed-failure required legs shall never count as passing, runs shall use reproducible dependencies, isolated Windows workspaces, synthetic data, and redacted outputs, current merge/release evidence shall not be cancelled away by supersession, hosted CI shall be supplemented by representative supported Windows desktop acceptance, and branch-protection bypass shall remain attributable and require follow-up validation.

`001` — CI acceptance shall run on Windows for every supported Python runtime.
`002` — Python 3.13 shall have an independent required Windows matrix leg.
`003` — Python 3.14 shall have an independent required Windows matrix leg.
`004` — Passing Python 3.13 shall not imply Python 3.14 passed.
`005` — Passing Python 3.14 shall not imply Python 3.13 passed.
`006` — Each matrix leg shall identify the exact Python runtime used.
`007` — Each matrix leg shall identify the exact code commit tested.
`008` — Each matrix leg shall identify the workflow definition/version where applicable.
`009` — Each matrix leg shall preserve enough dependency evidence for reproducibility.
`010` — Exact supported Windows edition/build coverage remains governed by the support matrix/`O-006` until finalized.
`011` — Draft pull requests may use a bounded reduced validation set.
`012` — Draft reduced validation shall include syntax/compile validation as applicable.
`013` — Draft reduced validation shall include import/smoke validation as applicable.
`014` — Draft reduced validation shall include migration-manifest/static lineage validation as applicable.
`015` — Draft reduced validation shall include affected deterministic tests as governed.
`016` — Draft reduced validation shall not be represented as full release acceptance.
`017` — Draft status shall remain visibly distinct from ready-for-review status.
`018` — Marking a PR ready for review shall require the full governed current-head matrix.
`019` — Every later non-draft revision shall require full current-head matrix evidence.
`020` — A prior revision's green matrix shall not satisfy a newer revision.
`021` — A merge shall require current evidence for the head revision selected for merge.
`022` — Protected-primary pushes shall run the complete governed matrix.
`023` — Release candidates/releases shall run the complete governed matrix.
`024` — Release evidence shall identify the exact release commit.
`025` — Release evidence shall identify the exact required matrix outcomes.
`026` — A required matrix leg that is stale shall not count as passing.
`027` — A required matrix leg that was cancelled shall not count as passing.
`028` — A required matrix leg that timed out shall not count as passing.
`029` — A required matrix leg that is missing shall not count as passing.
`030` — A required matrix leg that failed due to infrastructure shall not count as passing without valid rerun/current evidence.
`031` — A required matrix leg configured as allowed-failure shall not count as passing release evidence.
`032` — A required matrix leg configured as advisory shall not satisfy a required branch-protection gate.
`033` — A skipped required matrix leg shall not count as passing.
`034` — A neutral/no-result required matrix leg shall not count as passing.
`035` — A superseded result for an older commit shall not count as passing current head.
`036` — CI shall use governed reproducible dependency resolution.
`037` — Dependency resolution shall not silently float to arbitrary newest versions in release evidence if the reproducibility contract requires locks/pins.
`038` — Dependency manifests/locks shall be version-controlled where used.
`039` — Cache use shall not change dependency semantics silently.
`040` — Cache corruption/miss shall not convert failure into pass.
`041` — CI jobs shall use isolated Windows workspaces.
`042` — One matrix leg shall not rely on mutable leftovers from another leg.
`043` — Test databases shall be isolated per job/leg as required.
`044` — Temporary/import/export artifacts shall be isolated per job/leg as required.
`045` — CI shall use synthetic data.
`046` — CI shall not require live customer data.
`047` — CI shall not print customer data.
`048` — CI shall not print credentials/secrets.
`049` — CI shall not print runtime authentication material.
`050` — CI shall not print full Communication bodies.
`051` — CI outputs shall follow the diagnostic redaction/minimization contract.
`052` — CI crash artifacts shall follow the diagnostic redaction/minimization contract.
`053` — CI test fixtures containing secret canaries shall use synthetic fake secrets.
`054` — CI shall not upload operational databases as artifacts.
`055` — CI shall not upload PST/OST/MSG customer material as artifacts.
`056` — CI shall not upload generated operational customer artifacts.
`057` — CI may publish synthetic test reports/logs under redaction rules.
`058` — CI may cancel superseded draft/PR runs for old revisions when no longer needed.
`059` — CI may cancel superseded non-current PR runs when a newer commit exists.
`060` — CI shall not cancel away the only current merge evidence for the exact head that may be merged.
`061` — CI shall not cancel away required protected-primary evidence for the commit under validation merely because a later unrelated run exists.
`062` — CI shall not cancel away required release evidence for the release commit.
`063` — Concurrency groups shall distinguish supersedable PR work from protected merge/release evidence.
`064` — A cancelled old run shall remain historical and shall not be interpreted as a current failure or pass.
`065` — Full matrix workflow shall run the governed deterministic test suite.
`066` — Full matrix workflow shall include migration/schema tests.
`067` — Full matrix workflow shall include import/export contract tests.
`068` — Full matrix workflow shall include audit/append-only tests.
`069` — Full matrix workflow shall include relevant runtime/security tests feasible in hosted CI.
`070` — Full matrix workflow shall include static/manifest checks required for protected migration lineage.
`071` — Full matrix workflow shall include required packaging/import smoke checks as defined by release design.
`072` — Draft reduced workflow shall remain bounded to keep iteration practical.
`073` — Draft reduced workflow shall not skip obvious syntax/import failures.
`074` — Ready-for-review transition shall not rely solely on draft reduced evidence.
`075` — Branch protection shall require current required checks.
`076` — Branch protection shall require every supported Python matrix leg designated required.
`077` — Branch protection shall reject stale status for prior commit.
`078` — Branch protection shall not treat missing status as pass.
`079` — Branch protection configuration shall be versioned/documented as project governance where possible.
`080` — Emergency bypass shall be attributable.
`081` — Emergency bypass shall identify actor.
`082` — Emergency bypass shall identify affected commit/branch action.
`083` — Emergency bypass shall identify reason.
`084` — Emergency bypass shall not erase the requirement for follow-up validation.
`085` — Follow-up validation shall run the full governed matrix on the affected/current state as appropriate.
`086` — A bypassed unvalidated release shall not be represented as having ordinary gate evidence.
`087` — Hosted CI shall be supplemented by representative supported Windows desktop acceptance.
`088` — Representative desktop acceptance shall cover Python 3.13.
`089` — Representative desktop acceptance shall cover Python 3.14.
`090` — Representative desktop acceptance shall exercise the locally launched application.
`091` — Representative desktop acceptance shall exercise browser/UI behavior not fully represented in hosted runners.
`092` — Representative desktop acceptance shall exercise file-system/local-runtime behavior where environment differences matter.
`093` — Representative desktop acceptance shall remain traceable to exact build/commit.
`094` — Exact representative Windows editions/builds remain governed by `O-006` until finalized.
`095` — Hosted CI success shall not alone prove representative desktop acceptance when that acceptance is required.
`096` — Desktop acceptance success shall not replace automated matrix evidence.
`097` — CI evidence and desktop evidence shall complement each other.
`098` — CI workflow definitions shall be source-controlled.
`099` — Changes to CI required-check logic shall receive review.
`100` — CI workflow changes shall not silently drop a supported Python runtime.
`101` — CI workflow changes shall not silently downgrade required checks to advisory.
`102` — CI workflow changes shall not silently exclude critical test categories.
`103` — Supported Python additions shall add corresponding independent matrix evidence before support claim.
`104` — Supported Python removals require product/support authority rather than CI convenience.
`105` — Test-result retention shall preserve enough evidence for release audit according to project policy.
`106` — Old successful runs shall not be reused as current evidence after code changes.
`107` — Reruns shall remain associated with the same exact commit.
`108` — A rerun after infrastructure failure may provide valid evidence when it passes the exact required commit/workflow/dependency contract.
`109` — A rerun after product-test failure shall not hide the historical failure; current result may pass only after code/test condition changes or legitimate nondeterministic defect resolution with attributable evidence.
`110` — Flaky retries shall not be used to declare acceptance without addressing deterministic-test requirements.
`111` — Required test skips introduced by environment mismatch shall be treated as missing acceptance until resolved.
`112` — Matrix legs shall fail if the supported Python interpreter cannot install/import SOMA.
`113` — Matrix legs shall fail if migrations/schema tests fail.
`114` — Matrix legs shall fail if required acceptance tests fail.
`115` — Matrix legs shall fail if required manifest/drift checks fail.
`116` — Matrix legs shall fail if prohibited sensitive-output canaries are found.
`117` — Matrix legs shall fail on unexpected nondeterminism designated acceptance-blocking.
`118` — CI timeouts shall be bounded.
`119` — A timed-out job shall expose timeout rather than success.
`120` — Job cancellation shall expose cancelled state rather than success.
`121` — Infrastructure outage shall expose infrastructure failure/unknown rather than success.
`122` — CI logs shall use stable diagnostic context adequate to debug failures without leaking protected values.
`123` — Test fixtures shall remain deterministic under locale/timezone control.
`124` — CI shall explicitly set/control locale where tests depend on formatting/parsing.
`125` — CI shall explicitly set/control timezone where tests depend on display/chronology.
`126` — CI shall control filesystem paths rather than rely on developer machine directories.
`127` — CI shall not depend on operator Downloads content.
`128` — CI shall not depend on installed Outlook/live mailbox for core deterministic fixtures.
`129` — CI shall not depend on external network availability for offline core tests.
`130` — CI local HTTP tests shall use controlled loopback endpoints.
`131` — CI shall test proxy bypass/redirect rejection with synthetic controlled services where applicable.
`132` — CI shall test PID/port reuse logic where feasible and supplement with desktop acceptance where OS behavior is material.
`133` — CI artifact names shall identify commit/runtime/test family where useful.
`134` — CI summaries shall report each required matrix leg distinctly.
`135` — An aggregate green badge shall not hide one required missing leg.
`136` — Release notes/evidence shall not claim support for an untested runtime.
`137` — CI success shall remain acceptance evidence, not product authority that can change requirements.
`138` — CI configuration shall consume the accepted requirement/test contract rather than redefine it.
`139` — Protected-primary policy shall use current-head status checks.
`140` — Pull-request merge policy shall use current-head status checks.
`141` — Release policy shall use exact-release-commit status checks.
`142` — Manual rerun/approval actions shall remain attributable.
`143` — Bypass/follow-up evidence shall remain auditable.
`144` — Current required evidence shall never be inferred from a stale/cancelled/missing/allowed-failure result.
`145` — SOMA's supported Windows/Python claim shall remain conditional on both governed automated matrix evidence and representative desktop acceptance.
`146` — CI shall produce reproducible, isolated, redacted, current-commit acceptance evidence rather than merely executing some tests somewhere.

## `BETA-REQ-0139` — prefix `UI-ACCEPT`

**Governing obligation:** SOMA application acceptance shall combine deterministic automation with governed manual accessibility and interaction inspection across every release-critical workspace, workbench, dialog, proposal/import/export flow, protected action, and material UI state, proving keyboard/pointer equivalence, responsive reachability, visible and programmatic focus with correct modal restoration, reduced-motion behavior, semantic roles/names/states, non-color meaning, zoom/text enlargement, failure recovery, and hovered-pane wheel/trackpad ownership; consequential actions shall preserve their governed confirmation tiers, Device Reference promotion shall retain one cancellable monotonic three-second accessible hold followed by exactly one freshly revalidated commit without replacing required impact preview or spreading to ordinary actions, review surfaces shall remain non-authoritative until acceptance, and unresolved Critical or High interaction defects shall block release.

`001` — Application acceptance shall combine deterministic automated verification with governed manual inspection.
`002` — Automated UI acceptance alone shall not satisfy every accessibility/interaction obligation.
`003` — Manual inspection alone shall not replace deterministic automation where behavior can be automated reliably.
`004` — Acceptance criteria shall be versioned/governed with the release.
`005` — Acceptance evidence shall identify the tested release/commit.
`006` — Manual inspection results shall be recorded sufficiently for release review.
`007` — Required interaction defects shall be tracked to resolution or release-blocking disposition.
`008` — Acceptance shall exercise both ordinary and failure/recovery states.
`009` — Release-critical workspaces shall be covered.
`010` — Release-critical workbenches shall be covered.
`011` — Release-critical dialogs shall be covered.
`012` — Release-critical proposal-review surfaces shall be covered.
`013` — Release-critical import-review surfaces shall be covered.
`014` — Release-critical export/generation surfaces shall be covered.
`015` — Release-critical protected actions shall be covered.
`016` — Loading states shall be covered.
`017` — Empty states shall be covered.
`018` — Partial states shall be covered.
`019` — Warning states shall be covered.
`020` — Error states shall be covered.
`021` — Historical states shall be covered.
`022` — Stale/unavailable-evidence states shall be covered.
`023` — Full keyboard operation shall be tested for interactive controls.
`024` — Keyboard focus order shall follow a logical interaction sequence.
`025` — Keyboard navigation shall not trap focus outside governed modal containment.
`026` — `Enter` shall activate the same default open/accept action as the shared interaction contract.
`027` — `Space` shall perform membership/toggle semantics where assigned rather than open records.
`028` — `Escape` shall close/dismiss governed transient surfaces without unintended acceptance.
`029` — Arrow keys shall navigate active items according to shared component semantics.
`030` — Keyboard actions shall not require pointer hover to become discoverable.
`031` — Keyboard users shall be able to reach material actions.
`032` — Keyboard users shall be able to reach validation/error remediation.
`033` — Keyboard users shall be able to operate relationship selectors.
`034` — Keyboard users shall be able to operate import/proposal review.
`035` — Keyboard users shall be able to operate protected confirmation paths.
`036` — Keyboard users shall be able to recover from validation failure without losing safe input.
`037` — Keyboard behavior shall remain equivalent under responsive reflow.
`038` — Keyboard acceptance shall include nested pane/list interactions.
`039` — Pointer users shall be able to reach material actions.
`040` — Pointer activation shall not trigger unrelated nested-control actions.
`041` — Single click shall select where the shared list contract requires selection.
`042` — Double click shall open where the shared list contract requires opening.
`043` — Pointer actions shall preserve visible focus/selection semantics as required.
`044` — Pointer users shall be able to operate dialogs and selectors.
`045` — Pointer users shall be able to operate proposal/import review.
`046` — Pointer users shall be able to operate protected confirmation paths.
`047` — Pointer cancellation/release shall behave safely on deliberate holds.
`048` — Pointer acceptance shall include nested scroll surfaces.
`049` — Wheel/trackpad input shall scroll the eligible pane under the pointer.
`050` — Hovered Ticket lists shall own wheel/trackpad scrolling when eligible.
`051` — Hovered Communication previews shall own wheel/trackpad scrolling when eligible.
`052` — Hovered popups shall own wheel/trackpad scrolling when eligible.
`053` — Hovered tables shall own wheel/trackpad scrolling when eligible.
`054` — Hovered dialogs shall own wheel/trackpad scrolling when eligible.
`055` — Hovered panes shall own wheel/trackpad scrolling when eligible.
`056` — Reaching a hovered surface boundary shall not unexpectedly scroll an unrelated pane.
`057` — Reaching a popup boundary shall not unexpectedly scroll the underlying shell.
`058` — Wheel/trackpad scrolling shall not change selection merely because content moved.
`059` — Wheel/trackpad scrolling shall not open records.
`060` — Every material capability shall remain reachable under supported narrow viewport/container sizes.
`061` — Required information shall remain reachable under responsive reflow.
`062` — Required warnings shall remain reachable under responsive reflow.
`063` — Required evidence shall remain reachable under responsive reflow.
`064` — Required actions shall remain reachable under responsive reflow.
`065` — Overflow menus shall remain usable within the viewport.
`066` — Dialogs shall remain usable within the viewport.
`067` — Autocomplete popups shall remain usable within the viewport.
`068` — Wide tables shall retain bounded horizontal access to required columns/actions.
`069` — Split-pane workbenches shall retain access to both operational and Communication surfaces.
`070` — Every interactive control shall have visible focus.
`071` — Visible focus shall not rely only on color.
`072` — Focus indication shall remain perceptible in Light mode.
`073` — Focus indication shall remain perceptible in Dark mode.
`074` — Focus indication shall remain perceptible in high-contrast/forced-color contexts where supported.
`075` — Responsive reflow shall not cause focus to disappear without deterministic restoration.
`076` — Programmatic focus shall track the logically focused interactive element.
`077` — Focus shall move to actionable validation errors where the editor contract requires it.
`078` — Opening a dialog shall move/contain focus according to modal semantics.
`079` — Closing a dialog shall restore focus to the appropriate invoking/contextual control when still valid.
`080` — Stale invoking controls shall use deterministic fallback focus restoration.
`081` — Focus restoration shall not unexpectedly jump to an unrelated pane.
`082` — Modal dialogs shall expose semantic modal/dialog roles.
`083` — Modal dialogs shall prevent interaction with the underlying surface while modal.
`084` — Modal focus shall remain within the dialog until dismissal/acceptance as appropriate.
`085` — Nested transient controls inside a dialog shall return focus correctly when closed.
`086` — Accepting a modal action shall restore/focus the resulting context deterministically.
`087` — Cancelling a modal shall restore prior context without mutation.
`088` — Dialog validation failure shall keep focus/recovery within the actionable dialog state.
`089` — Modal restoration shall remain correct under responsive layout changes.
`090` — Reduced-motion preference shall be respected by non-essential animation.
`091` — Reduced motion shall not remove required state information.
`092` — Reduced motion shall not remove progress semantics.
`093` — Reduced motion shall not remove deliberate-hold timing requirements.
`094` — Deliberate-hold progress may use non-motion semantic progress under reduced motion.
`095` — Motion shall never be the sole cue for success/failure/state change.
`096` — Motion-heavy transitions shall not be required to understand workflow sequence.
`097` — Reduced-motion acceptance shall cover material animated/transitional controls.
`098` — Interactive components shall expose appropriate semantic roles.
`099` — Lists/tables/grids shall expose appropriate structural roles.
`100` — Combobox/listbox selectors shall expose appropriate roles.
`101` — Dialogs shall expose appropriate roles.
`102` — Buttons/links/toggles shall expose roles matching their behavior.
`103` — Interactive controls shall expose accessible names.
`104` — Icon-only actions shall expose accessible names independent of tooltips.
`105` — Inputs shall expose associated labels/names.
`106` — Relationship selectors shall expose their purpose/name.
`107` — Protected actions shall expose names describing the consequence.
`108` — Interactive components shall expose accessible states where applicable.
`109` — Disabled state shall be programmatically exposed.
`110` — Expanded/collapsed state shall be programmatically exposed where applicable.
`111` — Selected/checked state shall be programmatically exposed where applicable.
`112` — Invalid/error state shall be programmatically exposed where applicable.
`113` — Operational state shall not depend only on color.
`114` — Severity shall not depend only on color.
`115` — Selection shall not depend only on color.
`116` — Destructive action shall not depend only on color.
`117` — Provisional state shall not depend only on color.
`118` — Historical state shall not depend only on color.
`119` — Stale/unknown state shall not depend only on color.
`120` — Non-color cues shall remain understandable at supported zoom/text sizes.
`121` — Supported browser zoom shall preserve material capability.
`122` — Supported text enlargement shall preserve material capability.
`123` — Enlarged text shall not clip required labels/actions without an accessible alternative.
`124` — Enlarged text shall not render modal content unreachable.
`125` — Enlarged text shall not render autocomplete results unreachable.
`126` — Zoom shall preserve access to wide-table horizontal scrolling.
`127` — Zoom shall preserve split-pane reachability or governed reflow.
`128` — Zoom/text acceptance shall include validation/error states.
`129` — Validation failure shall preserve safe operator input.
`130` — Transaction failure shall preserve safe operator input where the editor contract requires it.
`131` — Import failure shall not mutate accepted authority before acceptance.
`132` — Proposal acceptance failure shall leave proposal/domain state truthful.
`133` — Background-job failure shall not be displayed as completed success.
`134` — Runtime failure shall expose bounded recovery/actionable diagnostics.
`135` — Recovery from stale state shall revalidate authoritative state.
`136` — Failure recovery shall remain keyboard/pointer accessible.
`137` — Consequential actions shall follow their assigned confirmation tier.
`138` — Confirmation tiers shall not be weakened by responsive layout.
`139` — Confirmation tiers shall not be weakened by keyboard shortcuts.
`140` — Confirmation tiers shall not be strengthened arbitrarily for ordinary reversible actions.
`141` — Required impact preview shall remain separate from any deliberate hold.
`142` — High-risk actions shall expose their material consequence before commit as governed.
`143` — Promotion/creation of a genuinely new Network Element from a provisional Device Reference shall use the exact three-second deliberate hold.
`144` — The three-second hold shall use monotonic elapsed time.
`145` — Wall-clock changes shall not shorten the required hold.
`146` — Hold progress shall be visibly represented.
`147` — Hold progress shall have semantic/assistive representation.
`148` — Releasing pointer/touch before three seconds shall cancel without creation.
`149` — Cancelling keyboard/assistive activation before completion shall cancel without creation.
`150` — Scrolling shall not accidentally satisfy the hold.
`151` — Completion shall issue exactly one creation command.
`152` — The creation command shall freshly revalidate eligibility/authoritative state.
`153` — Stale/ineligible Device Reference state at completion shall prevent creation.
`154` — Keyboard/assistive users shall have an equivalently deliberate path.
`155` — The hold shall not replace a required impact preview.
`156` — The hold shall be used only for its approved allowlisted deliberate actions.
`157` — Reconciliation/reassignment of a Device Reference to an already-existing Network Element shall remain a correction path and shall not inherit new-entity creation-hold semantics.
`158` — Proposal-review surfaces shall not mutate authoritative state before explicit acceptance.
`159` — Import review/staging shall not mutate authoritative state before explicit acceptance.
`160` — Unresolved Critical or High interaction/accessibility defects in release-critical scope shall block release acceptance.

## `BETA-REQ-0140` — prefix `LOCAL-RUN`

**Governing obligation:** SOMA's local service shall expose authoritative operation only on supported loopback origins after acquiring exclusive ownership of the canonical data instance and completing configuration, migration, and integrity validation; every run shall use fresh unpredictable run/authentication identity represented through an atomic minimal registry containing exact origin, PID plus independent process-birth identity, run/protocol/data identities, and secure readiness evidence, while the launcher shall trust or control an instance only after exact-origin, process/birth, ownership, and authenticated non-redirecting health verification that bypasses proxies and uses bounded timeouts; the server shall validate Host/origin and browser anti-forgery context, shutdown shall be authenticated and graceful before any freshly revalidated forced termination, and stale/forged registry data, port occupancy, PID reuse, or port reuse shall never independently establish identity or allow repeated launch/shutdown to affect an unrelated process.

`001` — SOMA Beta's local HTTP service shall bind only to supported loopback addresses.
`002` — The service shall not bind by default to all network interfaces.
`003` — The service shall not expose its operational interface to LAN interfaces merely for convenience.
`004` — The service shall not expose its operational interface to public interfaces.
`005` — Supported loopback forms shall be explicitly governed by runtime design.
`006` — Loopback binding shall remain consistent with SOMA's local-only product boundary.
`007` — A successful non-loopback bind shall not qualify as valid Beta 1.0 readiness.
`008` — Every authoritative SOMA runtime shall operate against one canonical data-instance identity.
`009` — Equivalent path spellings shall resolve to one canonical instance identity where they refer to the same underlying supported data target.
`010` — Runtime ownership shall be associated with canonical data-instance identity rather than merely user-entered path text.
`011` — The exact canonicalization mechanics shall be defined by LLD for supported Windows filesystems.
`012` — Canonicalization shall not fabricate identity for an inaccessible or ambiguous target.
`013` — SOMA shall acquire exclusive ownership of the canonical data instance before running migrations.
`014` — Migration shall not begin merely because the database path exists.
`015` — Migration shall not begin while another authoritative SOMA instance owns the same canonical data instance.
`016` — Concurrent launch against one data instance shall not produce two authoritative migrators.
`017` — SOMA shall retain appropriate exclusive canonical data-instance ownership before exposing ordinary authoritative service.
`018` — A second SOMA process shall not expose authoritative service against the same data instance simultaneously.
`019` — Port uniqueness alone shall not substitute for data-instance ownership.
`020` — Different ports shall not authorize competing writers against one authoritative data instance.
`021` — Required runtime configuration shall complete before readiness.
`022` — Invalid required configuration shall block readiness.
`023` — Configuration failure shall not launch the browser into an apparently healthy operational UI.
`024` — Required migrations shall complete before readiness.
`025` — Migration validation shall complete before readiness.
`026` — Migration pending/failure shall prevent ordinary service readiness.
`027` — The launcher shall not treat a listening socket alone as proof migration completed.
`028` — Required schema validation shall complete before readiness.
`029` — Required foreign-key/integrity validation shall complete before readiness.
`030` — Applicable audit-protection validation shall complete before readiness.
`031` — Integrity failure shall block readiness.
`032` — Automatic browser launch shall occur only after authenticated readiness is established.
`033` — Browser launch shall not race ahead merely because a TCP listener appeared.
`034` — Browser launch shall use the verified canonical origin.
`035` — Browser launch shall not substitute an unverified alternate host or port.
`036` — Every SOMA run shall receive an unpredictable run identity.
`037` — Run identity shall not be deterministically derived solely from PID.
`038` — Run identity shall not be deterministically derived solely from port.
`039` — Run identity shall not be reused merely because the same process path restarts.
`040` — A later run shall remain distinguishable from an earlier run using the same data instance.
`041` — Every run shall establish unpredictable authentication material for privileged launcher/runtime coordination.
`042` — Runtime authentication material shall not be a fixed application-wide secret.
`043` — Runtime authentication material shall not be inferable solely from PID or port.
`044` — Stale authentication from a previous run shall not authenticate a later run.
`045` — Authentication material shall be handled under the general secret-protection contract.
`046` — Runtime registry shall identify the expected protocol/runtime contract.
`047` — Protocol identity/version shall allow launcher and running service to detect incompatible coordination contracts.
`048` — Protocol mismatch shall not be interpreted as successful readiness.
`049` — Exact protocol versioning mechanics remain LLD-owned.
`050` — Runtime identity shall include the canonical data-instance identity.
`051` — A valid SOMA server using a different data instance shall not be mistaken for the intended instance.
`052` — Matching executable identity alone shall not prove intended data ownership.
`053` — SOMA shall maintain a minimal runtime registry for launcher coordination.
`054` — Runtime registry writes shall be atomic.
`055` — Readers shall not observe a partially written registry as valid runtime identity.
`056` — Registry shall contain only the minimum facts required for trusted coordination.
`057` — Registry shall not become authoritative domain storage.
`058` — Registry shall not store operational customer data.
`059` — Registry shall record the canonical service origin.
`060` — Canonical origin shall resolve to the approved loopback service endpoint.
`061` — Launcher shall compare the exact expected origin rather than accept any responding localhost URL.
`062` — Registry shall record process identifier.
`063` — PID shall be treated as one identity signal only.
`064` — PID alone shall never prove runtime identity.
`065` — Registry shall record a process-birth identity independent of PID.
`066` — Launcher validation shall compare both PID and process-birth identity where applicable.
`067` — A reused PID belonging to a later process shall fail birth-identity validation.
`068` — Exact Windows process-birth representation remains an LLD choice.
`069` — Registry shall record run identity.
`070` — Run identity shall match the responding SOMA service.
`071` — Registry run identity from a prior process shall not authenticate a later instance.
`072` — Registry shall record applicable coordination protocol identity/version.
`073` — Launcher shall reject an incompatible protocol identity rather than guessing compatibility.
`074` — Registry shall record canonical data-instance identity.
`075` — Launcher shall verify that the running instance owns the intended canonical data instance.
`076` — A valid SOMA process operating another data instance shall not satisfy this verification.
`077` — Registry shall contain or reference the minimal secure material needed to authenticate readiness.
`078` — Readiness material shall remain per-run or otherwise non-reusable across unrelated runs.
`079` — Readiness material shall be protected from ordinary disclosure.
`080` — Runtime registry shall not be trusted merely because its syntax is valid.
`081` — Launcher shall treat registry content as an untrusted claim until independently verified.
`082` — Presence of a registry file shall not prove that SOMA is running.
`083` — Presence of a PID shall not prove that the recorded process is the original SOMA process.
`084` — Presence of a listening port shall not prove that the intended SOMA instance is running.
`085` — Launcher shall verify the exact canonical origin.
`086` — A response from an unexpected port shall not prove identity.
`087` — A response from an unexpected hostname shall not prove identity.
`088` — Redirecting from the expected origin to another origin shall not prove identity.
`089` — Launcher shall verify that the registry PID corresponds to an existing process.
`090` — Launcher shall verify independent process-birth identity.
`091` — PID existence with mismatched birth identity shall be treated as stale/reused identity.
`092` — Failure to inspect process identity safely shall not be upgraded to trusted status.
`093` — Launcher/runtime verification shall establish that the responding process holds the expected data-instance ownership.
`094` — An authenticated service not owning the intended data instance shall not be accepted as the intended instance.
`095` — Ownership proof shall remain bound to canonical data identity.
`096` — Launcher shall use an authenticated health/readiness path.
`097` — An unauthenticated generic HTTP `200 OK` shall not by itself establish trusted SOMA readiness.
`098` — Health response shall establish applicable run/protocol/data identity.
`099` — Authenticated health validation shall occur before launcher trust.
`100` — Launcher health checks shall reject HTTP redirects.
`101` — Launcher shutdown requests shall reject redirects.
`102` — A redirect to another port shall not be followed as proof of identity.
`103` — A redirect to another host shall not be followed as proof of identity.
`104` — A redirect to a non-loopback origin shall fail immediately.
`105` — Health verification shall bypass configured HTTP proxies.
`106` — Shutdown coordination shall bypass configured HTTP proxies.
`107` — System/user proxy configuration shall not redirect launcher control traffic away from the verified loopback service.
`108` — A proxy response shall not be accepted as local SOMA identity.
`109` — Health checks shall use bounded connection/read timeouts.
`110` — Shutdown coordination shall use bounded timeouts.
`111` — Launcher shall not hang indefinitely waiting for an unresponsive stale endpoint.
`112` — Timeout shall remain distinguishable from successful identity verification.
`113` — The SOMA server shall validate the request `Host`/effective origin against the allowed local origin policy.
`114` — An arbitrary Host header shall not be accepted merely because the socket arrived through loopback.
`115` — Browser requests shall remain bound to the intended local SOMA origin.
`116` — Host/origin validation shall prevent attacker-controlled origin substitution from gaining trusted local-service behavior.
`117` — State-changing browser requests shall use an accepted anti-forgery context.
`118` — A malicious external webpage shall not be able to perform SOMA state-changing browser operations merely because SOMA listens on loopback.
`119` — Anti-forgery validation shall remain complementary to Local User authentication.
`120` — Exact browser anti-forgery mechanism remains security/LLD-owned.
`121` — Runtime shutdown shall require authentication.
`122` — Knowing the loopback port shall not be sufficient to shut SOMA down.
`123` — Shutdown authentication shall be bound to the intended run.
`124` — Stale prior-run shutdown credentials shall not control a later run.
`125` — Shutdown shall be treated as a state-changing control operation.
`126` — Shutdown shall not be exposed through a semantics-free unauthenticated read operation.
`127` — Browser anti-forgery protections shall apply where shutdown is browser-accessible.
`128` — Authenticated shutdown should request graceful application termination first.
`129` — Graceful shutdown shall allow applicable in-flight transaction boundaries to resolve safely.
`130` — Graceful shutdown shall allow governed background-job cancellation/stop handling.
`131` — Shutdown shall preserve committed authoritative state.
`132` — Shutdown shall not claim rollback of already committed transactions.
`133` — Forced process termination may occur only after the graceful path fails or becomes unavailable under governed launcher behavior.
`134` — Immediately before forced termination, launcher shall revalidate PID.
`135` — Immediately before forced termination, launcher shall revalidate process-birth identity.
`136` — Where applicable, launcher shall revalidate expected run/data ownership before forced termination.
`137` — A PID that has been reused shall never be killed based on stale registry data.
`138` — A registry referencing a non-existent process shall be treated as stale.
`139` — A registry whose PID exists but birth identity differs shall be treated as stale.
`140` — A registry whose run identity disagrees with the authenticated service shall be treated as stale/forged.
`141` — A registry whose data identity disagrees with the service shall not prove intended ownership.
`142` — Stale registry cleanup shall not terminate unrelated processes.
`143` — A syntactically valid forged registry shall not be sufficient to gain launcher trust.
`144` — Registry values shall be corroborated through process, ownership, origin, and authenticated health evidence.
`145` — A forged PID/port pair shall not cause launcher control of an unrelated local process.
`146` — An occupied desired port shall not prove SOMA is already running.
`147` — A responding unrelated local HTTP service shall not be mistaken for SOMA.
`148` — Port conflict shall produce a truthful unavailable/conflict state unless another verified SOMA run is proven.
`149` — Port collision handling shall not weaken exact-origin and authentication requirements.
`150` — PID reuse shall be treated as an expected operating-system possibility.
`151` — PID alone shall never authorize shutdown.
`152` — PID alone shall never prove continued ownership.
`153` — Birth identity mismatch shall invalidate stale process claims.
`154` — Port reuse shall be treated as an expected runtime possibility.
`155` — A later service binding the same port shall not inherit prior SOMA trust.
`156` — Run/authentication identity shall prevent prior registry information from authenticating the later service.
`157` — Repeated launch requests against an already verified intended instance shall not create duplicate competing authoritative instances.
`158` — Repeated launch shall safely reuse/navigate to the verified intended instance where the launcher contract permits.
`159` — Repeated launch against stale registry state shall recover without terminating unrelated processes.
`160` — Repeated launch shall not duplicate migration execution.
`161` — Repeating shutdown for an already-stopped verified run shall not affect another process.
`162` — Repeating shutdown after a port is reused shall not affect the new service solely because it occupies the old port.
`163` — Repeating shutdown after PID reuse shall not terminate the new process.
`164` — A stale shutdown request shall fail safely.
`165` — Runtime registry creation/update shall correspond to the current run.
`166` — Runtime registry removal/staleness handling shall not itself constitute proof that the server stopped cleanly.
`167` — Registry lifecycle shall remain infrastructure coordination state rather than domain/audit authority.
`168` — Successful launcher/runtime coordination shall be reproducibly verifiable from exact origin, process birth, ownership, run/protocol/data identity, and authenticated health rather than any single reusable signal.

## `BETA-REQ-0141` — prefix `DIAG-EXT`

**Governing obligation:** SOMA shall emit structured, versioned technical diagnostics outside authoritative SQLite, with each record carrying UTC emission time, severity, stable component/event identity, run identity, concise summary, and only minimal allowlisted context plus optional bounded correlation, monotonic duration, and sanitized exception evidence; diagnostic storage shall use owned paths, appropriate permissions, concurrent-complete writes, bounded buffering, and governed rotation with best-effort critical flushing and recursion-safe failure behavior, while diagnostic emission may fail open only for otherwise valid work and can never convert migration, audit, authorization, integrity, or domain-transaction failure into success, and diagnostics shall never upload automatically, with any future support export explicitly initiated, previewed, redacted, and non-authoritative by default.

`001` — Structured technical diagnostics shall be stored outside the authoritative SQLite database.
`002` — Technical diagnostics shall not require insertion into SQLite for ordinary emission.
`003` — Diagnostic storage shall remain operationally separate from authoritative domain persistence.
`004` — Loss of diagnostic storage shall not erase authoritative SQLite domain truth.
`005` — SQLite backup/restore shall not depend on external diagnostics to reconstruct authoritative state.
`006` — Technical diagnostics shall never serve as authoritative domain state.
`007` — A diagnostic record shall not create a Service Request lifecycle fact.
`008` — A diagnostic record shall not create an Objective/Task lifecycle fact.
`009` — A diagnostic record shall not create Inventory lifecycle truth.
`010` — A diagnostic record shall not create Infrastructure relationship truth.
`011` — A diagnostic message shall not substitute for a committed domain event.
`012` — Technical diagnostics shall remain distinct from accepted lifecycle evidence.
`013` — Diagnostic chronology shall not substitute for independently supported operational chronology.
`014` — A lifecycle event shall not be reconstructed solely from a diagnostic line when authoritative evidence is absent.
`015` — Deleting diagnostics under retention shall not remove lifecycle history.
`016` — Technical diagnostics shall remain distinct from application audit.
`017` — A diagnostic record shall not satisfy required mutation-audit atomicity.
`018` — Audit failure shall not be concealed by writing a diagnostic event instead.
`019` — Diagnostic retention/rotation shall not alter audit retention.
`020` — Technical diagnostics shall remain distinct from proposal history.
`021` — A parser diagnostic shall not create a Communication proposal.
`022` — A proposal shall not be considered accepted because a diagnostic says it was processed.
`023` — Proposal review state shall remain in its authoritative store.
`024` — Technical diagnostic records shall use a structured format.
`025` — Diagnostic record structure shall be versioned.
`026` — A diagnostic-format version shall identify its expected field contract.
`027` — Diagnostic consumers shall not silently interpret unknown versions as current.
`028` — Diagnostic format evolution shall preserve bounded historical readability where required.
`029` — Every diagnostic record shall contain UTC emission time.
`030` — Emission time shall represent when the diagnostic record was emitted.
`031` — Diagnostic emission time shall not substitute for domain occurrence time.
`032` — Diagnostic emission time shall use the accepted canonical temporal representation.
`033` — Every diagnostic record shall contain a governed severity.
`034` — Severity vocabulary shall be stable/versioned enough for filtering and support interpretation.
`035` — Diagnostic severity shall not redefine domain severity such as SR Severity.
`036` — A technical Critical diagnostic shall not itself mean a business entity entered a terminal state.
`037` — Every diagnostic record shall identify a stable emitting component.
`038` — Component identity shall not rely solely on free-text source names.
`039` — Renaming a UI label shall not alter historical diagnostic component semantics.
`040` — Every diagnostic record shall contain a stable event code.
`041` — Event code shall identify the technical condition class independently from free-text wording.
`042` — Free-text summary wording may evolve without destroying event-code identity.
`043` — Event codes shall not be reused for materially different technical meanings.
`044` — Every diagnostic record shall identify the current SOMA run.
`045` — Run ID shall use the runtime identity governed by `0140`.
`046` — Diagnostics from separate runs shall remain distinguishable even if PID or port repeats.
`047` — Run identity shall support bounded correlation without becoming an authentication secret.
`048` — Every diagnostic record shall contain a concise technical summary.
`049` — Summary shall be suitable for operator/support understanding.
`050` — Summary shall not contain prohibited body-like or secret material.
`051` — Structured fields shall carry machine-relevant context rather than force parsing of the summary.
`052` — Diagnostic context shall use an allowlisted field set.
`053` — Context shall be minimal for the technical condition.
`054` — Diagnostic code shall not dump arbitrary function arguments.
`055` — Diagnostic code shall not serialize whole domain entities.
`056` — Diagnostic code shall not serialize whole database rows as an ordinary logging pattern.
`057` — Unknown/unapproved diagnostic context fields shall not be accepted merely because they are convenient.
`058` — Diagnostics may contain approved correlation identifiers.
`059` — Correlation may link related technical records within one workflow/run.
`060` — Correlation may link a technical diagnostic to an application command/job identity where allowed.
`061` — Correlation shall not transfer authority between diagnostics and domain/audit records.
`062` — Correlation identifiers should be purpose-created opaque identities rather than sensitive business values.
`063` — Diagnostics may contain monotonic duration where elapsed-time measurement is relevant.
`064` — Monotonic duration shall represent elapsed technical duration rather than wall-clock chronology.
`065` — Wall-clock adjustments shall not corrupt duration measurement.
`066` — Duration shall not substitute for independently known start/end domain timestamps.
`067` — Diagnostics may include a sanitized exception description.
`068` — Diagnostics may include a sanitized traceback where governed.
`069` — Raw exception objects shall not be serialized blindly.
`070` — Traceback inclusion shall pass through the security/sanitization contract.
`071` — Sanitization failure shall prefer omission over raw fallback.
`072` — SOMA shall use an application-owned diagnostic storage location.
`073` — The location shall remain separate from source-controlled project material.
`074` — Diagnostics shall not be written into the repository working tree as operational output.
`075` — Exact supported Windows path mechanics remain an LLD decision.
`076` — Diagnostic files/directories shall use appropriate local permissions.
`077` — Runtime shall not deliberately make diagnostic files broadly accessible beyond the local operating context.
`078` — Permission failure shall not silently redirect diagnostics to an unsafe public location.
`079` — Failure to establish the preferred diagnostic path shall follow governed fail-open/fallback behavior without exposing secrets.
`080` — Concurrent diagnostic emission shall preserve complete records.
`081` — Concurrent writers shall not interleave records into structurally corrupt fragments.
`082` — Partial writes shall be detectable or safely bounded.
`083` — Multi-thread/job diagnostic activity shall not require serialized domain execution.
`084` — Exact writer/rotation coordination mechanics remain LLD-owned.
`085` — Asynchronous diagnostic buffering may use a bounded queue.
`086` — Diagnostic queues shall not grow without bound.
`087` — Diagnostic pressure shall not exhaust memory indefinitely.
`088` — Queue overflow behavior shall be explicit.
`089` — Queue overflow shall not turn an otherwise valid domain mutation into failure solely because ordinary diagnostics could not be emitted.
`090` — Dropped diagnostic records, if allowed under pressure, shall not be falsely represented as authoritative history.
`091` — Diagnostic storage shall have governed rotation.
`092` — Rotation may be bounded by size.
`093` — Rotation may be bounded by age.
`094` — Rotation may be bounded by volume/count.
`095` — Rotation shall prevent unbounded local storage growth.
`096` — Exact retention/rotation values remain LLD/configuration decisions unless separately approved.
`097` — Rotation shall not delete authoritative domain/audit records because those live elsewhere.
`098` — Rotation shall not corrupt concurrently emitted complete diagnostic records.
`099` — Rotation shall not produce partially overwritten files that masquerade as valid structured records.
`100` — Rotation state shall recover safely after restart.
`101` — At critical failure boundaries, buffered diagnostics should flush where practical.
`102` — Migration startup failure may trigger a best-effort diagnostic flush.
`103` — Fatal runtime failure may trigger a best-effort diagnostic flush.
`104` — Integrity/readiness failure may trigger a best-effort diagnostic flush.
`105` — Flush shall not override a more important safe shutdown/transaction boundary.
`106` — Diagnostic-emission failure shall not recursively produce unbounded diagnostic attempts.
`107` — A failure while flushing diagnostics shall not recurse indefinitely.
`108` — Logging subsystem failure shall use bounded fallback behavior.
`109` — Diagnostic recursion prevention shall not fabricate a successful domain result.
`110` — Failure to emit ordinary technical diagnostics shall not automatically fail an otherwise valid domain operation.
`111` — Failure to rotate a diagnostic file shall not automatically invalidate an otherwise valid already-governed operation.
`112` — Diagnostic queue pressure shall not automatically roll back valid business state.
`113` — Diagnostic fail-open semantics shall never cause a failed migration to be treated as successful.
`114` — Diagnostic fail-open semantics shall never cause required audit failure to be treated as successful mutation.
`115` — Diagnostic fail-open semantics shall never cause authorization failure to become success.
`116` — Diagnostic fail-open semantics shall never cause integrity-check failure to become readiness.
`117` — Diagnostic fail-open semantics shall never cause a failed domain transaction to be reported as committed.
`118` — Diagnostics observe results; they do not determine correctness of the underlying transaction.
`119` — SOMA Beta shall never automatically upload diagnostics.
`120` — Diagnostic upload shall not occur silently in the background.
`121` — Diagnostic upload shall not occur merely because an exception happened.
`122` — Offline/local operation shall remain functional without an external diagnostic service.
`123` — Beta 1.0 shall not require cloud telemetry for diagnostics.
`124` — A future support-diagnostics export shall be explicitly initiated.
`125` — Support export shall not occur automatically.
`126` — Support export shall show the operator what categories/content will be included.
`127` — Support export shall be previewable before creation/release.
`128` — Support export shall apply current redaction rules.
`129` — Support export shall exclude authoritative domain state by default.
`130` — Support export shall exclude application audit by default unless a separately governed support requirement explicitly includes minimized audit evidence.
`131` — Support export shall not silently become a full database export.
`132` — Support export shall remain an operator-managed generated artifact.
`133` — Exporting diagnostics shall not change domain lifecycle state.
`134` — Exporting diagnostics shall not constitute submission to an external support provider.
`135` — Saving a support artifact locally shall not upload it.
`136` — External transmission, if ever supported, shall require separately accepted product authority.
`137` — Combined History surfaces may reference relevant diagnostics only if the diagnostic nature is clearly labeled.
`138` — Diagnostic entries shall not appear indistinguishably as accepted lifecycle events.
`139` — Rotation/removal of technical diagnostics shall not create gaps in authoritative lifecycle/audit evidence.
`140` — Diagnostic initialization shall occur early enough to report applicable startup failures where practical.
`141` — Diagnostic initialization failure shall not bypass migration/readiness/integrity rules.
`142` — A successful diagnostic subsystem shall not prove application readiness.
`143` — Run identity from `0140` shall correlate diagnostics to the correct runtime instance.
`144` — Stale diagnostic files from prior runs shall remain distinguishable from current-run records.
`145` — Technical diagnostics shall remain disposable operational evidence whose absence or rotation cannot alter authoritative SOMA truth.

## `BETA-REQ-0142` — prefix `DIAG-SAFE`

**Governing obligation:** SOMA shall prevent credentials, secrets, authentication/session material, protected values, full body-like content, and other designated sensitive data from entering any diagnostic, console, CI, crash, startup-fallback, or support-output path by minimizing data at the call site and emitting only structured allowlisted facts that undergo semantic sensitivity classification, URL/header and exception sanitization, and bounded recursive inspection before any queue or sink; pattern redaction shall remain defense in depth rather than permission to log sensitive data, encoding, encryption, hashing, truncation, or partial display shall not automatically establish safety, correlations shall use purpose-created opaque identifiers, sanitization failure shall omit unsafe fields or records without raw fallback, support export shall reapply current inspection, and canary tests shall prove prohibited complete or reconstructable fragments are absent while approved diagnostic context remains useful.

`001` — Reusable credentials shall never enter technical diagnostics.
`002` — Passwords shall never enter technical diagnostics.
`003` — Cryptographic private keys shall never enter technical diagnostics.
`004` — Reusable authentication tokens shall never enter technical diagnostics.
`005` — Session authentication material shall never enter technical diagnostics.
`006` — Runtime launcher authentication material shall never enter technical diagnostics.
`007` — Device credentials shall never enter technical diagnostics.
`008` — External provider credentials shall never enter technical diagnostics.
`009` — Values designated sensitive by an owning contract shall not enter technical diagnostics unless an explicitly approved minimized representation exists.
`010` — Sensitive-field status shall derive from semantic classification rather than arbitrary developer judgment at each call site.
`011` — A value shall not become safe merely because its field name was changed.
`012` — Full Communication bodies shall never enter technical diagnostics.
`013` — Full email bodies shall never enter console output.
`014` — Full Communication bodies shall never enter CI logs.
`015` — Full Communication bodies shall never enter crash reports.
`016` — Full Communication bodies shall never enter support bundles by default.
`017` — Full Notes-like content shall be excluded from diagnostics unless a separately accepted narrow contract explicitly permits a non-reconstructable derivative.
`018` — Provider payload bodies shall not be dumped into diagnostics.
`019` — The prohibition applies to structured diagnostic files.
`020` — The prohibition applies to console output.
`021` — The prohibition applies to CI output.
`022` — The prohibition applies to crash reports.
`023` — The prohibition applies to startup fallback output.
`024` — The prohibition applies to support bundles.
`025` — The prohibition applies regardless of whether an output is intended for development, testing, production, or support.
`026` — Diagnostic call sites shall emit only the facts necessary to understand the technical condition.
`027` — Diagnostic APIs shall encourage structured named fields rather than arbitrary formatted object dumps.
`028` — Call sites shall not pass whole request objects.
`029` — Call sites shall not pass whole response objects.
`030` — Call sites shall not pass whole ORM/database objects.
`031` — Call sites shall not pass whole domain aggregates.
`032` — Call sites shall not pass whole provider message objects.
`033` — Call sites shall not pass arbitrary `locals()`/environment dumps.
`034` — Diagnostic helpers shall prefer purpose-built allowlisted fields.
`035` — Diagnostic event types shall define allowed context fields.
`036` — Allowed fields shall have known semantic meaning.
`037` — Unknown context fields shall not be serialized automatically.
`038` — Free-form details objects shall not bypass field governance.
`039` — Structured logging shall remain bounded even when source objects contain additional fields.
`040` — Diagnostic sanitization shall classify fields by semantic sensitivity.
`041` — Classification shall be normalized across supported diagnostic paths.
`042` — Equivalent sensitive concepts using different casing shall receive equivalent classification.
`043` — Equivalent sensitive concepts using approved aliases shall receive equivalent classification.
`044` — Classification shall not rely only on one exact literal field name.
`045` — Sensitive semantic categories shall remain versioned/governed as needed.
`046` — Password-like fields shall be classified as prohibited.
`047` — Token-like fields shall be classified as prohibited.
`048` — Session-like fields shall be classified as prohibited.
`049` — Authorization-header material shall be classified as prohibited.
`050` — Cookie/session-bearing header material shall be classified appropriately.
`051` — Private-key material shall be classified as prohibited.
`052` — URLs entering diagnostics shall undergo semantic sanitization.
`053` — URL user-info credentials shall be removed.
`054` — Sensitive query parameters shall be omitted or safely replaced.
`055` — Sensitive fragments shall be omitted where applicable.
`056` — Sanitization shall preserve only enough URL context for useful technical diagnosis.
`057` — A raw URL shall not be logged first and sanitized afterward in another sink.
`058` — HTTP/message headers entering diagnostics shall undergo allowlist/sanitization.
`059` — Authorization headers shall never be emitted raw.
`060` — Cookie-bearing headers shall never be emitted raw.
`061` — Authentication challenge/response material shall be handled according to sensitivity classification.
`062` — Unknown headers shall not automatically be considered safe.
`063` — Exceptions intended for diagnostic emission shall use safe summaries where possible.
`064` — Exception messages shall not deliberately embed secrets.
`065` — Validation exceptions shall avoid echoing complete sensitive input.
`066` — Authentication exceptions shall not contain supplied passwords/tokens.
`067` — HTTP/client exceptions shall not automatically dump full sensitive headers or payloads.
`068` — Database exceptions shall not automatically include unrestricted bound parameter values.
`069` — Import/parser exceptions shall not automatically include entire source rows/workbooks/message bodies.
`070` — Safe exception design is a primary control, not merely downstream redaction.
`071` — Tracebacks may be retained only after sanitization.
`072` — Local-variable capture shall not be included by default in diagnostic tracebacks.
`073` — Traceback frames shall not serialize arbitrary frame locals.
`074` — Exception chaining shall not cause an unsafe underlying message to bypass sanitization.
`075` — Sanitized traceback shall preserve useful code-location context where safe.
`076` — Sanitization shall recurse into nested structured context.
`077` — Nested objects shall not bypass field classification.
`078` — Nested arrays shall be sanitized element-wise as required.
`079` — Nested maps shall be sanitized according to allowed depth/field policy.
`080` — Recursion shall use bounded depth.
`081` — Collection traversal shall use bounded item counts.
`082` — Oversized nested values shall not cause unbounded sanitization work.
`083` — Cyclic object structures shall not cause infinite recursion.
`084` — Sensitive-data minimization/sanitization shall occur before diagnostic records enter asynchronous queues.
`085` — Raw sensitive records shall not sit temporarily in diagnostic queues awaiting later redaction.
`086` — Queue overflow/error handling shall therefore not expose unsanitized data.
`087` — Diagnostic-file output shall receive already sanitized records.
`088` — Console output shall receive already sanitized records.
`089` — CI output shall receive already sanitized records.
`090` — Crash-report construction shall receive sanitized data.
`091` — Startup fallback output shall receive sanitized data.
`092` — Support export shall receive sanitized/inspected data.
`093` — Pattern redaction shall serve as defense in depth.
`094` — Pattern redaction may detect accidental recognizable secret formats.
`095` — Pattern redaction shall not replace semantic field classification.
`096` — Pattern redaction shall not replace call-site minimization.
`097` — Pattern redaction shall not authorize deliberate raw logging of sensitive fields.
`098` — Failure of a pattern to recognize a secret shall not imply the value was safe to log.
`099` — Base64 encoding shall not automatically make a secret safe to log.
`100` — Hex encoding shall not automatically make a secret safe to log.
`101` — URL encoding shall not automatically make a secret safe to log.
`102` — Serialization into JSON shall not automatically make a secret safe to log.
`103` — Encrypting a sensitive value shall not automatically authorize diagnostic persistence.
`104` — Diagnostic policy shall minimize the data before considering storage protection.
`105` — A ciphertext derived from a prohibited reusable secret shall not be emitted simply because plaintext is hidden.
`106` — Hashing a secret shall not automatically authorize diagnostic emission.
`107` — Deterministic hashes of low-entropy secrets may remain sensitive.
`108` — Hash-based correlation shall use separately approved purpose-created identifiers rather than derived sensitive values where possible.
`109` — Truncation shall not automatically make a secret safe.
`110` — Prefix display shall not automatically make a token safe.
`111` — Suffix display shall not automatically make a token safe.
`112` — Partial body display shall not automatically make Communication content safe.
`113` — Any approved partial representation shall be explicitly justified by its owning diagnostic contract.
`114` — Diagnostic correlation shall use purpose-created opaque identifiers.
`115` — Correlation IDs shall not be derived from passwords.
`116` — Correlation IDs shall not be derived directly from authentication tokens.
`117` — Correlation IDs shall not expose Communication bodies.
`118` — Correlation IDs shall not rely on personally identifying Contact data where an opaque alternative exists.
`119` — Correlation IDs need not be globally meaningful outside the required diagnostic purpose.
`120` — If a field cannot be sanitized safely, that field shall be omitted.
`121` — Sanitization failure shall never fall back to the raw value.
`122` — If a record cannot be sanitized safely as a whole, that diagnostic record shall be omitted.
`123` — Omitting an unsafe diagnostic record shall not convert an otherwise valid business operation into failure solely because diagnostics failed.
`124` — The inability to emit diagnostics shall not weaken the underlying security/domain decision.
`125` — Startup fallback messages shall obey the same secret-prohibition rules as ordinary diagnostics.
`126` — Failure before the main diagnostic subsystem initializes shall not authorize raw exception dumping.
`127` — Emergency stderr/console output shall still use bounded safe messages.
`128` — CI test failures shall not dump real credentials.
`129` — CI assertion diffs shall not print full sensitive inputs.
`130` — Synthetic secrets used in canary tests shall remain intentionally fake and isolated.
`131` — CI artifact collection shall not bypass diagnostic redaction policy.
`132` — Support export shall apply the current sanitization/inspection policy.
`133` — Support export shall not blindly package old diagnostic files without reinspection.
`134` — Newly classified sensitive fields shall be removed from exported historical diagnostics.
`135` — Support export may omit records that cannot satisfy the current safe-export contract.
`136` — Support export shall not weaken current redaction merely because the original record predates the rule.
`137` — Diagnostic-security tests shall seed recognizable prohibited canary values.
`138` — Canary tests shall cover diagnostic files.
`139` — Canary tests shall cover console output.
`140` — Canary tests shall cover CI output where applicable.
`141` — Canary tests shall cover exception/traceback paths.
`142` — Canary tests shall cover startup fallback paths.
`143` — Canary tests shall cover support export.
`144` — Tests shall prove prohibited complete secret values are absent.
`145` — Tests shall prove prohibited reconstructable fragments are absent where combining retained fragments would materially reproduce the sensitive value.
`146` — Tests shall not consider a secret protected merely because it was split across several fields/records if practical reconstruction remains possible.
`147` — Tests shall include encoded/truncated recognizable canary forms where needed to prove defense-in-depth behavior.
`148` — Sanitized diagnostics shall preserve approved useful technical context.
`149` — Event/component codes shall remain available.
`150` — Run/correlation identity shall remain available.
`151` — Safe error category shall remain available.
`152` — Safe operation phase shall remain available where useful.
`153` — Safe target type or opaque target identity may remain where explicitly allowed.
`154` — Redaction shall not deliberately remove every useful diagnostic fact when a safe bounded representation exists.
`155` — The same semantic sensitivity policy shall govern diagnostics, console, CI, crash, startup fallback, and support-export paths.
`156` — A value forbidden in diagnostic files shall not become permissible merely because it is printed to console.
`157` — A value forbidden in console shall not become permissible merely because it appears inside a crash/support artifact.
`158` — No output sink shall serve as an unofficial bypass around the diagnostic data-minimization contract.

## `BETA-REQ-0143` — prefix `AUD-APPEND`

**Governing obligation:** `audit_events` shall form an application- and persistence-protected append-only ledger in which every accepted event has independent immutable opaque identity and is inserted exactly once through plain insert semantics; accepted rows shall never be updated, deleted, replaced, merged, reused, conflict-skipped, or silently ignored, duplicate identity shall be an explicit integrity error, command idempotency shall resolve before audit insertion, and required domain mutation plus audit shall commit atomically or roll back, while correction, reversal, cancellation, archival, restoration, and eligible deletion append new minimized events, no retention/purge/diagnostic/cache/JSON/optimization process may delete audit, migrations and backup/restore preserve historical rows, startup verifies protections, and SOMA shall claim only application-boundary append-only guarantees rather than unsupported cryptographic immunity from privileged datastore replacement.

`001` — `audit_events` shall be append-only.
`002` — An accepted audit row shall remain historically immutable.
`003` — Ordinary application workflows shall not mutate an accepted audit row.
`004` — Ordinary SQL persistence workflows shall not mutate an accepted audit row.
`005` — Current projections may interpret later audit events without rewriting earlier rows.
`006` — Accepted audit rows shall never be updated through ordinary application behavior.
`007` — Correcting an action shall not update the original audit row.
`008` — Changing a display label shall not rewrite historical audit payloads/fields.
`009` — Changing actor display data shall not rewrite the accepted historical audit identity/evidence.
`010` — Ordinary schema/repository APIs shall expose no generic audit-update operation.
`011` — Accepted audit rows shall never be deleted through ordinary application behavior.
`012` — Domain hard deletion shall not delete its required minimized audit events.
`013` — Archival shall not delete audit rows.
`014` — Cancellation shall not delete audit rows.
`015` — Restoration shall not delete prior audit rows.
`016` — Accepted audit rows shall never be replaced by another row using the same identity.
`017` — A “corrected” audit event shall receive a new identity.
`018` — Replacement semantics shall not overwrite the original row.
`019` — Audit storage shall not expose ordinary overwrite semantics.
`020` — A duplicate event identifier shall not overwrite an existing event.
`021` — Import/restore code shall not overwrite one accepted audit row with another.
`022` — Two accepted audit events shall not be merged into one row.
`023` — Historical events shall retain their independent event identities.
`024` — Later deduplication/optimization shall not collapse semantically distinct accepted events.
`025` — A conflicting audit insert shall not be silently skipped.
`026` — Duplicate identity shall not be interpreted as “already good enough.”
`027` — A conflicting insert shall produce an explicit integrity failure unless command idempotency prevented the insert earlier.
`028` — Every audit event shall have an independent immutable opaque identity.
`029` — An audit identity shall never be reused for another action.
`030` — Deletion/correction of the associated domain entity shall not free an audit identity for reuse.
`031` — Audit identity shall remain independent from business identifiers.
`032` — The canonical audit insertion path shall use plain insert semantics.
`033` — One logical audit event insertion shall expect exactly one row to be inserted.
`034` — Zero inserted rows shall not be considered successful audit insertion.
`035` — More than one inserted row for one event request shall fail the insertion contract.
`036` — Successful insertion shall return or preserve the exact accepted event identity.
`037` — Duplicate audit identity shall be an explicit error.
`038` — Duplicate identity shall not be converted into success.
`039` — Duplicate identity shall not be silently ignored.
`040` — Duplicate identity shall not be silently replaced.
`041` — Duplicate identity diagnostics shall preserve enough structural context to diagnose the defect without leaking prohibited data.
`042` — `INSERT OR IGNORE` shall not be used for accepted audit insertion.
`043` — Conflict-ignore semantics shall not be used to implement audit idempotency.
`044` — An ignored duplicate shall not be treated as proof that the intended prior event is semantically equivalent.
`045` — `INSERT OR REPLACE` shall not be used for accepted audit insertion.
`046` — Replace semantics shall not delete/recreate an existing audit row under the same logical identity.
`047` — SQLite convenience behavior shall not weaken append-only history.
`048` — Upsert-overwrite shall not be used for accepted audit events.
`049` — Upsert-do-nothing shall not be used to convert duplicate audit identity into idempotent success.
`050` — Generic repository upsert APIs shall not be used for canonical audit insertion.
`051` — Command idempotency shall resolve before audit insertion.
`052` — A repeated command with the same accepted idempotency identity shall be recognized before creating another audit event where the command contract defines idempotency.
`053` — Idempotency shall not depend on provoking a duplicate audit PK/identity error as the normal success path.
`054` — Audit identity and command-idempotency identity shall remain conceptually distinct.
`055` — A duplicate command shall not create a second accepted audit event when the owning command is defined as idempotent.
`056` — A genuinely distinct accepted command shall receive a distinct audit event even if its resulting domain state resembles an earlier state.
`057` — A duplicate audit identity shall not be assumed to refer to the same command inputs.
`058` — A duplicate audit identity shall not be assumed to refer to the same target.
`059` — A duplicate audit identity shall not be assumed to have the same resulting events.
`060` — Silent duplicate handling shall not conceal an event-ID generation defect.
`061` — The SQLite schema shall enforce applicable append-only audit protections.
`062` — Ordinary updates to accepted audit rows shall be rejected.
`063` — Ordinary deletes of accepted audit rows shall be rejected.
`064` — Indirect mutation through cascades/triggers shall not bypass append-only protection.
`065` — Schema protection shall remain compatible with backup/restore and governed migrations.
`066` — SOMA's persistence layer shall expose a dedicated audit insertion path.
`067` — Ordinary repository abstractions shall not expose audit update/delete operations.
`068` — Generic bulk-update logic shall exclude accepted audit rows.
`069` — Generic purge logic shall exclude accepted audit rows.
`070` — ORM/session behavior shall not silently mutate loaded audit events.
`071` — Direct SQL update attempts shall fail under the protected application boundary.
`072` — Direct SQL delete attempts shall fail under the protected application boundary.
`073` — Parent deletion shall not indirectly cascade-delete audit rows where the audit contract requires preservation.
`074` — Relationship cleanup shall not detach audit evidence in a way that erases its historical target meaning.
`075` — Optimization shall not rebuild audit history with changed row identities/content.
`076` — A required authoritative mutation and its required audit insertion shall commit atomically.
`077` — Audit insertion failure shall roll back the corresponding uncommitted domain mutation.
`078` — Domain mutation failure shall prevent the corresponding audit event from being committed as successful action evidence.
`079` — Transaction rollback shall leave neither a false domain success nor a false successful audit event.
`080` — This atomicity shall remain consistent with `0135`.
`081` — Correction shall append a new minimal audit event.
`082` — The correction event shall reference the applicable original action/evidence where required.
`083` — Original audit row shall remain unchanged.
`084` — Current projections may interpret the later correction while preserving both events historically.
`085` — Reversal shall append a new audit event.
`086` — Reversal shall not delete or modify the original event.
`087` — Accepted cancellation shall append its own audit evidence.
`088` — Cancellation shall not remove the audit event that created/progressed the cancelled entity.
`089` — Accepted archival shall append its own audit evidence.
`090` — Restoring from archive shall append a separate event.
`091` — Archive/restore cycles shall remain historically visible.
`092` — Restoration shall append new audit evidence.
`093` — Restoration shall not erase the event that caused the prior historical state.
`094` — Eligible hard deletion shall append or atomically preserve the required minimal deletion audit evidence.
`095` — Deleted domain content shall not survive merely as an oversized audit tombstone.
`096` — Deletion audit shall retain only the minimized evidence permitted by `0135/0144`.
`097` — General retention policy shall not delete accepted audit rows.
`098` — Communication orphan purge shall not delete application audit.
`099` — Diagnostic rotation shall not delete application audit.
`100` — Future retention features shall require explicit new authority before modifying this invariant.
`101` — Domain purge logic shall not remove required audit evidence.
`102` — Database cleanup utilities shall not purge audit events.
`103` — Storage-pressure behavior shall not silently delete audit events.
`104` — Diagnostic cleanup shall have no authority over audit storage.
`105` — Diagnostic configuration shall not set audit retention.
`106` — Cache invalidation shall not remove audit rows.
`107` — Projection rebuild shall not remove audit rows.
`108` — Database optimization shall not deduplicate audit events.
`109` — Maintenance/vacuum operations shall preserve accepted audit rows exactly.
`110` — JSON snapshots shall not substitute for the append-only relational audit ledger.
`111` — JSON cleanup/version upgrades shall not delete audit events.
`112` — Audit authority shall not be reconstructed from mutable JSON blobs.
`113` — Migrations shall preserve accepted audit rows.
`114` — An audit schema migration shall preserve event identity.
`115` — An audit schema migration shall preserve historical semantic content.
`116` — Migration shall not silently normalize away historical audit differences.
`117` — If schema representation changes, migration shall preserve exact required historical meaning and immutable event identity.
`118` — Backup shall preserve accepted audit rows.
`119` — Backup shall preserve event identities.
`120` — Backup shall not filter “old” audit events as an optimization.
`121` — Portable backup/recovery design shall retain the accepted audit ledger.
`122` — Restore shall preserve exact accepted audit rows represented in the backup.
`123` — Restore shall not regenerate audit identities.
`124` — Restore shall not recompute audit events from current domain state.
`125` — Restore shall not merge duplicate-looking historical audit records merely because their summaries match.
`126` — Restored audit rows shall undergo integrity/protection validation before authoritative service.
`127` — Startup shall verify required append-only audit protections.
`128` — Missing required audit-protection structures shall block readiness where their absence makes accepted audit mutation possible.
`129` — Startup validation shall detect a schema that permits forbidden ordinary audit mutation where deterministically testable.
`130` — Migration/readiness validation shall include applicable audit-protection checks as already required by `0132`.
`131` — SOMA shall protect audit append-only semantics at the application/persistence boundary.
`132` — SOMA shall not claim the audit ledger is cryptographically immutable unless separate cryptographic authority implements and proves that property.
`133` — Append-only database protections shall not be described as protection against an administrator who can replace the database file arbitrarily.
`134` — A privileged actor with filesystem/database replacement capability may remain outside the threat guarantee of this requirement.
`135` — Startup consistency validation may detect some tampering/drift but shall not be described as universal cryptographic proof.
`136` — History UI shall derive from the immutable event stream.
`137` — Later correction events may affect the interpreted current state without suppressing the original event.
`138` — History ordering shall preserve accepted event chronology/recording semantics.
`139` — UI filtering shall not delete hidden events.
`140` — Tests shall prove accepted audit rows reject update.
`141` — Tests shall prove accepted audit rows reject delete.
`142` — Tests shall prove duplicate event identity is an explicit error.
`143` — Tests shall prove `OR IGNORE`/replace/upsert behavior is not used in the canonical path.
`144` — Tests shall prove idempotent command replay is resolved before audit insertion.
`145` — Tests shall prove audit failure rolls back required domain mutation.
`146` — Tests shall prove corrections append rather than update.
`147` — Backup/restore tests shall prove event identity/content preservation.
`148` — Startup tests shall prove missing/broken append-only protections prevent authoritative readiness where required.

## `BETA-REQ-0144` — prefix `AUD-PAYLOAD`

**Governing obligation:** Every SOMA audit action shall use a named and versioned closed-allowlist JSON payload contract while core event, action, target, actor/source, time, correlation, and resulting-event authority remains relational; each permitted payload member shall define type, cardinality, bounds, sensitivity, nullability, and meaning, and any invalid, unknown, duplicate, non-finite, or excessive payload data shall fail the required audit and atomically roll back its associated mutation rather than fall back to serializing whole commands or entities, while identity, relationship, and changed-field evidence remains minimally allowlisted, secrets and unrestricted Communication/Notes/provider/import/exception/environment/request/response/database/ORM/snapshot/path content are excluded, provenance uses immutable references, correction and deletion payloads remain non-reconstructable and minimal, historical payload versions remain readable and unchanged, and per-action fixtures/canaries shall prove validation, rollback, minimization, historical rendering, and non-disclosure.

`001` — Every audit action that persists JSON payload data shall belong to an explicitly named payload schema.
`002` — Every such payload schema shall have an explicit version.
`003` — Payload schema identity shall correspond to the governed audit action family.
`004` — Payload schema shall not be inferred solely from whatever fields happen to appear in a JSON object.
`005` — An audit payload without a recognized action/schema contract shall not be persisted.
`006` — Every audit payload schema shall use a closed allowlist of permitted members.
`007` — Fields not listed by the applicable schema shall be unknown.
`008` — Unknown audit-payload fields shall be rejected.
`009` — Unknown fields shall not be silently preserved merely for convenience.
`010` — Unknown fields shall not silently acquire audit meaning.
`011` — SOMA shall not provide an unrestricted generic `details` object for audit events.
`012` — A generic arbitrary JSON map shall not substitute for action-specific audit schemas.
`013` — Audit callers shall not attach arbitrary key/value pairs outside the approved action payload.
`014` — Generic serialization helpers shall not bypass the action schema.
`015` — “Debugging convenience” shall not justify unrestricted audit details.
`016` — Core audit-event identity shall remain in owning relational fields.
`017` — Core audit-action identity shall remain in owning relational fields.
`018` — Core target identity shall remain in owning relational fields.
`019` — Core actor/source identity shall remain in owning relational fields.
`020` — Core UTC recording time shall remain in owning relational fields.
`021` — Core correlation references shall remain in owning relational fields where governed.
`022` — Resulting domain-event references shall remain relational where required by the audit model.
`023` — Payload JSON shall not duplicate these relational fields as competing authority.
`024` — Core relational audit fields shall remain directly queryable without deserializing payload JSON.
`025` — Payload version changes shall not alter the identity semantics of relational audit columns.
`026` — Audit filtering by actor/target/action/time shall not depend on parsing opaque payloads.
`027` — JSON payload shall supplement, not replace, the relational audit model.
`028` — Every permitted payload member shall define an expected type.
`029` — String members shall reject incompatible JSON types.
`030` — Numeric members shall reject incompatible JSON types.
`031` — Boolean members shall reject incompatible JSON types.
`032` — Object members shall use explicitly governed nested schemas where permitted.
`033` — Array members shall use governed element types.
`034` — Silent cross-type coercion shall not occur unless explicitly specified by the action schema.
`035` — Every payload member shall define its cardinality.
`036` — Required members shall be identifiable.
`037` — Optional members shall be identifiable.
`038` — Collection members shall define allowed element cardinality/bounds.
`039` — Multi-value members shall not silently accept scalar values.
`040` — Scalar members shall not silently accept arrays.
`041` — Every variable-size payload member shall have applicable bounds.
`042` — String lengths shall be bounded where appropriate.
`043` — Arrays shall have bounded item counts.
`044` — Nested objects shall have bounded structure/depth.
`045` — Numeric values shall respect semantic ranges where applicable.
`046` — Payload total size shall be bounded.
`047` — Excess data shall not be silently truncated into apparent validity unless that exact truncation is explicitly part of the schema.
`048` — Every permitted payload member shall have a governed sensitivity classification.
`049` — Sensitivity classification shall determine whether the field is permitted in audit at all.
`050` — A field permitted in one action schema shall not automatically become permitted in every action.
`051` — Audit payload sensitivity rules shall align with diagnostic/secret-protection authorities.
`052` — Every payload member shall define whether `null` is permitted.
`053` — Missing and explicit `null` shall remain distinguishable where the action schema assigns different meanings.
`054` — Empty string shall not automatically substitute for `null`.
`055` — Empty collection shall not automatically substitute for missing value.
`056` — Every allowed payload member shall have an explicit semantic meaning.
`057` — Two differently named fields shall not represent the same semantic fact ambiguously within one schema.
`058` — A payload field shall not change semantic meaning within the same schema version.
`059` — Incompatible semantic change shall require a new schema version.
`060` — Payload validation shall complete before the audit event is accepted.
`061` — Validation shall include schema identity/version.
`062` — Validation shall include allowed fields.
`063` — Validation shall include types.
`064` — Validation shall include required members.
`065` — Validation shall include bounds.
`066` — Validation shall include nullability.
`067` — Validation shall include semantic constraints.
`068` — Validation shall include sensitivity prohibitions.
`069` — Invalid payload data shall cause the required audit insertion to fail.
`070` — Audit shall not silently discard invalid members and continue as successful unless the exact schema explicitly defines an optional omission rule.
`071` — An invalid required payload shall not be stored partially.
`072` — Unknown payload members shall reject the required audit.
`073` — Unknown payload schema versions shall reject ordinary current-version audit insertion.
`074` — Unknown members shall not be silently moved into a generic extras bag.
`075` — Duplicate JSON keys shall reject an audit payload.
`076` — Last-key-wins parser behavior shall not silently resolve duplicate audit fields.
`077` — First-key-wins parser behavior shall not silently resolve duplicate audit fields.
`078` — `NaN` shall be rejected.
`079` — Positive infinity shall be rejected.
`080` — Negative infinity shall be rejected.
`081` — Non-standard non-finite numeric forms shall not enter accepted audit payloads.
`082` — Oversized payloads shall reject required audit insertion.
`083` — Excessive collection sizes shall reject required audit insertion.
`084` — Excessive nesting shall reject required audit insertion.
`085` — Excessive string/path content shall reject required audit insertion.
`086` — Required audit-payload validation failure shall roll back the associated uncommitted domain mutation.
`087` — Required audit-payload validation failure shall prevent the associated lifecycle event from being committed as accepted.
`088` — The application shall not commit business state and then merely report that audit payload validation failed.
`089` — Payload validation failure shall not trigger serialization of the complete application command.
`090` — Missing action-schema support shall not cause the entire command object to be stored.
`091` — Developer convenience fallback shall not replace strict schema validation.
`092` — Payload validation failure shall not cause serialization of the complete target entity.
`093` — A whole entity snapshot shall not be persisted because a smaller audit schema was difficult to implement.
`094` — Audit payload shall not become a second entity snapshot store.
`095` — Identity-related payload summaries shall contain only the minimal allowlisted difference not already represented relationally.
`096` — Identifier correction payloads may include bounded old/new identifier evidence where explicitly required.
`097` — Identity summaries shall not copy the full target entity.
`098` — Unchanged identity facts shall not be duplicated unnecessarily.
`099` — Relationship-change payloads shall contain only minimal allowlisted endpoint/change evidence.
`100` — Relationship audit shall not serialize entire parent and child entities.
`101` — Multi-target relationship changes shall remain bounded and explicitly structured.
`102` — Relationship payload shall preserve enough evidence to understand what relation changed.
`103` — Changed-field audit summaries shall contain only fields explicitly allowlisted for that action.
`104` — Unchanged fields shall not be included merely to create a convenient snapshot.
`105` — A changed field may include bounded prior/new representations where permitted.
`106` — Sensitive changed fields may require category-only or omission rather than value capture.
`107` — Changed-field summaries shall remain comprehensible without reconstructing the complete entity.
`108` — Passwords shall never enter audit payload JSON.
`109` — Reusable tokens shall never enter audit payload JSON.
`110` — Cryptographic keys shall never enter audit payload JSON.
`111` — Runtime authentication/session material shall never enter audit payload JSON.
`112` — Device/provider credentials shall never enter audit payload JSON.
`113` — Full Communication bodies shall never enter audit payload JSON.
`114` — Full email/message content shall never enter audit payload JSON.
`115` — Full Notes content shall not be copied into audit payloads.
`116` — Communication audit may preserve only bounded references/classification/difference facts explicitly permitted by its action schema.
`117` — Full provider payloads shall never enter audit JSON.
`118` — Whole RFC/WFM import rows shall not become audit payloads.
`119` — Whole workbook structures shall not become audit payloads.
`120` — Import audit shall preserve bounded provenance/review/result references instead of source snapshots.
`121` — Arbitrary exception objects shall never be placed in audit payloads.
`122` — Full tracebacks shall not enter application audit payloads.
`123` — Process/environment-variable dumps shall not enter audit payloads.
`124` — Machine environment snapshots shall not enter audit payloads.
`125` — Whole HTTP requests shall not enter audit payloads.
`126` — Whole HTTP responses shall not enter audit payloads.
`127` — Whole application command/request DTOs shall not enter audit payloads.
`128` — Whole response/result DTOs shall not enter audit payloads.
`129` — Database connection objects shall never enter audit payloads.
`130` — ORM entities/session objects shall never enter audit payloads.
`131` — Raw database rows shall not be dumped into audit JSON.
`132` — Internal persistence representations shall not be treated as audit payload contracts.
`133` — Whole pre-change entity snapshots shall not be ordinary audit payloads.
`134` — Whole post-change entity snapshots shall not be ordinary audit payloads.
`135` — Whole aggregate snapshots shall not be stored for convenience.
`136` — Audit is evidence of meaningful change, not a shadow backup system.
`137` — Full arbitrary filesystem paths shall not enter audit payloads by default.
`138` — Source provenance requiring file identity shall use bounded approved representation/reference.
`139` — User/profile directory portions shall not be retained unnecessarily.
`140` — Path values shall have explicit bounded semantics if an action schema permits them.
`141` — Audit provenance shall use immutable references where an authoritative source/event/run/import identity exists.
`142` — Provenance shall prefer reference identity over copying source content.
`143` — Import audit shall reference immutable import-run/source identities where applicable.
`144` — Proposal audit shall reference immutable proposal identities where applicable.
`145` — Domain-event provenance shall reference immutable event identities rather than duplicate event bodies.
`146` — Correction events shall preserve only the minimal action-specific facts necessary to explain the correction.
`147` — A correction shall reference prior immutable evidence where required.
`148` — A correction shall not create a full snapshot of the corrected entity merely to preserve history.
`149` — Eligible deletion audit shall retain only minimal deletion-action facts.
`150` — Deletion payload shall not retain a complete deleted entity.
`151` — Deletion payload shall not serve as a reconstructable tombstone.
`152` — Post-deletion audit shall remain compatible with the minimized non-reconstructable requirement from `0135`.
`153` — Historical audit payload versions shall remain readable under their original schema semantics.
`154` — Historical payloads shall not be rewritten in place into the newest schema version.
`155` — Historical payload bytes/logical fields shall remain unchanged except through separately governed storage-preserving migration that does not alter accepted semantics.
`156` — Per-action fixtures and sensitive-data canaries shall prove schema validation, transaction rollback on invalid required audit, minimization, historical-version rendering, and absence of prohibited/reconstructable content.

## `BETA-REQ-0145` — prefix `IMP-DISC`

**Governing obligation:** Enhanced RFC and WFM automatic workbook discovery shall inspect only stable direct regular files within one configurable operational import directory—initially suggesting Downloads—and shall classify candidates through exact source-family patterns, ranking WFM candidates by their supported embedded source timestamp and RFC candidates by deterministic discovery metadata that may include filesystem modification time while never treating that metadata or filename collision suffixes as business chronology; candidate ordering and ties shall be deterministic, the highest-ranked malformed candidate shall fail visibly without silent fallback to an older workbook, and explicit manual file selection shall remain available without bypassing downstream source validation, review, or authority rules.

`001` — Automatic Enhanced RFC and WFM workbook discovery shall use one operational import directory.
`002` — The operational import directory shall be configurable.
`003` — RFC automatic discovery shall use that configured directory.
`004` — WFM automatic discovery shall use that configured directory.
`005` — RFC and WFM automatic discovery shall not maintain competing implicit search roots.
`006` — Changing the operational import directory shall be an explicit Settings/configuration action.
`007` — SOMA shall initially suggest the operator's Downloads location as the operational import directory.
`008` — The Downloads location is an initial suggestion rather than immutable product authority.
`009` — The operator may configure another supported directory.
`010` — Merely reading the current import-directory setting shall not create or persist a setting under the Settings purity rule.
`011` — SOMA shall not require that the operational import directory permanently remain Downloads.
`012` — Automatic discovery shall use the currently accepted configured directory.
`013` — A missing configured directory shall not be silently replaced with an unrelated search location.
`014` — An inaccessible configured directory shall produce a truthful discovery limitation/error.
`015` — Discovery failure at the configured directory shall not trigger unrestricted filesystem searching.
`016` — Directory-validation failure shall not mutate RFC/WFM authority.
`017` — Enhanced RFC discovery shall use an exact recognized RFC source-family pattern.
`018` — WFM discovery shall use an exact recognized WFM source-family pattern.
`019` — RFC and WFM patterns shall remain independently defined.
`020` — Filename matching shall not rely on fuzzy similarity.
`021` — Filename matching shall not treat arbitrary workbooks containing “RFC” as recognized RFC exports.
`022` — Filename matching shall not treat arbitrary workbooks containing “WFM” as recognized WFM exports.
`023` — File extension requirements shall follow the exact source-family pattern.
`024` — Pattern interpretation shall be deterministic.
`025` — The exact accepted source-family patterns shall reside in the governed import adapter/registry rather than be guessed dynamically.
`026` — A discovered candidate shall be classified against the intended source family.
`027` — RFC discovery shall not accidentally select a WFM candidate.
`028` — WFM discovery shall not accidentally select an RFC candidate.
`029` — An ambiguous file that cannot safely be classified shall not be silently assigned to one family.
`030` — Automatic discovery shall inspect only direct entries in the configured operational import directory.
`031` — Automatic discovery shall not recursively search subdirectories.
`032` — A matching workbook stored only in a nested directory shall not become an automatic candidate merely through recursion.
`033` — Recursive filesystem crawling shall not be introduced as undocumented convenience behavior.
`034` — Automatic candidates shall be regular files according to the supported platform's governed file-inspection semantics.
`035` — Directories shall not become workbook candidates.
`036` — Non-file filesystem entries shall not be parsed as workbooks.
`037` — Exact handling of platform-specific link/reparse constructs remains an LLD security/filesystem decision while preserving the direct-stable-file invariant.
`038` — Automatic discovery shall inspect only candidates considered stable enough for deterministic inspection.
`039` — A file still undergoing an observable write/copy operation shall not be deliberately treated as a stable completed candidate.
`040` — File-stability determination shall be bounded.
`041` — Stability determination shall not require modifying the candidate file.
`042` — Exact stability-detection mechanics remain an LLD decision.
`043` — Discovery establishes a candidate workbook, not accepted RFC/WFM mutations.
`044` — Discovery ranking shall not create lifecycle evidence.
`045` — Discovery ranking shall not create business chronology.
`046` — Candidate selection remains upstream of parsing, validation, diff, review, and acceptance.
`047` — WFM candidate chronology shall derive from the supported embedded timestamp.
`048` — The embedded timestamp shall be parsed according to the governed WFM filename/source convention.
`049` — A valid later embedded WFM timestamp shall rank after an earlier valid embedded timestamp.
`050` — Filesystem modification time shall not override a valid WFM embedded chronology merely because the file was copied later.
`051` — Download time shall not replace WFM embedded chronology.
`052` — File creation time shall not replace WFM embedded chronology.
`053` — WFM embedded workbook timestamp shall govern candidate-file chronology.
`054` — Candidate-file chronology shall remain distinct from individual WFM Task business timestamps contained in the workbook.
`055` — WFM filename/source chronology shall not fabricate Task planned-start, planned-end, execution, creation, or completion time.
`056` — A WFM candidate whose required embedded timestamp cannot be interpreted according to its supported pattern shall be treated as malformed for automatic candidate selection.
`057` — An invalid embedded timestamp shall not be replaced with filesystem modification time silently.
`058` — An invalid embedded timestamp shall not be reconstructed from a collision suffix.
`059` — Failure to establish supported WFM candidate chronology shall remain visible.
`060` — RFC filesystem modification time may be used to rank RFC workbook candidates.
`061` — RFC modification-time ranking shall be used only for discovery candidate selection.
`062` — Later RFC file modification time may make a candidate rank as newer for discovery.
`063` — Exact supported filesystem timestamp retrieval/precision behavior shall be deterministic for the platform.
`064` — RFC file modification time shall never become RFC `Create Time`.
`065` — RFC file modification time shall never become RFC last-update business chronology.
`066` — RFC file modification time shall never become RFC status-transition chronology.
`067` — RFC file modification time shall never become import-derived lifecycle evidence.
`068` — RFC file modification time shall never substitute for a missing source-owned business timestamp.
`069` — Missing RFC source chronology shall remain missing/unknown even when file modification time exists.
`070` — Copying an old workbook today shall not make its RFC records operationally “new today.”
`071` — Download collision suffixes such as `(1)` shall not establish candidate chronology.
`072` — `(2)` shall not be interpreted as newer than `(1)` merely because its integer is larger.
`073` — Collision-suffix magnitude shall not become WFM chronology.
`074` — Collision-suffix magnitude shall not become RFC business chronology.
`075` — Collision suffixes may remain part of the physical filename without gaining temporal meaning.
`076` — Candidate ranking shall produce deterministic results from equivalent candidate state.
`077` — WFM ranking shall first honor its accepted embedded chronology.
`078` — RFC ranking shall honor its governed discovery chronology.
`079` — Candidate enumeration order returned by the filesystem shall not determine selection accidentally.
`080` — Locale-dependent lexical behavior shall not cause inconsistent candidate selection.
`081` — Equal candidate chronology shall be resolved deterministically.
`082` — Tie handling shall not rely on arbitrary filesystem enumeration order.
`083` — Collision-suffix integer shall not be assigned chronology merely to resolve a tie.
`084` — Exact deterministic tie-break mechanics may be specified by LLD/import-adapter design.
`085` — A deterministic tie-break shall establish selection order only and shall not fabricate business chronology.
`086` — Automatic selection shall identify the highest-ranked candidate under the applicable source-family chronology and tie rules.
`087` — Automatic discovery shall not intentionally prefer an older candidate merely because it is easier to parse.
`088` — If the highest-ranked selected candidate is malformed, automatic discovery shall fail visibly.
`089` — A malformed newest candidate shall not be silently skipped.
`090` — Automatic discovery shall not fall back to the next older valid candidate.
`091` — Malformed-candidate failure shall identify the affected source family.
`092` — Malformed-candidate failure shall provide bounded actionable information about the selected file/error.
`093` — Malformed-candidate failure shall not mutate authoritative RFC/WFM state.
`094` — SOMA shall not create the false impression that the newest source state was processed when it actually consumed an older workbook.
`095` — An older valid workbook shall remain discoverable through explicit operator action where appropriate rather than silent fallback.
`096` — Automatic fallback shall not hide a broken export pipeline.
`097` — Explicit manual workbook selection shall remain available for Enhanced RFC imports.
`098` — Explicit manual workbook selection shall remain available for WFM imports.
`099` — Manual selection shall remain distinct from automatic newest-candidate discovery.
`100` — Manual selection shall identify the exact operator-selected file.
`101` — Manual selection shall still require the applicable source-family validation.
`102` — Manual selection shall not bypass workbook parsing or security validation.
`103` — Manual selection shall not bypass import preview/review where the import contract requires review.
`104` — Manual selection shall not make malformed content authoritative.
`105` — Explicit operator selection may choose a file other than the automatically highest-ranked candidate.
`106` — Such selection shall be represented as an explicit manual source choice rather than pretending automatic chronology selected it.
`107` — Manual selection shall not rewrite the file's discovery chronology.
`108` — Manual selection shall not fabricate RFC/WFM business chronology.
`109` — Tests shall cover configurable discovery directory and initial Downloads suggestion without requiring Downloads permanently.
`110` — Tests shall cover exact family matching, direct/stable-file scope, WFM embedded-time ranking, RFC mtime ranking, collision-suffix non-chronology, and deterministic ties.
`111` — Tests shall prove a newest malformed candidate produces visible failure without automatic fallback to an older valid workbook.
`112` — Tests shall prove manual selection remains available while preserving all downstream validation, review, and authority boundaries.

## `BETA-REQ-0146` — prefix `IMP-OBS`

**Governing obligation:** Enhanced RFC and WFM workbooks shall be treated as untrusted external observations rather than replacement databases, so source validation, normalization, versioned logical fingerprinting, authoritative diff, and applicable warnings shall complete before any mutation; RFC and WFM shall maintain independent source-observation chronology checkpoints that are also separate from Communication coverage and business-event chronology, exact replay shall be a domain no-op, newer observations with logically identical content may update only bounded import-recency metadata, equal chronology with differing logical content shall conflict, older observations shall require an explicit reviewed recovery workflow, source-checkpoint state shall advance only consistently with accepted import work, and omission of an existing entity from any workbook shall carry no lifecycle, deletion, unlinking, or cascade authority.

`001` — An RFC workbook shall be treated as an untrusted source observation.
`002` — A WFM workbook shall be treated as an untrusted source observation.
`003` — An RFC workbook shall not be treated as a replacement for SOMA's authoritative RFC datastore.
`004` — A WFM workbook shall not be treated as a replacement for SOMA's authoritative WFM/Task datastore.
`005` — Workbook contents shall acquire authoritative effect only through the governed import acceptance workflow.
`006` — Merely discovering or opening a workbook shall create no authoritative RFC/WFM mutation.
`007` — An import shall affect only facts and relationships for which its source family has accepted authority.
`008` — Workbook import shall not erase SOMA-owned relationships merely because the external workbook does not represent them.
`009` — Workbook import shall not erase local Tasks merely because they do not appear in a WFM export.
`010` — Workbook import shall not erase SOMA audit history.
`011` — Workbook import shall not erase local correction history.
`012` — Workbook import shall not replace immutable SOMA internal identities.
`013` — Source validation shall complete before authoritative mutation.
`014` — File-family validation shall complete before authoritative mutation.
`015` — Required workbook structure validation shall complete before authoritative mutation.
`016` — Required row-identity validation shall complete before authoritative mutation.
`017` — Invalid source structure shall not partially mutate authoritative records merely because some rows appeared usable.
`018` — Validation results shall remain reviewable where the owning import workflow requires review.
`019` — Supported source values shall be normalized before authoritative comparison.
`020` — Normalization shall follow the versioned source adapter/header contract.
`021` — Normalization shall not silently invent missing source values.
`022` — Normalization shall not assign business meaning to unsupported fields.
`023` — Normalization shall preserve distinctions required by the source contract, including missing versus present values.
`024` — Normalization failure shall remain a staged import error rather than partially accepted state.
`025` — Fingerprinting and diff shall operate on the governed logical source representation rather than incidental workbook binary bytes alone.
`026` — Logically equivalent supported workbook content may remain equivalent despite irrelevant container-level `.xlsx` differences.
`027` — Irrelevant ZIP/package metadata shall not automatically make supported logical content different.
`028` — The exact logical canonicalization/fingerprint algorithm shall be versioned in import design.
`029` — Logical canonicalization shall not erase supported meaningful source differences.
`030` — Every staged RFC import observation shall obtain a logical fingerprint.
`031` — Every staged WFM import observation shall obtain a logical fingerprint.
`032` — The fingerprint shall be calculated before authoritative mutation.
`033` — The fingerprint shall represent the governed normalized logical import content.
`034` — Fingerprint identity shall be scoped sufficiently to the applicable source family/format contract.
`035` — Fingerprints shall support deterministic replay and conflict decisions.
`036` — A fingerprint shall detect logical equality/difference and shall not be represented as proof of authorship or malicious tampering.
`037` — A staged RFC observation shall be compared against current accepted SOMA authority before mutation.
`038` — A staged WFM observation shall be compared against current accepted SOMA authority before mutation.
`039` — Import shall determine intended additions where applicable.
`040` — Import shall determine intended updates where applicable.
`041` — Import shall identify source conflicts where applicable.
`042` — Import shall identify unchanged recognized entities where applicable.
`043` — The diff shall remain a proposal/review artifact until accepted.
`044` — Merely calculating a diff shall not mutate domain state.
`045` — Applicable source warnings shall be calculated before authoritative mutation.
`046` — Missing optional source fields may produce warnings under the relevant adapter contract.
`047` — Ambiguous source relationships shall produce warnings/conflicts rather than silent guesses.
`048` — Unknown source values shall remain visible where the owning adapter contract defines warning behavior.
`049` — Warnings shall not themselves constitute accepted lifecycle evidence.
`050` — Review shall expose material warnings before acceptance.
`051` — Validation state shall remain non-authoritative.
`052` — Normalized staged rows shall remain non-authoritative.
`053` — Fingerprints shall remain import metadata rather than domain lifecycle truth.
`054` — Diffs shall remain proposals until acceptance.
`055` — Warnings shall remain review evidence rather than accepted mutation.
`056` — Closing/cancelling an import preview shall leave authoritative RFC/WFM state unchanged.
`057` — The RFC import family shall maintain its own source chronology checkpoint.
`058` — The RFC checkpoint shall represent accepted RFC-source observation chronology.
`059` — The RFC source checkpoint shall remain distinct from individual RFC business timestamps.
`060` — RFC source chronology shall not overwrite RFC `Create Time`.
`061` — RFC source chronology shall not fabricate an RFC status-transition time.
`062` — The WFM import family shall maintain its own source chronology checkpoint.
`063` — The WFM checkpoint shall represent accepted WFM-source observation chronology.
`064` — The WFM source checkpoint shall remain distinct from Task planned-start/planned-end chronology.
`065` — The WFM source checkpoint shall remain distinct from actual Task execution chronology.
`066` — RFC source chronology shall not advance the WFM source checkpoint.
`067` — WFM source chronology shall not advance the RFC source checkpoint.
`068` — A successful RFC import shall not imply that WFM source state is current.
`069` — A successful WFM import shall not imply that RFC source state is current.
`070` — Each source family shall independently represent its last accepted import observation.
`071` — RFC source chronology checkpoint shall remain distinct from PST/OST communication coverage.
`072` — WFM source chronology checkpoint shall remain distinct from PST/OST communication coverage.
`073` — Communication scanner high-water advancement shall not advance RFC/WFM import checkpoints.
`074` — Workbook import shall not advance Communication coverage.
`075` — Communication targeted backfill shall not rewind workbook source chronology.
`076` — The UI/history shall not imply these independent workflow checkpoints are interchangeable.
`077` — Reprocessing the exact previously accepted logical source observation shall be recognized as replay.
`078` — Exact replay shall perform no authoritative RFC/WFM mutation.
`079` — Exact replay shall create no duplicate RFC.
`080` — Exact replay shall create no duplicate WFM.
`081` — Exact replay shall not duplicate accepted relationships.
`082` — Exact replay shall not duplicate lifecycle events.
`083` — Exact replay shall not generate artificial source changes merely because the workbook file was copied or selected again.
`084` — Exact replay may report that no authoritative changes are required.
`085` — A no-op replay result shall remain distinguishable from import failure.
`086` — A no-op replay result shall remain distinguishable from a newly accepted material import.
`087` — A source observation with newer accepted chronology and identical logical fingerprint shall not fabricate domain changes.
`088` — Newer-identical RFC content shall not create RFC lifecycle events.
`089` — Newer-identical WFM content shall not create Task lifecycle events.
`090` — Newer-identical content may update only governed bounded source-check recency/observation metadata.
`091` — Such recency metadata shall remain distinct from business entity timestamps.
`092` — Updated check recency shall not imply that every entity inside the workbook changed at that time.
`093` — Check-recency metadata shall remain operational import metadata.
`094` — Check-recency metadata shall be minimal.
`095` — Check-recency metadata shall not become a duplicate history stream for every row.
`096` — Exact fields retained for check recency shall be defined by import LLD without inventing business chronology.
`097` — Two source observations claiming equal governed chronology but different logical fingerprints shall conflict.
`098` — Equal-chronology conflicting RFC content shall not be silently ordered by filesystem metadata.
`099` — Equal-chronology conflicting WFM content shall not be silently accepted by filename collision order.
`100` — One conflicting observation shall not automatically overwrite the other.
`101` — The conflict shall remain visible for explicit resolution/recovery.
`102` — Conflict detection shall occur before authoritative mutation.
`103` — The source checkpoint shall not silently advance through an unresolved equal-chronology conflict.
`104` — A source observation older than the accepted source-family checkpoint shall be recognized as older source content.
`105` — Older source content shall not be applied through the ordinary forward import path.
`106` — Older RFC observation shall not silently regress accepted source-owned facts.
`107` — Older WFM observation shall not silently regress accepted source-owned facts.
`108` — Automatic import shall not rewind the source checkpoint merely because an older file was manually copied into the directory.
`109` — Processing older source content for authoritative recovery shall require an explicit recovery workflow.
`110` — Recovery shall identify the source family and selected older observation.
`111` — Recovery shall expose material differences before mutation.
`112` — Recovery shall not masquerade as ordinary newest-source import.
`113` — Recovery shall preserve history/provenance explaining why older source evidence was reconsidered.
`114` — Recovery shall revalidate current authoritative state before commit.
`115` — Exact recovery confirmation mechanics may be defined by the import/recovery LLD.
`116` — Absence of an existing RFC from an imported workbook shall not by itself close that RFC.
`117` — Absence of an existing RFC from an imported workbook shall not by itself cancel that RFC.
`118` — Absence of an existing RFC from an imported workbook shall not by itself archive that RFC.
`119` — Absence of an existing WFM from an imported workbook shall not by itself complete that WFM.
`120` — Absence of an existing WFM from an imported workbook shall not by itself cancel that WFM.
`121` — Absence of an existing WFM from an imported workbook shall not by itself delete or unlink that WFM.
`122` — Omission shall not produce synthetic lifecycle evidence.
`123` — Omission shall not cause a terminal-state cascade.
`124` — Omission shall remain compatible with full, partial, filtered, or otherwise source-scoped workbooks.
`125` — Once reviewed import mutations are accepted, each accepted scope shall follow its owning transactional contract.
`126` — Import failure shall not leave a misleading source checkpoint claiming acceptance of mutations that did not commit.
`127` — Source chronology/fingerprint metadata shall commit consistently with the accepted import result.
`128` — Deterministic tests shall prove validation-before-mutation, replay no-op, newer-identical recency-only behavior, equal-chronology conflict, older-source recovery requirement, independent RFC/WFM/Communication checkpoints, and omission without lifecycle effect.

## `BETA-REQ-0147` — prefix `IMP-STATUS`

**Governing obligation:** RFC and WFM active, terminal, cancelled, and historical presentation shall derive from accepted recognized source status and owning lifecycle authority rather than presence in any particular workbook; omission from full or filtered observations shall never close, archive, authoritatively hide, unlink, delete, or stop tracking an entity, Beta 1.0 shall define no separate stop-tracking lifecycle, historical entities shall remain persisted and locally filterable through ordinary and saved views, uncertain workbook coverage may be reported only as source-level uncertainty rather than fabricated per-record disappearance, and any later reappearance shall reconcile to the same immutable entity identity and proceed through ordinary reviewed updates without a synthetic resume proposal or lifecycle transition.

`001` — Recognized RFC status shall govern whether an RFC is presented as active, terminal, cancelled, or historical.
`002` — Recognized WFM status shall govern whether a WFM is presented as active, terminal, cancelled, or historical.
`003` — Workbook presence shall not independently govern lifecycle presentation.
`004` — Workbook absence shall not independently govern lifecycle presentation.
`005` — Source-status interpretation shall follow the owning RFC/WFM status vocabulary.
`006` — An RFC whose accepted recognized status is active shall remain available as active regardless of omission from a later workbook.
`007` — A WFM whose accepted recognized status is active shall remain available as active regardless of omission from a later workbook.
`008` — Active presentation shall not depend on current workbook membership alone.
`009` — A filtered workbook excluding an active entity shall not make the entity historical.
`010` — Accepted recognized terminal RFC status shall govern terminal RFC presentation.
`011` — Accepted recognized terminal WFM status shall govern terminal WFM presentation.
`012` — A terminal entity shall not become active merely because it appears again in a later workbook without accepted contradictory status evidence.
`013` — Terminal presentation shall remain distinct from archival presentation.
`014` — Accepted recognized cancelled RFC status shall govern cancelled RFC presentation.
`015` — Accepted recognized cancelled WFM status shall govern cancelled WFM presentation.
`016` — Cancellation shall derive from recognized status evidence, not omission.
`017` — Omission shall not fabricate cancelled state.
`018` — Historical presentation shall derive from accepted lifecycle/status authority.
`019` — Historical presentation shall not derive merely from disappearance from a workbook.
`020` — Historical entities shall remain persisted and queryable.
`021` — Historical entities shall remain available to relationship/history views where applicable.
`022` — Omission of an RFC from a workbook shall never close that RFC.
`023` — Omission of a WFM from a workbook shall never complete/close that WFM.
`024` — Omission shall create no synthetic terminal lifecycle evidence.
`025` — Omission shall never archive an RFC.
`026` — Omission shall never archive a WFM or Task.
`027` — Archive state shall remain governed by its owning explicit archival workflow.
`028` — Omission shall not automatically hide an RFC from SOMA.
`029` — Omission shall not automatically hide a WFM from SOMA.
`030` — Local views may filter entities by accepted lifecycle state without treating filtering as deletion or loss of tracking.
`031` — Hidden-by-view state shall remain presentation-only.
`032` — Omission shall not unlink an RFC from an SR.
`033` — Omission shall not unlink a WFM from its owning RFC.
`034` — Omission shall not remove a WFM from an Objective.
`035` — Omission shall not remove other accepted relationships.
`036` — Relationship correction shall require its own governed authority.
`037` — Omission shall not create a stop-tracking state.
`038` — Omission shall not deactivate import relevance independently of lifecycle state.
`039` — Omission shall not suppress future identity matching.
`040` — Omission shall not prevent a later workbook from updating the same accepted identity.
`041` — Beta 1.0 shall not define an independent `Stop tracking` lifecycle state for RFCs.
`042` — Beta 1.0 shall not define an independent `Stop tracking` lifecycle state for WFMs.
`043` — The UI shall not expose a hidden or renamed equivalent of `Stop tracking` as source-import lifecycle.
`044` — Import logic shall not persist an `ever_missing`, `tracking_disabled`, or equivalent state as lifecycle authority unless separately approved.
`045` — Historical/terminal status shall not be reinterpreted as `Stop tracking`.
`046` — Historical RFC rows shall remain available in SOMA.
`047` — Historical WFM rows shall remain available in SOMA.
`048` — Historical availability shall not depend on continued workbook presence.
`049` — Historical availability shall preserve immutable internal identity.
`050` — Historical availability shall preserve accepted relationships and provenance.
`051` — SOMA shall filter historical RFC/WFM records locally.
`052` — Local filtering shall operate on accepted SOMA lifecycle/status state.
`053` — Local filtering shall not require the source workbook to exclude historical rows.
`054` — Local filtering shall not mutate source data.
`055` — Local filtering shall not mutate authoritative lifecycle state.
`056` — Current/active views may exclude historical records by default according to product presentation rules.
`057` — Historical views shall allow operators to access historical RFCs/WFMs.
`058` — Filtering an entity out of one view shall not remove it from another valid view.
`059` — View filters shall remain presentation state, not lifecycle commands.
`060` — Saved filters may preserve local RFC/WFM presentation criteria.
`061` — Saved filters may include active/historical/cancelled/status-related criteria.
`062` — Saved filters shall not mutate entity status.
`063` — Saved filters shall not suppress future imports for filtered-out entities.
`064` — Deleting a saved filter shall not alter tracked entities.
`065` — Omission from a workbook believed to be full shall still have no direct lifecycle authority.
`066` — A full-workbook assumption shall not authorize silent closure.
`067` — A full-workbook assumption shall not authorize silent archive.
`068` — A full-workbook assumption shall not authorize silent unlinking.
`069` — Omission from a known filtered workbook shall have no lifecycle authority.
`070` — Filter criteria need not be reverse-engineered per omitted entity to preserve that invariant.
`071` — A filtered workbook shall not produce false record-disappearance events.
`072` — SOMA may represent uncertainty about workbook coverage.
`073` — Coverage uncertainty shall apply to the workbook/import observation as a whole where appropriate.
`074` — Coverage uncertainty shall remain distinct from an individual entity lifecycle warning.
`075` — Workbook-level coverage warning shall not imply that any specific omitted entity disappeared from the source system.
`076` — An omitted RFC shall not receive a per-record “disappeared” warning solely due to workbook absence.
`077` — An omitted WFM shall not receive a per-record “disappeared” warning solely due to workbook absence.
`078` — SOMA shall not imply source deletion for an omitted entity without positive source evidence.
`079` — SOMA shall not imply source closure for an omitted entity without positive status evidence.
`080` — SOMA shall not flood operators with entity-level disappearance warnings generated from coverage uncertainty.
`081` — A later workbook containing a previously omitted RFC shall match the existing RFC by its canonical identity.
`082` — A later workbook containing a previously omitted WFM shall match the existing WFM by its canonical Task identity.
`083` — Reappearance shall not create a duplicate entity.
`084` — Reappearance shall preserve immutable internal identity.
`085` — Reappearance shall preserve prior relationships and history unless separately corrected.
`086` — Reappearance shall not generate a `Resume tracking` proposal.
`087` — Reappearance shall not require a synthetic resume lifecycle transition.
`088` — Reappearance shall not create a resume audit event merely because the entity had been absent from one or more workbooks.
`089` — A normal accepted update from the reappearing source observation shall proceed against the same existing identity.
`090` — Reappearance may update source-owned facts through the ordinary reviewed import contract.
`091` — Reappearance shall still respect source chronology/conflict rules from `0146`.
`092` — Reappearance shall not bypass status review/correction rules.
`093` — Reappearance shall not implicitly reactivate a terminal entity unless accepted source status legitimately changes under its lifecycle contract.
`094` — Unknown/unrecognized status shall not gain destructive authority from workbook presence or absence.
`095` — Unknown status may warn under the source adapter/lifecycle contract.
`096` — Unknown status shall not be converted to historical solely because the entity later disappears from a workbook.
`097` — Lists, workbenches, counts, and historical views shall derive RFC/WFM presentation from accepted lifecycle/status state.
`098` — Dashboard/filter projections shall not create separate tracking state.
`099` — Recomputing views shall not create disappearance or resume lifecycle evidence.
`100` — Tests shall prove accepted active RFC/WFM entities remain present after omission from later full and filtered workbooks.
`101` — Tests shall prove omission cannot close, archive, hide authoritatively, unlink, delete, or stop tracking an entity.
`102` — Tests shall prove historical rows remain retrievable through local views/saved filters.
`103` — Tests shall prove workbook-level coverage uncertainty does not generate per-record disappearance warnings.
`104` — Tests shall prove reappearance updates the same identity without duplicate creation or synthetic resume proposal.

## `BETA-REQ-0148` — prefix `IMP-ADOPT`

**Governing obligation:** When a governed RFC or WFM source observation exactly matches the canonical external identifier of an existing manually registered entity, SOMA shall adopt that entity in place rather than create or merge a duplicate, preserving its immutable internal identity, valid relationships, and prior history while appending durable accepted source provenance from which adoption remains permanently derivable without a competing mutable `ever_imported` authority; source-owned facts shall prevail only through the governed diff/review process and only within their authority, SOMA-local creation chronology shall remain distinct from source `external_created_at` and all import/file chronology, absent source time shall remain unknown, conflicting chronology shall require reviewed correction, and descriptive or fuzzy similarity shall never establish adoption identity.

`001` — A manually registered RFC may be adopted by an imported RFC observation only when canonical RFC identity matches exactly.
`002` — RFC adoption shall use the governed canonical RFC identifier syntax.
`003` — Exact canonical RFC identity shall remain distinct from descriptive similarity.
`004` — Formatting normalization may occur only according to the governed canonical identifier contract.
`005` — A malformed source RFC identifier shall not authorize adoption.
`006` — A manually registered WFM may be adopted by an imported WFM observation only when canonical WFM Task identity matches exactly.
`007` — WFM adoption shall use the governed canonical `TK` identifier syntax.
`008` — Exact Task No. identity shall remain distinct from Task Name similarity.
`009` — A malformed source WFM identifier shall not authorize adoption.
`010` — Exact matching manual RFC shall be adopted in place rather than duplicated.
`011` — Exact matching manual WFM shall be adopted in place rather than duplicated.
`012` — Adoption shall preserve the pre-existing SOMA entity.
`013` — Adoption shall attach accepted source provenance to that entity.
`014` — Adoption shall not create a second entity representing the same canonical external identity.
`015` — RFC adoption shall preserve the existing immutable SOMA RFC internal identity.
`016` — WFM adoption shall preserve the existing immutable SOMA Task internal identity.
`017` — Import provenance shall not replace the internal identity.
`018` — External identifier shall remain a business/source identity rather than the relational primary identity.
`019` — Adoption shall not regenerate internal IDs merely because the source is now authoritative for some fields.
`020` — RFC adoption shall preserve valid existing SR relationships.
`021` — RFC adoption shall preserve valid hierarchy relationships subject to later reviewed conflict resolution.
`022` — RFC adoption shall preserve existing Task relationships.
`023` — WFM adoption shall preserve its owning RFC relationship when consistent with accepted source evidence.
`024` — WFM adoption shall preserve valid Objective membership.
`025` — Adoption shall preserve valid Communication relationships where applicable.
`026` — Adoption shall preserve existing audit/history references.
`027` — Existing relationships shall not be dropped merely because the imported workbook omits them.
`028` — Manual creation history shall remain preserved after adoption.
`029` — Prior accepted corrections shall remain preserved after adoption.
`030` — Existing audit events shall remain tied to the same internal entity identity.
`031` — Adoption shall append provenance/history rather than rewrite the entity's origin story.
`032` — Accepted adoption shall preserve source provenance.
`033` — Provenance shall identify the applicable source family.
`034` — Provenance shall identify the accepted import/source observation where applicable.
`035` — Provenance shall identify the canonical external identity adopted.
`036` — Adoption provenance shall be immutable historical evidence.
`037` — Once accepted source provenance establishes that an entity has been adopted from the governed external source, that historical fact shall not be erased.
`038` — Later correction shall not redefine the entity as though the adoption never occurred.
`039` — Later source inactivity shall not erase historical adoption provenance.
`040` — Later workbook omission shall not erase historical adoption provenance.
`041` — Terminal status shall not erase historical adoption provenance.
`042` — Archival shall not erase historical adoption provenance.
`043` — SOMA shall not create a mutable `ever_imported` flag as independent source-of-truth authority.
`044` — Whether adoption ever occurred shall derive from accepted provenance/history.
`045` — A cached/derived imported indicator may exist only as a projection of immutable provenance.
`046` — A derived imported indicator shall not be independently editable.
`047` — Clearing a UI/import indicator shall not erase provenance.
`048` — Recomputing projections shall reproduce the same adopted/not-adopted conclusion from accepted history.
`049` — A manually registered RFC is not considered erroneous merely because official source evidence arrives later.
`050` — A manually registered WFM is not considered erroneous merely because official source evidence arrives later.
`051` — Adoption shall preserve the fact that SOMA knew the entity before source import.
`052` — Adoption shall not fabricate an earlier import time.
`053` — Source-owned RFC facts shall be compared against existing manual values during adoption.
`054` — Source-owned WFM facts shall be compared against existing manual values during adoption.
`055` — Source-owned fact differences shall appear in the governed import diff.
`056` — Material source-owned differences shall require the applicable review/acceptance workflow.
`057` — Accepted source-owned values shall prevail over competing manual descriptive values for fields governed by that source.
`058` — Source precedence shall not bypass conflict review where the owning requirement requires review.
`059` — Source precedence shall apply only to fields that the source contract actually owns.
`060` — Source adoption shall not overwrite SOMA-owned relationships that the workbook does not govern.
`061` — Source adoption shall not overwrite SOMA audit identity/history.
`062` — Source adoption shall not overwrite Objective membership merely because the source lacks that concept.
`063` — Source adoption shall not overwrite local Notes.
`064` — Source adoption shall not replace internal entity identity.
`065` — Source adoption shall not overwrite local lifecycle facts outside the source's accepted authority.
`066` — A later source workbook omitting an adopted entity shall not reverse adoption.
`067` — Omission shall not convert an adopted entity back to manual-only status.
`068` — Omission shall not erase imported source-owned facts.
`069` — Omission behavior shall remain governed by `0146–0147`.
`070` — SOMA shall preserve the timestamp representing when the local entity was created in SOMA.
`071` — SOMA creation time shall remain distinct from source `external_created_at`.
`072` — Adoption shall not overwrite SOMA creation time with source creation time.
`073` — Source creation time shall not overwrite the historical fact that SOMA registered the entity earlier or later.
`074` — A usable source creation timestamp shall be stored as source-owned external chronology where the source adapter recognizes it.
`075` — Source `external_created_at` shall retain provenance.
`076` — External source creation chronology shall remain distinguishable from import observation chronology.
`077` — External source creation chronology shall remain distinguishable from file modification time.
`078` — External source creation chronology shall remain distinguishable from adoption/acceptance time.
`079` — If the source provides no usable external creation time, `external_created_at` shall remain unknown.
`080` — SOMA creation time shall not be copied into missing `external_created_at`.
`081` — Import time shall not be copied into missing `external_created_at`.
`082` — File modification time shall not be copied into missing `external_created_at`.
`083` — Filename chronology shall not be copied into missing `external_created_at`.
`084` — Missing external chronology shall remain visibly unknown where material.
`085` — A material conflict between existing external chronology evidence and newly imported source chronology shall require review.
`086` — Conflicting source chronology shall not be resolved by whichever value was imported most recently.
`087` — Conflicting chronology shall retain both relevant provenance references for review.
`088` — Accepted chronology correction shall append correction evidence.
`089` — Chronology conflict resolution shall not rewrite SOMA creation time.
`090` — Similar RFC Summary text shall not authorize RFC adoption.
`091` — Similar WFM Task Name text shall not authorize WFM adoption.
`092` — Similar Customer names shall not authorize RFC/WFM adoption.
`093` — Similar timestamps shall not authorize adoption.
`094` — Similar owner/creator values shall not authorize adoption.
`095` — Similar descriptive fields may support human reconciliation but cannot establish entity identity.
`096` — Fuzzy matching shall not silently adopt one entity into another.
`097` — If more than one local entity somehow claims the same canonical external RFC identity, import shall detect an integrity conflict rather than arbitrarily adopt one.
`098` — If more than one local entity somehow claims the same canonical WFM identity, import shall detect an integrity conflict.
`099` — Adoption shall not merge duplicate local entities silently.
`100` — Duplicate-identity correction shall follow a separately governed integrity/reconciliation path.
`101` — Adoption itself shall not fabricate an RFC lifecycle transition.
`102` — Adoption itself shall not fabricate a WFM completion/cancellation transition.
`103` — Source status differences encountered during adoption shall be processed through their owning lifecycle/status rules.
`104` — Adoption and lifecycle acceptance may occur within one reviewed import transaction only where their separate evidence remains distinguishable.
`105` — Tests shall prove exact canonical ID adopts a manual RFC/WFM in place and preserves internal identity and relationships.
`106` — Tests shall prove accepted source provenance remains historically derivable without a mutable `ever_imported` authority.
`107` — Tests shall prove SOMA creation time, source `external_created_at`, import chronology, and file chronology remain distinct and missing source time stays unknown.
`108` — Tests shall prove similar descriptive labels never authorize adoption and duplicate exact-identity anomalies produce explicit conflict rather than silent merge.

## `BETA-REQ-0149` — prefix `RFC-STATUS`

**Governing obligation:** RFC source status shall resolve case-insensitively through a closed canonical vocabulary in which `Closed` and `Cancelled` remain distinct terminal evidence; current status shall be a projection of accepted append-only evidence, so ordinary progression shall never silently regress and any correction shall be a high-risk reviewed decision targeting exact prior evidence, including potentially valid Post-Implement cancellation; acceptance of terminal evidence shall atomically create its linked pending cascade proposal without executing downstream consequences, which require separate explicit deliberate-hold confirmation and fresh revalidation, while unknown status shall remain warning-only evidence with no destructive lifecycle, relationship, archival, or cascade authority.

`001` — RFC source status shall be interpreted through a closed recognized vocabulary.
`002` — Only statuses explicitly present in the governed RFC status vocabulary shall receive recognized lifecycle meaning.
`003` — Arbitrary source text shall not automatically become a new lifecycle state.
`004` — Unknown status text shall remain unknown rather than extending the vocabulary dynamically.
`005` — The exact complete accepted vocabulary shall be maintained by the governed RFC source/lifecycle contract.
`006` — RFC source-status matching shall be case-insensitive.
`007` — Case differences alone shall not create distinct RFC lifecycle states.
`008` — `Closed`, `closed`, and equivalent casing variants shall resolve to the same canonical recognized status.
`009` — `Cancelled`, `cancelled`, and equivalent casing variants shall resolve to the same canonical recognized status.
`010` — Case-insensitive recognition shall not imply fuzzy recognition of additional characters or words.
`011` — A recognized source-status value shall map deterministically to one canonical RFC status meaning.
`012` — Canonical status representation shall remain queryable independently of the source's casing.
`013` — Source raw/normalized provenance may be preserved where required without creating competing lifecycle authority.
`014` — A presentation label change shall not alter canonical lifecycle semantics.
`015` — Partial string matching shall not establish recognized status.
`016` — Substring matching shall not establish recognized status.
`017` — Typographical similarity shall not establish recognized status automatically.
`018` — Positional workbook context shall not redefine unknown status into a known status.
`019` — An unrecognized value shall follow unknown-status behavior.
`020` — Recognized `Closed` shall constitute terminal RFC evidence.
`021` — Accepted `Closed` evidence shall terminate the RFC under the governing RFC lifecycle.
`022` — `Closed` shall remain historically distinguishable from other terminal reasons.
`023` — A `Closed` RFC shall remain available historically.
`024` — Recognized `Cancelled` shall constitute terminal RFC evidence.
`025` — Accepted `Cancelled` evidence shall terminate the RFC under the governing RFC lifecycle.
`026` — `Cancelled` shall remain historically distinguishable from `Closed`.
`027` — A `Cancelled` RFC shall remain available historically.
`028` — SOMA shall not collapse `Closed` and `Cancelled` into one indistinguishable persisted terminal reason.
`029` — History shall preserve whether accepted terminal evidence was `Closed` or `Cancelled`.
`030` — Filters may group terminal states for presentation while preserving their distinct underlying meaning.
`031` — A terminal projection shall not discard the specific accepted terminal evidence.
`032` — Source status evidence shall remain distinguishable from the current RFC status projection derived from accepted evidence.
`033` — Current RFC status projection shall derive from accepted lifecycle evidence.
`034` — Projection recomputation shall not rewrite the underlying evidence.
`035` — Correcting a projection shall target the exact evidence that caused the incorrect current interpretation.
`036` — RFC status projection correction shall be classified as a high-risk operation.
`037` — High-risk correction shall require deliberate reviewed operator action.
`038` — Correction shall expose the current projection.
`039` — Correction shall expose the evidence being corrected.
`040` — Correction shall expose the resulting proposed projection.
`041` — Correction shall not be a generic editable Status dropdown.
`042` — A correction shall identify the exact accepted status evidence being corrected.
`043` — Correction shall not vaguely target “the RFC status in general.”
`044` — Where multiple historical status observations exist, the operator shall be able to identify which evidence is being corrected.
`045` — Correction shall preserve the identity of the original evidence.
`046` — RFC status correction shall append new correction evidence.
`047` — Original accepted status evidence shall remain historically preserved.
`048` — Correction shall not update the original evidence row in place.
`049` — Correction shall not delete the original evidence.
`050` — Correction shall preserve actor/source and recording chronology.
`051` — Correction shall preserve an applicable reason.
`052` — Current RFC status projection shall incorporate accepted correction evidence.
`053` — A corrected current projection may differ from the original accepted source interpretation.
`054` — Historical views shall remain capable of explaining both the original evidence and its later correction.
`055` — Correction shall not fabricate a source observation that never occurred.
`056` — Ordinary RFC lifecycle progression shall not silently move the RFC backward to an earlier lifecycle interpretation.
`057` — A source observation that appears to regress accepted progression shall not be accepted automatically merely because it is newer.
`058` — Potential regression shall remain visible for governed review.
`059` — Ordinary import shall not silently erase later accepted lifecycle evidence.
`060` — Regression detection shall operate against accepted lifecycle/projection evidence rather than file order alone.
`061` — A newer workbook observation shall not automatically override a later-progressed accepted RFC state with an earlier state.
`062` — Source chronology and lifecycle progression shall remain separate dimensions.
`063` — Newer source evidence may legitimately require correction/review without being silently ignored or silently applied.
`064` — A `Cancelled` status observed after the RFC has reached Post-Implement context shall not be rejected categorically.
`065` — Post-Implement cancellation may represent valid source evidence.
`066` — SOMA shall preserve the possibility that provider lifecycle semantics permit such cancellation.
`067` — SOMA shall not “correct” the provider automatically back to Closed merely because cancellation appears unusual.
`068` — Post-Implement cancellation shall require high-risk review.
`069` — Review shall show the prior accepted RFC status/progression evidence.
`070` — Review shall show the new `Cancelled` source evidence.
`071` — Review shall show affected downstream consequences/proposals where applicable.
`072` — Post-Implement cancellation shall not silently mutate RFC lifecycle.
`073` — Rejection of the proposed correction shall preserve the prior current projection while retaining applicable reviewed source evidence/history.
`074` — Accepted `Closed` evidence shall be committed as terminal RFC evidence.
`075` — Accepted `Cancelled` evidence shall be committed as terminal RFC evidence.
`076` — Terminal evidence acceptance shall retain source provenance.
`077` — Terminal evidence acceptance shall retain applicable source chronology.
`078` — Terminal evidence acceptance shall create the required application audit.
`079` — Accepted terminal RFC evidence may imply downstream local consequences.
`080` — Such consequences shall not execute silently as an incidental side effect of merely parsing the workbook.
`081` — Such consequences shall be represented through a pending cascade proposal.
`082` — The exact affected cascade membership remains governed by RFC hierarchy/WFM lifecycle authorities.
`083` — Accepted terminal RFC evidence and its required pending cascade proposal shall commit atomically.
`084` — Terminal evidence shall not commit successfully while a required cascade proposal is lost.
`085` — Cascade-proposal persistence failure shall roll back the uncommitted terminal-evidence acceptance.
`086` — Terminal-evidence failure shall prevent creation of a successful pending cascade proposal.
`087` — The transaction shall preserve exact linkage between terminal evidence and its pending cascade proposal.
`088` — Creating the pending cascade proposal shall not itself execute the cascade.
`089` — Pending proposal shall remain non-authoritative with respect to proposed downstream lifecycle mutations.
`090` — Existing downstream entities shall remain in their current accepted states until cascade confirmation.
`091` — Proposal preview shall not count as confirmation.
`092` — Merely opening the cascade review shall not execute it.
`093` — Local RFC terminal cascade shall require explicit operator confirmation.
`094` — The confirmation shall use the applicable deliberate-hold pattern.
`095` — The deliberate hold shall be intentional and cancellable before completion.
`096` — Releasing/cancelling before completion shall execute no cascade mutation.
`097` — Cascade confirmation shall be separate from merely accepting the source observation when the workflow exposes those as separate review steps.
`098` — Confirmation shall revalidate the pending proposal before commit.
`099` — Until confirmed, the cascade shall remain pending.
`100` — A pending cascade shall remain visibly distinguishable from completed downstream mutation.
`101` — Restart/reload behavior for pending cascade shall preserve its governed durable review state where the cascade contract requires it.
`102` — A stale pending proposal shall not execute without revalidation.
`103` — Unrecognized RFC status shall produce a warning.
`104` — Unknown status shall preserve the observed source value/provenance as permitted by the import contract.
`105` — Unknown status shall not gain recognized lifecycle meaning.
`106` — Unknown status shall not close an RFC.
`107` — Unknown status shall not cancel an RFC.
`108` — Unknown status shall not archive an RFC.
`109` — Unknown status shall not create terminal cascade authority.
`110` — Unknown status shall not unlink relationships.
`111` — Unknown status shall leave destructive lifecycle state unchanged unless another accepted authority independently requires change.
`112` — Source uncertainty shall not be resolved through a guessed nearest status.
`113` — Later recognized evidence may update the same RFC identity through normal import review.
`114` — UI shall distinguish recognized terminal `Closed` from recognized terminal `Cancelled`.
`115` — UI shall distinguish unknown status from terminal status.
`116` — UI shall identify pending cascade consequences separately from already executed consequences.
`117` — High-risk correction shall be clearly distinguishable from ordinary status progression.
`118` — History shall explain original evidence, correction evidence, and cascade decision separately.
`119` — Tests shall prove status recognition is case-insensitive but closed rather than fuzzy.
`120` — Tests shall prove `Closed` and `Cancelled` are both terminal but retain distinct evidence.
`121` — Tests shall prove ordinary progression cannot silently regress and Post-Implement cancellation requires high-risk review rather than categorical rejection.
`122` — Tests shall prove projection correction targets exact evidence and appends history rather than overwriting.
`123` — Failure injection shall prove terminal evidence and its pending cascade proposal commit atomically while the cascade itself remains unexecuted before confirmation.
`124` — Tests shall prove unknown status only warns and cannot trigger terminal, archive, unlink, or cascade mutations.

## `BETA-REQ-0150` — prefix `RFC-WFM-ELIG`

**Governing obligation:** Only an RFC whose accepted lifecycle projection is Implement-eligible may ordinarily own active nonterminal WFM work; WFM source evidence may bootstrap a missing exact-identity provisional RFC and support separately reviewed provisional eligibility, but that inference shall remain subordinate to accepted Enhanced RFC evidence and shall never silently override a pre-Implement RFC state, while `Complete` and `Plan Cancel` WFM rows remain historical evidence that may create or adopt their exact WFM identities without promoting, reactivating, or creating active Objective work for the RFC, and WFM evidence shall never fabricate a Service Request, with any SR relationship arising only as a reviewed candidate against an already-existing SR under its owning linkage contract.

`001` — Active nonterminal WFM work shall belong only to an RFC currently eligible for implementation work.
`002` — RFC eligibility for active WFM work shall derive from the governing RFC lifecycle contract.
`003` — A pre-Implement RFC shall not ordinarily own active nonterminal WFM work.
`004` — A terminal RFC shall not ordinarily own newly active WFM work unless a separately governed correction/reversal changes its lifecycle authority.
`005` — WFM ownership shall not redefine RFC eligibility independently.
`006` — The set of RFC states considered Implement-eligible shall be explicitly governed by the RFC lifecycle vocabulary.
`007` — Normalization shall not invent additional eligible states.
`008` — Eligibility shall be determined from accepted RFC evidence/projection, not from descriptive labels alone.
`009` — Active nonterminal WFM evidence shall remain distinct from historical WFM evidence.
`010` — A WFM in `Complete` state shall be historical.
`011` — A WFM in `Plan Cancel` state shall be cancelled historical evidence.
`012` — Historical WFM evidence shall not be treated as currently executable work.
`013` — Historical WFM evidence shall remain queryable and retain provenance.
`014` — WFM evidence may bootstrap a missing RFC when the WFM contains a usable canonical RFC identity.
`015` — The bootstrapped RFC shall be provisional.
`016` — Provisional RFC creation shall preserve that its origin is WFM evidence rather than Enhanced RFC evidence.
`017` — Bootstrap shall preserve immutable SOMA RFC identity.
`018` — Bootstrap shall not pretend the RFC was imported from Enhanced RFC source.
`019` — WFM bootstrap shall require a usable canonical RFC identifier.
`020` — Similar RFC Summary text shall not bootstrap RFC identity.
`021` — Similar Task Name text shall not bootstrap RFC identity.
`022` — Malformed RFC identifiers shall not bootstrap an RFC.
`023` — A WFM-bootstrapped RFC shall remain visibly provisional until stronger RFC-source evidence is accepted or the owning review process resolves it.
`024` — Missing Enhanced RFC details shall remain unknown rather than fabricated from WFM fields.
`025` — Provisional RFC shall not gain source-owned RFC fields from guesses.
`026` — Later exact Enhanced RFC evidence shall adopt/enrich the same RFC identity under `0148`.
`027` — WFM evidence may support a proposal that the provisional RFC is Implement-eligible.
`028` — Provisional eligibility shall require review.
`029` — Provisional eligibility shall remain distinguishable from accepted Enhanced RFC lifecycle evidence.
`030` — WFM evidence shall not silently mark a provisional RFC Implement-eligible.
`031` — Review shall expose the WFM evidence supporting the provisional eligibility.
`032` — Rejection shall preserve the provisional RFC without accepting the proposed eligibility.
`033` — Active nonterminal WFM work under a bootstrapped RFC may be accepted only after the required provisional eligibility review succeeds.
`034` — The WFM shall remain linked to the bootstrapped RFC identity.
`035` — This provisional path shall not be represented as stronger Enhanced RFC lifecycle evidence.
`036` — Accepted Enhanced RFC lifecycle evidence shall outrank WFM-derived provisional RFC eligibility.
`037` — A WFM-derived provisional eligibility state shall not override accepted Enhanced RFC evidence.
`038` — If accepted Enhanced RFC evidence shows a pre-Implement state, active WFM evidence shall produce a conflict/review condition rather than silently promote the RFC.
`039` — WFM evidence shall not rewrite the accepted RFC status projection merely because active WFM work exists.
`040` — Source authority shall remain explicit in the conflict.
`041` — A pre-Implement RFC with newly observed active nonterminal WFM evidence shall be treated as inconsistent source evidence requiring review.
`042` — The RFC shall not silently transition to Implement.
`043` — The WFM shall not silently disappear merely because the RFC is pre-Implement.
`044` — Review shall expose both accepted RFC evidence and WFM evidence.
`045` — Resolution shall follow the governing correction/import authority rather than heuristic precedence beyond what is already approved.
`046` — Presence of a WFM shall not itself promote an RFC.
`047` — Active WFM Task Name shall not itself promote an RFC.
`048` — Planned WFM interval shall not itself promote an RFC.
`049` — WFM source chronology shall not itself promote an RFC.
`050` — The existence of multiple WFMs shall not by itself promote an RFC.
`051` — A `Complete` WFM row shall be treated as historical evidence.
`052` — `Complete` shall not promote a missing/provisional RFC to Implement-eligible.
`053` — `Complete` shall not reactivate a terminal RFC.
`054` — `Complete` shall not create active Objective work by itself.
`055` — `Complete` may create/adopt the exact historical WFM identity under its owning WFM import rules.
`056` — A `Plan Cancel` WFM row shall be treated as cancelled historical evidence.
`057` — `Plan Cancel` shall not promote a missing/provisional RFC to Implement-eligible.
`058` — `Plan Cancel` shall not reactivate a terminal RFC.
`059` — `Plan Cancel` shall not create active Objective work by itself.
`060` — `Plan Cancel` may create/adopt the exact historical WFM identity under its owning WFM rules.
`061` — Historical WFM existence shall not be interpreted as evidence that the RFC is currently Implement-eligible.
`062` — Historical WFM count shall not drive current RFC lifecycle promotion.
`063` — Reappearance of a historical WFM shall not reactivate the RFC automatically.
`064` — Later exact Enhanced RFC evidence shall reconcile to the existing provisional RFC identity.
`065` — Adoption shall preserve the RFC's internal identity and existing WFM relationships.
`066` — Accepted Enhanced RFC source-owned facts shall supersede conflicting provisional WFM-derived facts through review.
`067` — Prior provisional evidence shall remain historically visible.
`068` — A previously accepted provisional eligibility decision may later conflict with stronger Enhanced RFC evidence.
`069` — That conflict shall be handled through correction/review rather than silently rewriting prior history.
`070` — The prior provisional decision shall remain auditable.
`071` — Current projection may change after accepted correction while preserving original WFM bootstrap evidence.
`072` — WFM evidence shall never create a Service Request.
`073` — An SR-looking value in WFM Task Name shall not directly create an SR.
`074` — An SR-looking value in WFM descriptive fields shall not directly create an SR.
`075` — WFM source evidence may only propose/link to an already-existing SR through the governed SR-link extraction/review contract.
`076` — A WFM's owning RFC shall not imply an SR exists.
`077` — An RFC with no accepted SR link may still own WFM work where otherwise valid.
`078` — Missing SR relationship shall remain missing rather than fabricated.
`079` — WFM bootstrap of an RFC shall not bootstrap an SR alongside it.
`080` — WFM evidence shall not establish a direct authoritative WFM-to-SR lifecycle relationship outside the accepted RFC/SR/Task relationship model.
`081` — Any candidate SR relation extracted from WFM content shall remain a proposal until reviewed.
`082` — Accepted SR relation shall preserve its governing master-RFC semantics.
`083` — UI shall distinguish provisional RFCs bootstrapped from WFM evidence.
`084` — UI shall distinguish reviewed provisional eligibility from Enhanced RFC-confirmed eligibility.
`085` — UI shall distinguish active nonterminal WFM from `Complete` history.
`086` — UI shall distinguish active nonterminal WFM from `Plan Cancel` history.
`087` — A conflict between accepted pre-Implement RFC evidence and active WFM evidence shall be visible.
`088` — WFM import staging shall detect eligibility conflicts before authoritative mutation.
`089` — Eligibility conflict shall not be resolved merely by accepting the workbook wholesale.
`090` — Review acceptance shall preserve source provenance for both RFC and WFM evidence.
`091` — Rejected provisional eligibility shall not delete the underlying WFM observation.
`092` — Provisional RFC bootstrap shall produce applicable audit/provenance evidence.
`093` — Acceptance/rejection of provisional eligibility shall remain historically explainable.
`094` — Later Enhanced RFC adoption/correction shall preserve prior bootstrap and review chronology.
`095` — Tests shall prove WFM evidence can bootstrap a missing provisional RFC and reviewed provisional eligibility, but cannot override accepted pre-Implement Enhanced RFC evidence or use `Complete`/`Plan Cancel` to promote/reactivate an RFC.
`096` — Tests shall prove WFM evidence never creates an SR and any SR-link candidate remains review-only against an already-existing SR.

## `BETA-REQ-0151` — prefix `SR-LINK-CAND`

**Governing obligation:** SOMA shall perform bounded extraction of potential Service Request relationships from RFC Summary as the primary source and WFM Task Name as the secondary source, treating exact labelled `SR` or `TT` plus eight digits as strong evidence and isolated unlabelled eight-digit tokens as lower-confidence evidence while excluding dates and substrings of longer identifiers; every candidate shall normalize to an existing canonical SR identity only, never create an SR, and remain non-authoritative until explicit review, multiple candidates may be independently accepted without duplicate links, evidence originating from a subordinate RFC or its WFM shall propose linkage to the governing master RFC while retaining source provenance, and later source-text or workbook omission shall never unlink an accepted historical relationship.

`001` — SOMA may extract potential Service Request linkage evidence from governed RFC/WFM descriptive source fields.
`002` — Extracted values shall be SR-link candidates only.
`003` — Candidate extraction shall not itself create an SR↔RFC relationship.
`004` — Candidate extraction shall not itself create a Service Request.
`005` — Candidate extraction shall not constitute accepted lifecycle evidence.
`006` — Candidate extraction shall remain non-authoritative until explicit review acceptance.
`007` — Candidate extraction shall be bounded.
`008` — Extraction shall not scan unrestricted external content beyond the explicitly governed source fields for this capability.
`009` — Extraction shall not recursively search arbitrary linked files or message bodies merely to find additional SR-like numbers.
`010` — Extraction shall apply bounded text length/work limits defined by implementation while preserving complete evaluation of the governed field content within accepted source limits.
`011` — Extraction shall not create unbounded candidate counts from pathological source text.
`012` — Exact parser/resource bounds remain LLD controls unless otherwise approved.
`013` — RFC Summary shall be the first descriptive field considered for SR-link candidate extraction.
`014` — RFC Summary candidates shall preserve provenance identifying RFC Summary as their source.
`015` — Candidate location/context within the Summary may be retained in bounded form where useful for review.
`016` — RFC Summary text shall remain descriptive source evidence rather than SR identity authority.
`017` — WFM Task Name shall be the second governed descriptive source for SR-link candidate extraction.
`018` — WFM Task Name candidates shall preserve provenance identifying Task Name as their source.
`019` — WFM Task Name extraction shall not supersede valid RFC Summary evidence merely because the WFM observation is newer.
`020` — WFM Task Name remains lower source priority than RFC Summary for this candidate-extraction workflow.
`021` — Candidate extraction shall evaluate RFC Summary before WFM Task Name when both are available.
`022` — Source priority shall affect evidence ranking/review presentation rather than silently discard distinct valid candidates.
`023` — A candidate found in both fields shall be deduplicated by canonical SR identity while retaining both provenance references where useful.
`024` — Conflicting candidates across Summary and Task Name shall remain independently reviewable.
`025` — A recognized `SR` label followed by exactly eight digits shall constitute strong SR-link candidate evidence.
`026` — Label matching shall follow the governed case/spacing normalization rules.
`027` — Strong evidence shall preserve the canonical eight-digit SR identity separately from the observed label.
`028` — The observed `SR` label shall not become part of the immutable underlying SR identity.
`029` — A recognized `TT` label followed by exactly eight digits shall constitute strong SR-link candidate evidence.
`030` — `TT 12345678` and `SR 12345678` may refer to the same canonical eight-digit Service Request identity where the SR identity contract governs that mapping.
`031` — The observed `TT` label shall remain source/presentation evidence rather than a separate SR entity type.
`032` — Strong labelled TT evidence still requires relationship review.
`033` — Strong labelled candidate syntax shall contain exactly eight digits.
`034` — Seven-digit values shall not satisfy the Service Request candidate grammar.
`035` — Nine-or-more-digit values shall not satisfy the Service Request candidate grammar.
`036` — Candidate extraction shall not pad or truncate digit strings into eight-digit SR identities.
`037` — An isolated unlabelled eight-digit value may constitute lower-confidence SR-link candidate evidence.
`038` — Unlabelled eight-digit evidence shall be clearly distinguishable from labelled strong evidence.
`039` — Lower-confidence evidence shall require review before relationship creation.
`040` — Lower-confidence evidence shall not be silently upgraded to strong evidence merely because an existing SR happens to share that number.
`041` — An unlabelled eight-digit value shall qualify only when text boundaries establish it as an isolated numeric token under the governed parser.
`042` — Digits embedded within a longer numeric sequence shall not qualify.
`043` — Digits embedded inside a longer alphanumeric identifier shall not qualify merely because an eight-digit substring exists.
`044` — Candidate tokenization shall be deterministic.
`045` — Values recognizable as dates under the governed exclusion rules shall not become SR-link candidates solely because they contain eight digits.
`046` — Compact date forms such as `YYYYMMDD` shall be excluded where they are valid date representations.
`047` — Date-like values shall not be converted into SR identities merely because a matching SR exists.
`048` — Date exclusion shall apply especially to lower-confidence unlabelled candidates.
`049` — A strongly labelled exact `SR`/`TT` eight-digit token remains governed by the explicit labelled grammar rather than by an unrelated date interpretation.
`050` — An eight-digit substring of a longer numeric identifier shall not become a candidate.
`051` — An eight-digit substring inside an RFC `NC` identifier shall not become a candidate.
`052` — An eight-digit substring inside a WFM `TK` identifier shall not become a candidate.
`053` — An eight-digit substring inside another provider/internal identifier shall not become a candidate without valid token boundaries.
`054` — The parser shall not search sliding eight-digit windows through longer values.
`055` — Each valid extracted candidate shall normalize to the canonical eight-digit Service Request identity.
`056` — Candidate deduplication shall use canonical SR identity.
`057` — Candidate identity shall remain independent from observed `SR` versus `TT` label.
`058` — Candidate provenance shall preserve the observed source form where useful for review.
`059` — Extracted candidates shall resolve only against existing SOMA Service Request identities.
`060` — A matching existing external SR may become an eligible relationship target.
`061` — A candidate with no existing SR match shall remain unresolved candidate evidence.
`062` — Unresolved candidate evidence shall not create a new Service Request.
`063` — Candidate parsing shall not bootstrap an SR.
`064` — WFM evidence shall therefore remain consistent with `0150`'s prohibition on fabricating SRs.
`065` — An extracted external eight-digit SR candidate shall not silently target a local `LSR-########` merely because the numeric portion resembles it.
`066` — External and local Service Request identifier namespaces shall remain distinct.
`067` — Every candidate relationship shall require explicit review before acceptance.
`068` — Strong evidence shall still require review.
`069` — Lower-confidence evidence shall require review.
`070` — Review shall show the candidate SR identity.
`071` — Review shall show whether the SR currently exists.
`072` — Review shall show evidence source such as RFC Summary or WFM Task Name.
`073` — Review shall show applicable evidence strength.
`074` — Review shall identify the RFC relationship target that would actually be created.
`075` — Merely displaying a candidate shall not create a relationship.
`076` — Highlighting/selecting a candidate shall not create a relationship.
`077` — Rejecting a candidate shall leave SR/RFC relationships unchanged.
`078` — Acceptance shall use the ordinary governed relationship mutation/audit contract.
`079` — One RFC/WFM evidence scope may yield multiple distinct candidate SR identities.
`080` — Multiple valid existing SR candidates may be independently reviewed.
`081` — Multiple candidates may be accepted where the owning SR↔RFC relationship contract permits them.
`082` — Acceptance of one candidate shall not silently accept all others.
`083` — Rejection of one candidate shall not automatically reject another distinct candidate.
`084` — Duplicate occurrences of the same candidate shall not create duplicate relationships.
`085` — Acceptance of an already-existing exact SR↔RFC relationship shall be a governed no-op rather than a duplicate relationship.
`086` — Repeated import/candidate extraction shall not duplicate accepted links.
`087` — Candidate evidence may accumulate provenance without multiplying the same canonical relationship.
`088` — Candidate evidence originating from a subordinate RFC shall target its governing master RFC for SR linkage.
`089` — Candidate evidence originating from a WFM owned by a subordinate RFC shall target that subordinate's governing master RFC.
`090` — The source subordinate RFC identity shall remain preserved as provenance explaining where the candidate evidence came from.
`091` — SOMA shall not create a competing direct SR↔subordinate relationship when the accepted hierarchy contract requires master targeting.
`092` — Master-target resolution shall use the current accepted RFC hierarchy and shall be revalidated before relationship commit.
`093` — Evidence originating from a standalone/root RFC shall target that RFC itself.
`094` — Evidence originating directly from a master RFC shall target that master RFC.
`095` — Later hierarchy correction may change current target interpretation only through the governed relationship-correction model while preserving original candidate provenance.
`096` — Later omission of the SR-like token from RFC Summary shall not remove an accepted SR↔RFC relationship.
`097` — Later omission of the SR-like token from WFM Task Name shall not remove an accepted SR↔RFC relationship.
`098` — Later workbook omission of the entire RFC/WFM shall not remove an accepted SR↔RFC relationship.
`099` — Accepted relationship removal shall require a separate reasoned relationship-correction workflow.
`100` — Relationship correction shall preserve historical evidence that the link previously existed.
`101` — Accepted candidate evidence shall preserve bounded provenance sufficient to explain why the relationship was proposed.
`102` — Rejected candidate evidence may retain a minimized fingerprint/review result where the owning proposal contract requires suppression of repeated identical proposals.
`103` — Candidate provenance shall not duplicate unrestricted RFC/WFM text into audit payloads.
`104` — Tests shall prove RFC Summary is evaluated before WFM Task Name, labelled `SR`/`TT` eight-digit forms rank as strong evidence, and isolated unlabelled eight-digit forms remain lower confidence.
`105` — Tests shall prove dates and eight-digit substrings of longer identifiers are excluded, unresolved candidates never create SRs, multiple candidates may be independently accepted, and all relationships remain review-gated.
`106` — Tests shall prove subordinate-origin evidence links the master RFC, repeated extraction remains idempotent, and later text/workbook omission never unlinks accepted relationship history.

## `BETA-REQ-0152` — prefix `RFC-FOREST`

**Governing obligation:** RFC hierarchy shall be an acyclic one-parent forest of at most two RFC levels in which every parentless RFC is a root, roots with no children are standalone, roots with children derive Master role from those relationships, and child RFCs derive Subordinate role and can never themselves parent another RFC; resolved members of a branch shall share canonical Customer Organization identity while unresolved ownership remains an explicit warning, provider/import evidence shall never infer hierarchy, every hierarchy mutation shall revalidate depth, cycles, parent uniqueness, and applicable Customer consistency, reparenting after WFM history shall be a high-risk history-preserving correction, no arbitrary business cap such as twenty subordinates shall restrict valid branches because scale is handled through virtualization and measured technical limits, and hard deletion shall be permitted only while the RFC remains provably an untouched manual draft under the governing identity, provenance, relationship, WFM, and audit contracts.

`001` — RFC hierarchy shall form a forest.
`002` — The hierarchy may contain zero or more independent root RFCs.
`003` — Each hierarchy component shall contain exactly one root.
`004` — An RFC shall belong to at most one hierarchy component at a time.
`005` — Hierarchy shall be represented through explicit RFC-to-RFC relationships.
`006` — RFC hierarchy shall be acyclic.
`007` — An RFC shall never be its own parent.
`008` — An RFC shall never be its own descendant.
`009` — Relationship creation shall reject any edge that would introduce a cycle.
`010` — Relationship correction/reparenting shall revalidate acyclicity before commit.
`011` — Imported or manually proposed relationships shall not bypass cycle validation.
`012` — RFC hierarchy shall have a maximum depth of two RFC levels.
`013` — A root RFC may own direct subordinate RFCs.
`014` — A subordinate RFC shall not own another subordinate RFC.
`015` — A subordinate RFC shall therefore never simultaneously serve as a master.
`016` — A third RFC hierarchy level shall be rejected.
`017` — Arbitrary-depth RFC trees shall not be supported in Beta 1.0.
`018` — A subordinate RFC shall have exactly one parent root RFC.
`019` — An RFC shall not be subordinate to multiple masters simultaneously.
`020` — Attempting to add a second parent shall require reparenting rather than creating multiple parent relationships.
`021` — Parent uniqueness shall be enforced structurally rather than by UI convention alone.
`022` — An RFC with no parent is a root RFC.
`023` — Every standalone RFC is therefore a root.
`024` — A root may have zero subordinate RFCs.
`025` — A root with zero subordinates is standalone.
`026` — A root with one or more subordinates is a master RFC.
`027` — Master role shall derive from accepted child relationships.
`028` — SOMA shall not require an independently editable `is_master` business flag.
`029` — Adding the first accepted subordinate shall cause the root to project as Master.
`030` — Removing/reparenting the final subordinate may cause the root to project as standalone.
`031` — Master presentation shall therefore be a projection of hierarchy truth.
`032` — Subordinate role shall derive from the existence of an accepted parent relationship.
`033` — SOMA shall not require an independently editable `is_subordinate` business flag.
`034` — Removing an RFC's parent through a valid correction shall cause it to become a root.
`035` — A former subordinate with no children becomes standalone unless subsequently given children through a valid root-level hierarchy operation.
`036` — Role projection shall always follow the accepted current relationship graph.
`037` — An RFC shall never be both subordinate and master simultaneously.
`038` — An RFC shall never be both subordinate and standalone simultaneously.
`039` — Root, Master, and Subordinate presentation shall remain mutually coherent with the relationship graph.
`040` — Recomputed roles shall not create lifecycle or audit events merely because a projection refreshed.
`041` — Hierarchy role shall remain distinct from RFC lifecycle status.
`042` — Becoming Master shall not itself progress RFC lifecycle.
`043` — Becoming subordinate shall not itself progress RFC lifecycle.
`044` — Terminal status shall not erase the hierarchy relationship automatically.
`045` — Historical hierarchy shall remain explainable after terminal status.
`046` — Resolved members of one RFC hierarchy branch shall share the same Customer Organization.
`047` — A resolved root RFC and each resolved subordinate shall belong to the same Customer Organization.
`048` — A subordinate with a definitively different Customer Organization from its proposed root shall conflict.
`049` — Relationship acceptance shall revalidate known Customer Organization consistency.
`050` — Reparenting shall revalidate known Customer Organization consistency.
`051` — Customer consistency shall use canonical Customer Organization identity rather than display-name equality alone.
`052` — Two organizations with similar names shall not be treated as the same Customer merely to permit hierarchy.
`053` — Customer rename shall not invalidate hierarchy when immutable organization identity remains unchanged.
`054` — An RFC whose Customer Organization is not yet resolved may participate only according to the governed unresolved-ownership workflow.
`055` — Missing Customer ownership shall remain unknown rather than being copied from descriptive similarity.
`056` — Unresolved branch ownership shall produce a warning.
`057` — The warning shall identify that Customer consistency cannot yet be proven.
`058` — Unresolved ownership shall not be silently treated as matching.
`059` — Later accepted Customer resolution shall revalidate branch consistency.
`060` — A known Customer mismatch shall remain distinguishable from unresolved Customer ownership.
`061` — Known mismatch shall not be downgraded to a mere uncertainty warning.
`062` — A hierarchy mutation that would violate known Customer consistency shall not commit through the ordinary valid path.
`063` — RFC provider/source observations shall not infer Master/Subordinate relationships merely from workbook ordering.
`064` — WFM provider/source observations shall not infer RFC hierarchy.
`065` — Similar RFC Summary text shall not infer hierarchy.
`066` — Similar Task Name text shall not infer hierarchy.
`067` — Shared SR candidate references shall not infer hierarchy.
`068` — Shared Customer Organization shall not infer hierarchy.
`069` — Similar maintenance windows shall not infer hierarchy.
`070` — Provider row adjacency shall not infer hierarchy.
`071` — Import normalization shall not manufacture hierarchy relationships absent accepted hierarchy authority.
`072` — Importing a WFM under an RFC shall establish Task ownership only and shall not infer whether that RFC is subordinate.
`073` — A provider/source field shall gain hierarchy authority only if a future accepted requirement explicitly grants it.
`074` — Until then, hierarchy remains an explicitly governed SOMA relationship.
`075` — Hierarchy creation shall occur through an explicit governed relationship operation.
`076` — The operator shall be able to review the proposed parent and subordinate identities before acceptance.
`077` — Relationship acceptance shall validate depth, parent uniqueness, acyclicity, and Customer consistency.
`078` — Accepted hierarchy mutation shall create applicable audit/history evidence.
`079` — Reparenting shall mean changing an RFC from one root parent to another.
`080` — Reparenting shall preserve the subordinate RFC's immutable internal identity.
`081` — Reparenting shall preserve the subordinate RFC's historical evidence.
`082` — Reparenting shall not delete and recreate the RFC.
`083` — Reparenting shall validate the target root as eligible under the two-level forest invariant.
`084` — Reparenting before consequential WFM history exists shall still follow the ordinary reviewed relationship-correction contract.
`085` — Such correction shall preserve previous hierarchy evidence where already accepted.
`086` — Lack of WFM history shall not authorize invalid depth, cycles, or Customer mismatch.
`087` — Reparenting an RFC after WFM history exists shall be classified as a high-risk correction.
`088` — High-risk reparenting shall explicitly identify the current root.
`089` — High-risk reparenting shall explicitly identify the proposed new root.
`090` — High-risk reparenting shall expose relevant WFM history affected by the interpretation change.
`091` — High-risk reparenting shall expose relevant SR/master relationship consequences where applicable.
`092` — Reparenting shall not rewrite historical WFM ownership as though the new hierarchy always existed.
`093` — The original hierarchy/WFM context shall remain historically explainable.
`094` — Reparenting shall revalidate current parent identity immediately before commit.
`095` — Reparenting shall revalidate target-root status.
`096` — Reparenting shall revalidate acyclicity.
`097` — Reparenting shall revalidate two-level depth.
`098` — Reparenting shall revalidate Customer Organization consistency where resolved.
`099` — A stale reparenting proposal shall not commit blindly.
`100` — SOMA shall not impose an arbitrary business rule limiting a Master RFC to twenty subordinate RFCs.
`101` — The number `20` shall not be encoded as a product maximum for subordinates.
`102` — A Master RFC with more than twenty valid subordinates shall remain representable.
`103` — Import, UI, API, validation, and persistence layers shall not independently invent conflicting arbitrary subordinate caps.
`104` — Large subordinate collections shall remain semantically valid unless a separately approved product constraint exists.
`105` — UI shall use suitable virtualization/pagination/bounded rendering where necessary for large branches.
`106` — Search/autocomplete over large RFC branches shall remain bounded and responsive under applicable UX contracts.
`107` — Persistence/query design shall be measured for supported operational scale.
`108` — Genuine technical safety limits may exist only where justified by measured implementation constraints.
`109` — Technical limits shall not be misrepresented as a business rule such as “an RFC may have at most 20 children.”
`110` — Supported-scale limits shall be documented/tested when concrete LLD measurements establish them.
`111` — Hard deletion of an RFC shall be limited to an untouched manual draft.
`112` — A source-adopted/imported RFC shall not qualify as an untouched manual draft.
`113` — An RFC with accepted external provenance shall not qualify for hard deletion under this rule.
`114` — An RFC with accepted WFM history shall not qualify for hard deletion under this rule.
`115` — A terminal/historical operational RFC shall not qualify for hard deletion merely because it is no longer active.
`116` — Hard deletion shall not be used as an ordinary hierarchy-correction mechanism.
`117` — Hard-delete eligibility shall be revalidated at execution time.
`118` — Any accepted activity that causes the RFC to cease being an untouched manual draft shall remove hard-delete eligibility.
`119` — Exact exhaustive criteria defining “untouched” shall be made explicit in LLD consistent with all accepted identity, relationship, provenance, audit, WFM, and Draft authorities.
`120` — Failure to prove hard-delete eligibility shall deny hard deletion and require the appropriate correction/archive/history-preserving path instead.
`121` — Eligible hard deletion shall obey the minimized deletion-audit requirements established by `0135`, `0143`, and `0144`.
`122` — Hard deletion shall not leave a reconstructable full RFC tombstone in audit.
`123` — Tests shall prove the hierarchy remains an acyclic two-level one-parent forest with relationship-derived roles, same-Customer enforcement for resolved branch members, provider non-inference, and high-risk reparenting after WFM history.
`124` — Tests shall prove more than twenty subordinates remain semantically valid under supported technical scale and that hard deletion succeeds only for an RFC still proven to be an untouched manual draft.
