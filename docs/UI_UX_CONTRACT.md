# SOMA Beta UI/UX Interaction Contract

Status: **Foundation review v0.1**  
Target: **SOMA Beta 1.0.0**  
Authority: accepted `BETA-REQ-0123` through `BETA-REQ-0130`, application-acceptance requirement `BETA-REQ-0139`, and decisions `D-097` through `D-104` plus `D-113`.

## 1. Purpose and authority

This contract governs the shared SOMA shell, selection/opening, scroll ownership, autocomplete, responsive presentation, deliberate confirmation, semantic tokens, dialogs, motion, UI working copies, dashboards, Inventory action surfaces, Overview/Infrastructure composition, fixture governance, and cross-input accessibility.

Domain contracts own business meaning and transition validity. This contract owns how those facts and commands are presented and operated. A component shall not invent a business transition, and a domain contract shall not bypass the shared interaction safeguards.

## 2. Navigation and interaction state

Every selection-based list, table, grid, tree, result set, queue, and workbench navigator distinguishes:

- keyboard focus;
- active row or node;
- single selected record;
- multi-selection membership where supported;
- expanded/collapsed state;
- opened record; and
- nested-control focus or activation.

One state shall not silently substitute for another.

A single primary click selects a row without opening it. Double-clicking that row or pressing `Enter` on its active/focused row opens the same default destination. Arrow keys navigate without opening. In multi-select views, arrows move the active row and `Space` controls membership according to the component contract. Nested checkboxes, links, menus, expanders, and actions perform their own behavior and do not additionally open the row.

Touch surfaces provide an explicit labelled Open action rather than depending on double-tap. Blank regions, headers, placeholders, disabled rows, and empty states never open a record.

Returning from detail preserves applicable query, filters, expansion, active/selected rows, scroll position, and focus when the result survives. Removed/stale results use a deterministic nearby or container-level fallback and explain the change.

## 3. Scroll ownership

Pointer wheel and trackpad input belongs to the nearest applicable scrollable surface beneath the pointer. A child resolves to its nearest scrollable ancestor. The owner may be a Ticket list, communication preview, tree, table, autocomplete, card region, dialog, drawer, editor, or activity surface.

Reaching the owner's scroll boundary shall not unexpectedly chain input into a sibling or underlying pane. If the pointed region has no applicable scroll surface, the next legitimate containing surface may own the input according to the LLD.

Keyboard scrolling belongs to the focused surface. Touch scrolling belongs to the gesture-origin surface after gesture disambiguation. Horizontal input belongs to the hovered/gesture-origin/focused horizontally scrollable surface.

Scrolling never changes selection, multi-selection membership, accepts a suggestion, opens a record, confirms a hold, or submits a command.

## 4. Autocomplete and bounded choosers

Searchable autocomplete begins only after deliberate input reaches its domain threshold. Focus alone never enumerates an unbounded population. A domain may provide an explicit disclosure that opens a bounded eligible set.

Loaded results and popup height are bounded. Continued filtering or governed incremental loading exposes more. The popup owns hovered scrolling and does not scroll the underlying pane at its boundary.

Each query has identity. New input cancels or supersedes prior work; stale results cannot replace or mix with current results. Loading, minimum-input, no-match, empty, partial, additional-results, stale, source-warning, and error states remain distinct.

`ArrowDown`/`ArrowUp` move the active option without acceptance; `Enter` accepts one eligible active option; `Escape` closes without change. `Tab` follows the shared form contract and never commits ambiguity. Pointer, touch, and keyboard produce the same domain result.

Typed text, a visual match, or highlighting never creates an entity/relationship. Missing-entity creation is a separate labelled domain command. Exceptional or ineligible results remain identified with text/non-color cues. The popup exposes combobox/listbox semantics and remains within the usable viewport.

## 5. Responsive composition and icon actions

Responsive behavior is based on available container/viewport space rather than named device assumptions. Reflow preserves capability, material facts, warnings, evidence, actions, validation, labels, order, and keyboard navigation.

