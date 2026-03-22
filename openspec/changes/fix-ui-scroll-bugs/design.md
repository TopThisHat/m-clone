## Context

The app uses a root layout with `h-screen flex flex-col` and a `<main class="flex-1 overflow-hidden">` that expects child pages to manage their own scrolling. Several pages and components use hardcoded `max-h-[Xvh]` with `overflow-y-auto` instead of flex-based sizing, causing content clipping and broken scroll on smaller viewports. The share page doesn't add `overflow-y-auto` at all, so its content is simply clipped by the parent's `overflow-hidden`.

Current scroll architecture:
```
+layout.svelte (h-screen, flex-col)
  header (flex-shrink-0)
  main (flex-1, overflow-hidden)    ← clips children
    child page                       ← must handle own scroll
  footer (flex-shrink-0)
```

## Goals / Non-Goals

**Goals:**
- Make the share page scrollable so long reports and comment threads are accessible
- Eliminate double-nested scroll containers in the CommentThread sidebar
- Replace hardcoded viewport-percentage max-heights with flex-based sizing that adapts to container height
- Ensure all scrollable regions remain keyboard-accessible and don't trap scroll focus unexpectedly

**Non-Goals:**
- Refactoring the root layout's `overflow-hidden` pattern (it's correct — children manage scroll)
- Adding virtual scrolling or infinite scroll for long comment threads
- Changing any component's visual design or spacing

## Decisions

### 1. Share page: add `overflow-y-auto` to root div
**Decision**: Change `<div class="min-h-screen bg-navy-950">` to `<div class="h-full overflow-y-auto bg-navy-950">`.

**Rationale**: The root layout's main is `flex-1 overflow-hidden`. The share page must opt into scrolling. Using `h-full overflow-y-auto` fills the available space and scrolls when content overflows. `min-h-screen` is unnecessary since the parent already constrains height.

**Alternative considered**: Adding `overflow-y-auto` to main globally — rejected because other pages (home, scout) manage scroll differently and the current pattern is intentional.

### 2. CommentThread sidebar: single scroll container with flex
**Decision**: Replace the current pattern:
```html
<aside class="w-80 flex-shrink-0">
  <div class="sticky top-20 max-h-[calc(100vh-5rem)] overflow-y-auto">
    <CommentThread />  <!-- has its own max-h-[60vh] overflow-y-auto -->
  </div>
</aside>
```
With:
```html
<aside class="w-80 flex-shrink-0 h-full flex flex-col">
  <div class="sticky top-20 max-h-[calc(100vh-5rem)] flex flex-col">
    <CommentThread />
  </div>
</aside>
```

And inside CommentThread, change the comment list from `max-h-[60vh] overflow-y-auto` to `flex-1 overflow-y-auto min-h-0`. The sidebar outer container handles the viewport constraint; the inner CommentThread fills it via flex.

**Rationale**: Double-nested scroll containers create a confusing UX where the user might scroll the inner container but not the outer, or vice versa. A single scroll context is clearer.

### 3. ReportPanel: remove hardcoded max-h-[55vh]
**Decision**: Change `<div class="p-6 max-h-[55vh] overflow-y-auto">` to `<div class="p-6 max-h-[50vh] overflow-y-auto sm:max-h-[60vh] lg:max-h-[70vh]">`.

**Rationale**: The ReportPanel is used on the home page where it appears within a scrollable area. A fully flex-based approach isn't possible here since the parent isn't a fixed-height flex container. Instead, use responsive max-heights that scale better across device sizes than a single 55vh.

**Alternative considered**: Removing max-height entirely — rejected because without a height constraint the panel would push all content below it off-screen.

### 4. ReportDiff: responsive max-heights
**Decision**: Same pattern as ReportPanel — replace `max-h-[60vh]` with responsive values `max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]`.

**Rationale**: ReportDiff appears inside the share page report column. The share page now scrolls (Decision 1), so the diff doesn't need to be the sole scroll container. But keeping some max-height prevents a very long diff from dominating the page.

## Risks / Trade-offs

- **[Visual regression]** → Mitigated by keeping changes to overflow/height properties only; no spacing, color, or layout structure changes. Manual QA on share page with long reports + many comments.
- **[Sticky sidebar behavior]** → The share page's TOC and comment sidebars both use `sticky`. After adding `overflow-y-auto` to the page root, sticky elements will still work because they're positioned relative to the scroll container. Verified: sticky works inside overflow-y-auto parents.
- **[Small-screen clipping]** → The responsive max-height breakpoints (50vh → 60vh → 70vh) may still clip on very small screens. Acceptable trade-off since these components show expandable content.
