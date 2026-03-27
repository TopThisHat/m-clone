<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { traceStore } from '$lib/stores/traceStore';
	import { chatMessages, reportMarkdown, errorMessage, messageHistory, chartData, docSessionKey, docContextExpired } from '$lib/stores/reportStore';
	import { checkDocSessionAlive } from '$lib/api/documents';
	import { activeSessionId, sessionList, newResearch } from '$lib/stores/sessionStore';
	import { listSessions, getSession, deleteSession, updateSession } from '$lib/api/sessions';
	import { isStreaming } from '$lib/stores/reportStore';
	import type { TraceStep } from '$lib/stores/traceStore';
	import type { ChartPayload } from '$lib/stores/reportStore';

	let { onclose }: { onclose?: () => void } = $props();

	// ── Search ────────────────────────────────────────────────────────────────
	let searchQuery = $state('');
	let _searchTimer: ReturnType<typeof setTimeout> | undefined;

	function handleSearchInput(e: Event) {
		searchQuery = (e.target as HTMLInputElement).value;
		clearTimeout(_searchTimer);
		_searchTimer = setTimeout(async () => {
			try {
				sessionList.set(await listSessions(searchQuery.trim() || undefined));
			} catch {
				// ignore
			}
		}, 300);
	}

	// ── Rename ────────────────────────────────────────────────────────────────
	let renamingId = $state<string | null>(null);
	let renameValue = $state('');
	let confirmDeleteId = $state<string | null>(null);
	let confirmDialogEl = $state<HTMLDivElement | null>(null);

	// Focus the alertdialog when delete confirmation appears
	$effect(() => {
		if (confirmDeleteId && confirmDialogEl) {
			tick().then(() => confirmDialogEl?.focus());
		}
	});

	function startRename(id: string, currentTitle: string, e: MouseEvent | KeyboardEvent) {
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
			const steps = s.trace_steps as TraceStep[];
			reportMarkdown.set(s.report_markdown);
			messageHistory.set(s.message_history);
			traceStore.restore(steps);
			errorMessage.set(null);
			docSessionKey.set(s.doc_session_key ?? undefined);
			activeSessionId.set(id);
			chatMessages.set([
				{ id: crypto.randomUUID(), role: 'user', content: s.query },
				{ id: crypto.randomUUID(), role: 'assistant', content: s.report_markdown }
			]);
			// Restore persisted charts from trace steps
			const charts = steps
				.filter((step) => step.chart)
				.map((step) => step.chart as unknown as ChartPayload);
			chartData.set(charts);

			// Check if document context is still alive in Redis
			if (s.doc_session_key) {
				const alive = await checkDocSessionAlive(s.doc_session_key);
				docContextExpired.set(!alive);
			} else {
				docContextExpired.set(false);
			}
		} catch {
			// silently ignore
		}
	}

	function requestDelete(id: string, e: MouseEvent | KeyboardEvent) {
		e.stopPropagation();
		confirmDeleteId = id;
	}

	function cancelDelete(e: MouseEvent | KeyboardEvent) {
		e.stopPropagation();
		confirmDeleteId = null;
	}

	async function confirmDelete(id: string, e: MouseEvent | KeyboardEvent) {
		e.stopPropagation();
		confirmDeleteId = null;
		try {
			await deleteSession(id);
			if ($activeSessionId === id) newResearch();
			await refreshList();
		} catch {
			// silently ignore
		}
	}
</script>

