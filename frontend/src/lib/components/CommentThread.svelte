<script lang="ts">
	import { onMount, tick } from 'svelte';
	import {
		listComments,
		createComment,
		deleteComment,
		updateComment,
		toggleReaction,
		resolveSuggestion,
		getLastSeen,
		setLastSeen,
		type Comment,
	} from '$lib/api/comments';
	import { currentUser } from '$lib/stores/authStore';
	import { activeCommentId, pendingAnchor } from '$lib/stores/highlightStore';
	import { sessionComments } from '$lib/stores/reportStore';
	import { sanitizeHtml } from '$lib/utils/sanitize';

	const REACTION_EMOJIS = ['👍', '❤️', '🔥', '💡', '✅', '❓'];

	let { sessionId, onCommentsChange, unseenIds = new Set<string>() }: {
		sessionId: string;
		onCommentsChange?: (comments: Comment[]) => void;
		unseenIds?: Set<string>;
	} = $props();

	let comments = $state<Comment[]>([]);
	let loading = $state(false);
	let open = $state(false);
	let error = $state('');

	// New comment form
	let newBody = $state('');
	let submitting = $state(false);
	let replyingToId = $state<string | null>(null);
	let currentAnchor = $state<{ quote: string; context_before: string; context_after: string } | null>(null);
	// Suggestion mode
	let isSuggestion = $state(false);
	let proposedText = $state('');

	let containerEl = $state<HTMLElement | null>(null);
	let textareaEl = $state<HTMLTextAreaElement | null>(null);

	// Edit mode
	let editingId = $state<string | null>(null);
	let editBody = $state('');

	// Reaction picker open for which comment
	let reactionPickerFor = $state<string | null>(null);

	// ── @mention autocomplete ────────────────────────────────────────────────
	interface MentionUser { sid: string; display_name: string; avatar_url: string | null; }
	let mentionUsers = $state<MentionUser[]>([]);
	let mentionUsersFetched = $state(false);
	let mentionQuery = $state('');
	let mentionStart = $state(-1);
	let mentionVisible = $state(false);
	let mentionIndex = $state(0);

	let mentionFiltered = $derived(
		mentionQuery === ''
			? mentionUsers.slice(0, 6)
			: mentionUsers
				.filter((u) =>
					u.display_name.toLowerCase().includes(mentionQuery.toLowerCase()) ||
					u.sid.toLowerCase().includes(mentionQuery.toLowerCase())
				)
				.slice(0, 6)
	);

	async function ensureMentionUsers() {
		if (mentionUsersFetched) return;
		mentionUsersFetched = true;
		try {
			const res = await fetch(`/api/sessions/${sessionId}/mentionable-users`, { credentials: 'include' });
			if (res.ok) mentionUsers = await res.json();
		} catch {
			// ignore
		}
	}

	function onTextareaInput(e: Event) {
		const ta = e.target as HTMLTextAreaElement;
		const val = ta.value;
		const pos = ta.selectionStart ?? 0;

		let atIdx = -1;
		for (let i = pos - 1; i >= 0; i--) {
			if (val[i] === '@') {
				const before = val[i - 1];
				if (i === 0 || before === ' ' || before === '\n') { atIdx = i; break; }
				break;
			}
			if (val[i] === ' ' || val[i] === '\n') break;
		}

		if (atIdx !== -1) {
			const query = val.slice(atIdx + 1, pos);
			if (!query.includes(' ')) {
				mentionStart = atIdx;
				mentionQuery = query;
				mentionIndex = 0;
				mentionVisible = true;
				ensureMentionUsers();
				return;
			}
		}
		mentionVisible = false;
	}

	function insertMention(user: MentionUser) {
		if (!textareaEl) return;
		const val = newBody;
		const pos = textareaEl.selectionStart ?? 0;
		const before = val.slice(0, mentionStart);
		const after = val.slice(pos);
		newBody = `${before}@${user.sid} ${after}`;
		mentionVisible = false;
		tick().then(() => {
			if (!textareaEl) return;
			const newPos = before.length + user.sid.length + 2;
			textareaEl.setSelectionRange(newPos, newPos);
			textareaEl.focus();
		});
	}

	function handleKey(e: KeyboardEvent) {
		if (mentionVisible && mentionFiltered.length > 0) {
			if (e.key === 'ArrowDown') { e.preventDefault(); mentionIndex = (mentionIndex + 1) % mentionFiltered.length; return; }
			if (e.key === 'ArrowUp') { e.preventDefault(); mentionIndex = (mentionIndex - 1 + mentionFiltered.length) % mentionFiltered.length; return; }
			if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertMention(mentionFiltered[mentionIndex]); return; }
			if (e.key === 'Escape') { mentionVisible = false; return; }
		}
		if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit();
		if (e.key === 'Escape') cancelCompose();
	}

	async function load() {
		if (!sessionId) return;
		loading = true;
		try {
			comments = await listComments(sessionId);
			sessionComments.set(comments);
			onCommentsChange?.(comments);
		} catch {
			// silently ignore
		} finally {
			loading = false;
		}
	}

	onMount(load);

	$effect(() => {
		if (sessionId) load();
	});

	$effect(() => {
		const anchor = $pendingAnchor;
		if (anchor) {
			open = true;
			currentAnchor = anchor;
			replyingToId = null;
			newBody = '';
			isSuggestion = false;
			proposedText = '';
			tick().then(() => {
				const textarea = containerEl?.querySelector('textarea');
				textarea?.focus();
			});
		}
	});

	$effect(() => {
		const id = $activeCommentId;
		if (id) {
			open = true;
			tick().then(() => {
				const el = containerEl?.querySelector(`[data-comment-id="${id}"]`) as HTMLElement | null;
				el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
				el?.classList.add('ring-1', 'ring-gold/50');
				setTimeout(() => el?.classList.remove('ring-1', 'ring-gold/50'), 2000);
			});
		}
	});

	// When panel opens, mark as seen
	$effect(() => {
		if (open) setLastSeen(sessionId);
	});

	async function submit() {
		const body = newBody.trim();
		if (!body || submitting) return;
		submitting = true;
		error = '';
		try {
			const commentType = isSuggestion ? 'suggestion' : 'comment';
			const proposed = isSuggestion ? proposedText.trim() || undefined : undefined;
			const c = await createComment(
				sessionId,
				body,
				replyingToId ?? undefined,
				currentAnchor ?? undefined,
				commentType,
				proposed,
			);
			comments = [...comments, c];
			sessionComments.set(comments);
			onCommentsChange?.(comments);
			newBody = '';
			replyingToId = null;
			currentAnchor = null;
			isSuggestion = false;
			proposedText = '';
			pendingAnchor.set(null);
		} catch (e: unknown) {
			error = (e as Error).message || 'Failed to post comment.';
		} finally {
			submitting = false;
		}
	}

	async function remove(id: string) {
		try {
			await deleteComment(id);
			comments = comments.filter((c) => c.id !== id);
			sessionComments.set(comments);
			onCommentsChange?.(comments);
		} catch {
			// ignore
		}
	}

	async function startEdit(comment: Comment) {
		editingId = comment.id;
		editBody = comment.body;
	}

	async function saveEdit(id: string) {
		const body = editBody.trim();
		if (!body) return;
		try {
			const updated = await updateComment(id, body);
			comments = comments.map((c) => (c.id === id ? { ...c, ...updated } : c));
			sessionComments.set(comments);
			onCommentsChange?.(comments);
			editingId = null;
		} catch {
			// ignore
		}
	}

	async function handleReaction(commentId: string, emoji: string) {
		try {
			const reactions = await toggleReaction(commentId, emoji);
			comments = comments.map((c) =>
				c.id === commentId ? { ...c, reactions } : c
			);
			sessionComments.set(comments);
			onCommentsChange?.(comments);
		} catch {
			// ignore
		}
		reactionPickerFor = null;
	}

	async function handleResolveSuggestion(commentId: string, status: 'accepted' | 'rejected') {
		try {
			const updated = await resolveSuggestion(commentId, status);
			comments = comments.map((c) => (c.id === commentId ? { ...c, ...updated } : c));
			sessionComments.set(comments);
			onCommentsChange?.(comments);
		} catch {
			// ignore
		}
	}

	function startReply(commentId: string) {
		replyingToId = commentId;
		currentAnchor = null;
		pendingAnchor.set(null);
		newBody = '';
		tick().then(() => {
			const textarea = containerEl?.querySelector('textarea');
			textarea?.focus();
		});
	}

	function cancelCompose() {
		replyingToId = null;
		currentAnchor = null;
		newBody = '';
		isSuggestion = false;
		proposedText = '';
		pendingAnchor.set(null);
	}

	function highlightMentions(text: string): string {
		return sanitizeHtml(text.replace(/@([A-Za-z0-9_.\-]+)/g, '<span class="text-gold font-medium">@$1</span>'));
	}

	function isEdited(comment: Comment): boolean {
		const created = new Date(comment.created_at).getTime();
		const updated = new Date(comment.updated_at).getTime();
		return updated - created > 5000;
	}

	let topLevel = $derived(comments.filter((c) => !c.parent_id));
	let replies = $derived(
		comments.reduce<Record<string, Comment[]>>((acc, c) => {
			if (c.parent_id) {
				if (!acc[c.parent_id]) acc[c.parent_id] = [];
				acc[c.parent_id].push(c);
			}
			return acc;
		}, {}),
	);

	function focusHighlight(comment: Comment) {
		if (comment.highlight_anchor) {
			activeCommentId.set(comment.id);
		}
	}

	let unseenCount = $derived(
		comments.filter((c) => unseenIds.has(c.id)).length
	);
