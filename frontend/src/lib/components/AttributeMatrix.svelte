<script lang="ts">
	import type { Entity } from '$lib/api/entities';
	import type { Attribute } from '$lib/api/attributes';
	import type { Result, Knowledge } from '$lib/api/jobs';

	let {
		entities,
		attributes,
		results,
		knowledge = [],
		campaignId = '',
		minConfidence = 0,
		oncellclick,
	}: {
		entities: Entity[];
		attributes: Attribute[];
		results: Result[];
		knowledge?: Knowledge[];
		campaignId?: string;
		minConfidence?: number;
		oncellclick?: (result: Result) => void;
	} = $props();

	// Build a lookup map: "entityId:attributeId" → Result
	let resultMap = $derived(
		new Map(results.map((r) => [`${r.entity_id}:${r.attribute_id}`, r]))
	);

	// Build knowledge map: "gwm_id:attribute_label" → Knowledge (only from other campaigns)
	let knowledgeMap = $derived(
		new Map(
			knowledge
				.filter((k) => k.source_campaign_id && k.source_campaign_id !== campaignId)
				.map((k) => [`${k.gwm_id}:${k.attribute_label}`, k])
		)
	);

	function getCell(entityId: string, attributeId: string): Result | undefined {
		return resultMap.get(`${entityId}:${attributeId}`);
	}

	function getCachedKnowledge(entity: Entity, attr: Attribute): Knowledge | undefined {
		if (!entity.gwm_id) return undefined;
		return knowledgeMap.get(`${entity.gwm_id}:${attr.label}`);
	}

	function cellClass(result: Result | undefined, cached: Knowledge | undefined, lowConf: boolean): string {
		const base = lowConf ? 'opacity-40 ' : '';
		if (cached) return base + 'bg-yellow-950 text-yellow-300 border-2 border-yellow-500';
		if (!result) return 'bg-navy-700 text-slate-600';
		if (!result.present) return base + 'bg-red-950 text-red-400 border border-red-900';
		// Color-code by confidence
		const conf = result.confidence ?? 0;
		if (conf >= 0.8) return base + 'bg-green-900 text-green-300 border border-green-700';
		if (conf >= 0.5) return base + 'bg-yellow-900/50 text-yellow-300 border border-yellow-700';
		return base + 'bg-orange-950 text-orange-300 border border-orange-800';
	}

	function cellLabel(result: Result | undefined, cached: Knowledge | undefined): string {
		if (cached) return '⚡';
		if (!result) return '—';
		if (result.confidence != null) return result.confidence.toFixed(1);
		return result.present ? '✓' : '✗';
	}

	function handleClick(result: Result | undefined, cached: Knowledge | undefined) {
		if (result && oncellclick) oncellclick(result);
	}

	// Per-entity score for row sorting
	let entityScoreMap = $derived(() => {
		const map = new Map<string, number>();
		for (const entity of entities) {
			let present = 0, total = 0;
			for (const attr of attributes) {
				const r = getCell(entity.id, attr.id);
				if (r) { total++; if (r.present) present++; }
			}
			map.set(entity.id, total > 0 ? present / total : 0);
		}
		return map;
	});
</script>

<div class="overflow-auto">
	<table class="text-sm border-collapse">
		<thead class="sticky top-0 z-20 bg-navy-900">
			<tr>
				<th class="text-left px-3 py-2 text-slate-400 font-medium sticky left-0 bg-navy-900 z-30 min-w-40">
					Entity
				</th>
				{#each attributes as attr (attr.id)}
					<th class="px-2 py-2 text-slate-400 font-medium text-center max-w-28 whitespace-nowrap overflow-hidden text-ellipsis"
					    title="{attr.label} (weight: {attr.weight})">
						{attr.label}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each entities as entity (entity.id)}
				<tr class="border-t border-navy-700 hover:bg-navy-800">
					<td class="px-3 py-2 text-slate-300 sticky left-0 bg-navy-900 font-medium">
						{entity.label}
						{#if entity.gwm_id}
							<span class="text-slate-500 text-xs font-mono ml-1">{entity.gwm_id}</span>
						{/if}
					</td>
					{#each attributes as attr (attr.id)}
						{@const cell = getCell(entity.id, attr.id)}
						{@const cached = getCachedKnowledge(entity, attr)}
						{@const lowConf = minConfidence > 0 && cell != null && cell.confidence != null && cell.confidence < minConfidence}
						<td class="px-2 py-2 text-center">
							<button
								class="w-8 h-8 rounded text-sm font-bold transition-all hover:opacity-80 {cellClass(cell, cached, lowConf)}
								       {(cell || cached) ? 'cursor-pointer' : 'cursor-default'}"
								onclick={() => handleClick(cell, cached)}
								title={cached ? `Cached from ${cached.source_campaign_name}` : (cell?.evidence ?? '')}
							>
								{cellLabel(cell, cached)}
							</button>
						</td>
					{/each}
				</tr>
			{:else}
				<tr>
					<td colspan={attributes.length + 1} class="text-slate-500 text-center py-8">
						No entities in this campaign.
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
