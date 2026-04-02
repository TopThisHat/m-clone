<script lang="ts">
	import { kgApi, type KGSuggestResult } from '$lib/api/knowledgeGraph';

	const ENTITY_TYPES = ['person', 'company', 'sports_team', 'location', 'product', 'other'];
	const PREDICATE_FAMILIES = ['ownership', 'employment', 'transaction', 'location', 'partnership'];

	const TYPE_LABELS: Record<string, string> = {
		person: 'Person',
		company: 'Company',
		sports_team: 'Sports Team',
		location: 'Location',
		product: 'Product',
		other: 'Other',
	};

	const TYPE_COLORS: Record<string, string> = {
		person: 'bg-[#1B365D]',
		company: 'bg-[#1A5276]',
		sports_team: 'bg-[#8B6914]',
		location: 'bg-[#1E6E3E]',
		product: 'bg-[#5D6D7E]',
		other: 'bg-[#7B8794]',
	};

	interface FilterItem {
		kind: 'entity_type' | 'predicate_family';
		value: string;
		label: string;
	}

	let {
		open = $bindable(false),
		teamId,
		onSelectEntity,
		onSelectFilter,
	}: {
		open?: boolean;
		teamId: string | null;
		onSelectEntity: (entityId: string) => void;
		onSelectFilter: (kind: 'entity_type' | 'predicate_family', value: string) => void;
	} = $props();

	let query = $state('');
	let results = $state<KGSuggestResult[]>([]);
	let loading = $state(false);
	let selectedIndex = $state(-1);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let inputEl = $state<HTMLInputElement | null>(null);

	// Filter suggestions derived from current query
	let filterItems = $derived.by((): FilterItem[] => {
		const q = query.trim().toLowerCase();
		if (!q) return [];
		const items: FilterItem[] = [];
		for (const t of ENTITY_TYPES) {
			if (TYPE_LABELS[t].toLowerCase().includes(q) || t.includes(q)) {
				items.push({ kind: 'entity_type', value: t, label: `Show only ${TYPE_LABELS[t]}` });
			}
		}
		for (const f of PREDICATE_FAMILIES) {
			if (f.includes(q)) {
				items.push({ kind: 'predicate_family', value: f, label: `Show only ${f} relationships` });
			}
		}
		return items;
	});

	// Flat list of all selectable items for keyboard nav
	let allItems = $derived<Array<{ type: 'entity'; data: KGSuggestResult } | { type: 'filter'; data: FilterItem }>>([
		...results.map((r) => ({ type: 'entity' as const, data: r })),
		...filterItems.map((f) => ({ type: 'filter' as const, data: f })),
	]);

	// Auto-focus input when palette opens
	$effect(() => {
		if (open && inputEl) {
			inputEl.focus();
		}
		if (!open) {
			query = '';
			results = [];
			selectedIndex = -1;
		}
	});

	// Debounced search
	$effect(() => {
		const q = query;
		if (debounceTimer) clearTimeout(debounceTimer);
		if (!q.trim() || !teamId) {
			results = [];
			selectedIndex = -1;
			return;
		}
		debounceTimer = setTimeout(async () => {
			loading = true;
			try {
				results = await kgApi.suggest(q.trim(), teamId, 10);
				selectedIndex = -1;
			} catch {
				results = [];
			} finally {
				loading = false;
			}
		}, 150);
	});

	function close() {
		open = false;
	}

	function selectItem(index: number) {
		const item = allItems[index];
		if (!item) return;
		if (item.type === 'entity') {
			onSelectEntity(item.data.id);
		} else {
			onSelectFilter(item.data.kind, item.data.value);
		}
		close();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			close();
			return;
		}
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = Math.min(selectedIndex + 1, allItems.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = Math.max(selectedIndex - 1, 0);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (selectedIndex >= 0) {
				selectItem(selectedIndex);
			}
		}
	}

	function entityItemIndex(i: number) {
		return i;
	}

	function filterItemIndex(i: number) {
		return results.length + i;
	}

	function typeColor(type: string): string {
		return TYPE_COLORS[type.toLowerCase()] ?? 'bg-[#7B8794]';
	}

	function typeLabel(type: string): string {
		return TYPE_LABELS[type.toLowerCase()] ?? type;
	}
