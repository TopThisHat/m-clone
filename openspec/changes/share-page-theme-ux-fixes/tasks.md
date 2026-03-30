## 1. Dark/Light Mode Fixes (P0)

- [x] 1.1 Add `.light .bg-navy-950\/95` CSS override in `app.css` light mode section — set to `rgba(241, 245, 249, 0.95) !important`
- [x] 1.2 Add `.light .bg-red-900\/30` and `.light .bg-green-900\/30` CSS overrides in `app.css` for ReportDiff highlight colors
- [x] 1.3 Import `theme` store in `ChartCard.svelte` and use `$derived` to compute grid color, tick color based on theme
- [x] 1.4 Update ChartCard to call `chart.update()` reactively when theme-derived colors change
- [x] 1.5 Remove `class:light={$theme === 'light'}` from share page root div in `+page.svelte` (rely on layout's `.light`)
- [x] 1.6 Verify all theme fixes visually in both light and dark mode

## 2. Design System Alignment (P1)

- [x] 2.1 Replace hand-rolled button classes on share page action buttons (copy link, download PDF/MD/DOCX, fork) with `btn-secondary`
- [x] 2.2 Replace share page h1 `text-slate-100` with `text-gold` for brand heading consistency
- [x] 2.3 Apply `card` utility class to the report content container div
- [x] 2.4 Migrate CommentThread submit button and inline action buttons to `btn-gold` / `btn-secondary`
- [x] 2.5 Migrate CommentThread textareas (compose and edit) to `input-field` utility
- [x] 2.6 Normalize border-radius: ensure all buttons and containers use consistent `rounded-lg` matching design system

## 3. Accessibility (P2)

- [x] 3.1 Add `aria-label` to subscribe bell button with dynamic text based on subscribed state
- [x] 3.2 Add `aria-label` to copy link button, comments toggle button (with dynamic show/hide + count)
- [x] 3.3 Add visually-hidden skip-to-content link as first element in `+layout.svelte`, add `id="main-content"` to content area
- [x] 3.4 Upgrade metadata text from `text-slate-600`/`text-slate-700` to `text-slate-500` for WCAG AA contrast
- [x] 3.5 Add `group-focus-within:opacity-100` to presence avatar tooltip classes in `PresenceAvatars.svelte`
- [x] 3.6 Add focus trap and Escape-to-close behavior to reaction picker in `CommentThread.svelte`
- [x] 3.7 Add `aria-label="Table of contents"` to TOC nav element

## 4. Responsive/Mobile (P3)

- [x] 4.1 Wrap comments sidebar in mobile drawer component: hidden by default below `md`, slides from right on toggle
- [x] 4.2 Add outside-click and Escape-to-close handlers for mobile comments drawer
- [x] 4.3 Auto-select unified diff mode below `md` breakpoint, hide "Side by side" toggle option
- [x] 4.4 Add overflow handling for top bar buttons on small screens (priority-hide less important buttons or use `overflow-x-auto`)

## 5. Bug Fixes & Polish (P4)

- [x] 5.1 Fix `copyLink` function: move `copied = true` inside `.then()` callback so it only fires on success
- [x] 5.2 Add error feedback to `handleFork` — replace empty `catch {}` with user-visible error message
- [x] 5.3 Add error feedback to subscribe/unsubscribe — replace empty `catch {}` with user-visible error message
- [x] 5.4 Add confirmation dialog before comment deletion in `CommentThread.svelte`
- [x] 5.5 Add `document.visibilitychange` listener to pause/resume comment polling and presence heartbeat intervals
- [x] 5.6 Remove duplicate footer from share page (keep layout footer only)

## 6. Testing & Validation

- [x] 6.1 Write Playwright e2e tests for light/dark mode toggle on share page (verify header, diff, chart colors)
- [x] 6.2 Write Playwright tests for mobile comments drawer open/close behavior
- [x] 6.3 Write Playwright tests for copy link success/failure feedback
- [x] 6.4 Manual visual QA in both themes at desktop and mobile breakpoints
