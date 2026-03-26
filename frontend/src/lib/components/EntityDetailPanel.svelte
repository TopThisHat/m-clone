<script lang="ts">
	import type { Score, Result } from '$lib/api/jobs';
	import type { Attribute } from '$lib/api/attributes';

	let {
		score,
		results,
		attributes,
		campaignId,
		onclose,
		onrevalidate,
	}: {
		score: Score;
		results: Result[];
		attributes: Attribute[];
		campaignId: string;
		onclose: () => void;
		onrevalidate: (entityIds: string[]) => void;
	} = $props();

	// ── Score breakdown ───────────────────────────────────────────────────
	let entityResults = $derived(results.filter((r) => r.entity_id === score.entity_id));
	let resultByAttrId = $derived(new Map(entityResults.map((r) => [r.attribute_id, r])));
	let totalWeight = $derived(attributes.reduce((s, a) => s + a.weight, 0) || 1);

	interface BreakdownRow {
		attribute: Attribute;
		result: Result | undefined;
		present: boolean;
		confidence: number | null;
		weightPct: number;
		contribution: number;
	}

	let breakdown = $derived.by(() => {
		return attributes.map((attr): BreakdownRow => {
			const r = resultByAttrId.get(attr.id);
			const present = r?.present ?? false;
			const confidence = r?.confidence ?? null;
			const weightPct = attr.weight / totalWeight;
			const contribution = present ? weightPct * (confidence ?? 1) : 0;
			return { attribute: attr, result: r, present, confidence, weightPct, contribution };
		}).sort((a, b) => b.contribution - a.contribution);
	});

	let coveragePct = $derived(
		attributes.length ? Math.round((entityResults.length / attributes.length) * 100) : 0
	);
	let scorePct = $derived(Math.round(score.total_score * 100));

	// ── Expand/collapse ───────────────────────────────────────────────────
	let expandedId = $state<string | null>(null);

	// ── Re-validate ───────────────────────────────────────────────────────
	let revalidating = $state(false);

	function handleRevalidate() {
		revalidating = true;
		try {
			onrevalidate([score.entity_id]);
		} finally {
			revalidating = false;
		}
	}

	// ── Focus trap ────────────────────────────────────────────────────────
	let panel: HTMLDivElement | undefined = $state();

	function trapFocus(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
			return;
		}
		if (e.key !== 'Tab' || !panel) return;

		const focusable = panel.querySelectorAll<HTMLElement>(
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

	// Focus the panel on mount
	$effect(() => {
		if (panel) {
			const firstFocusable = panel.querySelector<HTMLElement>(
				'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
			);
			firstFocusable?.focus();
		}
	});

	// ── Helpers ───────────────────────────────────────────────────────────
	function statusIcon(row: BreakdownRow): string {
		if (!row.result) return '\u2014';
		return row.present ? '\u2713' : '\u2717';
	}

	function statusColor(row: BreakdownRow): string {
		if (!row.result) return 'text-slate-600';
		return row.present ? 'text-green-400' : 'text-red-400';
	}

	function confBar(confidence: number | null): number {
		if (confidence === null) return 0;
		return Math.round(confidence * 100);
	}

	function backdropClick(e: MouseEvent) {
		if ((e.target as HTMLElement).dataset.backdrop) onclose();
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 z-40 flex justify-end"
	role="presentation"
	data-backdrop="true"
	onmousedown={backdropClick}
>
	<div class="fixed inset-0 bg-black/50 transition-opacity"></div>

	<!-- Panel -->
	<div
		bind:this={panel}
		class="relative z-50 w-full max-w-lg bg-navy-900 border-l border-navy-700 h-full overflow-y-auto flex flex-col shadow-2xl"
		role="dialog"
		aria-modal="true"
		aria-labelledby="entity-panel-title"
		tabindex="-1"
		onkeydown={trapFocus}
	>
		<!-- Header -->
		<div class="sticky top-0 bg-navy-900 border-b border-navy-700 px-5 py-4 flex items-start gap-3 z-10">
			<div class="flex-1 min-w-0">
				<h2 id="entity-panel-title" class="font-medium text-slate-200 truncate">
					{score.entity_label ?? score.entity_id}
				</h2>
				{#if score.gwm_id}
					<p class="text-xs text-slate-500 font-mono mt-0.5">{score.gwm_id}</p>
				{/if}
			</div>
			<div class="flex items-center gap-2 shrink-0">
				<button
					onclick={handleRevalidate}
					disabled={revalidating}
					class="text-xs px-3 py-1.5 rounded-lg border border-navy-600 hover:border-gold/40 text-slate-400 hover:text-gold transition-all disabled:opacity-50"
				>
					{revalidating ? '\u2026' : '\u21BB Re-run'}
				</button>
				<button
					onclick={onclose}
					class="text-slate-500 hover:text-slate-300 p-1"
					aria-label="Close detail panel"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Score summary -->
		<div class="px-5 py-4 border-b border-navy-800">
			{#if score.score_stale}
				<div
					class="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-amber-950 border border-amber-700 text-amber-300 text-xs"
					role="status"
				>
					<svg class="w-4 h-4 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
					</svg>
					Score is being recalculated
				</div>
			{/if}
			<div class="grid grid-cols-3 gap-3 mb-3">
				<div class="text-center">
					<p class="text-2xl font-mono font-bold text-gold">{score.total_score.toFixed(2)}</p>
					<p class="text-[10px] text-slate-500 mt-0.5">Score</p>
				</div>
				<div class="text-center">
					<p class="text-2xl font-mono font-bold text-green-400">{score.attributes_present}</p>
					<p class="text-[10px] text-slate-500 mt-0.5">Present</p>
				</div>
				<div class="text-center">
					<p class="text-2xl font-mono font-bold text-slate-400">{coveragePct}<span class="text-sm text-slate-600">%</span></p>
					<p class="text-[10px] text-slate-500 mt-0.5">Coverage</p>
				</div>
			</div>
			<div class="h-1.5 bg-navy-700 rounded-full overflow-hidden">
				<div
					class="h-1.5 rounded-full bg-gold transition-all"
					style="width: {scorePct}%"
					role="progressbar"
					aria-valuenow={scorePct}
					aria-valuemin={0}
					aria-valuemax={100}
					aria-label="Total score"
				></div>
			</div>
		</div>

		<!-- Score breakdown table -->
		<div class="flex-1 px-5 py-4">
			<h3 class="text-[10px] text-slate-500 uppercase tracking-widest mb-3">
				Score Breakdown ({breakdown.length} attributes)
			</h3>

			{#if breakdown.length === 0}
				<p class="text-slate-500 text-sm text-center py-8">No attributes configured.</p>
			{:else}
				<!-- Column headers -->
				<div class="grid grid-cols-[auto_1fr_3.5rem_4rem_4.5rem] gap-x-2 px-3 py-1.5 text-[10px] text-slate-600 uppercase tracking-wider border-b border-navy-700 mb-1">
					<span></span>
					<span>Attribute</span>
					<span class="text-right">Weight</span>
					<span class="text-right">Conf.</span>
					<span class="text-right">Contrib.</span>
				</div>

				<!-- Rows -->
				<div class="space-y-0.5" role="list" aria-label="Score breakdown by attribute">
					{#each breakdown as row (row.attribute.id)}
						{@const isExpanded = expandedId === row.attribute.id}
						<div
							class="rounded-lg overflow-hidden border transition-colors
								{row.result ? 'bg-navy-800 border-navy-700 hover:border-navy-600' : 'bg-navy-800/30 border-navy-700/30'}"
							role="listitem"
						>
							<button
								onclick={() => (expandedId = isExpanded ? null : row.attribute.id)}
								class="w-full grid grid-cols-[auto_1fr_3.5rem_4rem_4.5rem] gap-x-2 items-center px-3 py-2 text-left"
								aria-expanded={isExpanded}
								aria-label="{row.attribute.label}: {row.result ? (row.present ? 'present' : 'absent') : 'not validated'}, contribution {(row.contribution * 100).toFixed(1)}%"
							>
								<!-- Status icon -->
								<span class="text-sm font-bold {statusColor(row)} w-4 text-center">
									{statusIcon(row)}
								</span>

								<!-- Attribute name -->
								<span class="text-sm text-slate-300 truncate">{row.attribute.label}</span>

								<!-- Weight -->
								<span class="text-xs text-slate-500 font-mono text-right tabular-nums">
									{row.attribute.weight.toFixed(1)}
								</span>

								<!-- Confidence -->
								<span class="text-xs font-mono text-right tabular-nums {row.confidence !== null ? 'text-slate-300' : 'text-slate-600'}">
									{row.confidence !== null ? `${confBar(row.confidence)}%` : '\u2014'}
								</span>

								<!-- Contribution -->
								<span class="text-xs font-mono text-right tabular-nums font-semibold
									{row.contribution > 0 ? 'text-gold' : 'text-slate-600'}">
									{row.contribution > 0 ? `+${(row.contribution * 100).toFixed(1)}%` : '0.0%'}
								</span>
							</button>

							<!-- Contribution bar -->
							{#if row.result}
								<div class="px-3 pb-1.5">
									<div class="h-0.5 bg-navy-700 rounded-full overflow-hidden">
										<div
											class="h-0.5 rounded-full transition-all {row.present ? 'bg-green-500' : 'bg-red-500/40'}"
											style="width: {row.present ? confBar(row.confidence) || 70 : 20}%"
										></div>
									</div>
								</div>
							{/if}

							<!-- Expanded evidence -->
							{#if isExpanded && row.result}
								<div class="border-t border-navy-700 px-3 py-3 space-y-2">
									{#if row.result.evidence}
										<div>
											<p class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Evidence</p>
											<p class="text-xs text-slate-300 leading-relaxed">{row.result.evidence}</p>
										</div>
									{/if}
									{#if row.attribute.description}
										<div>
											<p class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Attribute Description</p>
											<p class="text-xs text-slate-400 leading-relaxed">{row.attribute.description}</p>
										</div>
									{/if}
									{#if !row.result.evidence && !row.attribute.description}
										<p class="text-xs text-slate-600 italic">No evidence recorded.</p>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Footer actions -->
		<div class="sticky bottom-0 bg-navy-900 border-t border-navy-700 px-5 py-3 flex gap-2">
			<a
				href="/campaigns/{campaignId}/entities"
				class="flex-1 text-center text-xs py-2 rounded-lg border border-navy-600 text-slate-400 hover:text-gold hover:border-gold/30 transition-all"
			>
				Edit Entity
			</a>
			<button
				onclick={handleRevalidate}
				disabled={revalidating}
				class="flex-1 text-xs py-2 rounded-lg bg-gold text-navy font-semibold hover:bg-gold-light transition-all disabled:opacity-50"
			>
				{revalidating ? 'Starting\u2026' : '\u21BB Re-validate'}
			</button>
		</div>
	</div>
</div>
