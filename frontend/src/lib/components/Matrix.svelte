<script lang="ts">
	import type { Entity } from '$lib/api/entities';
	import type { Attribute } from '$lib/api/attributes';
	import type { Result, Knowledge, Score } from '$lib/api/jobs';
	import { OptimisticStore } from '$lib/utils/optimistic.svelte';

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
		pendingScores = {},
		oncellclick,
		onselectionchange,
		oncompare,
		onentitylabelsave,
	}: {
		entities: Entity[];
		attributes: Attribute[];
		results: Result[];
		knowledge?: Knowledge[];
		scores?: Score[];
		/**
		 * Client-side optimistic scores (entityId → 0–1 value).
		 * When provided for an entity, shown instead of the server score with a
		 * stale indicator until the server score refreshes.
		 * Computed by callers via computeClientScore() from $lib/utils/score.
		 */
		pendingScores?: Record<string, number>;
		campaignId?: string;
		minConfidence?: number;
		selectable?: boolean;
		selectedEntityIds?: Set<string>;
		oncellclick?: (result: Result) => void;
		onselectionchange?: (ids: Set<string>) => void;
		oncompare?: (ids: string[]) => void;
		/** Called when user saves an entity label edit. Return the confirmed label. */
		onentitylabelsave?: (entityId: string, label: string) => Promise<string>;
	} = $props();

	// ── Optimistic entity label edits ────────────────────────────────────
	const labelStore = new OptimisticStore<string, string>();
	let editingEntityId = $state<string | null>(null);
	let editDraft = $state('');
	let editInputEl = $state<HTMLInputElement | null>(null);

	// Auto-focus the inline input whenever we enter edit mode
	$effect(() => {
		if (editingEntityId && editInputEl) {
			editInputEl.focus();
			editInputEl.select();
		}
	});

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
	const STORAGE_ORDER_KEY_PREFIX = 'matrix-col-order-';

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
	let gridFocused = $state(false);

	// ── Search / filter ───────────────────────────────────────────────────
	let searchQuery = $state('');
	let searchOpen = $state(false);
	let searchInputEl = $state<HTMLInputElement | null>(null);

	// Auto-focus the search input when it opens
	$effect(() => {
		if (searchOpen && searchInputEl) {
			searchInputEl.focus();
			searchInputEl.select();
		}
	});

	function openSearch() {
		searchOpen = true;
	}

	function closeSearch() {
		searchOpen = false;
		searchQuery = '';
		scrollContainer?.focus();
	}

	let filteredEntities = $derived.by(() => {
		if (!searchQuery) return entities;
		const q = searchQuery.toLowerCase();
		return entities.filter((e) => (e.label || '').toLowerCase().includes(q));
	});

	// Clamp focusRow when search filter changes row count
	$effect(() => {
		const maxRow = filteredEntities.length - 1;
		if (focusRow > maxRow) focusRow = Math.max(0, maxRow);
	});

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

	// ── Column order (drag-and-drop, persisted to localStorage) ─────────
	let colOrder = $state<string[]>([]);
	$effect(() => {
		if (!campaignId) return;
		const stored = localStorage.getItem(STORAGE_ORDER_KEY_PREFIX + campaignId);
		if (stored) {
			try { colOrder = JSON.parse(stored); } catch { colOrder = []; }
		} else {
			colOrder = [];
		}
	});
	let orderedAttributes = $derived.by(() => {
		if (colOrder.length === 0) return attributes;
		const orderMap = new Map(colOrder.map((id, i) => [id, i]));
		return [...attributes].sort((a, b) => {
			const ia = orderMap.get(a.id) ?? Number.MAX_SAFE_INTEGER;
			const ib = orderMap.get(b.id) ?? Number.MAX_SAFE_INTEGER;
			return ia - ib;
		});
	});

	// drag state
	let draggingAttrId = $state<string | null>(null);
	let dragOverAttrId = $state<string | null>(null);

	function startColDrag(e: DragEvent, attrId: string) {
		draggingAttrId = attrId;
		if (e.dataTransfer) {
			e.dataTransfer.effectAllowed = 'move';
			e.dataTransfer.setData('text/plain', attrId);
		}
	}

	function onColDragOver(e: DragEvent, attrId: string) {
		if (!draggingAttrId || draggingAttrId === attrId) return;
		e.preventDefault();
		if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
		dragOverAttrId = attrId;
	}

	function onColDrop(e: DragEvent, targetAttrId: string) {
		e.preventDefault();
		if (!draggingAttrId || draggingAttrId === targetAttrId) {
			draggingAttrId = null;
			dragOverAttrId = null;
			return;
		}
		const ordered = [...orderedAttributes];
		const fromIdx = ordered.findIndex((a) => a.id === draggingAttrId);
		const toIdx = ordered.findIndex((a) => a.id === targetAttrId);
		if (fromIdx < 0 || toIdx < 0) { draggingAttrId = null; dragOverAttrId = null; return; }
		ordered.splice(toIdx, 0, ordered.splice(fromIdx, 1)[0]);
		const newOrder = ordered.map((a) => a.id);
		colOrder = newOrder;
		if (campaignId) {
			localStorage.setItem(STORAGE_ORDER_KEY_PREFIX + campaignId, JSON.stringify(newOrder));
		}
		draggingAttrId = null;
		dragOverAttrId = null;
	}

	function onColDragEnd() {
		draggingAttrId = null;
		dragOverAttrId = null;
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
		for (const attr of orderedAttributes) {
			offsets.push(offsets[offsets.length - 1] + getColWidth(attr.id));
		}
		return offsets;
	});

	let totalColsWidth = $derived(colOffsets[colOffsets.length - 1] ?? 0);

	// Binary search: find the column index whose left edge <= offset
	function findColAtOffset(offset: number): number {
		const offs = colOffsets;
		let lo = 0;
		let hi = orderedAttributes.length;
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

	const RESIZE_STEP = 16;

	function handleResizeKeydown(e: KeyboardEvent, attrId: string) {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
		e.preventDefault();
		e.stopPropagation();
		const delta = e.key === 'ArrowRight' ? RESIZE_STEP : -RESIZE_STEP;
		const newWidth = Math.max(MIN_COL_WIDTH, getColWidth(attrId) + delta);
		colWidths = { ...colWidths, [attrId]: newWidth };
		if (campaignId) localStorage.setItem(STORAGE_KEY_PREFIX + campaignId, JSON.stringify(colWidths));
	}

	// ── Per-attribute fill rate ───────────────────────────────────────────
	let fillRates = $derived.by(() => {
		const total = entities.length;
		if (total === 0) return new Map<string, number>();
		const counts = new Map<string, number>();
		for (const attr of orderedAttributes) counts.set(attr.id, 0);
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
	let totalHeight = $derived(HEADER_HEIGHT + filteredEntities.length * ROW_HEIGHT);

	// ── Visible row range ─────────────────────────────────────────────────
	let startRow = $derived(
		Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - ROW_OVERSCAN)
	);
	let endRow = $derived(
		Math.min(filteredEntities.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + ROW_OVERSCAN)
	);
	let visibleEntities = $derived(filteredEntities.slice(startRow, endRow));

	// ── Visible column range (binary search on prefix sums) ──────────────
	let startCol = $derived.by(() => {
		const offset = Math.max(0, scrollLeft - fixedColsWidth);
		return Math.max(0, findColAtOffset(offset) - COL_OVERSCAN);
	});
	let endCol = $derived.by(() => {
		const offset = Math.max(0, scrollLeft + viewportWidth - fixedColsWidth);
		return Math.min(orderedAttributes.length, findColAtOffset(offset) + 1 + COL_OVERSCAN);
	});
	let visibleAttributes = $derived(orderedAttributes.slice(startCol, endCol));

	// ── Padding for off-screen rows/columns ───────────────────────────────
	let topPadding = $derived(startRow * ROW_HEIGHT);
	let bottomPadding = $derived(Math.max(0, (filteredEntities.length - endRow) * ROW_HEIGHT));
	let leftColPadding = $derived(colOffsets[startCol] ?? 0);
	let rightColPadding = $derived(Math.max(0, (colOffsets[orderedAttributes.length] ?? 0) - (colOffsets[endCol] ?? 0)));

	// ── Scroll indicators for frozen pane shadows ────────────────────────
	let isScrolledDown = $derived(scrollTop > 0);
	let isScrolledRight = $derived(scrollLeft > 0);

	// ── Colspan for spacer rows ───────────────────────────────────────────
	let totalCols = $derived(
		(selectable ? 1 : 0) +
		1 +
		(startCol > 0 ? 1 : 0) +
		visibleAttributes.length +
		(endCol < orderedAttributes.length ? 1 : 0) +
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

	// ── Entity label inline editing ───────────────────────────────────────
	function startEntityEdit(entity: Entity) {
		if (!onentitylabelsave) return;
		editingEntityId = entity.id;
		editDraft = labelStore.get(entity.id, entity.label) || entity.label;
	}

	function cancelEntityEdit() {
		editingEntityId = null;
		editDraft = '';
	}

	async function commitEntityEdit(entity: Entity) {
		if (!onentitylabelsave || !editingEntityId) return;
		const trimmed = editDraft.trim();
		editingEntityId = null;
		editDraft = '';
		if (!trimmed || trimmed === labelStore.get(entity.id, entity.label)) return;
		await labelStore.update(entity.id, trimmed, () =>
			onentitylabelsave!(entity.id, trimmed)
		);
	}

	function handleEntityKeydown(e: KeyboardEvent, entity: Entity) {
		if (e.key === 'Enter') {
			e.preventDefault();
			commitEntityEdit(entity);
			// Return keyboard focus to the grid container
			scrollContainer?.focus();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancelEntityEdit();
			scrollContainer?.focus();
		} else if (e.key === 'Tab') {
			e.preventDefault();
			commitEntityEdit(entity);
			// Advance to next/prev row (Shift+Tab = prev)
			const maxRow = filteredEntities.length - 1;
			if (e.shiftKey) {
				focusRow = Math.max(focusRow - 1, 0);
			} else {
				focusRow = Math.min(focusRow + 1, maxRow);
			}
			scrollToCell(focusRow, focusCol);
			scrollContainer?.focus();
		}
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
		// If we're in inline edit mode, delegate to the input handler
		if (editingEntityId) return;

		// Cmd+F / Ctrl+F → open search
		if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
			e.preventDefault();
			openSearch();
			return;
		}

		const maxRow = filteredEntities.length - 1;
		const maxCol = orderedAttributes.length - 1;
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
			case 'Tab': {
				// Tab navigates columns; Shift+Tab goes backwards.
				// At grid edges, let focus escape naturally (don't trap).
				if (e.shiftKey) {
					if (focusCol > 0) {
						e.preventDefault();
						focusCol--;
					} else if (focusRow > 0) {
						e.preventDefault();
						focusRow--;
						focusCol = maxCol;
					}
					// else: Shift+Tab at first cell — let focus escape to previous element
				} else {
					if (focusCol < maxCol) {
						e.preventDefault();
						focusCol++;
					} else if (focusRow < maxRow) {
						e.preventDefault();
						focusRow++;
						focusCol = 0;
					}
					// else: Tab at last cell — let focus escape to next element
				}
				scrollToCell(focusRow, focusCol);
				break;
			}
			case 'Enter':
			case ' ': {
				e.preventDefault();
				const entity = filteredEntities[focusRow];
				const attr = orderedAttributes[focusCol];
				if (entity && attr) {
					handleClick(getCell(entity.id, attr.id));
				}
				break;
			}
			case 'F2': {
				// F2 = enter edit mode for entity label (standard spreadsheet shortcut)
				e.preventDefault();
				const entity = filteredEntities[focusRow];
				if (entity) startEntityEdit(entity);
				break;
			}
			case 'Escape':
				// Escape blurs the grid entirely when not editing
				e.preventDefault();
				scrollContainer?.blur();
				break;
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
		const cellRight = cellLeft + getColWidth(orderedAttributes[col]?.id ?? '');

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

<!-- Toolbar: search + grid dimensions -->
{#if entities.length > 0}
	<div class="flex items-center gap-3 mb-1 px-1">
		<!-- Search bar (expandable) -->
		<div class="flex items-center gap-1.5">
			{#if searchOpen}
				<div class="flex items-center gap-1 bg-navy-800 border border-navy-600 focus-within:border-gold/50 rounded-lg px-2 py-1 transition-all">
					<svg class="w-3 h-3 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
					</svg>
					<input
						bind:this={searchInputEl}
						bind:value={searchQuery}
						type="search"
						placeholder="Filter entities…"
						class="bg-transparent text-xs text-slate-200 placeholder-slate-600 outline-none w-36"
						aria-label="Filter entities by name"
						onkeydown={(e) => { if (e.key === 'Escape') { e.preventDefault(); closeSearch(); } }}
					/>
					{#if searchQuery}
						<span class="text-slate-500 text-xs shrink-0">{filteredEntities.length}/{entities.length}</span>
					{/if}
					<button
						onclick={closeSearch}
						class="text-slate-600 hover:text-slate-400 transition-colors ml-0.5"
						aria-label="Close search"
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>
			{:else}
				<button
					onclick={openSearch}
					class="flex items-center gap-1 text-slate-600 hover:text-slate-400 transition-colors"
					aria-label="Search entities (Cmd+F)"
					title="Search entities (Cmd+F)"
				>
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
					</svg>
					<span class="text-xs">Search</span>
				</button>
			{/if}
		</div>

		<!-- Dimension count -->
		<span class="text-xs text-slate-500 ml-auto">
			{filteredEntities.length.toLocaleString()}{searchQuery ? `/${entities.length.toLocaleString()}` : ''} rows
			<span class="text-navy-600 mx-1">&times;</span>
			{orderedAttributes.length} columns
		</span>
	</div>
{/if}

<!-- Virtualized grid container -->
<div
	bind:this={scrollContainer}
	class="overflow-auto max-h-[70vh] {resizingCol ? 'cursor-col-resize select-none' : ''}"
	onscroll={handleScroll}
	role="grid"
	aria-label="Attribute validation matrix — Arrow keys navigate, Enter/Space to view, Tab moves columns, F2 to edit label, Escape to exit"
	aria-rowcount={filteredEntities.length + 1}
	aria-colcount={orderedAttributes.length + (selectable ? 2 : 1)}
	tabindex="0"
	onkeydown={handleKeydown}
	onfocus={() => (gridFocused = true)}
	onblur={(e) => {
		if (!scrollContainer?.contains(e.relatedTarget as Node | null)) gridFocused = false;
	}}
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
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<th
						class="group relative px-1 py-2 text-slate-400 font-medium text-center whitespace-nowrap overflow-hidden text-ellipsis border-b border-navy-700 select-none cursor-grab {dragOverAttrId === attr.id && draggingAttrId !== attr.id ? 'border-l-2 border-l-gold' : ''} {draggingAttrId === attr.id ? 'opacity-40' : ''}"
						style="width: {w}px; min-width: {w}px"
						title="{attr.label} (weight: {attr.weight})"
						role="columnheader"
						scope="col"
						aria-colindex={startCol + ci + 2}
						draggable="true"
						ondragstart={(e) => startColDrag(e, attr.id)}
						ondragover={(e) => onColDragOver(e, attr.id)}
						ondrop={(e) => onColDrop(e, attr.id)}
						ondragend={onColDragEnd}
					>
						<span class="block truncate text-xs pr-2 pl-4 cursor-grab">{attr.label}</span>
						<!-- Drag grip icon -->
						<span class="absolute left-0.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs opacity-40 group-hover:opacity-100 pointer-events-none" aria-hidden="true">⠿</span>
						<!-- Resize handle (keyboard: Left/Right arrow keys) -->
						<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
						<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
						<div
							class="absolute right-0 top-0 bottom-0 w-2.5 cursor-col-resize hover:bg-gold/40 transition-colors focus-visible:bg-gold/60 outline-none {resizingCol === attr.id ? 'bg-gold/60' : ''}"
							role="separator"
							aria-label="Resize {attr.label} column"
							tabindex="0"
							onmousedown={(e) => startResize(attr.id, e)}
							onkeydown={(e) => handleResizeKeydown(e, attr.id)}
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
				{@const effectiveLabel = labelStore.get(entity.id, entity.label) || entity.label}
				{@const isSavingLabel = labelStore.isSaving(entity.id)}
				{@const labelError = labelStore.errorOf(entity.id)}
				{@const labelConflict = labelStore.isConflicted(entity.id)}
				<tr
					class="border-t border-navy-700 hover:bg-navy-800
						{gridFocused && focusRow === rowIdx ? 'ring-1 ring-gold/30 ring-inset' : ''}
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
						class="px-3 py-2 text-slate-300 sticky bg-navy-900 font-medium z-10 transition-shadow overflow-hidden
							{isScrolledRight ? 'shadow-[2px_0_6px_-1px_rgba(0,0,0,0.4)] border-r-2 border-r-navy-600' : 'border-r border-r-navy-700'}
							{labelConflict ? 'conflict-flash' : ''}"
						style="left: {selectable ? CHECKBOX_COL_WIDTH : 0}px; width: {ENTITY_COL_WIDTH}px; min-width: {ENTITY_COL_WIDTH}px; max-width: {ENTITY_COL_WIDTH}px"
						role="rowheader"
						title={labelError ?? (effectiveLabel + (entity.gwm_id ? ` (${entity.gwm_id})` : ''))}
					>
						{#if editingEntityId === entity.id}
							<input
								bind:this={editInputEl}
								class="w-full bg-navy-700 border border-gold rounded px-1 py-0.5 text-sm text-slate-100 focus:outline-none focus:border-gold-light"
								bind:value={editDraft}
								onblur={() => commitEntityEdit(entity)}
								onkeydown={(e) => handleEntityKeydown(e, entity)}
								aria-label="Edit entity label — Enter to save, Escape to cancel, Tab to move"
								maxlength={200}
							/>
						{:else}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<span
								class="flex items-center gap-1 min-h-[1em] {onentitylabelsave ? 'cursor-pointer group' : 'cursor-default'}"
								ondblclick={() => startEntityEdit(entity)}
							>
								<span class="truncate {isSavingLabel ? 'opacity-50' : ''} {labelError ? 'text-red-400' : ''}">
									{effectiveLabel}
								</span>
								{#if isSavingLabel}
									<span class="shrink-0 w-3 h-3 rounded-full border-2 border-gold border-t-transparent animate-spin" aria-hidden="true"></span>
								{:else if labelError}
									<span class="shrink-0 text-red-400 text-xs" title={labelError} aria-label="Save failed: {labelError}">!</span>
								{:else if onentitylabelsave}
									<span class="shrink-0 opacity-0 group-hover:opacity-40 text-slate-500 text-xs leading-none" aria-hidden="true">✎</span>
								{/if}
							</span>
							{#if entity.gwm_id && entity.label}
								<span class="text-slate-500 text-xs font-mono ml-1">{entity.gwm_id}</span>
							{/if}
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
									{gridFocused && focusRow === rowIdx && focusCol === globalCol ? 'ring-2 ring-gold' : ''}"
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
						{@const optimisticScore = pendingScores[entity.id]}
						{@const displayScore = optimisticScore ?? entityScore?.total_score}
						<td
							class="px-2 py-2 text-center sticky right-0 bg-navy-900 z-10 border-l border-l-navy-600 shadow-[-2px_0_6px_-1px_rgba(0,0,0,0.4)]"
							style="width: {SCORE_COL_WIDTH}px; min-width: {SCORE_COL_WIDTH}px"
						>
							{#if displayScore != null}
								<div
									class="inline-flex items-center gap-1 px-2 py-1 rounded {scoreGradient(displayScore)}"
									title={optimisticScore != null ? 'Score pending server confirmation' : undefined}
								>
									<span class="font-mono font-semibold text-xs tabular-nums">
										{displayScore.toFixed(2)}
									</span>
									{#if optimisticScore != null}
										<span class="opacity-50 text-[10px] leading-none" aria-label="Pending" aria-live="polite">~</span>
									{/if}
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
