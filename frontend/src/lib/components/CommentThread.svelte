<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { listComments, createComment, deleteComment, type Comment } from '$lib/api/comments';
	import { currentUser } from '$lib/stores/authStore';
	import { activeCommentId, pendingAnchor } from '$lib/stores/highlightStore';
	import { sessionComments } from '$lib/stores/reportStore';

	let { sessionId, onCommentsChange }: {
		sessionId: string;
		onCommentsChange?: (comments: Comment[]) => void;
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

	let containerEl = $state<HTMLElement | null>(null);
	let textareaEl = $state<HTMLTextAreaElement | null>(null);

	// ── @mention autocomplete ────────────────────────────────────────────────
	interface MentionUser { sid: string; display_name: string; avatar_url: string | null; }
	let mentionUsers = $state<MentionUser[]>([]);           // full list, fetched once
	let mentionUsersFetched = $state(false);
	let mentionQuery = $state('');                          // text after the @ trigger
	let mentionStart = $state(-1);                          // caret position of the @
	let mentionVisible = $state(false);
	let mentionIndex = $state(0);                           // keyboard-selected index

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
			// ignore — autocomplete just won't show
		}
	}

	function onTextareaInput(e: Event) {
		const ta = e.target as HTMLTextAreaElement;
		const val = ta.value;
		const pos = ta.selectionStart ?? 0;

		// Find the last @ before the cursor that starts a mention (preceded by space/start)
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
			// Only open if query has no spaces (still in the mention token)
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
			const newPos = before.length + user.sid.length + 2; // @sid + space
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

	// When pendingAnchor is set (user selected text in report), open thread and pre-fill anchor
	$effect(() => {
		const anchor = $pendingAnchor;
		if (anchor) {
			open = true;
			currentAnchor = anchor;
			replyingToId = null;
			newBody = '';
			tick().then(() => {
				const textarea = containerEl?.querySelector('textarea');
				textarea?.focus();
			});
		}
	});

	// When activeCommentId changes, scroll to that comment and open thread
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

	async function submit() {
		const body = newBody.trim();
		if (!body || submitting) return;
		submitting = true;
		error = '';
		try {
			const c = await createComment(
				sessionId,
				body,
				replyingToId ?? undefined,
				currentAnchor ?? undefined,
			);
			comments = [...comments, c];
			sessionComments.set(comments);
			onCommentsChange?.(comments);
			newBody = '';
			replyingToId = null;
			currentAnchor = null;
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
		pendingAnchor.set(null);
	}

	function highlightMentions(text: string): string {
		return text.replace(/@([A-Za-z0-9_.\-]+)/g, '<span class="text-gold font-medium">@$1</span>');
	}

	// Top-level comments (no parent)
	let topLevel = $derived(comments.filter((c) => !c.parent_id));
	// Replies grouped by parent
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
</script>

<div bind:this={containerEl} class="border-t border-navy-700 mt-4">
	<button
		onclick={() => (open = !open)}
		class="flex items-center gap-2 w-full px-4 py-2.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
	>
		<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
				d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
		</svg>
		<span>{comments.length} comment{comments.length !== 1 ? 's' : ''}</span>
		{#if $pendingAnchor}
			<span class="ml-1 text-gold text-[10px] font-medium">● drafting</span>
		{/if}
		<span class="ml-auto">{open ? '▲' : '▼'}</span>
	</button>

	{#if open}
		<div class="px-4 pb-4 space-y-4 max-h-[60vh] overflow-y-auto">
			{#if loading}
				<p class="text-xs text-slate-600">Loading…</p>
			{:else}
				{#if comments.length === 0 && !$pendingAnchor}
					<p class="text-xs text-slate-700 text-center py-2">No comments yet. Select text in the report to start a discussion.</p>
				{/if}

				<!-- Comment threads -->
				{#each topLevel as comment (comment.id)}
					<div data-comment-id={comment.id} class="rounded-lg transition-all duration-300">
						<!-- Root comment -->
						<div class="flex gap-2.5 group">
							<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-[10px] text-gold font-bold flex-shrink-0 mt-0.5">
								{comment.author_name?.charAt(0).toUpperCase() ?? '?'}
							</div>
							<div class="flex-1 min-w-0">
								<div class="flex items-baseline gap-2 flex-wrap">
									<span class="text-xs font-medium text-slate-200">{comment.author_name}</span>
									<span class="text-[10px] text-slate-700">{new Date(comment.created_at).toLocaleString()}</span>
									{#if $currentUser?.sid === comment.author_sid}
										<button
											onclick={() => remove(comment.id)}
											class="opacity-0 group-hover:opacity-100 text-[10px] text-slate-600 hover:text-red-400 transition-all ml-auto"
										>
											delete
										</button>
									{/if}
								</div>

								<!-- Highlight anchor badge -->
								{#if comment.highlight_anchor?.quote}
									<button
										onclick={() => focusHighlight(comment)}
										class="flex items-center gap-1 mt-1 mb-1 text-[10px] text-gold/70 hover:text-gold bg-gold/10 hover:bg-gold/20 rounded px-1.5 py-0.5 transition-colors max-w-full truncate"
										title="Click to jump to highlighted text"
									>
										<svg class="w-2.5 h-2.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
											<path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
										</svg>
										<span class="truncate">"{comment.highlight_anchor.quote.slice(0, 50)}{comment.highlight_anchor.quote.length > 50 ? '…' : ''}"</span>
									</button>
								{/if}

								<p class="text-xs text-slate-300 mt-0.5 leading-relaxed">
									<!-- eslint-disable-next-line svelte/no-at-html-tags -->
									{@html highlightMentions(comment.body)}
								</p>

								<button
									onclick={() => startReply(comment.id)}
									class="text-[10px] text-slate-600 hover:text-slate-400 mt-1 transition-colors"
								>
									Reply
								</button>
							</div>
						</div>

						<!-- Replies -->
						{#if replies[comment.id]?.length}
							<div class="ml-8 mt-2 space-y-2 border-l border-navy-700 pl-3">
								{#each replies[comment.id] as reply (reply.id)}
									<div data-comment-id={reply.id} class="flex gap-2 group rounded transition-all duration-300">
										<div class="w-5 h-5 rounded-full bg-navy-700 flex items-center justify-center text-[9px] text-gold font-bold flex-shrink-0 mt-0.5">
											{reply.author_name?.charAt(0).toUpperCase() ?? '?'}
										</div>
										<div class="flex-1 min-w-0">
											<div class="flex items-baseline gap-2 flex-wrap">
												<span class="text-[11px] font-medium text-slate-200">{reply.author_name}</span>
												<span class="text-[10px] text-slate-700">{new Date(reply.created_at).toLocaleString()}</span>
												{#if $currentUser?.sid === reply.author_sid}
													<button
														onclick={() => remove(reply.id)}
														class="opacity-0 group-hover:opacity-100 text-[10px] text-slate-600 hover:text-red-400 transition-all ml-auto"
													>
														delete
													</button>
												{/if}
											</div>
											<p class="text-xs text-slate-300 mt-0.5 leading-relaxed">
												<!-- eslint-disable-next-line svelte/no-at-html-tags -->
												{@html highlightMentions(reply.body)}
											</p>
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
						<div class="flex items-start gap-1.5 mb-2 bg-gold/10 border border-gold/20 rounded px-2 py-1.5 text-[10px] text-gold">
							<svg class="w-3 h-3 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
								<path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
							</svg>
							<span class="truncate">Commenting on: "{currentAnchor.quote.slice(0, 60)}{currentAnchor.quote.length > 60 ? '…' : ''}"</span>
							<button onclick={cancelCompose} class="ml-auto flex-shrink-0 hover:text-red-400">✕</button>
						</div>
					{:else if replyingToId}
						{@const parent = comments.find((c) => c.id === replyingToId)}
						{#if parent}
							<div class="flex items-center gap-1.5 mb-2 text-[10px] text-slate-500">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
								</svg>
								Replying to <span class="text-slate-300 font-medium">{parent.author_name}</span>
								<button onclick={cancelCompose} class="ml-auto hover:text-red-400">✕</button>
							</div>
						{/if}
					{/if}

					<div class="flex gap-2">
						<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-[10px] text-gold font-bold flex-shrink-0 mt-1">
							{$currentUser.display_name?.charAt(0).toUpperCase() ?? '?'}
						</div>
						<div class="flex-1 relative">
							<textarea
								bind:this={textareaEl}
								bind:value={newBody}
								onkeydown={handleKey}
								oninput={onTextareaInput}
								placeholder={currentAnchor
									? 'Comment on highlighted text… @mention teammates'
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
												<p class="text-[10px] text-slate-600 truncate">@{user.sid}</p>
											</div>
										</button>
									{/each}
								</div>
							{:else if mentionVisible && mentionQuery.length > 0 && mentionUsersFetched && mentionUsers.length === 0}
								<div class="absolute bottom-full left-0 mb-1 w-48 bg-navy-900 border border-navy-700 rounded-lg shadow-xl px-3 py-2 z-30">
									<p class="text-[10px] text-slate-600">No team members found. Share this report with a team first.</p>
								</div>
							{/if}

							{#if error}
								<p class="text-xs text-red-400 mt-1">{error}</p>
							{/if}
							<div class="flex items-center justify-between mt-1.5">
								<span class="text-[10px] text-slate-700">⌘↵ to submit · Esc to cancel</span>
								<button
									onclick={submit}
									disabled={!newBody.trim() || submitting}
									class="px-3 py-1 rounded text-xs bg-gold text-navy font-medium disabled:opacity-40 hover:bg-gold/90 transition-colors"
								>
									{submitting ? 'Posting…' : currentAnchor ? 'Comment on selection' : replyingToId ? 'Reply' : 'Comment'}
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
