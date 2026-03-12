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
	}: {
		scores: Score[];
		results?: Result[];
		knowledge?: Knowledge[];
		campaignId?: string;
		attributes?: Attribute[];
		minConfidence?: number;
	} = $props();

	let expanded = $state<Set<string>>(new Set());

	function toggle(entityId: string) {
		const next = new Set(expanded);
		if (next.has(entityId)) next.delete(entityId);
		else next.add(entityId);
		expanded = next;
	}

	function entityResults(entityId: string) {
		return results.filter((r) => r.entity_id === entityId);
	}

	// Set of gwm_ids that have cached knowledge from other campaigns
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

	let maxScore = $derived(Math.max(...scores.map((s) => s.total_score), 1));

	// Build attribute lookup by label for weight info
	let attrByLabel = $derived(new Map(attributes.map((a) => [a.label, a])));

	let totalWeight = $derived(attributes.reduce((s, a) => s + a.weight, 0) || 1);
</script>

<div class="space-y-2">
	{#each scores as score (score.entity_id)}
		<div class="bg-navy-800 border border-navy-700 rounded-lg overflow-hidden">
			<!-- Header row -->
			<button
				onclick={() => toggle(score.entity_id)}
				class="w-full flex items-center gap-4 px-4 py-3 hover:bg-navy-700 transition-colors text-left"
			>
				<!-- Score bar -->
				<div class="flex-1 min-w-0">
					<div class="flex items-center justify-between mb-1">
						<span class="font-medium text-slate-200 truncate">{score.entity_label ?? score.entity_id}</span>
						<div class="flex items-center gap-2 ml-2">
							{#if hasCachedKnowledge(score.gwm_id)}
								<span
									class="text-yellow-400 text-xs font-bold px-1.5 py-0.5 rounded border border-yellow-600 bg-yellow-950"
									title="Has cached knowledge from another campaign"
								>⚡</span>
							{/if}
							{#if score.gwm_id}
								<span class="text-xs text-slate-500 font-mono">{score.gwm_id}</span>
							{/if}
						</div>
					</div>
					<div class="flex items-center gap-3">
						<div class="flex-1 bg-navy-700 rounded-full h-1.5">
							<div
								class="h-1.5 rounded-full bg-gold transition-all"
								style="width: {(score.total_score / maxScore) * 100}%"
							></div>
						</div>
						<span class="text-gold font-mono text-sm w-12 text-right">
							{score.total_score.toFixed(2)}
						</span>
					</div>
				</div>
				<!-- Stats -->
				<div class="text-xs text-slate-500 whitespace-nowrap">
					{score.attributes_present}/{score.attributes_checked} attrs
				</div>
				<svg
					class="w-4 h-4 text-slate-500 transition-transform {expanded.has(score.entity_id) ? 'rotate-180' : ''}"
					fill="none" stroke="currentColor" viewBox="0 0 24 24"
				>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
				</svg>
			</button>

			<!-- Expanded attribute breakdown -->
			{#if expanded.has(score.entity_id)}
				<div class="border-t border-navy-700 px-4 py-3 space-y-2">
					{#each entityResults(score.entity_id) as r (r.id)}
						{@const attr = attrByLabel.get(r.attribute_label ?? '')}
						{@const lowConf = minConfidence > 0 && r.confidence != null && r.confidence < minConfidence}
						<div class="flex items-start gap-2 text-sm {lowConf ? 'opacity-40' : ''}">
							<span class="mt-0.5 {r.present ? 'text-green-400' : 'text-red-400'}">
								{r.present ? '✓' : '✗'}
							</span>
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2 flex-wrap">
									<span class="text-slate-300">{r.attribute_label}</span>
									{#if r.confidence !== null}
										<span class="text-slate-500 text-xs">({(r.confidence * 100).toFixed(0)}%)</span>
									{/if}
									{#if attr}
										<span class="text-xs text-slate-600 bg-navy-700 px-1.5 py-0.5 rounded"
										      title="Attribute weight">w:{attr.weight.toFixed(1)}</span>
									{/if}
								</div>
								{#if attr && r.present}
									<!-- Weight contribution bar -->
									<div class="mt-1 h-1 bg-navy-700 rounded-full w-32">
										<div
											class="h-1 rounded-full bg-gold/60 transition-all"
											style="width: {(attr.weight / totalWeight) * 100}%"
										></div>
									</div>
								{/if}
								{#if r.evidence}
									<p class="text-slate-500 text-xs mt-0.5 truncate">{r.evidence}</p>
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
		<p class="text-slate-500 text-center py-8">No scores yet. Run a job first.</p>
	{/each}
</div>
