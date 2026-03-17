<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { jobsApi, type DeadJob } from '$lib/api/jobs';

	let campaignId = $derived($page.params.id as string);
	let deadJobs = $state<DeadJob[]>([]);
	let loading = $state(true);
	let error = $state('');
	let retrying = $state<Set<string>>(new Set());
	let retryingAll = $state(false);

	onMount(async () => {
		try {
			deadJobs = await jobsApi.listDeadJobs(campaignId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load dead jobs';
		} finally {
			loading = false;
		}
	});

	async function retryJob(jobId: string) {
		retrying = new Set([...retrying, jobId]);
		try {
			await jobsApi.retryJob(jobId);
			deadJobs = deadJobs.filter((j) => j.id !== jobId);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to retry job');
		} finally {
			retrying = new Set([...retrying].filter((x) => x !== jobId));
		}
	}

	async function retryAll() {
		retryingAll = true;
		try {
			await Promise.all(deadJobs.map((j) => jobsApi.retryJob(j.id)));
			deadJobs = [];
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Some retries failed');
			deadJobs = await jobsApi.listDeadJobs(campaignId);
		} finally {
			retryingAll = false;
		}
	}

	function age(dateStr: string): string {
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4">
		<h2 class="font-serif text-gold text-xl font-bold">Failed Jobs ({deadJobs.length})</h2>
		{#if deadJobs.length > 0}
			<button
				onclick={retryAll}
				disabled={retryingAll}
				class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm disabled:opacity-50"
			>
				{retryingAll ? 'Retrying...' : `Retry All (${deadJobs.length})`}
			</button>
		{/if}
	</div>

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading...</p>
	{:else if deadJobs.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No failed jobs. All tasks completed successfully.</p>
		</div>
	{:else}
		<div class="space-y-3">
			{#each deadJobs as job (job.id)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl p-4">
					<div class="flex items-center justify-between mb-2">
						<div class="flex items-center gap-3">
							<span class="text-xs px-2 py-0.5 rounded font-medium bg-red-950 text-red-400">
								dead
							</span>
							<span class="text-slate-500 text-xs">{job.job_type}</span>
							<span class="text-slate-500 text-xs">
								{job.completed_at ? age(job.completed_at) : age(job.created_at)}
							</span>
						</div>
						<div class="flex items-center gap-3">
							<span class="text-xs text-slate-500">{job.attempts} attempts</span>
							<button
								onclick={() => retryJob(job.id)}
								disabled={retrying.has(job.id)}
								class="text-xs bg-gold text-navy font-semibold px-3 py-1 rounded-lg hover:bg-gold-light
								       transition-colors disabled:opacity-50"
							>
								{retrying.has(job.id) ? '...' : 'Retry'}
							</button>
						</div>
					</div>

					{#if job.last_error}
						<p class="text-red-400 text-xs mt-1 font-mono bg-navy-900 rounded-lg p-2 whitespace-pre-wrap">{job.last_error}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