Wide split workbenches retain operational and communication panes. Narrow layouts may use switchable panes, drawers, stacks, or overflow menus without losing either side or its state.

Comparison tables remain tabular inside bounded horizontal-scroll surfaces; the page does not overflow merely because the table is wide. Row identity, selection, warnings, and actions remain understandable during horizontal navigation.

Empty/loading/warning/error states center relative to their owning content region. Text, badges, dialogs, menus, autocomplete, actions, and impact previews remain viewport-safe under supported zoom and text enlargement.

Icon-only actions are used only where space or repeated high-frequency presentation makes visible text impractical. They require accessible name, focus, non-color state, supplemental pointer/focus tooltip, and a labelled touch/overflow presentation. A tooltip is never the only label.

Layout changes preserve active pane, filters, selection, scroll context, UI working copies, unsaved protection, and applicable focus.

## 6. Deliberate confirmation tiers

Confirmation friction is proportional to consequence:

| Tier | Use |
|---|---|
| Ordinary activation | Reversible, low-consequence actions |
| Deliberate hold | Simple consequential action where interruption prevents mistakes |
| Impact preview | Complex, dependent, bulk, destructive, or difficult-to-recover action |
| Impact preview plus hold | Only an allowlisted consequential action where both understanding and final deliberate commitment are needed |
| Domain-specific authority | Immutable/external effects requiring additional owning-domain rules |

A hold is not universal approval ritual. The LLD maintains an explicit action allowlist and rationale. Device Reference promotion always uses a deliberate hold. Other actions use it only through an accepted contract/registry entry.

A deliberate hold lasts one continuous three exact elapsed seconds measured by a monotonic source. Throughout the hold the control retains its action/consequence label and exposes visible plus semantic progress. Pointer, touch, and keyboard have equivalent behavior. Reduced motion retains textual/semantic progress.

Release, activation loss, cancellation, stale target, invalid dependency, route change, or movement classified as scrolling before completion resets without command. Completion triggers at most one command and immediately revalidates current state before commit. A hold animation never authorizes the action by itself.

Complex/destructive/bulk actions retain impact preview even when followed by a hold. The hold confirms the reviewed command; it does not replace target/consequence presentation.

## 7. Semantic tokens, typography, and status

One versioned token system separates primitive palette/type/spacing/radius/elevation/duration values from semantic meaning. Components use semantic tokens such as informational, selected, focused, pending review, provisional, incomplete, accepted, success, warning, action required, error, destructive, disabled, archived, historical, stale, and unknown.

SOMA's primary visual direction is a proprietary terminal-inspired operations interface—not a literal terminal emulator. It combines compact command-like cues and strong information density with vSphere-style contextual exploration, entity headers, predictable tabs, modular cards and activity surfaces, plus Wireshark-style list/detail/evidence inspection. Monospace typography is reserved for identifiers, statuses, timestamps, metrics, command cues, and shortcuts; readable sans-serif typography remains the default for email bodies, notes, dialogs, help, and other long-form content.

The operator may choose from a small governed set of built-in skins, including SOMA Core and terminal-inspired green, amber, and violet/pink families. Skin and appearance mode are independent axes: **System** follows the operating-system light/dark mode within the selected skin, while explicit Light and Dark select that skin's corresponding mode. Every skin supplies semantic tokens for Light, Dark, high-contrast, and forced-color behavior and previews immediately and reversibly as typed local preference.

A skin may change palette, approved typographic accents, border/radius/elevation treatment, restrained texture, and chart hues. It shall not change layout, information architecture, workflow, command availability or names, density, status/severity meaning, confirmation friction, accessibility, or acceptance logic. Beta 1.0 supports no arbitrary CSS or imported theme packages.

Light, dark, high-contrast, forced-color, enlarged-text, and zoomed presentation preserve equivalent meaning. Typography provides a readable hierarchy for workspace/entity titles, headings, body, controls, labels, tables, identifiers, metadata, evidence, and warnings.

