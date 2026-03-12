<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { jobsApi, type Score, type Result, type Knowledge } from '$lib/api/jobs';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import ScoreBoard from '$lib/components/ScoreBoard.svelte';
	import AttributeMatrix from '$lib/components/AttributeMatrix.svelte';

	let campaignId = $derived($page.params.id as string);
	let scores = $state<Score[]>([]);
	let results = $state<Result[]>([]);
	let entities = $state<Entity[]>([]);
	let attributes = $state<Attribute[]>([]);
	let knowledge = $state<Knowledge[]>([]);
	let loading = $state(true);
	let error = $state('');
	let activeTab = $state<'scores' | 'matrix'>('scores');

	// Search / filter
	let searchQuery = $state('');
	let selectedAttrs = $state<Set<string>>(new Set());
	let sortAsc = $state(false);
	let minConfidence = $state(0);

	// Evidence modal
	let modalResult = $state<Result | null>(null);

	let filteredScores = $derived(() => {
		let s = scores.filter((sc) =>
			searchQuery === '' || (sc.entity_label ?? '').toLowerCase().includes(searchQuery.toLowerCase())
		);
		s = [...s].sort((a, b) =>
			sortAsc ? a.total_score - b.total_score : b.total_score - a.total_score
		);
		return s;
	});

	let filteredAttributes = $derived(
		selectedAttrs.size === 0 ? attributes : attributes.filter((a) => selectedAttrs.has(a.id))
	);

	let filteredEntities = $derived(
		searchQuery === ''
			? entities
			: entities.filter((e) => e.label.toLowerCase().includes(searchQuery.toLowerCase()))
	);

	function toggleAttr(id: string) {
		const next = new Set(selectedAttrs);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedAttrs = next;
	}

	function exportCSV() {
		const rows: string[][] = [['Entity', 'Attribute', 'Present', 'Confidence', 'Evidence']];
		for (const r of results) {
			rows.push([
				r.entity_label ?? '',
				r.attribute_label ?? '',
				String(r.present),
				r.confidence != null ? (r.confidence * 100).toFixed(0) + '%' : '',
				r.evidence ?? '',
			]);
		}
		const csv = rows.map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
		const a = document.createElement('a');
		a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
		a.download = `campaign-results.csv`;
		a.click();
	}

	onMount(async () => {
		try {
			[scores, entities, attributes, knowledge] = await Promise.all([
				jobsApi.getScores(campaignId),
				entitiesApi.list(campaignId),
				attributesApi.list(campaignId),
				jobsApi.getKnowledge(campaignId),
			]);

			const jobs = await jobsApi.list(campaignId);
			const doneJobs = jobs.filter((j) => j.status === 'done');
			if (doneJobs.length > 0) {
				const allResults: Result[] = [];
				for (const job of doneJobs.slice(0, 5)) {
					const r = await jobsApi.getResults(job.id, { limit: 500 });
					allResults.push(...r);
				}
				const seen = new Map<string, Result>();
				for (const r of allResults) {
					seen.set(`${r.entity_id}:${r.attribute_id}`, r);
				}
				results = [...seen.values()];
			}
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load results';
		} finally {
			loading = false;
		}
	});
</script>

