<script lang="ts">
	import type { Entity } from '$lib/api/entities';
	import type { Attribute } from '$lib/api/attributes';
	import type { Result, Knowledge, Score } from '$lib/api/jobs';

	let {
		entities,
		attributes,
		results,
		knowledge = [],
		campaignId = '',
		minConfidence = 0,
		selectable = false,
		selectedEntityIds = new Set<string>(),
		scores = [],
		oncellclick,
		onselectionchange,
		oncompare,
	}: {
		entities: Entity[];
		attributes: Attribute[];
		results: Result[];
		knowledge?: Knowledge[];
		scores?: Score[];
		campaignId?: string;
		minConfidence?: number;
		selectable?: boolean;
		selectedEntityIds?: Set<string>;
		oncellclick?: (result: Result) => void;
		onselectionchange?: (ids: Set<string>) => void;
		oncompare?: (ids: string[]) => void;
	} = $props();

	// ── Layout constants ──────────────────────────────────────────────────
	const DEFAULT_COL_WIDTH = 120;
	const MIN_COL_WIDTH = 60;
	const ENTITY_COL_WIDTH = 160;
	const HEADER_HEIGHT = 44;
	const ROW_HEIGHT = 44;
	const CHECKBOX_COL_WIDTH = 40;
	const SCORE_COL_WIDTH = 90;
	const ROW_OVERSCAN = 5;
	const COL_OVERSCAN = 3;
	const STORAGE_KEY_PREFIX = 'matrix-col-widths-';

	// ── Scroll state ──────────────────────────────────────────────────────
	let scrollContainer: HTMLDivElement | undefined = $state();
	let scrollTop = $state(0);
	let scrollLeft = $state(0);
	let viewportWidth = $state(800);
	let viewportHeight = $state(600);
	let rafId = 0;

	// ── Keyboard focus ────────────────────────────────────────────────────
	let focusRow = $state(0);
	let focusCol = $state(0);

	// ── Selection ─────────────────────────────────────────────────────────
	let canCompare = $derived(selectedEntityIds.size >= 2 && selectedEntityIds.size <= 5);
	let selectionCount = $derived(selectedEntityIds.size);

	// ── Lookup maps ───────────────────────────────────────────────────────
	let resultMap = $derived(
		new Map(results.map((r) => [`${r.entity_id}:${r.attribute_id}`, r]))
	);
	let knowledgeMap = $derived(
		new Map(
			knowledge
				.filter((k) => k.source_campaign_id && k.source_campaign_id !== campaignId)
				.map((k) => [`${k.gwm_id}:${k.attribute_label}`, k])
		)
	);

	let scoreMap = $derived(new Map(scores.map((s) => [s.entity_id, s])));
	let hasScores = $derived(scores.length > 0);

	function scoreGradient(val: number): string {
		if (val >= 0.8) return 'bg-green-500/20 text-green-400';
		if (val >= 0.6) return 'bg-emerald-500/15 text-emerald-400';
		if (val >= 0.4) return 'bg-gold/15 text-gold';
		if (val >= 0.2) return 'bg-orange-500/15 text-orange-400';
		return 'bg-red-500/15 text-red-400';
	}

	// ── Column widths (resizable, persisted to localStorage) ─────────────
	let colWidths = $state<Record<string, number>>({});

	// Load widths from localStorage when campaignId is available
	$effect(() => {
		if (!campaignId) return;
		const stored = localStorage.getItem(STORAGE_KEY_PREFIX + campaignId);
		if (stored) {
			try { colWidths = JSON.parse(stored); } catch { colWidths = {}; }
		} else {
			colWidths = {};
		}
	});

	function getColWidth(attrId: string): number {
		return colWidths[attrId] ?? DEFAULT_COL_WIDTH;
	}

	// Prefix sum of column offsets: colOffsets[i] = sum of widths of cols 0..i-1
	let colOffsets = $derived.by(() => {
		const offsets = [0];
		for (const attr of attributes) {
			offsets.push(offsets[offsets.length - 1] + getColWidth(attr.id));
		}
		return offsets;
	});

	let totalColsWidth = $derived(colOffsets[colOffsets.length - 1] ?? 0);

	// Binary search: find the column index whose left edge <= offset
	function findColAtOffset(offset: number): number {
		const offs = colOffsets;
		let lo = 0;
		let hi = attributes.length;
		while (lo < hi) {
			const mid = (lo + hi) >>> 1;
			if (offs[mid + 1] <= offset) lo = mid + 1;
			else hi = mid;
		}
		return lo;
	}

	// ── Column resize state ──────────────────────────────────────────────
	let resizingCol = $state<string | null>(null);
	let resizeStartX = 0;
	let resizeStartWidth = 0;

	function startResize(attrId: string, e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		resizingCol = attrId;
		resizeStartX = e.clientX;
		resizeStartWidth = getColWidth(attrId);
		document.addEventListener('mousemove', onResizeMove);
		document.addEventListener('mouseup', onResizeEnd);
	}

	function onResizeMove(e: MouseEvent) {
		if (!resizingCol) return;
		const delta = e.clientX - resizeStartX;
		const newWidth = Math.max(MIN_COL_WIDTH, resizeStartWidth + delta);
		colWidths = { ...colWidths, [resizingCol]: newWidth };
	}

	function onResizeEnd() {
		document.removeEventListener('mousemove', onResizeMove);
		document.removeEventListener('mouseup', onResizeEnd);
		if (campaignId && Object.keys(colWidths).length > 0) {
			localStorage.setItem(STORAGE_KEY_PREFIX + campaignId, JSON.stringify(colWidths));
		}
		resizingCol = null;
	}

	// ── Per-attribute fill rate ───────────────────────────────────────────
	let fillRates = $derived.by(() => {
		const total = entities.length;
		if (total === 0) return new Map<string, number>();
		const counts = new Map<string, number>();
		for (const attr of attributes) counts.set(attr.id, 0);
		for (const r of results) {
			const prev = counts.get(r.attribute_id);
			if (prev !== undefined) counts.set(r.attribute_id, prev + 1);
		}
		return new Map([...counts.entries()].map(([id, c]) => [id, c / total]));
	});

	function fillRateColor(rate: number): string {
		if (rate >= 0.8) return 'text-green-400';
		if (rate >= 0.5) return 'text-gold';
		if (rate >= 0.3) return 'text-orange-400';
		return 'text-red-400';
	}

	// ── Virtual dimensions ────────────────────────────────────────────────
	let fixedColsWidth = $derived(ENTITY_COL_WIDTH + (selectable ? CHECKBOX_COL_WIDTH : 0));
	let totalWidth = $derived(fixedColsWidth + totalColsWidth + (hasScores ? SCORE_COL_WIDTH : 0));
	let totalHeight = $derived(HEADER_HEIGHT + entities.length * ROW_HEIGHT);

	// ── Visible row range ─────────────────────────────────────────────────
	let startRow = $derived(
		Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - ROW_OVERSCAN)
	);
	let endRow = $derived(
		Math.min(entities.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + ROW_OVERSCAN)
	);
	let visibleEntities = $derived(entities.slice(startRow, endRow));

	// ── Visible column range (binary search on prefix sums) ──────────────
	let startCol = $derived.by(() => {
		const offset = Math.max(0, scrollLeft - fixedColsWidth);
		return Math.max(0, findColAtOffset(offset) - COL_OVERSCAN);
	});
	let endCol = $derived.by(() => {
		const offset = Math.max(0, scrollLeft + viewportWidth - fixedColsWidth);
		return Math.min(attributes.length, findColAtOffset(offset) + 1 + COL_OVERSCAN);
	});
	let visibleAttributes = $derived(attributes.slice(startCol, endCol));

	// ── Padding for off-screen rows/columns ───────────────────────────────
	let topPadding = $derived(startRow * ROW_HEIGHT);
	let bottomPadding = $derived(Math.max(0, (entities.length - endRow) * ROW_HEIGHT));
	let leftColPadding = $derived(colOffsets[startCol] ?? 0);
	let rightColPadding = $derived(Math.max(0, (colOffsets[attributes.length] ?? 0) - (colOffsets[endCol] ?? 0)));

	// ── Scroll indicators for frozen pane shadows ────────────────────────
	let isScrolledDown = $derived(scrollTop > 0);
	let isScrolledRight = $derived(scrollLeft > 0);

	// ── Colspan for spacer rows ───────────────────────────────────────────
	let totalCols = $derived(
		(selectable ? 1 : 0) +
		1 +
		(startCol > 0 ? 1 : 0) +
		visibleAttributes.length +
		(endCol < attributes.length ? 1 : 0) +
		(hasScores ? 1 : 0)
	);

	// ── Cell helpers ──────────────────────────────────────────────────────
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

	function cellAriaLabel(
		entity: Entity,
		attr: Attribute,
		result: Result | undefined,
		cached: Knowledge | undefined
	): string {
		const entityName = entity.label || entity.gwm_id || entity.id;
		const status = cached
			? 'cached from another campaign'
			: !result
				? 'not validated'
				: result.confidence === null
					? result.present
						? 'present, no confidence data'
						: 'absent, no confidence data'
					: result.present
						? `present, confidence ${(result.confidence * 100).toFixed(0)}%`
						: 'absent';
		return `${entityName}, ${attr.label}: ${status}`;
	}

	function handleClick(result: Result | undefined) {
		if (result && oncellclick) oncellclick(result);
	}

	// ── Scroll handling (rAF-throttled) ───────────────────────────────────
	function handleScroll() {
		if (rafId) return;
		rafId = requestAnimationFrame(() => {
			if (scrollContainer) {
				scrollTop = scrollContainer.scrollTop;
				scrollLeft = scrollContainer.scrollLeft;
				viewportWidth = scrollContainer.clientWidth;
				viewportHeight = scrollContainer.clientHeight;
			}
			rafId = 0;
		});
	}

	// ── Selection ─────────────────────────────────────────────────────────
	function toggleEntity(entityId: string) {
		const next = new Set(selectedEntityIds);
		if (next.has(entityId)) {
			next.delete(entityId);
		} else if (next.size < 5) {
			next.add(entityId);
		}
		onselectionchange?.(next);
	}

	function handleCompare() {
		if (canCompare) oncompare?.([...selectedEntityIds]);
	}

	// ── Keyboard navigation ───────────────────────────────────────────────
	function handleKeydown(e: KeyboardEvent) {
		const maxRow = entities.length - 1;
		const maxCol = attributes.length - 1;
		if (maxRow < 0 || maxCol < 0) return;

		switch (e.key) {
			case 'ArrowDown':
				e.preventDefault();
				focusRow = Math.min(focusRow + 1, maxRow);
				scrollToCell(focusRow, focusCol);
				break;
			case 'ArrowUp':
				e.preventDefault();
				focusRow = Math.max(focusRow - 1, 0);
				scrollToCell(focusRow, focusCol);
				break;
			case 'ArrowRight':
				e.preventDefault();
				focusCol = Math.min(focusCol + 1, maxCol);
				scrollToCell(focusRow, focusCol);
				break;
			case 'ArrowLeft':
				e.preventDefault();
				focusCol = Math.max(focusCol - 1, 0);
				scrollToCell(focusRow, focusCol);
				break;
			case 'Enter':
			case ' ': {
				e.preventDefault();
				const entity = entities[focusRow];
				const attr = attributes[focusCol];
				if (entity && attr) {
					handleClick(getCell(entity.id, attr.id));
				}
				break;
			}
			case 'Home':
				e.preventDefault();
				if (e.ctrlKey) {
					focusRow = 0;
					focusCol = 0;
				} else {
					focusCol = 0;
				}
				scrollToCell(focusRow, focusCol);
				break;
			case 'End':
				e.preventDefault();
				if (e.ctrlKey) {
					focusRow = maxRow;
					focusCol = maxCol;
				} else {
					focusCol = maxCol;
				}
				scrollToCell(focusRow, focusCol);
				break;
		}
	}

	function scrollToCell(row: number, col: number) {
		if (!scrollContainer) return;
		const cellTop = row * ROW_HEIGHT;
		const cellLeft = fixedColsWidth + (colOffsets[col] ?? 0);
		const cellBottom = cellTop + ROW_HEIGHT;
		const cellRight = cellLeft + getColWidth(attributes[col]?.id ?? '');

		if (cellTop < scrollContainer.scrollTop + HEADER_HEIGHT) {
			scrollContainer.scrollTop = cellTop;
		} else if (cellBottom > scrollContainer.scrollTop + viewportHeight) {
			scrollContainer.scrollTop = cellBottom - viewportHeight;
		}

		if (cellLeft < scrollContainer.scrollLeft + fixedColsWidth) {
			scrollContainer.scrollLeft = cellLeft - fixedColsWidth;
		} else if (cellRight > scrollContainer.scrollLeft + viewportWidth) {
			scrollContainer.scrollLeft = cellRight - viewportWidth;
		}
	}

	// ── Viewport measurement via ResizeObserver ───────────────────────────
	$effect(() => {
		if (!scrollContainer) return;
		viewportWidth = scrollContainer.clientWidth;
		viewportHeight = scrollContainer.clientHeight;
		const observer = new ResizeObserver((entries) => {
			for (const entry of entries) {
				viewportWidth = entry.contentRect.width;
				viewportHeight = entry.contentRect.height;
			}
		});
		observer.observe(scrollContainer);
		return () => observer.disconnect();
	});
