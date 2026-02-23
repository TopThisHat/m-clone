<script lang="ts">
	import { onMount } from 'svelte';
	import { traceStore } from '$lib/stores/traceStore';
	import { chatMessages, reportMarkdown, errorMessage, messageHistory } from '$lib/stores/reportStore';
	import { activeSessionId, sessionList, newResearch } from '$lib/stores/sessionStore';
	import { listSessions, getSession, deleteSession, updateSession } from '$lib/api/sessions';
	import { isStreaming } from '$lib/stores/reportStore';
	import type { TraceStep } from '$lib/stores/traceStore';

	// ── Search ────────────────────────────────────────────────────────────────
	let searchQuery = $state('');
	const filteredSessions = $derived(
		searchQuery.trim()
			? $sessionList.filter((s) =>
					s.title.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: $sessionList
	);

	// ── Rename ────────────────────────────────────────────────────────────────
	let renamingId = $state<string | null>(null);
	let renameValue = $state('');

	function startRename(id: string, currentTitle: string, e: MouseEvent) {
		e.stopPropagation();
		renamingId = id;
		renameValue = currentTitle;
	}

	async function submitRename(id: string) {
		const title = renameValue.trim();
		renamingId = null;
		if (!title) return;
		try {
			await updateSession(id, { title });
			sessionList.update((list) => list.map((s) => (s.id === id ? { ...s, title } : s)));
		} catch {
			// ignore
		}
	}

	function handleRenameKey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter') submitRename(id);
		if (e.key === 'Escape') renamingId = null;
	}

	// ── Timestamps ────────────────────────────────────────────────────────────
	let timeTick = $state(0);

	function relativeTime(isoString: string): string {
		// timeTick dependency forces recompute every minute
		const _tick = timeTick;
		const diff = Date.now() - new Date(isoString).getTime();
		const mins = Math.floor(diff / 60_000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}

	// ── Data ──────────────────────────────────────────────────────────────────
	async function refreshList() {
		try {
			sessionList.set(await listSessions());
		} catch {
			// silently ignore
		}
	}

	onMount(() => {
		refreshList();
		const interval = setInterval(() => timeTick++, 60_000);
		return () => clearInterval(interval);
	});

	async function loadSession(id: string) {
		if ($isStreaming) return;
		try {
			const s = await getSession(id);
			reportMarkdown.set(s.report_markdown);
			messageHistory.set(s.message_history);
			traceStore.restore(s.trace_steps as TraceStep[]);
			errorMessage.set(null);
			activeSessionId.set(id);
			chatMessages.set([
				{ id: crypto.randomUUID(), role: 'user', content: s.query },
				{ id: crypto.randomUUID(), role: 'assistant', content: s.report_markdown }
			]);
		} catch {
			// silently ignore
		}
	}

	async function removeSession(id: string, e: MouseEvent) {
		e.stopPropagation();
		try {
			await deleteSession(id);
			if ($activeSessionId === id) newResearch();
			await refreshList();
		} catch {
			// silently ignore
		}
	}
</script>

<aside class="flex flex-col h-full border-r border-navy-700 bg-navy-950 overflow-hidden w-[220px] flex-shrink-0">
	<!-- Header -->
	<div class="px-4 py-4 border-b border-navy-700 flex-shrink-0">
		<h2 class="font-serif text-sm text-gold tracking-wide uppercase">Sessions</h2>
	</div>

	<!-- New Research button -->
	<div class="px-3 pt-3 pb-2 flex-shrink-0">
		<button
			onclick={newResearch}
			class="w-full flex items-center gap-2 px-3 py-2 rounded text-xs text-slate-400 hover:text-gold hover:bg-navy-800 border border-navy-700 hover:border-gold/30 transition-colors"
		>
			<span class="text-base leading-none">+</span>
			<span>New Research</span>
			<span class="ml-auto text-[10px] text-slate-700">⌘⇧N</span>
		</button>
	</div>

	<!-- Search -->
	<div class="px-3 pb-2 flex-shrink-0">
		<input
			bind:value={searchQuery}
			type="text"
			placeholder="Filter sessions..."
			class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-gold/40 transition-colors"
		/>
	</div>

	<!-- Session list -->
	<div class="flex-1 overflow-y-auto px-2 pb-4 space-y-0.5">
		{#each filteredSessions as session (session.id)}
			{@const isActive = $activeSessionId === session.id}
			<div
				role="button"
				tabindex="0"
				onclick={() => loadSession(session.id)}
				onkeydown={(e) => e.key === 'Enter' && loadSession(session.id)}
				class="group relative flex flex-col gap-0.5 px-3 py-2.5 rounded cursor-pointer transition-colors
					{isActive
						? 'bg-navy-800 border-l-2 border-gold'
						: 'border-l-2 border-transparent hover:bg-navy-800/50'}
					{$isStreaming ? 'opacity-50 pointer-events-none' : ''}"
			>
				<!-- Title or rename input -->
				{#if renamingId === session.id}
					<input
						bind:value={renameValue}
						onblur={() => submitRename(session.id)}
						onkeydown={(e) => handleRenameKey(e, session.id)}
						class="text-xs bg-navy-700 border border-gold/40 rounded px-1.5 py-0.5 text-slate-100 focus:outline-none w-full pr-5"
						autofocus
						onclick={(e) => e.stopPropagation()}
					/>
				{:else}
					<span
						class="text-xs font-medium leading-snug truncate pr-5
							{isActive ? 'text-gold' : 'text-slate-300 group-hover:text-slate-100'}"
						title={session.title}
						ondblclick={(e) => startRename(session.id, session.title, e)}
					>
						{session.title}
					</span>
				{/if}

				<span class="text-[10px] text-slate-600">
					{relativeTime(session.updated_at)}
				</span>

				<!-- Delete button -->
				<button
					onclick={(e) => removeSession(session.id, e)}
					class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400 transition-all text-xs leading-none p-1"
					title="Delete session"
					aria-label="Delete session"
				>
					✕
				</button>
			</div>
		{/each}

		{#if filteredSessions.length === 0}
			<p class="text-[11px] text-slate-700 px-3 pt-4 text-center leading-relaxed">
				{searchQuery ? 'No matching sessions.' : 'No saved sessions yet.\nSubmit a query to begin.'}
			</p>
		{/if}
	</div>
</aside>
