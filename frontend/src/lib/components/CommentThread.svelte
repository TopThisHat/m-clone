<script lang="ts">
	import { onMount } from 'svelte';
	import { listComments, createComment, deleteComment, type Comment } from '$lib/api/comments';
	import { currentUser } from '$lib/stores/authStore';

	let { sessionId }: { sessionId: string } = $props();

	let comments = $state<Comment[]>([]);
	let loading = $state(false);
	let newBody = $state('');
	let submitting = $state(false);
	let open = $state(false);
	let error = $state('');

	async function load() {
		if (!sessionId) return;
		loading = true;
		try {
			comments = await listComments(sessionId);
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

	async function submit() {
		const body = newBody.trim();
		if (!body || submitting) return;
		submitting = true;
		error = '';
		try {
			const c = await createComment(sessionId, body);
			comments = [...comments, c];
			newBody = '';
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
		} catch {
			// ignore
		}
	}

	function handleKey(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit();
	}

	// Highlight @mentions in body text
	function highlightMentions(text: string): string {
		return text.replace(/@([A-Za-z0-9_.\-]+)/g, '<span class="text-gold font-medium">@$1</span>');
	}
</script>

<div class="border-t border-navy-700 mt-4">
	<button
		onclick={() => (open = !open)}
		class="flex items-center gap-2 w-full px-4 py-2.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
	>
		<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
				d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
		</svg>
		<span>{comments.length} comment{comments.length !== 1 ? 's' : ''}</span>
		<span class="ml-auto">{open ? '▲' : '▼'}</span>
	</button>

	{#if open}
		<div class="px-4 pb-4 space-y-3">
			{#if loading}
				<p class="text-xs text-slate-600">Loading…</p>
			{:else}
				{#each comments as comment (comment.id)}
					<div class="flex gap-2.5 group">
						<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-[10px] text-gold font-bold flex-shrink-0 mt-0.5">
							{comment.author_name?.charAt(0).toUpperCase() ?? '?'}
						</div>
						<div class="flex-1 min-w-0">
							<div class="flex items-baseline gap-2">
								<span class="text-xs font-medium text-slate-200">{comment.author_name}</span>
								<span class="text-[10px] text-slate-700">{new Date(comment.created_at).toLocaleString()}</span>
								{#if $currentUser?.sid === comment.author_sid}
									<button
										onclick={() => remove(comment.id)}
										class="ml-auto opacity-0 group-hover:opacity-100 text-[10px] text-slate-600 hover:text-red-400 transition-all"
									>
										delete
									</button>
								{/if}
							</div>
							<p class="text-xs text-slate-300 mt-0.5 leading-relaxed">
								{@html highlightMentions(comment.body)}
							</p>
						</div>
					</div>
				{/each}

				{#if comments.length === 0}
					<p class="text-xs text-slate-700 text-center py-2">No comments yet</p>
				{/if}
			{/if}

			<!-- New comment input -->
			{#if $currentUser}
				<div class="mt-3 flex gap-2">
					<div class="w-6 h-6 rounded-full bg-navy-700 flex items-center justify-center text-[10px] text-gold font-bold flex-shrink-0 mt-1">
						{$currentUser.display_name?.charAt(0).toUpperCase() ?? '?'}
					</div>
					<div class="flex-1">
						<textarea
							bind:value={newBody}
							onkeydown={handleKey}
							placeholder="Add a comment… @mention teammates"
							rows="2"
							class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40 resize-none transition-colors"
						></textarea>
						{#if error}
							<p class="text-xs text-red-400 mt-1">{error}</p>
						{/if}
						<div class="flex items-center justify-between mt-1.5">
							<span class="text-[10px] text-slate-700">⌘↵ to submit</span>
							<button
								onclick={submit}
								disabled={!newBody.trim() || submitting}
								class="px-3 py-1 rounded text-xs bg-gold text-navy font-medium disabled:opacity-40 hover:bg-gold/90 transition-colors"
							>
								{submitting ? 'Posting…' : 'Comment'}
							</button>
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