<div class="max-w-6xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4">
		<h2 class="font-serif text-gold text-xl font-bold">Results</h2>
		<button
			onclick={exportCSV}
			class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg
			       hover:bg-navy-600 transition-colors"
		>
			Export CSV
		</button>
	</div>

	{#if error}<p class="text-red-400 mb-4">{error}</p>{/if}

	<!-- Filter bar -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-4 space-y-3">
		<div class="flex gap-4 items-center flex-wrap">
			<!-- Search -->
			<div class="flex-1 min-w-48">
				<input
					bind:value={searchQuery}
					placeholder="Search entities…"
					class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
					       placeholder-slate-500 focus:outline-none focus:border-gold"
				/>
			</div>
			<!-- Sort toggle -->
			<button
				onclick={() => (sortAsc = !sortAsc)}
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg
				       hover:bg-navy-600 transition-colors whitespace-nowrap"
			>
				Score: {sortAsc ? '↑ Low→High' : '↓ High→Low'}
			</button>
			<!-- Confidence slider -->
			<div class="flex items-center gap-2">
				<span class="text-xs text-slate-400 whitespace-nowrap">Min confidence:</span>
				<input type="range" min="0" max="1" step="0.05" bind:value={minConfidence} class="w-28 accent-gold" />
				<span class="text-xs text-slate-300 w-8">{(minConfidence * 100).toFixed(0)}%</span>
			</div>
		</div>

		<!-- Attribute filter pills -->
		{#if attributes.length > 0}
			<div class="flex gap-2 flex-wrap">
				{#each attributes as attr (attr.id)}
					<button
						onclick={() => toggleAttr(attr.id)}
						class="text-xs px-2.5 py-0.5 rounded-full border transition-colors
						       {selectedAttrs.has(attr.id)
						         ? 'bg-gold text-navy border-gold font-semibold'
						         : 'bg-navy-700 text-slate-400 border-navy-600 hover:border-navy-500'}"
					>
						{attr.label}
					</button>
				{/each}
				{#if selectedAttrs.size > 0}
					<button
						onclick={() => (selectedAttrs = new Set())}
						class="text-xs text-slate-500 hover:text-slate-300 px-2"
					>
						Clear
					</button>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Tabs -->
	<div class="flex gap-1 border-b border-navy-700 mb-6">
		<button
			onclick={() => (activeTab = 'scores')}
			class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
			       {activeTab === 'scores' ? 'bg-navy-700 text-gold' : 'text-slate-400 hover:text-slate-200'}"
		>
			Score Board
		</button>
		<button
			onclick={() => (activeTab = 'matrix')}
			class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
			       {activeTab === 'matrix' ? 'bg-navy-700 text-gold' : 'text-slate-400 hover:text-slate-200'}"
		>
			Attribute Matrix
		</button>
	</div>

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if activeTab === 'scores'}
		<ScoreBoard
			scores={filteredScores()}
			{results}
			{knowledge}
			{campaignId}
			{attributes}
			{minConfidence}
		/>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 overflow-auto">
			<AttributeMatrix
				entities={filteredEntities}
				attributes={filteredAttributes}
				{results}
				{knowledge}
				{campaignId}
				{minConfidence}
				oncellclick={(r) => (modalResult = r)}
			/>
		</div>
	{/if}
</div>

<!-- Evidence modal -->
{#if modalResult}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
		onclick={() => (modalResult = null)}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
		<div
			class="bg-navy-800 border border-navy-600 rounded-xl w-full max-w-lg shadow-2xl p-6 max-h-[80vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-start justify-between mb-4">
				<div>
					<p class="font-medium text-slate-200">{modalResult.entity_label}</p>
					<p class="text-slate-400 text-sm">{modalResult.attribute_label}</p>
				</div>
				<button onclick={() => (modalResult = null)} class="text-slate-500 hover:text-slate-300 text-lg leading-none">✕</button>
			</div>
			<div class="flex items-center gap-3 mb-4">
				<span class="font-semibold {modalResult.present ? 'text-green-400' : 'text-red-400'}">
					{modalResult.present ? '✓ Present' : '✗ Absent'}
				</span>
				{#if modalResult.confidence != null}
					<span class="text-slate-400 text-sm">({(modalResult.confidence * 100).toFixed(0)}% confidence)</span>
				{/if}
			</div>
			{#if modalResult.evidence}
				<div class="mb-4">
					<p class="text-xs text-slate-500 mb-1 uppercase tracking-wide">Evidence</p>
					<p class="text-slate-300 text-sm">{modalResult.evidence}</p>
				</div>
			{/if}
			{#if modalResult.report_md}
				<div>
					<p class="text-xs text-slate-500 mb-1 uppercase tracking-wide">Research Report</p>
					<pre class="text-slate-400 text-xs whitespace-pre-wrap font-mono bg-navy-900 rounded-lg p-3 max-h-64 overflow-y-auto">{modalResult.report_md}</pre>
				</div>
			{/if}
		</div>
	</div>
{/if}