</script>

<div bind:this={containerEl} class="border-t border-navy-700 mt-4 flex flex-col h-full">
	<button
		onclick={() => { open = !open; if (open) setLastSeen(sessionId); }}
		aria-expanded={open}
		aria-label="Comments ({comments.length}){unseenCount > 0 ? `, ${unseenCount} new` : ''}"
		class="flex items-center gap-2 w-full px-4 py-2.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
	>
		<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
				d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
		</svg>
		<span>{comments.length} comment{comments.length !== 1 ? 's' : ''}</span>
		{#if unseenCount > 0 && !open}
			<span class="bg-gold text-navy text-[9px] font-bold rounded-full px-1.5 py-0.5 leading-none">{unseenCount} new</span>
		{/if}
		{#if $pendingAnchor}
			<span class="ml-1 text-gold text-xs font-medium">● drafting</span>
		{/if}
		<span class="ml-auto">{open ? '▲' : '▼'}</span>
	</button>

	{#if open}
		<div class="px-4 pb-4 space-y-4 flex-1 overflow-y-auto min-h-0">
			{#if loading}
				<p class="text-xs text-slate-600">Loading…</p>
			{:else}
				{#if comments.length === 0 && !$pendingAnchor}
					<p class="text-xs text-slate-700 text-center py-2">No comments yet. Select text in the report to start a discussion.</p>
				{/if}

				<!-- Comment threads -->
				{#each topLevel as comment (comment.id)}
					<div
						data-comment-id={comment.id}
						class="rounded-lg transition-all duration-300 {unseenIds.has(comment.id) ? 'border-l-2 border-gold/50 pl-2' : ''}"
					>
						<!-- Root comment -->
						<div class="flex gap-2.5 group">
							<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-xs text-gold font-bold flex-shrink-0 mt-0.5">
								{comment.author_name?.charAt(0).toUpperCase() ?? '?'}
							</div>
							<div class="flex-1 min-w-0">
								<div class="flex items-baseline gap-2 flex-wrap">
									<span class="text-xs font-medium text-slate-200">{comment.author_name}</span>
									<span class="text-xs text-slate-700">{new Date(comment.created_at).toLocaleString()}</span>
									{#if isEdited(comment)}
										<span class="text-xs text-slate-600 italic">(edited)</span>
									{/if}
									{#if $currentUser?.sid === comment.author_sid}
										<button
											onclick={() => startEdit(comment)}
											aria-label="Edit comment"
											class="opacity-0 group-hover:opacity-100 focus:opacity-100 text-xs text-slate-600 hover:text-gold transition-all"
										>
											edit
										</button>
										<button
											onclick={() => remove(comment.id)}
											aria-label="Delete comment"
											class="opacity-0 group-hover:opacity-100 focus:opacity-100 text-xs text-slate-600 hover:text-red-400 transition-all ml-auto"
										>
											delete
										</button>
									{/if}
								</div>

								<!-- Highlight anchor badge -->
								{#if comment.highlight_anchor?.quote}
									<button
										onclick={() => focusHighlight(comment)}
										class="flex items-center gap-1 mt-1 mb-1 text-xs text-gold/70 hover:text-gold bg-gold/10 hover:bg-gold/20 rounded px-1.5 py-0.5 transition-colors max-w-full truncate"
										title="Click to jump to highlighted text"
									>
										<svg class="w-2.5 h-2.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
											<path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
										</svg>
										{#if comment.highlight_anchor.context_before || comment.highlight_anchor.context_after}
											<span class="text-slate-500 italic truncate">
												…{comment.highlight_anchor.context_before.slice(-20)}<strong class="text-gold not-italic">"{comment.highlight_anchor.quote.slice(0, 40)}"</strong>{comment.highlight_anchor.context_after.slice(0, 20)}…
											</span>
										{:else}
											<span class="truncate">"{comment.highlight_anchor.quote.slice(0, 50)}{comment.highlight_anchor.quote.length > 50 ? '…' : ''}"</span>
										{/if}
									</button>
								{/if}

								<!-- Suggestion badge -->
								{#if comment.comment_type === 'suggestion'}
									<div class="mt-1 mb-1 rounded border border-navy-600 p-1.5 text-xs">
										<div class="text-slate-500 mb-1">Suggestion</div>
										{#if comment.proposed_text}
											<div class="line-through text-red-400/70 truncate">{comment.highlight_anchor?.quote ?? '(original)'}</div>
											<div class="text-green-400/80 truncate">→ {comment.proposed_text}</div>
										{/if}
										{#if comment.suggestion_status === 'open' && $currentUser}
											<!-- Owner can resolve -->
											<div class="flex gap-1 mt-1.5">
												<button
													onclick={() => handleResolveSuggestion(comment.id, 'accepted')}
													class="px-1.5 py-0.5 rounded bg-green-900/40 text-green-400 hover:bg-green-900/60 transition-colors"
												>Accept</button>
												<button
													onclick={() => handleResolveSuggestion(comment.id, 'rejected')}
													class="px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 hover:bg-red-900/60 transition-colors"
												>Reject</button>
											</div>
										{:else if comment.suggestion_status === 'accepted'}
											<span class="text-green-400/70">✓ Accepted</span>
										{:else if comment.suggestion_status === 'rejected'}
											<span class="text-red-400/70">✗ Rejected</span>
										{/if}
									</div>
								{/if}

								<!-- Edit mode -->
								{#if editingId === comment.id}
									<div class="mt-1">
										<textarea
											bind:value={editBody}
											rows="2"
											class="w-full bg-navy-800 border border-navy-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold/40 resize-none"
										></textarea>
										<div class="flex gap-2 mt-1">
											<button
												onclick={() => saveEdit(comment.id)}
												class="text-xs px-2 py-0.5 bg-gold text-navy rounded"
											>Save</button>
											<button
												onclick={() => (editingId = null)}
												class="text-xs text-slate-500 hover:text-slate-300"
											>Cancel</button>
										</div>
									</div>
								{:else}
									<p class="text-xs text-slate-300 mt-0.5 leading-relaxed">
										<!-- eslint-disable-next-line svelte/no-at-html-tags -->
										{@html highlightMentions(comment.body)}
									</p>
								{/if}

								<!-- Reactions row -->
								<div class="flex items-center gap-1 mt-1 flex-wrap">
									{#each Object.entries(comment.reactions ?? {}) as [emoji, sids] (emoji)}
										<button
											onclick={() => handleReaction(comment.id, emoji)}
											class="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-xs border border-navy-600 hover:border-gold/30 transition-colors
												{$currentUser && sids.includes($currentUser.sid) ? 'bg-gold/10 border-gold/30 text-gold' : 'text-slate-400'}"
										>
											{emoji} <span>{sids.length}</span>
										</button>
									{/each}
									{#if $currentUser}
										<div class="relative">
											<button
												onclick={() => (reactionPickerFor = reactionPickerFor === comment.id ? null : comment.id)}
												aria-label="Add reaction" class="text-xs text-slate-600 hover:text-slate-400 px-1 py-0.5 rounded border border-navy-700 hover:border-navy-600 transition-colors"
											>+</button>
											{#if reactionPickerFor === comment.id}
												<div class="absolute bottom-full left-0 mb-1 bg-navy-900 border border-navy-700 rounded-lg p-1.5 flex gap-1 z-30 shadow-xl">
													{#each ['👍','❤️','🔥','💡','✅','❓'] as emoji}
														<button
															onclick={() => handleReaction(comment.id, emoji)}
															aria-label="React with {emoji}" class="text-sm hover:scale-125 transition-transform p-0.5"
														>{emoji}</button>
													{/each}
												</div>
											{/if}
										</div>
									{/if}
								</div>

								<button
									onclick={() => startReply(comment.id)}
									aria-label="Reply to comment"
									class="text-xs text-slate-600 hover:text-slate-400 mt-1 transition-colors"
								>
									Reply
								</button>
							</div>
						</div>

						<!-- Replies -->
						{#if replies[comment.id]?.length}
							<div class="ml-8 mt-2 space-y-2 border-l border-navy-700 pl-3">
								{#each replies[comment.id] as reply (reply.id)}
									<div data-comment-id={reply.id} class="flex gap-2 group rounded transition-all duration-300 {unseenIds.has(reply.id) ? 'border-l-2 border-gold/40 pl-1' : ''}">
										<div class="w-5 h-5 rounded-full bg-navy-700 flex items-center justify-center text-[9px] text-gold font-bold flex-shrink-0 mt-0.5">
											{reply.author_name?.charAt(0).toUpperCase() ?? '?'}
										</div>
										<div class="flex-1 min-w-0">
											<div class="flex items-baseline gap-2 flex-wrap">
												<span class="text-xs font-medium text-slate-200">{reply.author_name}</span>
												<span class="text-xs text-slate-700">{new Date(reply.created_at).toLocaleString()}</span>
												{#if isEdited(reply)}
													<span class="text-xs text-slate-600 italic">(edited)</span>
												{/if}
												{#if $currentUser?.sid === reply.author_sid}
													<button
														onclick={() => startEdit(reply)}
														aria-label="Edit reply"
														class="opacity-0 group-hover:opacity-100 focus:opacity-100 text-xs text-slate-600 hover:text-gold transition-all"
													>edit</button>
													<button
														onclick={() => remove(reply.id)}
														class="opacity-0 group-hover:opacity-100 focus:opacity-100 text-xs text-slate-600 hover:text-red-400 transition-all ml-auto"
														aria-label="Delete reply"
													>delete</button>
												{/if}
											</div>
											{#if editingId === reply.id}
												<div class="mt-1">
													<textarea
														bind:value={editBody}
														rows="2"
														class="w-full bg-navy-800 border border-navy-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold/40 resize-none"
													></textarea>
													<div class="flex gap-2 mt-1">
														<button onclick={() => saveEdit(reply.id)} class="text-xs px-2 py-0.5 bg-gold text-navy rounded">Save</button>
														<button onclick={() => (editingId = null)} class="text-xs text-slate-500 hover:text-slate-300">Cancel</button>
													</div>
												</div>
											{:else}
												<p class="text-xs text-slate-300 mt-0.5 leading-relaxed">
													<!-- eslint-disable-next-line svelte/no-at-html-tags -->
													{@html highlightMentions(reply.body)}
												</p>
											{/if}
											<!-- Reactions on replies -->
											<div class="flex items-center gap-1 mt-1 flex-wrap">
												{#each Object.entries(reply.reactions ?? {}) as [emoji, sids] (emoji)}
													<button
														onclick={() => handleReaction(reply.id, emoji)}
														class="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-xs border border-navy-600 hover:border-gold/30 transition-colors
															{$currentUser && sids.includes($currentUser.sid) ? 'bg-gold/10 border-gold/30 text-gold' : 'text-slate-400'}"
													>{emoji} {sids.length}</button>
												{/each}
												{#if $currentUser}
													<div class="relative">
														<button
															onclick={() => (reactionPickerFor = reactionPickerFor === reply.id ? null : reply.id)}
															aria-label="Add reaction" class="text-xs text-slate-600 hover:text-slate-400 px-1 py-0.5 rounded border border-navy-700 hover:border-navy-600 transition-colors"
														>+</button>
														{#if reactionPickerFor === reply.id}
															<div class="absolute bottom-full left-0 mb-1 bg-navy-900 border border-navy-700 rounded-lg p-1.5 flex gap-1 z-30 shadow-xl">
																{#each ['👍','❤️','🔥','💡','✅','❓'] as emoji}
																	<button aria-label="React with {emoji}" onclick={() => handleReaction(reply.id, emoji)} class="text-sm hover:scale-125 transition-transform p-0.5">{emoji}</button>
																{/each}
															</div>
														{/if}
													</div>
												{/if}
											</div>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			{/if}

			<!-- Compose area -->
			{#if $currentUser}
				<div class="mt-3 border-t border-navy-700/50 pt-3">
					<!-- Context indicators -->
					{#if currentAnchor}
						<div class="flex items-start gap-1.5 mb-2 bg-gold/10 border border-gold/20 rounded px-2 py-1.5 text-xs text-gold">
							<svg class="w-3 h-3 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
								<path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
							</svg>
							<span class="truncate">Commenting on: "{currentAnchor.quote.slice(0, 60)}{currentAnchor.quote.length > 60 ? '…' : ''}"</span>
							<button onclick={cancelCompose} class="ml-auto flex-shrink-0 hover:text-red-400">✕</button>
						</div>
						<!-- Suggestion toggle (only when anchor is set) -->
						<div class="flex items-center gap-2 mb-2">
							<button
								onclick={() => { isSuggestion = !isSuggestion; }}
								class="text-xs px-2 py-0.5 rounded border transition-colors {isSuggestion ? 'border-gold/40 text-gold bg-gold/10' : 'border-navy-700 text-slate-500 hover:text-slate-300'}"
							>{isSuggestion ? '✎ Suggestion mode' : 'Switch to suggestion'}</button>
						</div>
						{#if isSuggestion}
							<div class="mb-2">
								<label for="proposed-text" class="text-xs text-slate-500 mb-1 block">Proposed replacement text</label>
								<textarea
									id="proposed-text"
									bind:value={proposedText}
									placeholder="Enter your suggested replacement…"
									rows="2"
									class="w-full bg-navy-800 border border-green-900/40 rounded px-2 py-1 text-xs text-green-300 placeholder-slate-600 focus:outline-none focus:border-green-700/40 resize-none"
								></textarea>
							</div>
						{/if}
					{:else if replyingToId}
						{@const parent = comments.find((c) => c.id === replyingToId)}
						{#if parent}
							<div class="flex items-center gap-1.5 mb-2 text-xs text-slate-500">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
								</svg>
								Replying to <span class="text-slate-300 font-medium">{parent.author_name}</span>
								<button onclick={cancelCompose} class="ml-auto hover:text-red-400">✕</button>
							</div>
						{/if}
					{/if}

					<div class="flex gap-2">
						<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-xs text-gold font-bold flex-shrink-0 mt-1">
							{$currentUser.display_name?.charAt(0).toUpperCase() ?? '?'}
						</div>
						<div class="flex-1 relative">
							<textarea
								bind:this={textareaEl}
								bind:value={newBody}
								onkeydown={handleKey}
								oninput={onTextareaInput}
								placeholder={currentAnchor
									? (isSuggestion ? 'Describe your suggestion… @mention teammates' : 'Comment on highlighted text… @mention teammates')
									: replyingToId
									? 'Write a reply… @mention teammates'
									: 'Add a comment… @mention teammates'}
								rows="2"
								class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40 resize-none transition-colors"
							></textarea>

							<!-- @mention autocomplete dropdown -->
							{#if mentionVisible && mentionFiltered.length > 0}
								<div class="absolute bottom-full left-0 mb-1 w-56 bg-navy-900 border border-navy-600 rounded-lg shadow-xl overflow-hidden z-30">
									<p class="text-[9px] text-slate-600 uppercase tracking-wider px-3 pt-2 pb-1">Team members</p>
									{#each mentionFiltered as user, idx (user.sid)}
										<!-- svelte-ignore a11y_mouse_events_have_key_events -->
										<button
											type="button"
											onmousedown={(e) => { e.preventDefault(); insertMention(user); }}
											onmouseover={() => (mentionIndex = idx)}
											class="w-full flex items-center gap-2.5 px-3 py-1.5 text-left transition-colors
												{mentionIndex === idx ? 'bg-navy-700' : 'hover:bg-navy-800'}"
										>
											<div class="w-5 h-5 rounded-full bg-navy-600 flex items-center justify-center text-[9px] text-gold font-bold flex-shrink-0">
												{user.display_name?.charAt(0).toUpperCase() ?? '?'}
											</div>
											<div class="min-w-0">
												<p class="text-xs text-slate-200 font-medium truncate">{user.display_name}</p>
												<p class="text-xs text-slate-600 truncate">@{user.sid}</p>
											</div>
										</button>
									{/each}
								</div>
							{:else if mentionVisible && mentionQuery.length > 0 && mentionUsersFetched && mentionUsers.length === 0}
								<div class="absolute bottom-full left-0 mb-1 w-48 bg-navy-900 border border-navy-700 rounded-lg shadow-xl px-3 py-2 z-30">
									<p class="text-xs text-slate-600">No team members found. Share this report with a team first.</p>
								</div>
							{/if}

							{#if error}
								<p class="text-xs text-red-400 mt-1">{error}</p>
							{/if}
							<div class="flex items-center justify-between mt-1.5">
								<span class="text-xs text-slate-700">⌘↵ to submit · Esc to cancel</span>
								<button
									onclick={submit}
									disabled={!newBody.trim() || submitting}
									class="px-3 py-1 rounded text-xs bg-gold text-navy font-medium disabled:opacity-40 hover:bg-gold/90 transition-colors"
								>
									{submitting ? 'Posting…' : isSuggestion ? 'Post suggestion' : currentAnchor ? 'Comment on selection' : replyingToId ? 'Reply' : 'Comment'}
								</button>
							</div>
						</div>
					</div>
				</div>
			{:else}
				<p class="text-xs text-slate-600 text-center py-1">
					<a href="/login" class="text-gold hover:underline">Log in</a> to comment
				</p>
			{/if}
		</div>
	{/if}
</div>
