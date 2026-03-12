<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { entitiesApi } from '$lib/api/entities';
	import { attributesApi } from '$lib/api/attributes';
	import { jobsApi, type Job } from '$lib/api/jobs';
	import JobProgress from '$lib/components/JobProgress.svelte';

	let campaignId = $derived($page.params.id as string);
	let campaign = $state<Campaign | null>(null);
	let entityCount = $state(0);
	let attributeCount = $state(0);
	let jobs = $state<Job[]>([]);
	let loading = $state(true);
	let error = $state('');
	let runningJobId = $state<string | null>(null);

	onMount(async () => {
		try {
			[campaign, , , jobs] = await Promise.all([
				campaignsApi.get(campaignId),
				entitiesApi.list(campaignId).then((e) => { entityCount = e.length; }),
				attributesApi.list(campaignId).then((a) => { attributeCount = a.length; }),
				jobsApi.list(campaignId),
			]);
			const running = jobs.find((j) => j.status === 'running' || j.status === 'queued');
			if (running) runningJobId = running.id;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load campaign';
		} finally {
			loading = false;
		}
	});

	async function runNow() {
		try {
			const job = await jobsApi.create(campaignId, {});
			jobs = [job, ...jobs];
			runningJobId = job.id;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to start job');
		}
	}

	function onJobDone(job: Job) {
		jobs = jobs.map((j) => (j.id === job.id ? job : j));
		runningJobId = null;
	}

	let latestJob = $derived(jobs[0] ?? null);

	const tabs = [
		{ label: 'Entities', href: 'entities' },
		{ label: 'Attributes', href: 'attributes' },
		{ label: 'Jobs', href: 'jobs' },
		{ label: 'Results', href: 'results' },
	];
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaigns</a>
	</div>

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if error}
		<p class="text-red-400">{error}</p>
	{:else if campaign}
		<div class="flex items-start justify-between mb-6">
			<div>
				<h1 class="font-serif text-gold text-2xl font-bold">{campaign.name}</h1>
				{#if campaign.description}
					<p class="text-slate-400 mt-1">{campaign.description}</p>
				{/if}
				{#if campaign.schedule}
					<p class="text-xs text-slate-500 mt-1 font-mono">⏰ {campaign.schedule}</p>
				{/if}
			</div>
			<button
				onclick={runNow}
				disabled={runningJobId !== null}
				class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light
				       transition-colors disabled:opacity-50 text-sm"
			>
				{runningJobId ? 'Running…' : 'Run Now'}
			</button>
		</div>

		<!-- Stats row -->
		<div class="grid grid-cols-3 gap-4 mb-6">
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-4 text-center">
				<p class="text-2xl font-bold text-slate-200">{entityCount}</p>
				<p class="text-sm text-slate-500 mt-1">Entities</p>
			</div>
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-4 text-center">
				<p class="text-2xl font-bold text-slate-200">{attributeCount}</p>
				<p class="text-sm text-slate-500 mt-1">Attributes</p>
			</div>
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-4 text-center">
				<p class="text-2xl font-bold text-slate-200">{jobs.length}</p>
				<p class="text-sm text-slate-500 mt-1">Jobs</p>
			</div>
		</div>

		<!-- Active job progress -->
		{#if runningJobId}
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-4 mb-6">
				<p class="text-sm text-slate-400 mb-2">Active job</p>
				<JobProgress jobId={runningJobId} onDone={onJobDone} />
			</div>
		{:else if latestJob}
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-4 mb-6">
				<p class="text-xs text-slate-500 mb-1">Last job ({new Date(latestJob.created_at).toLocaleDateString()})</p>
				<div class="flex items-center gap-2">
					<span class="text-sm {latestJob.status === 'done' ? 'text-green-400' : latestJob.status === 'failed' ? 'text-red-400' : 'text-slate-400'}">
						{latestJob.status}
					</span>
					{#if latestJob.total_pairs > 0}
						<span class="text-sm text-slate-500">{latestJob.completed_pairs}/{latestJob.total_pairs} pairs</span>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Nav tabs -->
		<div class="flex gap-1 border-b border-navy-700 mb-6">
			{#each tabs as tab}
				<a
					href="/campaigns/{campaignId}/{tab.href}"
					class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
					       text-slate-400 hover:text-slate-200"
				>
					{tab.label}
				</a>
			{/each}
		</div>

		<p class="text-slate-500 text-sm">Select a tab to manage this campaign.</p>
	{/if}
</div>
