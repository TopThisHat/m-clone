<script lang="ts">
	import type { Score, Result, Knowledge } from '$lib/api/jobs';
	import type { Attribute } from '$lib/api/attributes';

	let {
		scores,
		results = [],
		knowledge = [],
		campaignId = '',
		attributes = [],
		minConfidence = 0,
		selectedIds = new Set<string>(),
		onselect,
		onopen,
	}: {
		scores: Score[];
		results?: Result[];
		knowledge?: Knowledge[];
		campaignId?: string;
		attributes?: Attribute[];
		minConfidence?: number;
		selectedIds?: Set<string>;
		onselect?: (ids: Set<string>) => void;
		onopen?: (score: Score) => void;
	} = $props();

	let expanded = $state<Set<string>>(new Set());

	function toggle(entityId: string) {
		const next = new Set(expanded);
		if (next.has(entityId)) next.delete(entityId);
		else next.add(entityId);
		expanded = next;
	}

	function toggleSelect(entityId: string, e: MouseEvent) {
		e.stopPropagation();
		const next = new Set(selectedIds);
		if (next.has(entityId)) next.delete(entityId);
		else next.add(entityId);
		onselect?.(next);
	}

	// Pre-index results by entity_id for O(1) lookup instead of O(n) per render
	let resultsByEntity = $derived(
		results.reduce((map, r) => {
			const arr = map.get(r.entity_id);
			if (arr) arr.push(r);
			else map.set(r.entity_id, [r]);
			return map;
		}, new Map<string, Result[]>())
	);

	function entityResults(entityId: string) {
		return resultsByEntity.get(entityId) ?? [];
	}

	let cachedGwmIds = $derived(
		new Set(
			knowledge
				.filter((k) => k.source_campaign_id && k.source_campaign_id !== campaignId)
				.map((k) => k.gwm_id)
		)
	);

	function hasCachedKnowledge(gwm_id: string | null): boolean {
		return !!gwm_id && cachedGwmIds.has(gwm_id);
	}

	let maxScore = $derived(scores.length === 0 ? 0.01 : Math.max(...scores.map((s) => s.total_score), 0.01));
	let attrByLabel = $derived(new Map(attributes.map((a) => [a.label, a])));
	let totalWeight = $derived(attributes.reduce((s, a) => s + a.weight, 0) || 1);

	function timeAgo(iso: string | null): string {
		if (!iso) return '';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 2) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}

	function stalenessColor(iso: string | null): string {
		if (!iso) return 'text-slate-600';
		const days = (Date.now() - new Date(iso).getTime()) / 86400000;
		if (days < 1) return 'text-green-500';
		if (days < 7) return 'text-gold';
		if (days < 30) return 'text-orange-400';
		return 'text-red-400';
	}
</script>

