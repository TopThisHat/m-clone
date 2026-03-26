<script lang="ts">
	/**
	 * Wraps report HTML content to support:
	 * - Text selection → floating "Add comment" toolbar → creates anchored comment
	 * - Rendering highlight marks for anchored comments
	 * - Hover tooltip over highlights showing comment preview + anchor context
	 * - Click highlight to focus comment in sidebar (via activeCommentId store)
	 * - Suggestion underlines: gold = open, green = accepted
	 */
	import { tick } from 'svelte';
	import type { Comment } from '$lib/api/comments';
	import { sanitizeHtml } from '$lib/utils/sanitize';
	import { activeCommentId, pendingAnchor } from '$lib/stores/highlightStore';
	import { injectButtons } from '$lib/actions/tableExport';

	let {
		html,
		comments = [],
		canComment = false,
	}: {
		html: string;
		comments: Comment[];
		canComment?: boolean;
	} = $props();

	let containerEl = $state<HTMLElement | null>(null);

	// Floating toolbar
	let toolbarVisible = $state(false);
	let toolbarX = $state(0);
	let toolbarY = $state(0);
	let selectionText = $state('');

	// Tooltip for existing highlights
	let tooltipVisible = $state(false);
	let tooltipX = $state(0);
	let tooltipY = $state(0);
	let tooltipComment = $state<Comment | null>(null);

	// Anchored comments (those with highlight_anchor)
	let anchoredComments = $derived(comments.filter((c) => c.highlight_anchor?.quote));

	// Re-apply highlights and table export buttons whenever comments or html changes
	$effect(() => {
		const _comments = anchoredComments;
		const _html = html;
		if (containerEl) {
			tick().then(() => {
				applyHighlights();
				injectButtons(containerEl!);
			});
		}
	});

	// Also apply after activeCommentId changes (to pulse the active mark)
	$effect(() => {
		const _id = $activeCommentId;
		if (containerEl) {
			tick().then(() => refreshActivePulse());
		}
	});

	function getMarkStyle(comment: Comment): { bg: string; border: string } {
		if (comment.comment_type === 'suggestion') {
			if (comment.suggestion_status === 'accepted') {
				return { bg: 'rgba(34,197,94,0.18)', border: '2px solid rgba(34,197,94,0.6)' };
			}
			// open suggestion → gold underline
			return { bg: 'rgba(212,175,55,0.15)', border: '2px solid rgba(212,175,55,0.8)' };
		}
		return { bg: 'rgba(212,175,55,0.25)', border: '2px solid rgba(212,175,55,0.6)' };
	}

	function applyHighlights() {
		if (!containerEl) return;
		const article = containerEl.querySelector('article');
		if (!article) return;

		// Remove existing marks
		article.querySelectorAll('mark[data-comment-id]').forEach((m) => {
			const parent = m.parentNode!;
			parent.replaceChild(document.createTextNode(m.textContent ?? ''), m);
			parent.normalize();
		});

		// Apply each anchored comment
		for (const comment of anchoredComments) {
			const quote = comment.highlight_anchor!.quote;
			if (!quote) continue;
			wrapTextInMark(article, quote, comment.id, comment);
		}

		refreshActivePulse();
	}

	function wrapTextInMark(root: Element, quote: string, commentId: string, comment: Comment) {
		const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		let node: Text | null;
		while ((node = walker.nextNode() as Text | null)) {
			const idx = node.nodeValue?.indexOf(quote) ?? -1;
			if (idx === -1) continue;

			const before = node.nodeValue!.slice(0, idx);
			const after = node.nodeValue!.slice(idx + quote.length);

			const mark = document.createElement('mark');
			mark.dataset.commentId = commentId;
			mark.textContent = quote;
			mark.className = 'highlight-mark cursor-pointer rounded-sm px-0.5 transition-colors';
			const style = getMarkStyle(comment);
			mark.style.backgroundColor = style.bg;
			mark.style.borderBottom = style.border;

			const parent = node.parentNode!;
			const ref = node.nextSibling;
			parent.removeChild(node);
			if (before) parent.insertBefore(document.createTextNode(before), ref ?? null);
			parent.insertBefore(mark, ref ?? null);
			if (after) parent.insertBefore(document.createTextNode(after), ref ?? null);

			break; // Only highlight first occurrence
		}
	}

	function refreshActivePulse() {
		if (!containerEl) return;
		containerEl.querySelectorAll('mark[data-comment-id]').forEach((m) => {
			const el = m as HTMLElement;
			const commentId = el.dataset.commentId;
			const comment = comments.find((c) => c.id === commentId);
			const isActive = commentId === $activeCommentId;
			if (comment) {
				const style = getMarkStyle(comment);
				el.style.backgroundColor = isActive
					? style.bg.replace(/[\d.]+\)$/, '0.55)')
					: style.bg;
				el.style.outline = isActive ? `2px solid ${style.border.split(' ')[2]}` : '';
			}
		});
	}

	// ── Text selection for new comments ─────────────────────────────────────────

	function onMouseUp(e: MouseEvent) {
		if (!canComment) return;
		const sel = window.getSelection();
		if (!sel || sel.isCollapsed || !sel.toString().trim()) {
			toolbarVisible = false;
			return;
		}

		if (!containerEl?.contains(sel.anchorNode)) {
			toolbarVisible = false;
			return;
		}

		const selected = sel.toString().trim();
		if (selected.length < 3) { toolbarVisible = false; return; }

		selectionText = selected;

		const range = sel.getRangeAt(0);
		const rect = range.getBoundingClientRect();
		const containerRect = containerEl!.getBoundingClientRect();
		toolbarX = rect.left - containerRect.left + rect.width / 2;
		toolbarY = rect.top - containerRect.top - 8;
		toolbarVisible = true;
	}

	function captureAndComment() {
		const sel = window.getSelection();
		let contextBefore = '';
		let contextAfter = '';

		if (sel && !sel.isCollapsed && containerEl) {
			const fullText = containerEl.textContent ?? '';
			const quoteIdx = fullText.indexOf(selectionText);
			if (quoteIdx !== -1) {
				contextBefore = fullText.slice(Math.max(0, quoteIdx - 60), quoteIdx);
				contextAfter = fullText.slice(quoteIdx + selectionText.length, quoteIdx + selectionText.length + 60);
			}
		}

		pendingAnchor.set({
			quote: selectionText,
			context_before: contextBefore,
			context_after: contextAfter,
		});

		toolbarVisible = false;
		window.getSelection()?.removeAllRanges();
	}

	// ── Highlight hover tooltip ──────────────────────────────────────────────────

	function onMarkMouseEnter(e: MouseEvent) {
		const target = (e.target as HTMLElement).closest('mark[data-comment-id]') as HTMLElement | null;
		if (!target) return;
		const commentId = target.dataset.commentId;
		const comment = comments.find((c) => c.id === commentId) ?? null;
		if (!comment) return;

		const rect = target.getBoundingClientRect();
		const containerRect = containerEl!.getBoundingClientRect();
		tooltipX = rect.left - containerRect.left;
		tooltipY = rect.bottom - containerRect.top + 6;
		tooltipComment = comment;
		tooltipVisible = true;
	}

	function onMarkMouseLeave() {
		tooltipVisible = false;
	}

	function onMarkClick(e: MouseEvent) {
		const target = (e.target as HTMLElement).closest('mark[data-comment-id]') as HTMLElement | null;
		if (!target) return;
		const commentId = target.dataset.commentId!;
		activeCommentId.set(commentId);
		e.stopPropagation();
	}

	function onContainerClick(e: MouseEvent) {
		if (!(e.target as HTMLElement).closest('mark[data-comment-id]')) {
			toolbarVisible = false;
		}
	}

	function highlightMentions(text: string): string {
		return sanitizeHtml(text.replace(/@([A-Za-z0-9_.\-]+)/g, '<span class="text-gold font-medium">@$1</span>'));
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_click_events_have_key_events, a11y_mouse_events_have_key_events -->
<div
	bind:this={containerEl}
	class="relative"
	onmouseup={onMouseUp}
	onclick={onContainerClick}
	onmouseover={onMarkMouseEnter}
	onmouseleave={onMarkMouseLeave}
	role="region"
	aria-label="Research report"
>
	<article class="prose prose-sm max-w-none">
		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		{@html sanitizeHtml(html)}
	</article>

	<!-- Floating "Add comment" toolbar -->
	{#if toolbarVisible && canComment}
		<div
			class="absolute z-20 flex items-center gap-1 bg-navy-900 border border-navy-600 rounded-lg shadow-xl px-2 py-1 -translate-x-1/2"
			style="left: {toolbarX}px; top: {toolbarY}px; transform: translateX(-50%) translateY(-100%);"
		>
			<button
				onclick={captureAndComment}
				class="flex items-center gap-1.5 text-xs text-slate-200 hover:text-gold px-2 py-1 rounded transition-colors"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
						d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
				</svg>
				Comment
			</button>
		</div>
	{/if}

	<!-- Hover tooltip over existing highlight -->
	{#if tooltipVisible && tooltipComment}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="absolute z-20 max-w-xs bg-navy-900 border border-navy-600 rounded-lg shadow-xl p-3 text-xs"
			style="left: {tooltipX}px; top: {tooltipY}px;"
			onmouseenter={() => (tooltipVisible = true)}
			onmouseleave={() => (tooltipVisible = false)}
		>
			<div class="flex items-center gap-2 mb-1.5">
				<div class="w-5 h-5 rounded-full bg-navy-700 flex items-center justify-center text-[9px] text-gold font-bold flex-shrink-0">
					{tooltipComment.author_name?.charAt(0).toUpperCase() ?? '?'}
				</div>
				<span class="font-medium text-slate-200">{tooltipComment.author_name}</span>
				<span class="text-slate-600 text-xs">{new Date(tooltipComment.created_at).toLocaleDateString()}</span>
			</div>
			<!-- Anchor context (Feature 5) -->
			{#if tooltipComment.highlight_anchor && (tooltipComment.highlight_anchor.context_before || tooltipComment.highlight_anchor.context_after)}
				<p class="text-slate-600 text-xs leading-relaxed mb-1.5 italic line-clamp-2">
					…{tooltipComment.highlight_anchor.context_before.slice(-30)}<strong class="text-slate-400 not-italic">"{tooltipComment.highlight_anchor.quote}"</strong>{tooltipComment.highlight_anchor.context_after.slice(0, 30)}…
				</p>
			{/if}
			<p class="text-slate-300 leading-relaxed line-clamp-3">
				<!-- eslint-disable-next-line svelte/no-at-html-tags -->
				{@html highlightMentions(tooltipComment.body)}
			</p>
			{#if tooltipComment.comment_type === 'suggestion' && tooltipComment.proposed_text}
				<p class="text-green-400/70 text-xs mt-1">→ {tooltipComment.proposed_text}</p>
			{/if}
			<p class="text-gold text-xs mt-1.5">Click to view thread →</p>
		</div>
	{/if}
</div>
