## Context

The share page (`/share/[id]`) is a public-facing report view with comments, charts, presence indicators, and diff comparison. It uses the app's class-based theme system (`.light` on layout div, `html.theme-light` for flash prevention) with light mode overrides in `app.css` lines 287-562.

The core bug: the sticky header uses Tailwind's `bg-navy-950/95` (opacity variant), which generates a different CSS class than `bg-navy-950`. The light mode overrides only target the base class, so the header stays dark navy in light mode.

Investigation revealed 20 total issues across theme support, design system usage, accessibility, responsive layout, and interaction bugs. The share page was built with hand-rolled Tailwind classes throughout, bypassing the design system utilities defined in `app.css`.

## Goals / Non-Goals

**Goals:**
- Fix all dark/light mode rendering issues on the share page and its components
- Align the share page with the app's design system (utility classes, heading conventions)
- Meet WCAG 2.1 AA for the share page (ARIA labels, contrast, keyboard navigation)
- Make the share page usable on mobile devices (comments, diff, top bar)
- Fix interaction bugs (clipboard, error feedback, polling efficiency)

**Non-Goals:**
- Redesigning the share page layout or information architecture
- Adding new features (sharing options, export formats, etc.)
- Changing the global theme system architecture (class-based approach stays)
- Backend API changes
- Fixing theme issues outside the share page and its components
- WCAG AAA compliance

## Decisions

### 1. Fix opacity variant via CSS override (not class restructuring)

**Decision:** Add a new CSS rule in `app.css` targeting the Tailwind-generated opacity variant class for `bg-navy-950/95` inside `.light`.

**Alternative considered:** Replace `bg-navy-950/95` with separate `bg-navy-950 bg-opacity-95` classes. Rejected because Tailwind 4 handles opacity differently and the CSS override is simpler, more targeted, and doesn't risk breaking the backdrop-blur visual.

**Implementation:** Add `.light .bg-navy-950\/95 { background-color: rgba(241, 245, 249, 0.95) !important; }` to the light mode section of `app.css`. This uses slate-50 at 95% opacity, matching the existing `.light .bg-navy-950` override but preserving the translucency for the sticky header's backdrop-blur effect.

### 2. Theme-aware ChartCard via reactive store subscription

**Decision:** Import `theme` store in ChartCard and use `$derived` to compute chart.js config colors. Destroy and recreate the chart instance when theme changes.

**Alternative considered:** CSS custom properties for chart colors. Rejected because Chart.js renders to `<canvas>` and doesn't read CSS variables — colors must be passed programmatically.

### 3. ReportDiff light mode via global CSS overrides

**Decision:** Add light mode overrides for `bg-red-900/30` and `bg-green-900/30` in `app.css` rather than making ReportDiff theme-aware in JS.

**Rationale:** ReportDiff injects classes via `{@html}` strings. Changing those strings to be theme-reactive would require significant refactoring. CSS overrides are simpler and consistent with how the rest of the light mode system works.

### 4. Mobile comments as slide-over drawer

**Decision:** On screens below `md` breakpoint, render the comments sidebar as a slide-over drawer triggered by the existing comments toggle button, instead of the inline `w-80` column.

**Alternative considered:** Accordion/collapsible below the report. Rejected because it pushes content down and the toggle button already exists, making a drawer the natural pattern.

### 5. Design system migration — incremental, same PR

**Decision:** Migrate all buttons and inputs to design system utilities in the same PR as the theme fixes. No functional changes, just class replacements.

**Rationale:** The hand-rolled classes and the design system classes produce similar (but not identical) visuals. Doing it in the same PR as theme fixes ensures we only need one round of visual QA.

### 6. Skip-to-content in root layout

**Decision:** Add a visually-hidden skip-to-content link as the first focusable element in `+layout.svelte`, targeting `#main-content`. Add `id="main-content"` to the main content area.

**Rationale:** This is a one-line addition to the layout that benefits all pages, not just the share page.

## Risks / Trade-offs

**[Risk] Chart recreation on theme toggle may flash** → Use Chart.js `update()` method instead of destroy/create when possible. If update doesn't cover all color properties, accept a brief flash since theme toggles are infrequent user actions.

**[Risk] CSS overrides for opacity variants may break if Tailwind 4 changes class naming** → Pin Tailwind version. The override is isolated to one rule and easy to update.

**[Risk] Mobile drawer for comments adds interaction complexity** → Keep it simple: slide from right, close on outside click and Escape. No animation library — use CSS transitions.

**[Risk] Design system class migration may subtly change visual appearance** → Verify each component visually in both light and dark mode. The design system classes were built to match the existing hand-rolled patterns, so differences should be minimal (mainly border-radius normalization).

**[Trade-off] Polling pause uses visibility API, not WebSocket** → Acceptable for now. WebSocket would eliminate polling entirely but is a larger architectural change outside scope.