</script>

<!-- Compare bar -->
{#if selectable && selectionCount > 0}
	<div class="flex items-center gap-3 mb-2 px-1">
		<span class="text-xs text-slate-400">
			{selectionCount} selected
			{#if selectionCount < 2}
				<span class="text-slate-500">(select {2 - selectionCount} more to compare)</span>
			{:else if selectionCount > 5}
				<span class="text-red-400">(max 5)</span>
			{/if}
		</span>
		<button
			onclick={handleCompare}
			disabled={!canCompare}
			class="text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors
				{canCompare
					? 'bg-gold text-navy hover:bg-gold-light'
					: 'bg-navy-700 text-slate-500 cursor-not-allowed'}"
		>
			Compare
		</button>
		<button
			onclick={() => onselectionchange?.(new Set())}
			class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
		>
			Clear
		</button>
	</div>
{/if}

<!-- Grid dimensions indicator -->
{#if entities.length > 0}
	<div class="flex items-center gap-2 mb-1 px-1 text-xs text-slate-500">
		<span>{entities.length.toLocaleString()} rows</span>
		<span class="text-navy-600">&times;</span>
		<span>{attributes.length} columns</span>
	</div>
{/if}

<!-- Virtualized grid container -->
<div
	bind:this={scrollContainer}
	class="overflow-auto max-h-[70vh] {resizingCol ? 'cursor-col-resize select-none' : ''}"
	onscroll={handleScroll}
	role="grid"
	aria-label="Attribute validation matrix"
	aria-rowcount={entities.length + 1}
	aria-colcount={attributes.length + (selectable ? 2 : 1)}
	tabindex="0"
	onkeydown={handleKeydown}
>
	<table
		class="text-sm border-collapse"
		style="table-layout: fixed; width: {totalWidth}px"
	>
		<!-- Header row -->
		<thead class="sticky top-0 z-20 bg-navy-900 transition-shadow {isScrolledDown ? 'shadow-[0_4px_8px_-2px_rgba(0,0,0,0.5)]' : ''}">
			<tr aria-rowindex={1} style="height: {HEADER_HEIGHT}px">
				{#if selectable}
					<th
						class="bg-navy-900 z-30 sticky left-0 border-b border-navy-700"
						style="width: {CHECKBOX_COL_WIDTH}px; min-width: {CHECKBOX_COL_WIDTH}px"
						role="columnheader"
						scope="col"
					>
						<span class="sr-only">Select</span>
					</th>
				{/if}
				<th
					class="text-left px-3 py-2 text-slate-400 font-medium sticky bg-navy-900 z-30 border-b border-navy-700 transition-shadow
						{isScrolledRight ? 'shadow-[2px_0_6px_-1px_rgba(0,0,0,0.4)] border-r-2 border-r-navy-600' : 'border-r border-r-navy-700'}"
					style="left: {selectable ? CHECKBOX_COL_WIDTH : 0}px; width: {ENTITY_COL_WIDTH}px; min-width: {ENTITY_COL_WIDTH}px"
					role="columnheader"
					scope="col"
				>
					Entity
				</th>
				{#if leftColPadding > 0}
					<th
						class="border-b border-navy-700"
						style="width: {leftColPadding}px; min-width: {leftColPadding}px; padding: 0"
						aria-hidden="true"
					></th>
				{/if}
				{#each visibleAttributes as attr, ci (attr.id)}
					{@const w = getColWidth(attr.id)}
					<th
						class="relative px-1 py-2 text-slate-400 font-medium text-center whitespace-nowrap overflow-hidden text-ellipsis border-b border-navy-700 select-none"
						style="width: {w}px; min-width: {w}px"
						title="{attr.label} (weight: {attr.weight})"
						role="columnheader"
						scope="col"
						aria-colindex={startCol + ci + 2}
					>
						<span class="block truncate text-xs pr-2">{attr.label}</span>
						<!-- Resize handle -->
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-gold/40 transition-colors {resizingCol === attr.id ? 'bg-gold/60' : ''}"
							onmousedown={(e) => startResize(attr.id, e)}
						></div>
					</th>
				{/each}
				{#if rightColPadding > 0}
					<th
						class="border-b border-navy-700"
						style="width: {rightColPadding}px; min-width: {rightColPadding}px; padding: 0"
						aria-hidden="true"
					></th>
				{/if}
				{#if hasScores}
					<th
						class="px-2 py-2 text-slate-400 font-medium text-center whitespace-nowrap border-b border-navy-700 sticky right-0 bg-navy-900 z-30 border-l border-l-navy-600 shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.4)]"
						style="width: {SCORE_COL_WIDTH}px; min-width: {SCORE_COL_WIDTH}px"
						role="columnheader"
						scope="col"
					>
						<span class="text-xs text-gold font-semibold">Score</span>
					</th>
				{/if}
			</tr>
		</thead>

		<tbody>
			<!-- Top spacer for off-screen rows -->
			{#if topPadding > 0}
				<tr style="height: {topPadding}px" aria-hidden="true">
					<td colspan={totalCols}></td>
				</tr>
			{/if}

			<!-- Visible rows -->
			{#each visibleEntities as entity, vi (entity.id)}
				{@const rowIdx = startRow + vi}
				{@const isChecked = selectedEntityIds.has(entity.id)}
				<tr
					class="border-t border-navy-700 hover:bg-navy-800
						{focusRow === rowIdx ? 'ring-1 ring-gold/30 ring-inset' : ''}
						{isChecked ? 'bg-gold/5' : ''}"
					aria-rowindex={rowIdx + 2}
					style="height: {ROW_HEIGHT}px"
				>
					<!-- Checkbox column (sticky left) -->
					{#if selectable}
						<td
							class="px-2 py-2 text-center sticky left-0 bg-navy-900 z-10"
							style="width: {CHECKBOX_COL_WIDTH}px; min-width: {CHECKBOX_COL_WIDTH}px"
						>
							<button
								onclick={() => toggleEntity(entity.id)}
								class="min-w-[44px] min-h-[44px] flex items-center justify-center"
								aria-label="Select {entity.label || entity.id} for comparison"
								aria-checked={isChecked}
								role="checkbox"
							>
								<span class="w-4 h-4 rounded border-2 flex items-center justify-center transition-all
									{isChecked ? 'border-gold bg-gold' : 'border-navy-500 hover:border-gold/50'}">
									{#if isChecked}
										<svg class="w-2.5 h-2.5 text-navy" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
										</svg>
									{/if}
								</span>
							</button>
						</td>
					{/if}

					<!-- Entity label column (sticky left, frozen pane) -->
					<td
						class="px-3 py-2 text-slate-300 sticky bg-navy-900 font-medium z-10 truncate transition-shadow
							{isScrolledRight ? 'shadow-[2px_0_6px_-1px_rgba(0,0,0,0.4)] border-r-2 border-r-navy-600' : 'border-r border-r-navy-700'}"
						style="left: {selectable ? CHECKBOX_COL_WIDTH : 0}px; width: {ENTITY_COL_WIDTH}px; min-width: {ENTITY_COL_WIDTH}px; max-width: {ENTITY_COL_WIDTH}px"
						role="rowheader"
						title={entity.label || entity.gwm_id || entity.id}
					>
						{entity.label || entity.gwm_id || entity.id}
						{#if entity.gwm_id && entity.label}
							<span class="text-slate-500 text-xs font-mono ml-1">{entity.gwm_id}</span>
						{/if}
					</td>

					<!-- Left spacer for off-screen columns -->
					{#if leftColPadding > 0}
						<td
							style="width: {leftColPadding}px; min-width: {leftColPadding}px; padding: 0"
							aria-hidden="true"
						></td>
					{/if}

					<!-- Visible data cells -->
					{#each visibleAttributes as attr, ci (attr.id)}
						{@const cell = getCell(entity.id, attr.id)}
						{@const cached = getCachedKnowledge(entity, attr)}
						{@const lowConf = minConfidence > 0 && cell != null && cell.confidence != null && cell.confidence < minConfidence}
						{@const globalCol = startCol + ci}
						{@const w = getColWidth(attr.id)}
						<td
							class="px-2 py-2 text-center"
							style="width: {w}px; min-width: {w}px"
							role="gridcell"
							aria-colindex={globalCol + 2}
						>
							<button
								class="w-11 h-11 rounded text-sm font-bold transition-all hover:opacity-80 {cellClass(cell, cached, lowConf)}
									{cell || cached ? 'cursor-pointer' : 'cursor-default'}
									{focusRow === rowIdx && focusCol === globalCol ? 'ring-2 ring-gold' : ''}"
								onclick={() => handleClick(cell)}
								title={cached ? `Cached from ${cached.source_campaign_name}` : (cell?.evidence ?? '')}
								aria-label={cellAriaLabel(entity, attr, cell, cached)}
								tabindex={focusRow === rowIdx && focusCol === globalCol ? 0 : -1}
							>
								{cellLabel(cell, cached)}
							</button>
						</td>
					{/each}

					<!-- Right spacer for off-screen columns -->
					{#if rightColPadding > 0}
						<td
							style="width: {rightColPadding}px; min-width: {rightColPadding}px; padding: 0"
							aria-hidden="true"
						></td>
					{/if}

					<!-- Score column (sticky right) -->
					{#if hasScores}
						{@const entityScore = scoreMap.get(entity.id)}
						<td
							class="px-2 py-2 text-center sticky right-0 bg-navy-900 z-10 border-l border-l-navy-600 shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.4)]"
							style="width: {SCORE_COL_WIDTH}px; min-width: {SCORE_COL_WIDTH}px"
						>
							{#if entityScore}
								<div class="inline-flex items-center gap-1 px-2 py-1 rounded {scoreGradient(entityScore.total_score)}">
									<span class="font-mono font-semibold text-xs tabular-nums">
										{entityScore.total_score.toFixed(2)}
									</span>
								</div>
							{:else}
								<span class="text-slate-600 text-xs">&mdash;</span>
							{/if}
						</td>
					{/if}
				</tr>
			{:else}
				<tr>
					<td colspan={totalCols} class="text-slate-500 text-center py-8">
						No entities in this campaign.
					</td>
				</tr>
			{/each}

			<!-- Bottom spacer for off-screen rows -->
			{#if bottomPadding > 0}
				<tr style="height: {bottomPadding}px" aria-hidden="true">
					<td colspan={totalCols}></td>
				</tr>
			{/if}
		</tbody>
		{#if entities.length > 0}
			<tfoot class="sticky bottom-0 z-20 bg-navy-900 border-t-2 border-navy-600">
				<tr style="height: {ROW_HEIGHT}px">
					{#if selectable}
						<td
							class="sticky left-0 bg-navy-900 z-30"
							style="width: {CHECKBOX_COL_WIDTH}px; min-width: {CHECKBOX_COL_WIDTH}px"
						></td>
					{/if}
					<td
						class="px-3 py-2 text-xs text-slate-500 font-medium sticky bg-navy-900 z-30 transition-shadow
							{isScrolledRight ? 'shadow-[2px_0_6px_-1px_rgba(0,0,0,0.4)] border-r-2 border-r-navy-600' : 'border-r border-r-navy-700'}"
						style="left: {selectable ? CHECKBOX_COL_WIDTH : 0}px; width: {ENTITY_COL_WIDTH}px; min-width: {ENTITY_COL_WIDTH}px"
					>
						Fill rate
					</td>
					{#if leftColPadding > 0}
						<td style="width: {leftColPadding}px; min-width: {leftColPadding}px; padding: 0" aria-hidden="true"></td>
					{/if}
					{#each visibleAttributes as attr (attr.id)}
						{@const rate = fillRates.get(attr.id) ?? 0}
						{@const pct = Math.round(rate * 100)}
						{@const w = getColWidth(attr.id)}
						<td
							class="px-2 py-2 text-center"
							style="width: {w}px; min-width: {w}px"
						>
							<span class="text-xs font-mono font-semibold {fillRateColor(rate)}">{pct}%</span>
						</td>
					{/each}
					{#if rightColPadding > 0}
						<td style="width: {rightColPadding}px; min-width: {rightColPadding}px; padding: 0" aria-hidden="true"></td>
					{/if}
					{#if hasScores}
						<td
							class="sticky right-0 bg-navy-900 z-10 border-l border-l-navy-600 shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.4)]"
							style="width: {SCORE_COL_WIDTH}px; min-width: {SCORE_COL_WIDTH}px"
						></td>
					{/if}
				</tr>
			</tfoot>
		{/if}
	</table>
</div>
