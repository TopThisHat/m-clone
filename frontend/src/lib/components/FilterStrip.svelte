<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';

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

	let {
		nodeCount,
		edgeCount,
		selectedTypes,
		selectedFamilies,
		dealModeActive,
		dealPartnerCount,
		metadataKey,
		metadataValue,
		ontoggletype,
		ontogglefamily,
		ontoggledeal,
		onmetadatachange,
		onclearall,
	}: {
		nodeCount: number;
		edgeCount: number;
		selectedTypes: SvelteSet<string>;
		selectedFamilies: SvelteSet<string>;
		dealModeActive: boolean;
		dealPartnerCount: number;
		metadataKey: string;
		metadataValue: string;
		ontoggletype: (type: string) => void;
		ontogglefamily: (family: string) => void;
		ontoggledeal: () => void;
		onmetadatachange: (key: string, value: string) => void;
		onclearall: () => void;
	} = $props();

	let expanded = $state(false);

	let countPillClass = $derived(
		nodeCount <= 100
			? 'bg-green-900/60 text-green-300 border-green-700/50'
			: nodeCount <= 300
				? 'bg-amber-900/60 text-amber-300 border-amber-700/50'
				: 'bg-red-900/60 text-red-300 border-red-700/50'
	);

	let hasActiveFilters = $derived(
		selectedTypes.size > 0 ||
		selectedFamilies.size > 0 ||
		dealModeActive ||
		metadataKey.trim() !== '' ||
		metadataValue.trim() !== ''
	);
</script>

<div class="backdrop-blur-sm bg-navy-900/95 border-t border-navy-700">
	<!-- Collapsed bar (always visible) -->
	<div class="flex items-center gap-3 px-4 py-2">
		<span class="text-xs px-2.5 py-0.5 rounded-full border font-mono {countPillClass}">
			{nodeCount} nodes
		</span>
		<span class="text-xs px-2.5 py-0.5 rounded-full border border-navy-600/60 bg-navy-800/60 text-slate-400">
			{edgeCount} edges
		</span>

		{#if hasActiveFilters}
			<span class="text-[10px] px-1.5 py-0.5 rounded bg-gold/10 border border-gold/20 text-gold">
				filtered
			</span>
		{/if}

		<button
			onclick={() => (expanded = !expanded)}
			class="ml-auto flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
			aria-expanded={expanded}
		>
			Filters
			<svg
				class="w-3.5 h-3.5 transition-transform {expanded ? 'rotate-180' : ''}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				aria-hidden="true"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>
	</div>

	<!-- Expanded filter controls -->
	{#if expanded}
		<div class="border-t border-navy-700/60 px-4 py-3 space-y-3 transition-all duration-200">
			<!-- Entity types -->
			<div class="flex flex-wrap items-center gap-1.5">
				<span class="text-[10px] text-slate-500 uppercase tracking-wider w-14 shrink-0">Types</span>
				{#each ENTITY_TYPES as type (type)}
					<button
						onclick={() => ontoggletype(type)}
						class="text-xs px-2 py-0.5 rounded border transition-colors {selectedTypes.has(type)
							? 'border-gold text-gold bg-gold/10'
							: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
					>
						{TYPE_LABELS[type] ?? type}
					</button>
				{/each}
			</div>

			<!-- Predicate families -->
			<div class="flex flex-wrap items-center gap-1.5">
				<span class="text-[10px] text-slate-500 uppercase tracking-wider w-14 shrink-0">Relations</span>
				{#each PREDICATE_FAMILIES as family (family)}
					<button
						onclick={() => ontogglefamily(family)}
						class="text-xs px-2 py-0.5 rounded border transition-colors {selectedFamilies.has(family)
							? 'border-gold text-gold bg-gold/10'
							: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
					>
						{family}
					</button>
				{/each}
			</div>

			<!-- Deal Partners + Metadata + Clear All -->
			<div class="flex flex-wrap items-center gap-3">
				<button
					onclick={ontoggledeal}
					class="text-xs px-2.5 py-1 rounded border transition-colors {dealModeActive
						? 'border-[#C0922B] text-[#C0922B] bg-[#C0922B]/10'
						: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
				>
					Deal Partners{dealPartnerCount > 0 ? ` (${dealPartnerCount})` : ''}
				</button>

				<div class="flex items-center gap-1">
					<span class="text-[10px] text-slate-500">Metadata:</span>
					<input
						value={metadataKey}
						oninput={(e) => onmetadatachange((e.target as HTMLInputElement).value, metadataValue)}
						placeholder="Key"
						class="bg-navy-800 border border-navy-600 rounded px-2 py-0.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-24"
					/>
					<input
						value={metadataValue}
						oninput={(e) => onmetadatachange(metadataKey, (e.target as HTMLInputElement).value)}
						placeholder="Value"
						class="bg-navy-800 border border-navy-600 rounded px-2 py-0.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-24"
					/>
				</div>

				{#if hasActiveFilters}
					<button
						onclick={onclearall}
						class="ml-auto text-xs text-slate-500 hover:text-red-400 transition-colors"
					>
						Clear All
					</button>
				{/if}
			</div>
		</div>
	{/if}
</div>
