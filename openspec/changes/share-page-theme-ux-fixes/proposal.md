## Why

The share page (`/share/[id]`) has a critical styling bug: the sticky header does not respect the light/dark mode toggle because `bg-navy-950/95` (Tailwind opacity variant) is not covered by the light mode CSS overrides that only target `.light .bg-navy-950`. Users see a dark navy bar against a white page in light mode. Investigation revealed 20 additional issues across theme support, design system consistency, accessibility, responsive design, and interaction bugs — making this a good opportunity to bring the share page up to the quality bar of the rest of the application.

## What Changes

### Dark/Light Mode Fixes
- Fix sticky header `bg-navy-950/95` to respect light mode by adding opacity-variant override or restructuring the class
- Add light mode overrides for ReportDiff's `bg-red-900/30` and `bg-green-900/30` diff highlight colors
- Make ChartCard theme-aware by reading the theme store and computing chart.js colors dynamically
- Remove redundant `class:light` from share page root div (layout already provides it)

### Design System Alignment
- Migrate all hand-rolled button styles to `btn-gold`, `btn-secondary` utilities
- Migrate input/textarea styles to `input-field` utility in CommentThread
- Apply `card` utility to report container
- Use `text-gold` for the share page h1 heading to match app-wide heading convention

### Accessibility
- Add `aria-label` attributes to icon-only buttons (subscribe bell, copy link, comments toggle)
- Add skip-to-content link in root layout
- Fix contrast failures: upgrade `text-slate-600`/`text-slate-700` metadata to `text-slate-500` minimum
- Add `focus-within` support for presence avatar tooltips
- Add focus trap and Escape-to-close for reaction picker

### Responsive/Mobile
- Add mobile layout for comments sidebar (overlay/drawer pattern instead of inline `w-80`)
- Auto-select unified diff mode on mobile, hide side-by-side option below breakpoint
- Add overflow handling for top bar buttons on small screens

### Bug Fixes & Polish
- Fix copy link to only show "Copied!" on clipboard API success
- Add error feedback for fork/subscribe failures (replace empty catch blocks)
- Add confirmation dialog for comment deletion
- Pause comment polling and presence heartbeat when tab is backgrounded
- Remove duplicate footer (share page footer vs layout footer)

## Capabilities

### New Capabilities
- `share-page-theme-fixes`: Fix all dark/light mode issues on the share page including sticky header, ReportDiff, and ChartCard
- `share-page-design-system`: Migrate share page and CommentThread to use design system utility classes consistently
- `share-page-accessibility`: Address WCAG compliance gaps including ARIA labels, skip-to-content, contrast, keyboard navigation
- `share-page-responsive`: Add mobile-friendly layouts for comments sidebar, diff view, and top bar
- `share-page-bug-fixes`: Fix interaction bugs (clipboard, error handling, polling, duplicate footer)

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

**Files directly affected:**
- `frontend/src/routes/share/[id]/+page.svelte` — primary target, ~15 of 20 issues
- `frontend/src/lib/components/CommentThread.svelte` — design system migration, accessibility, delete confirmation
- `frontend/src/lib/components/ChartCard.svelte` — theme-aware chart colors
- `frontend/src/lib/components/ReportDiff.svelte` — light mode diff highlights
- `frontend/src/lib/components/PresenceAvatars.svelte` — keyboard-accessible tooltips
- `frontend/src/app.css` — new light mode overrides for opacity variants and diff colors
- `frontend/src/routes/+layout.svelte` — skip-to-content link, duplicate footer resolution

**No backend changes required.** No API changes. No new dependencies.
