## 1. Share Page Scroll Fix

- [x] 1.1 In `frontend/src/routes/share/[id]/+page.svelte`, change root div from `min-h-screen bg-navy-950` to `h-full overflow-y-auto bg-navy-950`
- [x] 1.2 In the same file, update the CommentThread sidebar wrapper: remove `overflow-y-auto` from the inner sticky div and add `flex flex-col` so CommentThread fills via flex instead of double scroll nesting

## 2. CommentThread Scroll Fix

- [x] 2.1 In `frontend/src/lib/components/CommentThread.svelte`, change the comment list container from `max-h-[60vh] overflow-y-auto` to `flex-1 overflow-y-auto min-h-0` so it adapts to parent height
- [x] 2.2 Update the CommentThread outer wrapper to use `flex flex-col h-full` so flex-1 children can fill available space

## 3. ReportPanel Responsive Height

- [x] 3.1 In `frontend/src/lib/components/ReportPanel.svelte`, change the content div from `max-h-[55vh] overflow-y-auto` to `max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto`

## 4. ReportDiff Responsive Heights

- [x] 4.1 In `frontend/src/lib/components/ReportDiff.svelte`, change the unified diff container from `max-h-[60vh] overflow-y-auto` to `max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto`
- [x] 4.2 In the same file, change the side-by-side grid container from `max-h-[60vh] overflow-y-auto` to `max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto`

## 5. Verification

- [x] 5.1 Run `npm run check` in frontend to confirm no type/Svelte errors
- [x] 5.2 Visually verify share page scrolls with long report content (manual — requires browser)
- [x] 5.3 Visually verify comment sidebar scrolls without double scroll nesting (manual — requires browser)