<div class="space-y-1.5">
	{#each scores as score (score.entity_id)}
		{@const isSelected = selectedIds.has(score.entity_id)}
		<div class="bg-navy-800 border rounded-lg overflow-hidden transition-all {isSelected ? 'border-gold/40 bg-gold/5' : 'border-navy-700'}">
			<!-- Header row -->
			<div class="flex items-center gap-2">
				<!-- Checkbox -->
				{#if onselect}
					<button
						onclick={(e) => toggleSelect(score.entity_id, e)}
						class="min-w-[44px] min-h-[44px] flex items-center justify-center flex-shrink-0 text-slate-500 hover:text-gold transition-colors"
						title="Select for re-validation"
					>
						<div class="w-4 h-4 rounded border-2 flex items-center justify-center transition-all
							{isSelected ? 'border-gold bg-gold' : 'border-navy-500 hover:border-gold/50'}">
							{#if isSelected}
								<svg class="w-2.5 h-2.5 text-navy" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
								</svg>
							{/if}
						</div>
					</button>
				{/if}

				<!-- Main clickable row -->
				<button
					onclick={() => toggle(score.entity_id)}
					aria-expanded={expanded.has(score.entity_id)}
					class="flex-1 flex items-center gap-4 pr-2 py-3 hover:bg-navy-700/40 transition-colors text-left min-w-0"
				>
					<div class="flex-1 min-w-0">
						<div class="flex items-center justify-between mb-1">
							<span class="font-medium text-slate-200 truncate">{score.entity_label ?? score.entity_id}</span>
							<div class="flex items-center gap-1.5 ml-2 flex-shrink-0">
								{#if score.score_stale}
									<span
										class="text-amber-400 text-xs px-1.5 py-0.5 rounded border border-amber-700 bg-amber-950 animate-pulse"
										title="Score is being recalculated"
										role="status"
										tabindex="0"
										aria-label="Score is being recalculated"
									>recalculating</span>
								{/if}
								{#if hasCachedKnowledge(score.gwm_id)}
									<span class="text-yellow-400 text-xs px-1 py-0.5 rounded border border-yellow-700 bg-yellow-950" title="Has cached knowledge">⚡</span>
								{/if}
								{#if score.last_updated}
									<span class="text-xs {stalenessColor(score.last_updated)}" title="Last updated">{timeAgo(score.last_updated)}</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-3">
							<div class="flex-1 bg-navy-700 rounded-full h-1.5 max-w-40">
								<div class="h-1.5 rounded-full bg-gold transition-all" style="width:{(score.total_score / maxScore) * 100}%"></div>
							</div>
							<span class="text-gold font-mono text-sm">{score.total_score.toFixed(2)}</span>
							<span class="text-xs text-slate-500">{score.attributes_present}/{score.attributes_checked}</span>
						</div>
					</div>
					<svg
						class="w-4 h-4 text-slate-600 transition-transform flex-shrink-0 {expanded.has(score.entity_id) ? 'rotate-180' : ''}"
						fill="none" stroke="currentColor" viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
					</svg>
				</button>

				<!-- Open drawer button -->
				{#if onopen}
					<button
						onclick={() => onopen?.(score)}
						class="pr-3 py-3 text-slate-600 hover:text-gold transition-colors flex-shrink-0"
						title="Open detail panel"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
						</svg>
					</button>
				{/if}
			</div>

			<!-- Expanded attribute breakdown -->
			{#if expanded.has(score.entity_id)}
				<div class="border-t border-navy-700 px-4 py-3 space-y-2">
					{#each entityResults(score.entity_id) as r (r.id)}
						{@const attr = attrByLabel.get(r.attribute_label ?? '')}
						{@const lowConf = minConfidence > 0 && r.confidence != null && r.confidence < minConfidence}
						<div class="flex items-start gap-2 text-sm {lowConf ? 'opacity-40' : ''}">
							<span class="mt-0.5 flex-shrink-0 {r.present ? 'text-green-400' : 'text-red-400'}">{r.present ? '✓' : '✗'}</span>
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2 flex-wrap">
									<span class="text-slate-300">{r.attribute_label}</span>
									{#if r.confidence !== null}
										<span class="text-slate-500 text-xs">({(r.confidence * 100).toFixed(0)}%)</span>
									{/if}
									{#if attr}
										<span class="text-xs text-slate-600 bg-navy-700 px-1.5 py-0.5 rounded">w:{attr.weight.toFixed(1)}</span>
									{/if}
								</div>
								{#if attr && r.present}
									<div class="mt-1 h-0.5 bg-navy-700 rounded-full w-24">
										<div class="h-0.5 rounded-full bg-gold/50" style="width:{(attr.weight / totalWeight) * 100}%"></div>
									</div>
								{/if}
								{#if r.evidence}
									<p class="text-slate-500 text-xs mt-0.5 line-clamp-3" title={r.evidence}>{r.evidence}</p>
								{/if}
							</div>
						</div>
					{:else}
						<p class="text-slate-500 text-sm">No detailed results loaded.</p>
					{/each}
				</div>
			{/if}
		</div>
	{:else}
		<p class="text-slate-500 text-center py-10">No scores yet. Run a job first.</p>
	{/each}
</div>