<aside class="flex flex-col h-full border-r border-navy-700 bg-navy-950 overflow-hidden w-64 md:w-[220px]">
	<!-- Header -->
	<div class="px-4 py-4 border-b border-navy-700 flex-shrink-0 flex items-center justify-between">
		<h2 class="font-serif text-sm text-gold tracking-wide uppercase">Sessions</h2>
		{#if onclose}
			<button
				onclick={onclose}
				class="md:hidden text-slate-500 hover:text-slate-300 text-xl leading-none p-1"
				aria-label="Close sidebar"
			>
				×
			</button>
		{/if}
	</div>

	<!-- New Research button -->
	<div class="px-3 pt-3 pb-2 flex-shrink-0">
		<button
			onclick={newResearch}
			class="w-full flex items-center gap-2 px-3 py-2 rounded text-xs text-slate-400 hover:text-gold hover:bg-navy-800 border border-navy-700 hover:border-gold/30 transition-colors"
		>
			<span class="text-base leading-none">+</span>
			<span>New Research</span>
			<span class="ml-auto text-xs text-slate-700">⌘⇧N</span>
		</button>
	</div>

	<!-- Search -->
	<div class="px-3 pb-2 flex-shrink-0">
		<input
			value={searchQuery}
			oninput={handleSearchInput}
			type="text"
			placeholder="Filter sessions..."
			aria-label="Filter sessions"
			class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-gold/40 transition-colors"
		/>
	</div>

	<!-- Session list -->
	<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-4 space-y-0.5">
		{#each $sessionList as session (session.id)}
			{@const isActive = $activeSessionId === session.id}
			<div
				class="group relative flex flex-col rounded transition-colors
					{isActive
						? 'bg-navy-800 border-l-2 border-gold'
						: 'border-l-2 border-transparent hover:bg-navy-800/50'}
					{$isStreaming ? 'opacity-50 pointer-events-none' : ''}"
			>
				{#if renamingId === session.id}
					<!-- Rename mode -->
					<div class="px-3 py-2.5 flex flex-col gap-0.5">
						<!-- svelte-ignore a11y_autofocus -->
						<input
							bind:value={renameValue}
							onblur={() => submitRename(session.id)}
							onkeydown={(e) => handleRenameKey(e, session.id)}
							class="text-xs bg-navy-700 border border-gold/40 rounded px-1.5 py-0.5 text-slate-100 focus:outline-none w-full"
							aria-label="Rename session"
							autofocus
						/>
						<span class="text-xs text-slate-600 flex items-center gap-1">
							{relativeTime(session.updated_at)}
						</span>
					</div>
				{:else if confirmDeleteId === session.id}
					<!-- Delete confirmation -->
					<div
						bind:this={confirmDialogEl}
						class="flex items-center justify-between px-3 py-2.5"
						role="alertdialog"
						tabindex="-1"
						aria-label="Confirm deletion of {session.title}"
						onkeydown={(e) => { if (e.key === 'Escape') cancelDelete(e); }}
					>
						<span class="text-xs text-slate-300 truncate mr-2">Delete this session?</span>
						<div class="flex items-center gap-1.5 flex-shrink-0">
							<button
								onclick={(e) => confirmDelete(session.id, e)}
								class="text-xs text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded hover:bg-navy-800"
							>
								Delete
							</button>
							<button
								onclick={(e) => cancelDelete(e)}
								class="text-xs text-slate-400 hover:text-slate-300 px-1.5 py-0.5 rounded hover:bg-navy-800"
							>
								Cancel
							</button>
						</div>
					</div>
				{:else}
					<!-- Normal mode: proper button, no nested interactives -->
					<button
						onclick={() => loadSession(session.id)}
						ondblclick={(e) => startRename(session.id, session.title, e)}
						onkeydown={(e) => {
							if (e.key === 'F2') { e.preventDefault(); startRename(session.id, session.title, e); }
						}}
						class="w-full text-left flex flex-col gap-0.5 px-3 py-2.5 cursor-pointer"
						aria-label="Session: {session.title}"
						aria-current={isActive ? 'true' : undefined}
					>
						<span
							class="text-xs font-medium leading-snug truncate pr-5
								{isActive ? 'text-gold' : 'text-slate-300 group-hover:text-slate-100'}"
							title="Double-click or F2 to rename: {session.title}"
						>
							{session.title}
						</span>
						<span class="text-xs text-slate-600 flex items-center gap-1">
							{relativeTime(session.updated_at)}
							{#if session.doc_session_key}
								<svg class="w-3 h-3 text-slate-500 inline-block" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
								</svg>
							{/if}
						</span>
					</button>
					<!-- Delete button — sibling of session button, not nested -->
					<button
						onclick={(e) => requestDelete(session.id, e)}
						class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus:opacity-100 text-slate-600 hover:text-red-400 transition-all text-xs leading-none p-1"
						title="Delete session"
						aria-label="Delete session: {session.title}"
					>
						✕
					</button>
				{/if}
			</div>
		{/each}

		{#if $sessionList.length === 0}
			<p class="text-xs text-slate-700 px-3 pt-4 text-center leading-relaxed">
				{searchQuery ? 'No matching sessions.' : 'No saved sessions yet.\nSubmit a query to begin.'}
			</p>
		{/if}
	</div>

	<!-- Monitors nav link -->
	<div class="px-3 py-2 border-t border-navy-700 flex-shrink-0">
		<a
			href="/monitors"
			class="block px-3 py-2 text-xs text-slate-500 hover:text-gold transition-colors rounded hover:bg-navy-800/50"
		>
			Monitors
		</a>
	</div>
</aside>
