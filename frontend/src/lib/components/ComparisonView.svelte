<script lang="ts">
	import type {
		ComparisonOut,
		ComparisonEntityInfo,
		ComparisonAttributeRow,
		ComparisonEntityValue,
	} from '$lib/api/campaigns';

	let {
		data,
		ondismiss,
	}: {
		data: ComparisonOut;
		ondismiss?: () => void;
	} = $props();

	// ── Best/Worst highlighting logic (uses backend-computed values) ─────────

	type Highlight = 'best' | 'worst' | null;

	function getHighlight(
		row: ComparisonAttributeRow,
		entityId: string
	): Highlight {
		if (row.best_entity_ids.includes(entityId)) return 'best';
		if (row.worst_entity_ids.includes(entityId)) return 'worst';
		return null;
	}

	function highlightClass(highlight: Highlight): string {
		if (highlight === 'best') return 'ring-2 ring-green-500/60 bg-green-950/30';
		if (highlight === 'worst') return 'ring-2 ring-red-500/60 bg-red-950/30';
		return '';
	}

	// ── Score highlight (uses backend-computed values) ──────────────────────

	let bestScoreIds = $derived(new Set(data.highlights.best_score_entity_ids));
	let worstScoreIds = $derived(new Set(data.highlights.worst_score_entity_ids));

	// ── Group attributes by category ─────────────────────────────────────────

	let groupedAttributes = $derived.by(() => {
		const groups = new Map<string, ComparisonAttributeRow[]>();
		for (const attr of data.attributes) {
			const cat = attr.category ?? 'Uncategorized';
			const arr = groups.get(cat);
			if (arr) arr.push(attr);
			else groups.set(cat, [attr]);
		}
		return groups;
	});

	// ── Keyboard handling ────────────────────────────────────────────────────

	function handleKeydown(e: KeyboardEvent) {
		// Escape is handled natively by <dialog> — fires onclose which calls handleClose
	}

	function formatConfidence(val: ComparisonEntityValue | null): string {
		if (!val) return '\u2014';
		if (val.confidence !== null) return `${(val.confidence * 100).toFixed(0)}%`;
		return val.present ? '\u2713' : '\u2717';
	}

	function cellStatusClass(val: ComparisonEntityValue | null): string {
		if (!val) return 'text-slate-600';
		if (!val.present) return 'text-red-400';
		if (val.confidence === null) return 'text-slate-400';
		if (val.confidence >= 0.8) return 'text-green-400';
		if (val.confidence >= 0.5) return 'text-yellow-300';
		return 'text-orange-400';
	}

	function scoreHighlightClass(entity: ComparisonEntityInfo): string {
		if (bestScoreIds.has(entity.id)) return 'text-green-400';
		if (worstScoreIds.has(entity.id)) return 'text-red-400';
		return '';
	}

	// ── Auto-focus and return-focus on close ───────────────────────────────
	let panel: HTMLDialogElement | undefined = $state();
	let triggerEl: HTMLElement | null = null;

	$effect(() => {
		if (panel) {
			triggerEl = document.activeElement as HTMLElement | null;
			panel.showModal();
		}
	});

	function handleClose() {
		queueMicrotask(() => triggerEl?.focus());
		ondismiss?.();
	}
</script>

<dialog
	bind:this={panel}
	class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden backdrop:bg-black/60 max-w-5xl w-full max-h-[90vh] p-0"
	aria-label="Entity comparison view"
	onclose={handleClose}
	onkeydown={handleKeydown}