</script>

{#if open}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/60 backdrop-blur-sm"
		role="dialog"
		aria-modal="true"
		aria-label="Command palette"
		tabindex="-1"
		onclick={close}
		onkeydown={(e) => e.key === 'Escape' && close()}
	>
		<!-- Panel — stop click propagation so clicking inside doesn't close -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="w-full max-w-xl bg-navy-900 border border-navy-600 rounded-lg shadow-2xl overflow-hidden"
			role="document"
			onclick={(e) => e.stopPropagation()}
			onkeydown={handleKeydown}
		>
			<!-- Search input -->
			<div class="flex items-center gap-2 px-4 py-3 border-b border-navy-700">
				<svg class="w-4 h-4 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
				</svg>
				<input
					bind:this={inputEl}
					bind:value={query}
					type="text"
					placeholder="Search Knowledge Graph..."
					class="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 outline-none"
					autocomplete="off"
					spellcheck={false}
				/>
				{#if loading}
					<svg class="w-4 h-4 text-slate-500 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
					</svg>
				{/if}
				<kbd class="hidden sm:block text-xs text-slate-500 bg-navy-800 border border-navy-600 rounded px-1.5 py-0.5">Esc</kbd>
			</div>

			<!-- Results -->
			{#if query.trim()}
				<div class="max-h-80 overflow-y-auto">
					<!-- Entities section -->
					{#if results.length > 0}
						<div class="px-3 pt-2 pb-1">
							<span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Entities</span>
						</div>
						{#each results as entity, i (entity.id)}
							{@const idx = entityItemIndex(i)}
							<button
								class="w-full flex items-center gap-3 px-4 py-2 text-left hover:bg-navy-800 transition-colors {selectedIndex === idx ? 'bg-navy-800' : ''}"
								onclick={() => selectItem(idx)}
								onmouseenter={() => { selectedIndex = idx; }}
							>
								<span class="text-sm text-slate-100 truncate flex-1">{entity.name}</span>
								<span class="text-xs px-1.5 py-0.5 rounded {typeColor(entity.entity_type)} text-slate-200 shrink-0">
									{typeLabel(entity.entity_type)}
								</span>
								<span class="text-xs text-slate-500 shrink-0">{entity.relationship_count} rels</span>
							</button>
						{/each}
					{/if}

					<!-- Filters section -->
					{#if filterItems.length > 0}
						<div class="px-3 pt-2 pb-1 {results.length > 0 ? 'border-t border-navy-700 mt-1' : ''}">
							<span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Filters</span>
						</div>
						{#each filterItems as filter, i (filter.kind + ':' + filter.value)}
							{@const idx = filterItemIndex(i)}
							<button
								class="w-full flex items-center gap-2 px-4 py-2 text-left hover:bg-navy-800 transition-colors {selectedIndex === idx ? 'bg-navy-800' : ''}"
								onclick={() => selectItem(idx)}
								onmouseenter={() => { selectedIndex = idx; }}
							>
								<svg class="w-3.5 h-3.5 text-gold shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
								</svg>
								<span class="text-sm text-slate-200">{filter.label}</span>
							</button>
						{/each}
					{/if}

					<!-- Empty state -->
					{#if results.length === 0 && filterItems.length === 0 && !loading}
						<div class="px-4 py-8 text-center text-sm text-slate-500">
							No results for &ldquo;{query}&rdquo;
						</div>
					{/if}
				</div>
			{:else}
				<div class="px-4 py-6 text-center text-sm text-slate-500">
					Type to search entities or filters
				</div>
			{/if}
		</div>
	</div>
{/if}
