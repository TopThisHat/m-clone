<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { jobsApi, type Score, type Result, type Knowledge } from '$lib/api/jobs';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import { marked } from 'marked';
	import ScoreBoard from '$lib/components/ScoreBoard.svelte';
	import AttributeMatrix from '$lib/components/AttributeMatrix.svelte';
	import EntityDetailDrawer from '$lib/components/EntityDetailDrawer.svelte';
	import JobProgress from '$lib/components/JobProgress.svelte';
	import type { Job } from '$lib/api/jobs';

	let campaignId = $derived($page.params.id as string);
	let scores = $state<Score[]>([]);
	let results = $state<Result[]>([]);
	let entities = $state<Entity[]>([]);
	let attributes = $state<Attribute[]>([]);
	let knowledge = $state<Knowledge[]>([]);
	let loading = $state(true);
	let error = $state('');
	let activeTab = $state<'scores' | 'matrix'>('scores');

	// Filters
	let searchQuery = $state('');
	let selectedAttrs = $state<Set<string>>(new Set());
	let sortAsc = $state(false);
	let minConfidence = $state(0);
	let minScore = $state(0);
	let presenceOnly = $state(false);

	// Selection + re-validate
	let selectedEntityIds = $state<Set<string>>(new Set());
	let revalidateJob = $state<Job | null>(null);
	let revalidating = $state(false);

	// Active job tracking (detected on mount or via re-validate)
	let activeJob = $state<Job | null>(null);
	let lastResultCount = $state(0);

	// Entity detail drawer
	let drawerScore = $state<Score | null>(null);

	// Evidence modal (matrix tab)
	let modalResult = $state<Result | null>(null);

	const filteredScores = $derived.by(() => {
		let s = scores.filter((sc) => {
			if (searchQuery && !(sc.entity_label ?? '').toLowerCase().includes(searchQuery.toLowerCase())) return false;
			if (sc.total_score < minScore) return false;
			if (presenceOnly && sc.attributes_present === 0) return false;
			return true;
		});
		return [...s].sort((a, b) => sortAsc ? a.total_score - b.total_score : b.total_score - a.total_score);
	});

	const filteredAttributes = $derived(
		selectedAttrs.size === 0 ? attributes : attributes.filter((a) => selectedAttrs.has(a.id))
	);

	const filteredEntities = $derived(
		searchQuery === '' ? entities : entities.filter((e) => e.label.toLowerCase().includes(searchQuery.toLowerCase()))
	);

	const allFilteredIds = $derived(new Set(filteredScores.map((s) => s.entity_id)));
	const allSelected = $derived(filteredScores.length > 0 && filteredScores.every((s) => selectedEntityIds.has(s.entity_id)));

	function toggleAttr(id: string) {
		const next = new Set(selectedAttrs);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedAttrs = next;
	}

	function toggleSelectAll() {
		if (allSelected) {
			selectedEntityIds = new Set();
		} else {
			selectedEntityIds = new Set(filteredScores.map((s) => s.entity_id));
		}
	}

	function resetFilters() {
		searchQuery = '';
		selectedAttrs = new Set();
		minScore = 0;
		presenceOnly = false;
		minConfidence = 0;
	}

	const hasActiveFilters = $derived(
		searchQuery !== '' || selectedAttrs.size > 0 || minScore > 0 || presenceOnly || minConfidence > 0
	);

	async function startRevalidate(entityIds: string[]) {
		if (!entityIds.length) return;
		revalidating = true;
		try {
			const job = await jobsApi.create(campaignId, { entity_ids: entityIds });
			revalidateJob = job;
			activeJob = job;
			lastResultCount = 0;
			selectedEntityIds = new Set();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to start job');
		} finally {
			revalidating = false;
		}
	}

	function exportCSV() {
		window.location.href = `/api/campaigns/${campaignId}/export?format=csv`;
	}

	async function loadResultsForJobs(jobs: Job[]) {
		const allResults: Result[] = [];
		for (const job of jobs.slice(0, 5)) {
			const r = await jobsApi.getResults(job.id, { limit: 500 });
			allResults.push(...r);
		}
		const seen = new Map<string, Result>();
		for (const r of allResults) seen.set(`${r.entity_id}:${r.attribute_id}`, r);
		return [...seen.values()];
	}

	async function refreshIncrementalResults() {
		if (!activeJob) return;
		try {
			const [liveScores, liveResults] = await Promise.all([
				jobsApi.getLiveScores(activeJob.id),
				jobsApi.getResults(activeJob.id, { limit: 500 }),
			]);
			// Merge live scores with existing finalized scores
			const scoreMap = new Map(scores.map((s) => [s.entity_id, s]));
			for (const ls of liveScores) scoreMap.set(ls.entity_id, ls);
			scores = [...scoreMap.values()];
			// Merge live results with existing results
			const seen = new Map(results.map((r) => [`${r.entity_id}:${r.attribute_id}`, r]));
			for (const r of liveResults) seen.set(`${r.entity_id}:${r.attribute_id}`, r);
			results = [...seen.values()];
			lastResultCount = liveResults.length;
		} catch {
			// ignore incremental refresh errors
		}
	}

	onMount(async () => {
		try {
			const [scoresResult, entitiesResult, attributesResult, knowledgeResult] = await Promise.all([
				jobsApi.getScores(campaignId),
				entitiesApi.list(campaignId, { limit: 0 }),
				attributesApi.list(campaignId, { limit: 0 }),
				jobsApi.getKnowledge(campaignId),
			]);
			scores = scoresResult;
			entities = entitiesResult.items;
			attributes = attributesResult.items;
			knowledge = knowledgeResult;
			const jobs = await jobsApi.list(campaignId);

			// Check for running/queued job
			const runningJob = jobs.find((j) => j.status === 'running' || j.status === 'queued');
			if (runningJob) {
				activeJob = runningJob;
				// Load whatever results exist so far
				if (runningJob.status === 'running' && runningJob.completed_pairs > 0) {
					await refreshIncrementalResults();
				}
			}

			// Also load results from done jobs
			const doneJobs = jobs.filter((j) => j.status === 'done');
			if (doneJobs.length > 0) {
				const doneResults = await loadResultsForJobs(doneJobs);
				// Merge (live results take precedence since they may be newer)
				const seen = new Map(doneResults.map((r) => [`${r.entity_id}:${r.attribute_id}`, r]));
				for (const r of results) seen.set(`${r.entity_id}:${r.attribute_id}`, r);
				results = [...seen.values()];
			}
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load results';
		} finally {
			loading = false;
		}
	});

	async function onJobProgress(_job: Job) {
		await refreshIncrementalResults();
	}

	async function onActiveJobDone() {
		activeJob = null;
		revalidateJob = null;
		// Final refresh with finalized scores
		const [finalScores, finalKnowledge] = await Promise.all([
			jobsApi.getScores(campaignId),
			jobsApi.getKnowledge(campaignId),
		]);
		scores = finalScores;
		knowledge = finalKnowledge;
		const jobs = await jobsApi.list(campaignId);
		const doneJobs = jobs.filter((j) => j.status === 'done');
		results = await loadResultsForJobs(doneJobs);
	}