State never depends solely on hue, saturation, motion, blinking, position, or one visual channel. Badges/warnings include concise text and may add icon, border, shape, or pattern. Selection, hover, active row, keyboard focus, checked membership, disabled, provisional, destructive, and historical states remain distinct.

Game-inspired language may strengthen objective, hierarchy, progress, readiness, and consequence awareness. It never replaces domain terms, trivializes risk, implies unsupported certainty, or represents decorative score as authoritative truth.

## 8. Focus, dialogs, and motion

Every operable element exposes visible, unclipped focus distinct from selection/hover. Focus order follows meaningful reading/action order and remains visible across scroll containers, sticky regions, and overlays.

A modal exposes accessible title, purpose, target, material consequence, validation/warnings, primary action, and cancellation/safe-exit behavior. Initial focus is safe and context-appropriate rather than automatically destructive. Focus remains within the modal, background interaction is suppressed, and close restores the invoker or deterministic fallback.

`Escape` closes a dismissible modal without acceptance. Dismissal is blocked only during a genuinely noninterruptible atomic stage or when an owning domain rule requires it, and the UI explains why. Long content scrolls internally using §3.

Repetitive blinking/flashing is prohibited. Motion has an identifiable purpose—continuity, hierarchy, progress, completion, escalation, or consequence—and is never the only information or an obstacle to work. Reduced-motion preference preserves final state, chronology, progress meaning, warnings, and operability.

## 9. UI working copies, save/discard, conflict, and Undo

An unsaved UI working copy is distinct from the last accepted revision and from a persistent domain entity whose accepted lifecycle state is Draft.

Modified fields/sections are identifiable. Save, selective save, discard, and selective discard disclose their scope. Partial save is allowed only as a complete valid transaction; otherwise the UI explains and includes/requests the required dependent scope. Discarding one scope preserves unrelated edits.

Validation/permission/stale/transaction failure preserves safe input, reports actionable errors, and never presents false success. Material edits do not silently autosave into accepted truth unless an owning contract approves the exact class.

Recoverable working copies remain inside the security envelope and identify target, base revision, chronology, and staleness. Restoration does not accept them. Navigation/reload/closure warns before abandonment; switching tabs, responsive panes, communication preview, or nested selectors in the same flow preserves them.

A working copy based on an older revision never overwrites newer truth. Conflict review distinguishes current, draft, affected relationships, and safely reapplicable changes; last-write-wins is prohibited for identity/evidence/lifecycle.

Undo exists only when the exact inverse is currently valid, bounded, and safe. It is action-scoped rather than one global latest-action slot: independent reversible actions may retain independent bounded Undo opportunities while their own inverses remain valid. It revalidates dependencies and explains the reversal; stale or unsafe inverses become unavailable with a reason. Warning acknowledgement changes presentation only and never changes the underlying fact. Accepted evidence/lifecycle uses owning correction, cancellation, supersession, replacement, resend, restoration, or other append-oriented command instead.

Unsaved values do not affect authoritative lists, counts, warnings, SLA, matching, availability, relationships, or reports.

## 10. Service Request and Overview summaries

SR list/dashboard/Overview/workbench/export summaries derive from owning domain state.

Customer filters use immutable Customer Organization identity, support all/specific/unassigned scope where applicable, remain visible, and apply consistently to rows, cards, counts, trends, warnings, empty states, and exports.

Communication summary derives received/sent/unknown direction, last independently supported interaction/age, proposals and coverage from canonical links. MSG drafts do not count. Terminal SR/RFC uses its frozen summary without body reconstruction.

Inventory summary derives Needs, allocations, requests, RMAs, physical units, Task outcomes, returns, Fault Tags, warehouse decisions, and resend/action-required positions. Mixed/partial state exposes constituent counts instead of false aggregate completion.

Objective/Maintenance Window context derives through Tasks and identifies applicable Task, Objective interval/state, and RFC/WFM context. No competing direct mutable SR-Objective relationship is created.

