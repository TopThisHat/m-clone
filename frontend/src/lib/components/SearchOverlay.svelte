<script lang="ts">
	import { apiFetch } from '$lib/api/apiFetch';
	import { goto } from '$app/navigation';

	let {
		open = false,
		onclose,
	}: {
		open?: boolean;
		onclose?: () => void;
	} = $props();

	// ── Search state ──────────────────────────────────────────────────────
	let query = $state('');
	let loading = $state(false);
	let results = $state<SearchResults>({ campaigns: [], entities: [], attributes: [], programs: [] });
	let activeFilter = $state<FilterType>('all');
	let highlightIndex = $state(0);
	let inputEl: HTMLInputElement | undefined = $state();
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	type FilterType = 'all' | 'campaigns' | 'entities' | 'attributes' | 'programs';

	interface SearchItem {
		id: string;
		label: string;
		description?: string | null;
		campaign_id?: string;
		campaign_name?: string;
		created_at?: string;
	}

	interface SearchResults {
		campaigns: SearchItem[];
		entities: SearchItem[];
		attributes: SearchItem[];
		programs: SearchItem[];
	}

	const FILTERS: { key: FilterType; label: string; shortcut: string }[] = [
		{ key: 'all', label: 'All', shortcut: '' },
		{ key: 'campaigns', label: 'Campaigns', shortcut: '' },
		{ key: 'entities', label: 'Entities', shortcut: '' },
		{ key: 'attributes', label: 'Attributes', shortcut: '' },
		{ key: 'programs', label: 'Programs', shortcut: '' },
	];

	// ── Flat result list for keyboard nav ─────────────────────────────────
	interface FlatItem {
		type: FilterType;
		item: SearchItem;
	}

	let flatResults = $derived.by((): FlatItem[] => {
		const items: FlatItem[] = [];
		const categories: (Exclude<FilterType, 'all'>)[] = ['campaigns', 'entities', 'attributes', 'programs'];
		for (const cat of categories) {
			if (activeFilter !== 'all' && activeFilter !== cat) continue;
			for (const item of results[cat]) {
				items.push({ type: cat, item });
			}
		}
		return items;
	});

	let totalCount = $derived(
		results.campaigns.length + results.entities.length + results.attributes.length + results.programs.length
	);

	// ── Debounced search ──────────────────────────────────────────────────
	function handleInput() {
		if (debounceTimer) clearTimeout(debounceTimer);
		highlightIndex = 0;
		if (!query.trim()) {
			results = { campaigns: [], entities: [], attributes: [], programs: [] };
			loading = false;
			return;
		}
		loading = true;
		debounceTimer = setTimeout(() => doSearch(query.trim()), 150);
	}

	async function doSearch(q: string) {
		try {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const raw: any = await apiFetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`);
			results = {
				campaigns: (raw.campaigns ?? []).map((c: Record<string, string | null>) => ({
					id: c.id ?? '',
					label: c.name ?? c.label ?? c.id ?? '',
					description: c.description ?? null,
					created_at: c.created_at ?? '',
				})),
				entities: (raw.entities ?? []).map((e: Record<string, string | null>) => ({
					id: e.id ?? '',
					label: e.label ?? e.id ?? '',
					description: e.description ?? null,
					campaign_id: e.campaign_id ?? '',
					campaign_name: e.campaign_name ?? '',
				})),
				attributes: (raw.attributes ?? []).map((a: Record<string, string | null>) => ({
					id: a.id ?? '',
					label: a.label ?? a.id ?? '',
					description: a.description ?? null,
					campaign_id: a.campaign_id ?? '',
					campaign_name: a.campaign_name ?? '',
				})),
				programs: (raw.programs ?? []).map((p: Record<string, string | null>) => ({
					id: p.id ?? '',
					label: p.name ?? p.label ?? p.id ?? '',
					description: p.description ?? null,
				})),
			};
		} catch {
			results = { campaigns: [], entities: [], attributes: [], programs: [] };
		} finally {
			loading = false;
		}
	}

	// ── Navigation ────────────────────────────────────────────────────────
	function navigateToResult(flat: FlatItem) {
		switch (flat.type) {
			case 'campaigns':
				goto(`/campaigns/${flat.item.id}`);
				break;
			case 'entities':
				if (flat.item.campaign_id) goto(`/campaigns/${flat.item.campaign_id}/entities`);
				break;
			case 'attributes':
				if (flat.item.campaign_id) goto(`/campaigns/${flat.item.campaign_id}/attributes`);
				break;
			case 'programs':
				goto(`/campaigns`);
				break;
		}
		close();
	}

	function close() {
		query = '';
		results = { campaigns: [], entities: [], attributes: [], programs: [] };
		highlightIndex = 0;
		activeFilter = 'all';
		onclose?.();
	}

	// ── Keyboard handling ─────────────────────────────────────────────────
	function handleKeydown(e: KeyboardEvent) {
		switch (e.key) {
			case 'Escape':
				e.preventDefault();
				close();
				break;
			case 'ArrowDown':
				e.preventDefault();
				highlightIndex = Math.min(highlightIndex + 1, flatResults.length - 1);
				scrollHighlightedIntoView();
				break;
			case 'ArrowUp':
				e.preventDefault();
				highlightIndex = Math.max(highlightIndex - 1, 0);
				scrollHighlightedIntoView();
				break;
			case 'Enter':
				e.preventDefault();
				if (flatResults[highlightIndex]) {
					navigateToResult(flatResults[highlightIndex]);
				}
				break;
		}
	}

	function scrollHighlightedIntoView() {
		queueMicrotask(() => {
			const el = document.querySelector('[data-search-highlighted="true"]');
			el?.scrollIntoView({ block: 'nearest' });
		});
	}

	// ── Match highlighting (safe — no @html) ─────────────────────────────
	interface HighlightSegment {
		text: string;
		match: boolean;
	}

	function highlightSegments(text: string): HighlightSegment[] {
		if (!query.trim()) return [{ text, match: false }];
		const escaped = query.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const re = new RegExp(`(${escaped})`, 'gi');
		const parts = text.split(re);
		return parts.filter(Boolean).map((part) => ({
			text: part,
			match: re.test(part) || part.toLowerCase() === query.trim().toLowerCase(),
		}));
	}

	// ── Type badge styling ────────────────────────────────────────────────
	function typeBadge(type: FilterType): string {
		switch (type) {
			case 'campaigns': return 'bg-blue-900/50 text-blue-300 border-blue-700';
			case 'entities': return 'bg-emerald-900/50 text-emerald-300 border-emerald-700';
			case 'attributes': return 'bg-purple-900/50 text-purple-300 border-purple-700';
			case 'programs': return 'bg-amber-900/50 text-amber-300 border-amber-700';
			default: return 'bg-navy-700 text-slate-400 border-navy-600';
		}
	}

	function typeLabel(type: FilterType): string {
		return type.charAt(0).toUpperCase() + type.slice(1, -1);
	}

	// ── Global keyboard listener for Cmd+K ────────────────────────────────
	function handleGlobalKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
			e.preventDefault();
			if (open) {
				close();
			}
		}
	}

	// ── Focus trap ───────────────────────────────────────────────────────
	let dialogEl: HTMLDivElement | undefined = $state();

	function trapFocus(e: KeyboardEvent) {
		if (e.key !== 'Tab' || !dialogEl) return;

		const focusable = dialogEl.querySelectorAll<HTMLElement>(
			'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
		);
		if (focusable.length === 0) return;

		const first = focusable[0];
		const last = focusable[focusable.length - 1];

		if (e.shiftKey) {
			if (document.activeElement === first) {
				e.preventDefault();
				last.focus();
			}
		} else {
			if (document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}

	// ── Focus input when opening ──────────────────────────────────────────
	$effect(() => {
		if (open && inputEl) {
			queueMicrotask(() => inputEl?.focus());
		}
	});
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4"
		onmousedown={(e) => { if (e.target === e.currentTarget) close(); }}
	>
		<div class="fixed inset-0 bg-black/60 backdrop-blur-sm"></div>

		<!-- Search dialog -->
		<div
			bind:this={dialogEl}
			class="relative z-10 w-full max-w-xl bg-navy-900 border border-navy-600 rounded-xl shadow-2xl flex flex-col max-h-[60vh] overflow-hidden"
			role="dialog"
			aria-modal="true"
			aria-label="Search"
			tabindex="-1"
			onkeydown={(e) => { handleKeydown(e); trapFocus(e); }}
		>
			<!-- Search input -->
			<div class="flex items-center gap-3 px-4 py-3 border-b border-navy-700">
				<svg class="w-5 h-5 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
				</svg>
				<input
					bind:this={inputEl}
					bind:value={query}
					oninput={handleInput}
					type="text"
					placeholder="Search campaigns, entities, attributes..."
					class="flex-1 bg-transparent text-slate-200 placeholder-slate-500 text-sm focus:outline-none"
					aria-label="Search"
					autocomplete="off"
					spellcheck="false"
				/>
				{#if loading}
					<div class="w-4 h-4 border-2 border-gold/30 border-t-gold rounded-full animate-spin"></div>
				{/if}
				<kbd class="text-[10px] text-slate-500 bg-navy-700 border border-navy-600 px-1.5 py-0.5 rounded font-mono">ESC</kbd>
			</div>

			<!-- Filter chips -->
			<div class="flex items-center gap-1.5 px-4 py-2 border-b border-navy-700/50">
				{#each FILTERS as filter (filter.key)}
					{@const count = filter.key === 'all' ? totalCount : results[filter.key as keyof SearchResults]?.length ?? 0}
					<button
						onclick={() => { activeFilter = filter.key; highlightIndex = 0; }}
						class="text-[11px] px-2.5 py-1 rounded-full border transition-all
							{activeFilter === filter.key
								? 'bg-gold/10 border-gold/40 text-gold font-medium'
								: 'bg-navy-800 border-navy-700 text-slate-400 hover:border-navy-600 hover:text-slate-300'}"
						aria-pressed={activeFilter === filter.key}
					>
						{filter.label}
						{#if query.trim() && count > 0}
							<span class="ml-1 text-[10px] opacity-70">{count}</span>
						{/if}
					</button>
				{/each}
			</div>

			<!-- Results -->
			<div class="flex-1 overflow-y-auto" role="listbox" aria-label="Search results">
				{#if !query.trim()}
					<div class="px-4 py-8 text-center text-sm text-slate-500">
						Type to search across all data
					</div>
				{:else if loading && flatResults.length === 0}
					<div class="px-4 py-8 text-center text-sm text-slate-500">
						Searching...
					</div>
				{:else if flatResults.length === 0 && !loading}
					<div class="px-4 py-8 text-center text-sm text-slate-500">
						No results for "{query}"
					</div>
				{:else}
					{#each flatResults as flat, i (flat.type + ':' + flat.item.id)}
						<button
							class="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors
								{i === highlightIndex ? 'bg-navy-700' : 'hover:bg-navy-800'}"
							role="option"
							aria-selected={i === highlightIndex}
							data-search-highlighted={i === highlightIndex}
							onclick={() => navigateToResult(flat)}
							onmouseenter={() => (highlightIndex = i)}
						>
							<!-- Type badge -->
							<span class="text-[10px] px-1.5 py-0.5 rounded border shrink-0 {typeBadge(flat.type)}">
								{typeLabel(flat.type)}
							</span>

							<!-- Result content -->
							<div class="flex-1 min-w-0">
								<p class="text-sm text-slate-200 truncate">
									{#each highlightSegments(flat.item.label) as seg}
										{#if seg.match}<mark class="bg-gold/30 text-gold rounded-sm px-0.5">{seg.text}</mark>{:else}{seg.text}{/if}
									{/each}
								</p>
								{#if flat.item.campaign_name}
									<p class="text-[11px] text-slate-500 truncate">
										in {flat.item.campaign_name}
									</p>
								{/if}
							</div>

							<!-- Arrow indicator when highlighted -->
							{#if i === highlightIndex}
								<svg class="w-3.5 h-3.5 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
								</svg>
							{/if}
						</button>
					{/each}
				{/if}
			</div>

			<!-- Footer hints -->
			<div class="flex items-center gap-4 px-4 py-2 border-t border-navy-700/50 text-[10px] text-slate-600">
				<span class="flex items-center gap-1">
					<kbd class="bg-navy-700 border border-navy-600 px-1 py-0.5 rounded font-mono">&uarr;</kbd>
					<kbd class="bg-navy-700 border border-navy-600 px-1 py-0.5 rounded font-mono">&darr;</kbd>
					navigate
				</span>
				<span class="flex items-center gap-1">
					<kbd class="bg-navy-700 border border-navy-600 px-1 py-0.5 rounded font-mono">&crarr;</kbd>
					open
				</span>
				<span class="flex items-center gap-1">
					<kbd class="bg-navy-700 border border-navy-600 px-1 py-0.5 rounded font-mono">esc</kbd>
					close
				</span>
			</div>
		</div>
	</div>
{/if}