</script>

<div class="max-w-6xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4 flex-wrap gap-2">
		<h2 class="font-serif text-gold text-xl font-bold">Results</h2>
		<div class="flex gap-2">
			{#if selectedEntityIds.size > 0}
				<button
					onclick={() => startRevalidate([...selectedEntityIds])}
					disabled={revalidating}
					class="text-xs bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg hover:bg-gold-light transition-colors disabled:opacity-50"
				>
					{revalidating ? '…' : `↻ Re-run ${selectedEntityIds.size} selected`}
				</button>
			{/if}
			<button
				onclick={exportCSV}
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors"
			>
				Export CSV
			</button>
		</div>
	</div>

	<!-- Active job progress (running on mount or re-validation) -->
	{#if activeJob}
		<div class="mb-4 bg-navy-800 border border-navy-700 rounded-xl p-3">
			<div class="flex items-center gap-2 mb-2">
				<span class="relative flex h-2.5 w-2.5">
					<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-gold opacity-75"></span>
					<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-gold"></span>
				</span>
				<span class="text-xs text-slate-400">Results updating live as pairs complete</span>
			</div>
			<JobProgress jobId={activeJob.id} onDone={onActiveJobDone} onProgress={onJobProgress} />
		</div>
	{/if}

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	<!-- Filter bar -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-4 space-y-3">
		<div class="flex gap-3 items-center flex-wrap">
			<!-- Search -->
			<div class="flex-1 min-w-40">
				<input
					bind:value={searchQuery}
					placeholder="Search entities…"
					aria-label="Search entities"
					class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
				/>
			</div>

			<!-- Sort -->
			<button
				onclick={() => (sortAsc = !sortAsc)}
				aria-label="Sort by score {sortAsc ? 'ascending' : 'descending'}"
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors whitespace-nowrap"
			>
				Score {sortAsc ? '↑' : '↓'}
			</button>

			<!-- Presence only toggle -->
			<button
				onclick={() => (presenceOnly = !presenceOnly)}
				aria-pressed={presenceOnly}
				class="text-xs px-3 py-1.5 rounded-lg border transition-all whitespace-nowrap
					{presenceOnly ? 'bg-gold/10 border-gold/40 text-gold' : 'bg-navy-700 border-navy-600 text-slate-400 hover:text-slate-300'}"
			>
				✓ With results only
			</button>

			{#if hasActiveFilters}
				<button onclick={resetFilters} class="text-xs text-slate-500 hover:text-slate-300 transition-colors">Reset filters</button>
			{/if}
		</div>

		<!-- Score range -->
		<div class="flex items-center gap-3">
			<span class="text-xs text-slate-500 whitespace-nowrap">Min score:</span>
			<input type="range" min="0" max="1" step="0.05" bind:value={minScore} aria-label="Minimum score" aria-valuenow={minScore} class="flex-1 max-w-40 accent-gold" />
			<span class="text-xs text-slate-400 font-mono w-10">{minScore.toFixed(2)}</span>
		</div>

		<!-- Confidence slider -->
		<div class="flex items-center gap-3">
			<span class="text-xs text-slate-500 whitespace-nowrap">Min confidence:</span>
			<input type="range" min="0" max="1" step="0.05" bind:value={minConfidence} aria-label="Minimum confidence" aria-valuenow={Math.round(minConfidence * 100)} class="flex-1 max-w-40 accent-gold" />
			<span class="text-xs text-slate-400 font-mono w-8">{(minConfidence * 100).toFixed(0)}%</span>
		</div>

		<!-- Attribute filter pills -->
		{#if attributes.length > 0}
			<div class="flex gap-2 flex-wrap" role="group" aria-label="Filter by attribute">
				{#each attributes as attr (attr.id)}
					<button
						onclick={() => toggleAttr(attr.id)}
						class="text-xs px-2.5 py-0.5 rounded-full border transition-all
							{selectedAttrs.has(attr.id) ? 'bg-gold text-navy border-gold font-semibold' : 'bg-navy-700 text-slate-400 border-navy-600 hover:border-navy-500'}"
					>
						{attr.label}
					</button>
				{/each}
				{#if selectedAttrs.size > 0}
					<button onclick={() => (selectedAttrs = new Set())} class="text-xs text-slate-500 hover:text-slate-300 px-2">Clear</button>
				{/if}
			</div>
		{/if}

		<!-- Active filters summary -->
		<div class="flex items-center gap-3 text-xs text-slate-500">
			<span>Showing <span class="text-slate-300 font-mono">{filteredScores.length}</span> of <span class="text-slate-300 font-mono">{scores.length}</span> entities</span>
			{#if activeTab === 'scores' && filteredScores.length > 0}
				<button onclick={toggleSelectAll} class="text-slate-500 hover:text-gold transition-colors">
					{allSelected ? 'Deselect all' : 'Select all visible'}
				</button>
				{#if selectedEntityIds.size > 0}
					<span class="text-gold">{selectedEntityIds.size} selected</span>
				{/if}
			{/if}
		</div>
	</div>

	<!-- Tabs -->
	<div class="flex gap-1 border-b border-navy-700 mb-4" role="tablist">
		{#each [['scores', 'Score Board'], ['matrix', 'Attribute Matrix']] as [val, label]}
			<button
				onclick={() => { activeTab = val as 'scores' | 'matrix'; selectedEntityIds = new Set(); }}
				role="tab"
				aria-selected={activeTab === val}
				class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
					{activeTab === val ? 'bg-navy-700 text-gold' : 'text-slate-400 hover:text-slate-200'}"
			>
				{label}
			</button>
		{/each}
	</div>

	{#if loading}
		<div class="flex justify-center py-16" aria-live="polite" aria-busy="true" aria-label="Loading results">
			<span class="flex gap-1" aria-hidden="true">{#each [0,1,2] as j}<span class="w-2 h-2 bg-gold/40 rounded-full animate-bounce" style="animation-delay:{j*0.15}s"></span>{/each}</span>
		</div>
	{:else if activeTab === 'scores'}
		<ScoreBoard
			scores={filteredScores}
			{results}
			{knowledge}
			{campaignId}
			{attributes}
			{minConfidence}
			selectedIds={selectedEntityIds}
			onselect={(ids) => (selectedEntityIds = ids)}
			onopen={(score) => (drawerScore = score)}
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

<!-- Entity detail drawer -->
{#if drawerScore}
	<EntityDetailDrawer
		score={drawerScore}
		{results}
		{attributes}
		{campaignId}
		onClose={() => (drawerScore = null)}
		onRevalidate={(ids) => { drawerScore = null; startRevalidate(ids); }}
	/>
{/if}

<!-- Evidence modal (matrix) -->
{#if modalResult}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
		onclick={() => (modalResult = null)}>
		<div class="bg-navy-800 border border-navy-600 rounded-xl w-full max-w-lg shadow-2xl p-6 max-h-[80vh] overflow-y-auto"
		role="dialog"
		aria-modal="true"
		aria-labelledby="evidence-modal-title"
		tabindex="-1"
		onclick={(e) => e.stopPropagation()}>
			<div class="flex items-start justify-between mb-4">
				<div>
					<p id="evidence-modal-title" class="font-medium text-slate-200">{modalResult.entity_label}</p>
					<p class="text-slate-400 text-sm">{modalResult.attribute_label}</p>
				</div>
				<button onclick={() => (modalResult = null)} aria-label="Close evidence panel" class="text-slate-500 hover:text-slate-300">✕</button>
			</div>
			<div class="flex items-center gap-3 mb-4">
				<span class="font-semibold {modalResult.present ? 'text-green-400' : 'text-red-400'}">{modalResult.present ? '✓ Present' : '✗ Absent'}</span>
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
					<div class="prose prose-sm prose-invert max-w-none bg-navy-900 rounded-lg p-3 max-h-64 overflow-y-auto">
						{@html marked.parse(modalResult.report_md)}
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}