Individual duration, Contract Product Line cohort SLA, suspension, classification, missing chronology, and main-view presentation timing remain separate. Historical movement is not retention. `Resolved Status Date` is never imported, persisted, displayed, inferred, reconstructed, or replaced by another timestamp.

Summary scope, coverage, freshness, unknown, partial, and draft/proposal exclusion remain visible.

## 11. Inventory contextual and bulk actions

Inventory commands derive from accepted lifecycle projections and exact dependencies rather than editable labels. Manual commands, communication proposals, export, correction, replacement, resend, cancellation, archival, and eligible hard deletion remain distinct.

Predictable unavailable commands normally remain discoverable with blocker/remediation. A known-invalid command is not enabled merely to fail after activation.

Bulk selection exposes only supported command types. Preflight partitions each target into eligible, incompatible, stale, missing-input, and individual-review groups. No target is silently skipped/coerced. Preview identifies targets/effects/preservation. Execution follows the owning all-or-nothing or independent per-target contract. Batch and per-target identity/results survive correction.

Every supported transition keeps a manual path without communication/upload evidence. Proposal rejection does not remove it. Export never constitutes transition and external artifacts remain operator-managed.

Every valid nonterminal state exposes a next action or actionable blocker/remediation. Failures preserve actual state and safe retry/correction. False submission, material membership correction, warehouse rejection/resend, cancellation, archival, and deletion remain separate workflows.

## 12. Overview and Infrastructure composition

SOMA adopts a clean technical hierarchy:

- stable global shell and scoped alerts;
- contextual explorer where hierarchy helps;
- selected-entity header and truthful contextual actions;
- predictable tabs;
- restrained modular summary cards;
- progressive disclosure;
- independent scrollable panes; and
- collapsible activity surface for jobs, reviews, warnings, failures, and recent changes.

Overview composes Customer/period scope, Tickets, Objectives, Inventory, SLA/cohort health, Needs Attention, communication coverage, operational narrative, and recent processing/review activity.

Infrastructure composes a relationship-projection explorer, entity header, Summary/Placement/Components/IP/Relationships/History/Workbook Activity tabs as applicable, accepted-state cards, and workbook/review/job activity. The explorer never changes domain cardinality or creates competing ownership.

The reviewed vSphere interface is an approved directional reference for these patterns only. SOMA does not copy VMware/Broadcom branding, logos, icons, screenshots, proprietary assets, trade dress, exact pixels, product terminology, or operational meaning. SOMA improves on the reference with larger readable typography, labelled actions, responsive/touch behavior, clearer warnings, restrained density, and its proprietary game-informed identity.

Wireshark is likewise a directional reference only for high-volume selectable lists, explicit filters, synchronized detail/evidence panes, and inspectable field provenance. Terminal-inspired references guide hierarchy, concise notation, and keyboard fluency without turning operational data into unstructured command output. All third-party references remain subordinate to SOMA's contracts, identity, accessibility, and responsive behavior.

## 13. Reference and fixture classes

Every visual/artifact reference is classified:

| Class | Authority |
|---|---|
| Directional design reference | Hierarchy, composition, density, interaction inspiration only |
| Visual acceptance fixture | Versioned rendered-state acceptance/regression evidence |
| Export golden fixture | Versioned normalized artifact structure/content/rendering evidence |
| Historical screenshot/artifact | Non-normative unless explicitly reviewed and reclassified |

One class never silently gains another's authority.

A directional reference does not prescribe exact pixels, colors, typography, assets, terminology, domain behavior, or acceptance tolerance.

A visual fixture records identity/version, mapped requirement/use case, synthetic or irreversibly sanitized data, state, viewport/container, browser/platform, theme, zoom/text, time zone/deterministic clock, responsive breakpoint, expected interaction/focus, tolerance, provenance, owner, and approval chronology.

