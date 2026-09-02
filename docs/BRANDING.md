# SOMA Beta Brand and UX Contract

SOMA Beta deliberately carries forward the approved SOMA identity. Migration of the canonical Alpha assets is a later, reviewed repository change; this document prevents accidental reinterpretation in the meantime.

## 1. Canonical identity

- **Mark:** irregular monoline stellated icosahedron / neural form.
- **Primary blue:** SOMA Blue `#0A33FF`.
- **Dark neutral:** SOMA Dark `#0F1115`.
- **Wordmark:** custom geometric SOMA lettering with the open triangular `A`.
- **Approved source assets:** `soma-mark.svg`, `soma-wordmark.svg`, `soma-lockup.svg`, `soma.ico`, and `soma-tray.ico`.

These assets must be selectively migrated from the approved historical source and compared visually; they must not be recreated from memory.

## 2. Placement

| Surface | Asset/use |
|---|---|
| Desktop header | Full SOMA lockup |
| Compact/mobile header | Mark |
| Browser favicon | Mark |
| Windows application icon | `soma.ico` |
| Windows tray | `soma-tray.ico`, including its light squircle treatment |
| Tray tooltip | `Soma` |

## 3. Prohibited transformations

Do not redraw, regenerate, rotate, recolor, glow, simplify, or symmetrize the mark. Do not substitute a generic geometric font for the wordmark. Do not use SOMA Blue as a generic semantic status color; brand identity and operational status must remain distinguishable.

## 4. Experience character

SOMA borrows from games where that language reduces cognitive load: clear objectives, visible progress, actionable warnings, nested missions/work, and consequences that are easy to trace. It must not become playful decoration, cyberpunk spectacle, or a gamified reward system.

The product should feel precise, calm, technical, and confidently local.

Its primary interface is terminal-inspired but proprietary: disciplined monospace accents, concise state notation, high information density, and keyboard fluency are paired with readable long-form content and modern responsive controls. vSphere contributes contextual hierarchy and modular entity summaries; Wireshark contributes list/detail/evidence inspection. Neither reference authorizes copied trade dress, assets, terminology, or pixels.

SOMA ships a small curated skin family rather than arbitrary themes. Each skin has complete Light and Dark modes plus accessibility-safe semantic behavior for high contrast and forced colors. Skins may vary aesthetic tokens but never domain meaning, layout, workflow, confirmation safety, or accessibility. System appearance selects Light or Dark inside the chosen skin.

## 5. 1.0.0 UX requirements

The complete normative interaction behavior is in the [UI/UX Interaction Contract](UI_UX_CONTRACT.md).

- Responsive layouts preserve every material fact, warning, action, pane, and workflow.
- Light, dark, high-contrast, forced-color, enlarged-text, and reduced-motion presentations retain equivalent meaning and operability.
- One semantic token system governs typography, status, focus, dialogs, motion, spacing, and component presentation.
- Curated built-in skins use that same semantic system; arbitrary CSS and imported themes are outside Beta 1.0.
- Keyboard, pointer, and touch are equivalent for supported primary workflows.
- Status and warnings use text and/or semantic icons in addition to color; repetitive blinking/flashing is prohibited.
- The shell uses restrained density, clear hierarchy, generous enough whitespace, progressive disclosure, contextual actions, and independent scrollable surfaces.
- The reviewed vSphere interface is directional inspiration for hierarchy and composition only. SOMA copies no VMware/Broadcom branding, icons, screenshots, trade dress, exact pixels, or proprietary product meaning.
- Three-second deliberate hold is an allowlisted confirmation tier with accessible progress. It is required for Device Reference promotion and may be assigned only to other consequential actions where it meaningfully interrupts mistakes.
- Overview metrics and attention items preserve filter/scope context and remain projections over accepted domain state.
- Windows tray behavior remains required.

Language switching is scheduled for 1.x.0.

Language switching is scheduled for 1.x.0.
