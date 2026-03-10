<script lang="ts">
	import { onMount } from 'svelte';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { jobsApi, type Job } from '$lib/api/jobs';

	let campaigns = $state<Campaign[]>([]);
	let latestJobs = $state<Record<string, Job | null>>({});
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			campaigns = await campaignsApi.list();
			// Load latest job for each campaign
			await Promise.all(
				campaigns.map(async (c) => {
					try {
						const jobs = await jobsApi.list(c.id);
						latestJobs[c.id] = jobs[0] ?? null;
					} catch {
						latestJobs[c.id] = null;
					}
				})
			);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load campaigns';
		} finally {
			loading = false;
		}
	});

	async function runNow(campaignId: string, e: Event) {
		e.preventDefault();
		try {
			const job = await jobsApi.create(campaignId, {});
			latestJobs[campaignId] = job;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to start job');
		}
	}

	function statusColor(status: string) {
		return {
			queued: 'text-slate-400',
			running: 'text-gold',
			done: 'text-green-400',
			failed: 'text-red-400',
		}[status] ?? 'text-slate-400';
	}
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-center justify-between mb-6">
		<h1 class="font-serif text-gold text-2xl font-bold">Campaigns</h1>
		<a
			href="/campaigns/new"
			class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm"
		>
			+ New Campaign
		</a>
	</div>

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if error}
		<p class="text-red-400">{error}</p>
	{:else if campaigns.length === 0}
		<div class="text-center py-16 text-slate-500">
			<p class="text-lg mb-2">No campaigns yet.</p>
			<a href="/campaigns/new" class="text-gold hover:underline">Create your first campaign →</a>
		</div>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each campaigns as c (c.id)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 hover:border-navy-600 transition-colors">
					<div class="flex items-start justify-between mb-3">
						<a href="/campaigns/{c.id}" class="font-medium text-slate-200 hover:text-gold transition-colors">
							{c.name}
						</a>
						<span class="text-xs px-2 py-0.5 rounded {c.is_active ? 'bg-green-900 text-green-400' : 'bg-navy-700 text-slate-500'}">
							{c.is_active ? 'active' : 'paused'}
						</span>
					</div>

					{#if c.description}
						<p class="text-slate-500 text-sm mb-3 line-clamp-2">{c.description}</p>
					{/if}

					{#if c.schedule}
						<p class="text-xs text-slate-500 mb-3 font-mono">⏰ {c.schedule}</p>
					{/if}

					<!-- Latest job status -->
					{#if latestJobs[c.id]}
						{@const job = latestJobs[c.id]!}
						<div class="text-xs mb-3">
							<span class="text-slate-500">Last job: </span>
							<span class={statusColor(job.status)}>{job.status}</span>
							{#if job.status === 'running'}
								<span class="text-slate-500"> — {job.completed_pairs}/{job.total_pairs}</span>
							{/if}
						</div>
					{/if}

					<div class="flex items-center gap-2 mt-auto pt-2 border-t border-navy-700">
						<a href="/campaigns/{c.id}/results" class="text-xs text-slate-400 hover:text-gold transition-colors">
							Results
						</a>
						<span class="text-navy-600">·</span>
						<a href="/campaigns/{c.id}/jobs" class="text-xs text-slate-400 hover:text-gold transition-colors">
							Jobs
						</a>
						<div class="flex-1"></div>
						<button
							onclick={(e) => runNow(c.id, e)}
							class="text-xs bg-navy-700 hover:bg-navy-600 text-slate-300 px-3 py-1 rounded-lg transition-colors border border-navy-600"
						>
							Run Now
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
