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

	// Virtual scrolling constants
	const ROW_HEIGHT = 44;
	const OVERSCAN = 5;
	const VIRTUAL_THRESHOLD = 50;

	let scrollContainer: HTMLDivElement;
	let scrollTop = $state(0);
	let containerHeight = $state(600);

	// Keyboard navigation
	let focusRow = $state(0);
	let focusCol = $state(0);

	// Build a lookup map: "entityId:attributeId" -> Result
	let resultMap = $derived(
		new Map(results.map((r) => [`${r.entity_id}:${r.attribute_id}`, r]))
	);

	// Build knowledge map: "gwm_id:attribute_label" -> Knowledge (only from other campaigns)
	let knowledgeMap = $derived(
		new Map(
			knowledge
				.filter((k) => k.source_campaign_id && k.source_campaign_id !== campaignId)
				.map((k) => [`${k.gwm_id}:${k.attribute_label}`, k])
		)
	);

	// Virtual scrolling derived state
	let useVirtualScroll = $derived(entities.length > VIRTUAL_THRESHOLD);
	let totalHeight = $derived(entities.length * ROW_HEIGHT);
	let startIndex = $derived(
		useVirtualScroll
			? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
			: 0
	);
	let endIndex = $derived(
		useVirtualScroll
			? Math.min(entities.length, Math.ceil((scrollTop + containerHeight) / ROW_HEIGHT) + OVERSCAN)
			: entities.length
	);
	let visibleEntities = $derived(entities.slice(startIndex, endIndex));
	let topPadding = $derived(startIndex * ROW_HEIGHT);
	let bottomPadding = $derived((entities.length - endIndex) * ROW_HEIGHT);

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
		if (result.confidence === null) return base + 'bg-slate-800 text-slate-400 border border-slate-600';
		const conf = result.confidence;
		if (conf >= 0.8) return base + 'bg-green-900 text-green-300 border border-green-700';
		if (conf >= 0.5) return base + 'bg-yellow-900/50 text-yellow-300 border border-yellow-700';
		return base + 'bg-orange-950 text-orange-300 border border-orange-800';
	}

	function cellLabel(result: Result | undefined, cached: Knowledge | undefined): string {
		if (cached) return '\u26A1';
		if (!result) return '\u2014';
		if (result.confidence != null) return result.confidence.toFixed(1);
		return result.present ? '\u2713' : '\u2717';
	}

	function cellAriaLabel(entity: Entity, attr: Attribute, result: Result | undefined, cached: Knowledge | undefined): string {
		const entityName = entity.label || entity.gwm_id || entity.id;
		const status = cached
			? 'cached from another campaign'
			: !result
				? 'not validated'
				: result.confidence === null
					? (result.present ? 'present, no confidence data' : 'absent, no confidence data')
					: result.present
						? `present, confidence ${(result.confidence * 100).toFixed(0)}%`
						: 'absent';
		return `${entityName}, ${attr.label}: ${status}`;
	}

	function handleClick(result: Result | undefined) {
		if (result && oncellclick) oncellclick(result);
	}

	function handleScroll() {
		if (scrollContainer) {
			scrollTop = scrollContainer.scrollTop;
			containerHeight = scrollContainer.clientHeight;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		const maxRow = entities.length - 1;
		const maxCol = attributes.length - 1;

		switch (e.key) {
			case 'ArrowDown':
				e.preventDefault();
				focusRow = Math.min(focusRow + 1, maxRow);
				scrollToRow(focusRow);
				break;
			case 'ArrowUp':
				e.preventDefault();
				focusRow = Math.max(focusRow - 1, 0);
				scrollToRow(focusRow);
				break;
			case 'ArrowRight':
				e.preventDefault();
				focusCol = Math.min(focusCol + 1, maxCol);
				break;
			case 'ArrowLeft':
				e.preventDefault();
				focusCol = Math.max(focusCol - 1, 0);
				break;
			case 'Enter':
			case ' ': {
				e.preventDefault();
				const entity = entities[focusRow];
				const attr = attributes[focusCol];
				if (entity && attr) {
					const cell = getCell(entity.id, attr.id);
					handleClick(cell);
				}
				break;
			}
			case 'Home':
				e.preventDefault();
				focusCol = 0;
				break;
			case 'End':
				e.preventDefault();
				focusCol = maxCol;
				break;
		}
	}

	function scrollToRow(row: number) {
		if (!scrollContainer || !useVirtualScroll) return;
		const rowTop = row * ROW_HEIGHT;
		const rowBottom = rowTop + ROW_HEIGHT;
		// Account for sticky header (approx 40px)
		const headerOffset = 40;
		if (rowTop < scrollContainer.scrollTop + headerOffset) {
			scrollContainer.scrollTop = rowTop - headerOffset;
		} else if (rowBottom > scrollContainer.scrollTop + containerHeight) {
			scrollContainer.scrollTop = rowBottom - containerHeight;
		}
	}
</script>

<div
	bind:this={scrollContainer}
	class="overflow-auto {useVirtualScroll ? 'max-h-[70vh]' : ''}"
	onscroll={handleScroll}
	role="grid"
	aria-label="Attribute validation matrix"
	aria-rowcount={entities.length + 1}
	aria-colcount={attributes.length + 1}
	tabindex="0"
	onkeydown={handleKeydown}
>
	<table class="text-sm border-collapse" style={useVirtualScroll ? `height: ${totalHeight + 40}px` : ''}>
		<thead class="sticky top-0 z-20 bg-navy-900">
			<tr aria-rowindex={1}>
				<th
					class="text-left px-3 py-2 text-slate-400 font-medium sticky left-0 bg-navy-900 z-30 min-w-40"
					role="columnheader"
					scope="col"
				>
					Entity
				</th>
				{#each attributes as attr, ci (attr.id)}
					<th
						class="px-2 py-2 text-slate-400 font-medium text-center max-w-28 whitespace-nowrap overflow-hidden text-ellipsis"
						title="{attr.label} (weight: {attr.weight})"
						role="columnheader"
						scope="col"
						aria-colindex={ci + 2}
					>
						{attr.label}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#if useVirtualScroll && topPadding > 0}
				<tr style="height: {topPadding}px;" aria-hidden="true"><td></td></tr>
			{/if}
			{#each visibleEntities as entity, vi (entity.id)}
				{@const rowIdx = startIndex + vi}
				<tr
					class="border-t border-navy-700 hover:bg-navy-800 {focusRow === rowIdx ? 'ring-1 ring-gold/30 ring-inset' : ''}"
					aria-rowindex={rowIdx + 2}
					style={useVirtualScroll ? `height: ${ROW_HEIGHT}px` : ''}
				>
					<td
						class="px-3 py-2 text-slate-300 sticky left-0 bg-navy-900 font-medium"
						role="rowheader"
					>
						{entity.label || entity.gwm_id || entity.id}
						{#if entity.gwm_id && entity.label}
							<span class="text-slate-500 text-xs font-mono ml-1">{entity.gwm_id}</span>
						{/if}
					</td>
					{#each attributes as attr, ci (attr.id)}
						{@const cell = getCell(entity.id, attr.id)}
						{@const cached = getCachedKnowledge(entity, attr)}
						{@const lowConf = minConfidence > 0 && cell != null && cell.confidence != null && cell.confidence < minConfidence}
						<td class="px-2 py-2 text-center" role="gridcell" aria-colindex={ci + 2}>
							<button
								class="w-8 h-8 rounded text-sm font-bold transition-all hover:opacity-80 {cellClass(cell, cached, lowConf)}
								       {(cell || cached) ? 'cursor-pointer' : 'cursor-default'}
								       {focusRow === rowIdx && focusCol === ci ? 'ring-2 ring-gold' : ''}"
								onclick={() => handleClick(cell)}
								title={cached ? `Cached from ${cached.source_campaign_name}` : (cell?.evidence ?? '')}
								aria-label={cellAriaLabel(entity, attr, cell, cached)}
								tabindex={focusRow === rowIdx && focusCol === ci ? 0 : -1}
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
			{#if useVirtualScroll && bottomPadding > 0}
				<tr style="height: {bottomPadding}px;" aria-hidden="true"><td></td></tr>
			{/if}
		</tbody>
	</table>
</div>
