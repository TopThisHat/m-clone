## Why

Multiple pages have broken or degraded scroll behavior. The primary report is that the CommentThread panel on the share page (`/share/[id]`) doesn't scroll — caused by double-nested scroll containers with conflicting `max-height` values. The share page itself also clips content because it renders `min-h-screen` content inside the root layout's `overflow-hidden` main without its own scroll wrapper. Similar hardcoded viewport-percentage max-heights (`max-h-[55vh]`, `max-h-[60vh]`) in ReportPanel and ReportDiff create content cutoff on smaller screens and prevent proper flex-based sizing.

## What Changes

- **Share page scroll**: Add `overflow-y-auto` to the share page root container so long reports and comment threads are scrollable within the root layout's `overflow-hidden` main.
- **CommentThread sidebar (share page)**: Replace the double-nested scroll pattern (outer `max-h-[calc(100vh-5rem)] overflow-y-auto` wrapping inner `max-h-[60vh] overflow-y-auto`) with a single flex-based column that fills available viewport height, using `flex-1 overflow-y-auto` for the comment list.
- **CommentThread component**: Change the comments list from `max-h-[60vh] overflow-y-auto` to a flex-friendly pattern that adapts to its parent container height.
- **ReportPanel**: Remove `max-h-[55vh]` on the report content area; use flex layout so the panel grows/shrinks with its parent.
- **ReportDiff**: Remove `max-h-[60vh]` from both unified and side-by-side diff containers; use flex layout instead.

## Capabilities

### New Capabilities
- `scroll-layout-fix`: Corrects scroll and overflow behavior across share page, CommentThread, ReportPanel, and ReportDiff components to use flex-based layouts instead of hardcoded viewport-percentage max-heights.

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

- **Frontend components**: `CommentThread.svelte`, `ReportPanel.svelte`, `ReportDiff.svelte`
- **Frontend routes**: `routes/share/[id]/+page.svelte`
- **No API changes, no backend changes, no dependency changes**
- **Risk**: Low — CSS-only changes scoped to overflow/height properties. Visual regression testing recommended.