Responsive acceptance uses representative wide/intermediate/narrow fixtures rather than cropping/scaling one desktop baseline. Fixtures cover material panes, nested scroll, tables, dialogs, autocomplete, deliberate-hold states, empty/loading/warning/error/stale/destructive/historical/recovery, text enlargement, reduced motion, and keyboard focus.

## 14. Export goldens, sanitization, and regression governance

Export goldens identify versioned input, command/options, format/schema, expected sheets/sections/fields/order/styles/formulas/relationships/warnings/snapshots, deterministic chronology, and explicitly variable metadata.

Validation distinguishes structural correctness, normalized content, rendered usability, and raw serialization. Package artifacts such as `.xlsx` and `.msg` do not fail solely for safe permitted archive ordering, metadata, internal IDs, or timestamps. The harness masks only explicit allowlisted nondeterminism and still detects missing/altered/duplicated/reordered semantic content.

Repository fixtures contain no customer data, operational email, credentials, secrets, production IDs, private addresses, recoverable personal information, or third-party proprietary assets. Synthetic fixtures are preferred; sanitization is verified.

Fixture provenance/version/mapping/approval is retained. Baselines are not replaced merely to pass regressions. Normative contracts/accessibility/security prevail over conflicting fixtures; the fixture is corrected through controlled change. A required missing fixture blocks its acceptance case rather than authorizing a guess.

## 15. Complete state and accessibility matrix

Every applicable component/workflow defines and tests populated, empty, filtered-empty, loading, partial, stale, warning, error, disabled, locked, unsupported, conflict, draft, destructive, cancelled, success, historical, recovery, and unavailable-evidence states.

Supported states are operable through keyboard and applicable pointer/touch input, expose semantic labels/relationships/live feedback, visible focus, non-color meaning, logical reading order, and appropriate announcements without excessive noise.

No responsive, icon-only, tooltip, animation, hold, drag/gesture, virtualized, or nested-scroll implementation weakens the same action's consequence, accessibility, or domain validation.

## 16. Required use cases and acceptance evidence

Beta 1.0 acceptance includes at least:

1. click/select, double-click/Enter/open, arrows, multi-select, nested controls, return context;
2. hovered Ticket/email/table/dialog/autocomplete scrolling, boundary isolation, keyboard/touch ownership;
3. autocomplete query/disclosure, stale cancellation, states, explicit create;
4. wide/intermediate/narrow split panes, horizontal tables, viewport overlays, zoom/text;
5. Device promotion hold and every additional allowlisted hold across pointer/touch/keyboard, early release, scroll gesture, stale target, reduced motion, one-shot completion;
6. semantic themes, badges, focus, dialogs, dismissal, motion;
7. working-copy save/discard/recovery/navigation/conflict/Undo boundaries;
8. Customer/communication/Inventory/Objective/SLA/main-view summaries and Resolved Status Date exclusion;
9. Inventory contextual actions, mixed bulk preflight/results, manual/proposal/export/failure/continuation;
10. Overview and Infrastructure composition/activity panes;
11. directional/visual/export fixture classification, sanitization, provenance, baseline change; and
12. deterministic visual/export regression across the supported matrix.

The use-case catalogue, HLD, LLD, implementation, and automated/manual acceptance evidence shall trace each case to `BETA-REQ-0123`–`0130` and the cross-cutting acceptance rules in `BETA-REQ-0139` and Foundation Runtime Contract §10.

## 17. LLD responsibilities

LLD defines exact component state machines, event/gesture arbitration, scroll containment, focus restoration, keyboard mappings, touch targets, breakpoints/container queries, overlay positioning, autocomplete thresholds/debounce/cancellation/limits, token names/values/contrast, type scale, icon system, motion durations/easing, reduced-motion behavior, dialog primitives, draft storage/recovery duration, concurrency tokens/conflict diff, Undo allowlist, action/confirmation tier registry, monotonic hold implementation, responsive Overview/Infrastructure layouts, activity surfaces, fixture metadata/schema/tooling/tolerances, export normalization, supported rendering matrix, stable errors, tests, and telemetry-free local diagnostics. These details may not weaken this contract.