>
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-3 border-b border-navy-700 bg-navy-900">
		<div class="flex items-center gap-3">
			<h3 class="font-serif text-gold text-lg font-bold">
				Comparing {data.summary.entity_count} Entities
			</h3>
			<span class="text-xs text-slate-500">
				{data.summary.attribute_count} attributes
			</span>
		</div>
		{#if ondismiss}
			<button
				onclick={() => panel?.close()}
				class="text-slate-400 hover:text-slate-200 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
				aria-label="Close comparison (Escape)"
				title="Close (Esc)"
			>
				<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		{/if}
	</div>

	<!-- Comparison table -->
	<div class="overflow-auto max-h-[75vh]">
		<table class="w-full text-sm border-collapse">
			<thead class="sticky top-0 z-20 bg-navy-900">
				<tr>
					<th
						class="text-left px-4 py-3 text-slate-400 font-medium sticky left-0 bg-navy-900 z-30 min-w-48 border-b border-navy-700"
						scope="col"
					>
						Attribute
					</th>
					{#each data.entities as entity (entity.id)}
						<th
							class="px-4 py-3 text-center font-medium border-b border-navy-700 min-w-36"
							scope="col"
						>
							<div class="text-slate-200 truncate" title={entity.label}>
								{entity.label}
							</div>
							{#if entity.gwm_id}
								<div class="text-xs text-slate-500 font-mono">{entity.gwm_id}</div>
							{/if}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				<!-- Score row -->
				<tr class="border-b border-navy-600 bg-navy-800">
					<td class="px-4 py-2.5 text-slate-300 font-medium sticky left-0 bg-navy-800 z-10">
						Overall Score
					</td>
					{#each data.entities as entity (entity.id)}
						<td class="px-4 py-2.5 text-center">
							<span class="font-mono font-bold text-base {scoreHighlightClass(entity)}">
								{entity.total_score !== null ? entity.total_score.toFixed(2) : '\u2014'}
							</span>
							{#if entity.attributes_present !== null && entity.attributes_checked !== null}
								<div class="text-xs text-slate-500 mt-0.5">
									{entity.attributes_present}/{entity.attributes_checked} present
								</div>
							{/if}
						</td>
					{/each}
				</tr>

				<!-- Attribute rows grouped by category -->
				{#each [...groupedAttributes] as [category, attrs] (category)}
					{#if groupedAttributes.size > 1}
						<tr class="border-b border-navy-700">
							<td
								colspan={data.entities.length + 1}
								class="px-4 py-2 text-xs text-slate-500 uppercase tracking-wider font-semibold bg-navy-900/50"
							>
								{category}
							</td>
						</tr>
					{/if}
					{#each attrs as row (row.attribute_id)}
						<tr class="border-b border-navy-700 hover:bg-navy-700 transition-colors">
							<td
								class="px-4 py-2.5 text-slate-300 sticky left-0 bg-navy-800 z-10"
								title={row.description ?? row.label}
							>
								<div class="flex items-center gap-2">
									<span>{row.label}</span>
									{#if row.weight !== 1.0}
										<span class="text-xs text-slate-600 bg-navy-700 px-1 py-0.5 rounded">
											w:{row.weight.toFixed(1)}
										</span>
									{/if}
								</div>
							</td>
							{#each data.entities as entity (entity.id)}
								{@const val = row.entity_values[entity.id] ?? null}
								{@const highlight = getHighlight(row, entity.id)}
								<td class="px-4 py-2.5 text-center">
									<div
										class="inline-flex flex-col items-center rounded-md px-2 py-1 transition-all {highlightClass(highlight)}"
										title={val?.evidence ?? ''}
									>
										<span class="font-mono font-semibold {cellStatusClass(val)}">
											{formatConfidence(val)}
										</span>
										{#if val?.evidence}
											<span class="text-xs text-slate-500 max-w-24 truncate mt-0.5">
												{val.evidence}
											</span>
										{/if}
									</div>
								</td>
							{/each}
						</tr>
					{/each}
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Legend -->
	<div class="flex items-center gap-4 px-4 py-2.5 border-t border-navy-700 bg-navy-900 text-xs text-slate-500">
		<span class="flex items-center gap-1.5">
			<span class="w-3 h-3 rounded ring-2 ring-green-500/60 bg-green-950/30"></span>
			Best
		</span>
		<span class="flex items-center gap-1.5">
			<span class="w-3 h-3 rounded ring-2 ring-red-500/60 bg-red-950/30"></span>
			Worst
		</span>
		<span class="ml-auto">Press <kbd class="bg-navy-700 px-1.5 py-0.5 rounded text-slate-400">Esc</kbd> to close</span>
	</div>
</dialog>
