<script lang="ts">
	import type { Result } from '$lib/api/jobs';
	import type { Entity } from '$lib/api/entities';

	let {
		attributeId,
		attributeLabel,
		entities,
		results,
		active = false,
		ontoggle,
	}: {
		attributeId: string;
		attributeLabel: string;
		entities: Entity[];
		results: Result[];
		active?: boolean;
		ontoggle?: (attributeId: string) => void;
	} = $props();

	// Filter results for this attribute and compute stats
	let columnResults = $derived(
		results.filter((r) => r.attribute_id === attributeId)
	);

	let stats = $derived.by(() => {
		const total = entities.length;
		const filled = columnResults.length;
		const present = columnResults.filter((r) => r.present).length;
		const confidences = columnResults
			.map((r) => r.confidence)
			.filter((c): c is number => c !== null);
		const avgConfidence =
			confidences.length > 0
				? confidences.reduce((a, b) => a + b, 0) / confidences.length
				: null;

		return {
			total,
			filled,
			present,
			absent: filled - present,
			fillRate: total > 0 ? filled / total : 0,
			presenceRate: filled > 0 ? present / filled : 0,
			avgConfidence,
		};
	});

	// Build a lookup for per-entity heatmap intensity
	let heatmap = $derived(
		new Map(
			columnResults.map((r) => [
				r.entity_id,
				{
					present: r.present,
					confidence: r.confidence,
					intensity: r.confidence ?? (r.present ? 0.7 : 0.2),
				},
			])
		)
	);

	function intensityColor(intensity: number, present: boolean): string {
		if (!present) return `rgba(239, 68, 68, ${0.2 + intensity * 0.5})`;
		return `rgba(34, 197, 94, ${0.2 + intensity * 0.6})`;
	}

	function barWidth(rate: number): string {
		return `${Math.max(2, rate * 100)}%`;
	}
</script>

{#if active}
	<div class="absolute inset-0 z-10 pointer-events-none">
		<!-- Per-entity heatmap bars (rendered in the column context by the parent) -->
		{#each entities as entity, i (entity.id)}
			{@const cell = heatmap.get(entity.id)}
			{#if cell}
				<div
					class="absolute left-0 right-0 opacity-40 rounded-sm"
					style="
						top: {i * 44 + 40}px;
						height: 44px;
						background: {intensityColor(cell.intensity, cell.present)};
					"
				></div>
			{/if}
		{/each}
	</div>
{/if}

<!-- Toggle button + stats popup -->
<div class="relative inline-flex items-center group">
	<button
		onclick={() => ontoggle?.(attributeId)}
		class="min-w-[44px] min-h-[44px] flex items-center justify-center transition-all"
		title="Toggle heatmap for {attributeLabel}"
		aria-pressed={active}
		aria-label="Toggle heatmap for {attributeLabel}"
	>
		<span class="w-4 h-4 rounded-sm border flex items-center justify-center
			{active
				? 'border-gold bg-gold/20 text-gold'
				: 'border-navy-600 bg-navy-700 text-slate-500 hover:border-navy-500 hover:text-slate-400'}">
		<svg class="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 16 16">
			<rect x="1" y="1" width="6" height="6" rx="1" opacity="0.9" />
			<rect x="9" y="1" width="6" height="6" rx="1" opacity="0.5" />
			<rect x="1" y="9" width="6" height="6" rx="1" opacity="0.3" />
			<rect x="9" y="9" width="6" height="6" rx="1" opacity="0.7" />
		</svg>
		</span>
	</button>

	<!-- Stats tooltip on hover -->
	<div
		class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block group-focus-within:block
			bg-navy-900 border border-navy-600 rounded-lg p-3 shadow-xl z-50 min-w-48"
		role="tooltip"
	>
		<p class="text-xs text-slate-300 font-medium mb-2 truncate">{attributeLabel}</p>
		<div class="space-y-1.5 text-xs">
			<div class="flex justify-between">
				<span class="text-slate-500">Fill rate</span>
				<div class="flex items-center gap-1.5">
					<div class="w-16 h-1.5 bg-navy-700 rounded-full overflow-hidden">
						<div class="h-full bg-gold rounded-full" style="width: {barWidth(stats.fillRate)}"></div>
					</div>
					<span class="text-slate-300 font-mono w-10 text-right">{(stats.fillRate * 100).toFixed(0)}%</span>
				</div>
			</div>
			<div class="flex justify-between">
				<span class="text-slate-500">Presence</span>
				<div class="flex items-center gap-1.5">
					<div class="w-16 h-1.5 bg-navy-700 rounded-full overflow-hidden">
						<div class="h-full bg-green-500 rounded-full" style="width: {barWidth(stats.presenceRate)}"></div>
					</div>
					<span class="text-slate-300 font-mono w-10 text-right">{(stats.presenceRate * 100).toFixed(0)}%</span>
				</div>
			</div>
			{#if stats.avgConfidence !== null}
				<div class="flex justify-between">
					<span class="text-slate-500">Avg confidence</span>
					<span class="text-slate-300 font-mono">{(stats.avgConfidence * 100).toFixed(0)}%</span>
				</div>
			{/if}
			<div class="flex justify-between text-slate-500">
				<span>{stats.present} present</span>
				<span>{stats.absent} absent</span>
				<span>{stats.total - stats.filled} empty</span>
			</div>
		</div>
		<!-- Tooltip arrow -->
		<div class="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-navy-900 border-r border-b border-navy-600 rotate-45 -mt-1"></div>
	</div>
</div>
