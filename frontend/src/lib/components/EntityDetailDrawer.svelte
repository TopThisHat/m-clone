<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import { jobsApi, type Score, type Result, type CrossCampaignResult } from '$lib/api/jobs';
	import type { Attribute } from '$lib/api/attributes';

	interface Props {
		score: Score;
		results: Result[];
		attributes: Attribute[];
		campaignId: string;
		onClose: () => void;
		onRevalidate: (entityIds: string[]) => void;
	}

	let { score, results, attributes, campaignId, onClose, onRevalidate }: Props = $props();

	let expandedResult = $state<string | null>(null);
	let revalidating = $state(false);
	let crossResults = $state<CrossCampaignResult[]>([]);
	let showCross = $state(false);

	onMount(async () => {
		if (score.gwm_id) {
			try {
				crossResults = await jobsApi.getEntityCrossCampaign(score.gwm_id);
			} catch { /* ignore */ }
		}
	});

	let otherCampaignResults = $derived(
		crossResults.filter((r) => r.campaign_id !== campaignId)
	);

	const entityResults = $derived(results.filter((r) => r.entity_id === score.entity_id));
	const attrByLabel = $derived(new Map(attributes.map((a) => [a.label, a])));
	const totalWeight = $derived(attributes.reduce((s, a) => s + a.weight, 0) || 1);
	const present = $derived(entityResults.filter((r) => r.present));
	const absent = $derived(entityResults.filter((r) => !r.present));
	const coveragePct = $derived(attributes.length ? Math.round((entityResults.length / attributes.length) * 100) : 0);
	const scoreRaw = $derived(score.total_score.toFixed(2));
	const scoreBarPct = $derived(Math.round(score.total_score * 100));

	function renderMd(md: string | null) {
		return md ? (marked.parse(md) as string) : '';
	}

	async function handleRevalidate() {
		revalidating = true;
		try {
			onRevalidate([score.entity_id]);
		} finally {
			revalidating = false;
		}
	}

	function backdropClick(e: MouseEvent) {
		if ((e.target as HTMLElement).dataset.backdrop) onClose();
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 z-40 flex justify-end"
	role="presentation"
	data-backdrop="true"
	onmousedown={backdropClick}
>
	<div class="fixed inset-0 bg-black/40"></div>

	<!-- Drawer panel -->
	<div class="relative z-50 w-full max-w-md bg-navy-900 border-l border-navy-700 h-full overflow-y-auto flex flex-col shadow-2xl">
		<!-- Header -->
		<div class="sticky top-0 bg-navy-900 border-b border-navy-700 px-5 py-4 flex items-start gap-3">
			<div class="flex-1 min-w-0">
				<h2 class="font-medium text-slate-200 truncate">{score.entity_label ?? score.entity_id}</h2>
				{#if score.gwm_id}
					<p class="text-xs text-slate-600 font-mono mt-0.5">{score.gwm_id}</p>
				{/if}
			</div>
			<div class="flex items-center gap-2 flex-shrink-0">
				<button
					onclick={handleRevalidate}
					disabled={revalidating}
					class="text-xs px-3 py-1.5 rounded-lg border border-navy-600 hover:border-gold/40 text-slate-400 hover:text-gold transition-all disabled:opacity-50"
				>
					{revalidating ? '…' : '↻ Re-run'}
				</button>
				<button onclick={onClose} class="text-slate-500 hover:text-slate-300 p-1" aria-label="Close detail drawer">
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Score summary -->
		<div class="px-5 py-4 border-b border-navy-800">
			<div class="grid grid-cols-3 gap-3 mb-3">
				<div class="text-center">
					<p class="text-2xl font-mono font-bold text-gold">{scoreRaw}</p>
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
			<!-- Score bar -->
			<div class="h-1.5 bg-navy-700 rounded-full">
				<div class="h-1.5 rounded-full bg-gold transition-all" style="width:{scoreBarPct}%"></div>
			</div>
		</div>

		<!-- Attribute results -->
		<div class="flex-1 px-5 py-4 space-y-2">
			{#if entityResults.length === 0}
				<p class="text-slate-500 text-sm text-center py-8">No results yet. Run a validation job first.</p>
			{:else}
				<!-- Present attributes -->
				{#if present.length > 0}
					<p class="text-[10px] text-slate-600 uppercase tracking-widest mb-2">Present ({present.length})</p>
					{#each present as r (r.id)}
						{@const attr = attrByLabel.get(r.attribute_label ?? '')}
						<div class="bg-navy-800 border border-navy-700 rounded-lg overflow-hidden">
							<button
								onclick={() => (expandedResult = expandedResult === r.id ? null : r.id)}
								class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-navy-700 transition-colors"
							>
								<span class="text-green-400 font-bold text-sm flex-shrink-0">✓</span>
								<div class="flex-1 min-w-0">
									<p class="text-sm text-slate-200 truncate">{r.attribute_label}</p>
									{#if r.confidence != null}
										<div class="flex items-center gap-2 mt-0.5">
											<div class="flex-1 h-0.5 bg-navy-700 rounded-full max-w-20">
												<div class="h-0.5 rounded-full bg-green-500" style="width:{r.confidence * 100}%"></div>
											</div>
											<span class="text-[10px] text-slate-500">{(r.confidence * 100).toFixed(0)}%</span>
										</div>
									{/if}
								</div>
								{#if attr}
									<span class="text-[10px] text-slate-600 bg-navy-700 px-1.5 py-0.5 rounded flex-shrink-0">w:{attr.weight.toFixed(1)}</span>
								{/if}
								<svg class="w-3 h-3 text-slate-600 flex-shrink-0 transition-transform {expandedResult === r.id ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
							</button>
							{#if expandedResult === r.id}
								<div class="border-t border-navy-700 px-3 py-3 space-y-2">
									{#if r.evidence}
										<div>
											<p class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Evidence</p>
											<p class="text-xs text-slate-300 leading-relaxed">{r.evidence}</p>
										</div>
									{/if}
									{#if r.report_md}
										<details>
											<summary class="text-[10px] text-slate-500 uppercase tracking-wider cursor-pointer hover:text-gold">Research report ▸</summary>
											<div class="mt-2 prose prose-xs max-w-none text-xs bg-navy-900 rounded p-2 max-h-48 overflow-y-auto">
												<!-- eslint-disable-next-line svelte/no-at-html-tags -->
												{@html renderMd(r.report_md)}
											</div>
										</details>
									{/if}
									{#if !r.evidence && !r.report_md}
										<p class="text-xs text-slate-600 italic">No evidence recorded.</p>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				{/if}

				<!-- Absent attributes -->
				{#if absent.length > 0}
					<p class="text-[10px] text-slate-600 uppercase tracking-widest mb-2 mt-4">Absent ({absent.length})</p>
					{#each absent as r (r.id)}
						<div class="bg-navy-800/50 border border-navy-700/50 rounded-lg overflow-hidden">
							<button
								onclick={() => (expandedResult = expandedResult === r.id ? null : r.id)}
								class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-navy-700/50 transition-colors"
							>
								<span class="text-red-400 text-sm flex-shrink-0">✗</span>
								<div class="flex-1 min-w-0">
									<p class="text-sm text-slate-400 truncate">{r.attribute_label}</p>
									{#if r.confidence != null}
										<span class="text-[10px] text-slate-600">{(r.confidence * 100).toFixed(0)}% conf</span>
									{/if}
								</div>
								<svg class="w-3 h-3 text-slate-600 flex-shrink-0 transition-transform {expandedResult === r.id ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
							</button>
							{#if expandedResult === r.id && (r.evidence || r.report_md)}
								<div class="border-t border-navy-700/50 px-3 py-3 space-y-2">
									{#if r.evidence}
										<p class="text-xs text-slate-400">{r.evidence}</p>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				{/if}

				<!-- Unchecked attributes -->
				{#if entityResults.length < attributes.length}
					{@const checkedLabels = new Set(entityResults.map((r) => r.attribute_label))}
					{@const unchecked = attributes.filter((a) => !checkedLabels.has(a.label))}
					{#if unchecked.length > 0}
						<p class="text-[10px] text-slate-600 uppercase tracking-widest mb-2 mt-4">Not validated ({unchecked.length})</p>
						{#each unchecked as attr (attr.id)}
							<div class="flex items-center gap-3 px-3 py-2 bg-navy-800/30 border border-navy-700/30 rounded-lg">
								<span class="text-slate-600 text-sm">—</span>
								<p class="text-sm text-slate-600">{attr.label}</p>
							</div>
						{/each}
					{/if}
				{/if}
			{/if}

			<!-- Cross-campaign results -->
			{#if otherCampaignResults.length > 0}
				<button
					onclick={() => (showCross = !showCross)}
					class="w-full text-left text-[10px] text-slate-600 uppercase tracking-widest mt-4 hover:text-gold transition-colors"
				>
					Across campaigns ({otherCampaignResults.length} results) {showCross ? '▾' : '▸'}
				</button>
				{#if showCross}
					<div class="space-y-1 mt-2">
						{#each otherCampaignResults as cr}
							<div class="flex items-center gap-2 px-2 py-1.5 bg-navy-800/50 rounded text-xs">
								<span class="{cr.present ? 'text-green-400' : 'text-red-400'}">{cr.present ? '✓' : '✗'}</span>
								<span class="text-slate-300 flex-1 min-w-0 truncate">{cr.attribute_label}</span>
								<span class="text-slate-500 flex-shrink-0">{cr.campaign_name}</span>
								{#if cr.total_score != null}
									<span class="text-gold font-mono flex-shrink-0">{cr.total_score.toFixed(2)}</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
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
				{revalidating ? 'Starting…' : '↻ Re-validate'}
			</button>
		</div>
	</div>
</div>
