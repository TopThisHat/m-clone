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

	onMount(async () => {
		try {
			[scores, entities, attributes, knowledge] = await Promise.all([
				jobsApi.getScores(campaignId),
				entitiesApi.list(campaignId),
				attributesApi.list(campaignId),
				jobsApi.getKnowledge(campaignId),
			]);

			// Load all results for the matrix (from all jobs' latest results)
			// We fetch by getting jobs then the most recent job's results
			const jobs = await jobsApi.list(campaignId);
			const doneJobs = jobs.filter((j) => j.status === 'done');
			if (doneJobs.length > 0) {
				// Gather all results, deduplicated by entity×attribute (keep latest)
				const allResults: Result[] = [];
				for (const job of doneJobs.slice(0, 5)) {
					const r = await jobsApi.getResults(job.id, { limit: 500 });
					allResults.push(...r);
				}
				// Deduplicate: keep last seen per entity×attribute
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

	<h2 class="font-serif text-gold text-xl font-bold mb-4">Results</h2>

	{#if error}<p class="text-red-400 mb-4">{error}</p>{/if}

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
		<ScoreBoard {scores} {results} {knowledge} {campaignId} />
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 overflow-auto">
			<AttributeMatrix {entities} {attributes} {results} {knowledge} {campaignId} />
		</div>
	{/if}
</div>
