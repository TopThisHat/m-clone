<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { jobsApi, type Job } from '$lib/api/jobs';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import JobProgress from '$lib/components/JobProgress.svelte';

	let campaignId = $derived($page.params.id as string);
	let jobs = $state<Job[]>([]);
	let entities = $state<Entity[]>([]);
	let attributes = $state<Attribute[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Status filter
	let statusFilter = $state<string>('all');
	let filteredJobs = $derived(
		statusFilter === 'all' ? jobs : jobs.filter((j) => j.status === statusFilter)
	);

	// Cancel state
	let cancelling = $state<Set<string>>(new Set());

	// Ad-hoc modal
	let showModal = $state(false);
	let selectedEntities = $state<Set<string>>(new Set());
	let selectedAttributes = $state<Set<string>>(new Set());
	let launching = $state(false);

	onMount(async () => {
		try {
			[jobs, entities, attributes] = await Promise.all([
				jobsApi.list(campaignId),
				entitiesApi.list(campaignId),
				attributesApi.list(campaignId),
			]);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load';
		} finally {
			loading = false;
		}
	});

	function onJobDone(job: Job) {
		jobs = jobs.map((j) => (j.id === job.id ? job : j));
	}

	async function cancelJob(jobId: string) {
		cancelling = new Set([...cancelling, jobId]);
		try {
			await jobsApi.cancel(jobId);
			jobs = jobs.map((j) => j.id === jobId ? { ...j, status: 'cancelled' as const } : j);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to cancel');
		} finally {
			cancelling = new Set([...cancelling].filter((x) => x !== jobId));
		}
	}

	async function launchAdHoc() {
		launching = true;
		try {
			const job = await jobsApi.create(campaignId, {
				entity_ids: selectedEntities.size > 0 ? [...selectedEntities] : undefined,
				attribute_ids: selectedAttributes.size > 0 ? [...selectedAttributes] : undefined,
			});
			jobs = [job, ...jobs];
			showModal = false;
			selectedEntities = new Set();
			selectedAttributes = new Set();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to start job');
		} finally {
			launching = false;
		}
	}

	function toggleEntity(id: string) {
		const next = new Set(selectedEntities);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedEntities = next;
	}

	function toggleAttribute(id: string) {
		const next = new Set(selectedAttributes);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedAttributes = next;
	}

	function statusColor(status: string): string {
		return {
			queued: 'bg-slate-700 text-slate-300',
			running: 'bg-gold/20 text-gold',
			done: 'bg-green-900 text-green-400',
			failed: 'bg-red-950 text-red-400',
			cancelled: 'bg-slate-800 text-slate-400',
		}[status] ?? 'bg-slate-700 text-slate-300';
	}

	function age(dateStr: string): string {
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}

	const filterOptions = ['all', 'queued', 'running', 'done', 'failed', 'cancelled'];
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4">
		<h2 class="font-serif text-gold text-xl font-bold">Jobs ({jobs.length})</h2>
		<button
			onclick={() => (showModal = true)}
			class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm"
		>
			Run Ad-hoc
		</button>
	</div>

	<!-- Status filter pills -->
	<div class="flex gap-2 mb-6 flex-wrap" role="group" aria-label="Filter jobs by status">
		{#each filterOptions as opt}
			<button
				onclick={() => (statusFilter = opt)}
				aria-pressed={statusFilter === opt}
				class="text-xs px-3 py-1 rounded-full transition-colors border
				       {statusFilter === opt
				         ? 'bg-gold text-navy border-gold font-semibold'
				         : 'bg-navy-800 text-slate-400 border-navy-600 hover:border-navy-500'}"
			>
				{opt.charAt(0).toUpperCase() + opt.slice(1)}
			</button>
		{/each}
	</div>

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading…</p>
	{:else if filteredJobs.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>{statusFilter === 'all' ? 'No jobs yet. Run one to get started.' : `No ${statusFilter} jobs.`}</p>
		</div>
	{:else}
		<div class="space-y-3">
			{#each filteredJobs as job (job.id)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl p-4">
					<div class="flex items-center justify-between mb-2">
						<div class="flex items-center gap-3">
							<span class="text-xs px-2 py-0.5 rounded font-medium {statusColor(job.status)}">
								{job.status}
							</span>
							<span class="text-slate-500 text-xs">{age(job.created_at)}</span>
							<span class="text-slate-500 text-xs">by {job.triggered_by ?? 'unknown'}</span>
						</div>
						<div class="flex items-center gap-3">
							{#if job.entity_filter || job.attribute_filter}
								<span class="text-xs text-slate-500">
									subset: {job.entity_filter?.length ?? 'all'} entities × {job.attribute_filter?.length ?? 'all'} attrs
								</span>
							{/if}
							{#if job.status === 'queued' || job.status === 'running'}
								<button
									onclick={() => cancelJob(job.id)}
									disabled={cancelling.has(job.id)}
									aria-label="Cancel job"
									class="text-xs text-red-400 hover:text-red-300 border border-red-900 px-2 py-0.5 rounded
									       hover:bg-red-950 transition-colors disabled:opacity-50"
								>
									{cancelling.has(job.id) ? '…' : 'Cancel'}
								</button>
							{/if}
						</div>
					</div>

					{#if job.status === 'running' || job.status === 'queued'}
						<JobProgress jobId={job.id} onDone={onJobDone} />
					{:else if job.total_pairs > 0}
						<div class="text-sm text-slate-400">
							{job.completed_pairs}/{job.total_pairs} pairs completed
						</div>
					{/if}

					{#if job.error}
						<p class="text-red-400 text-xs mt-1">{job.error}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Ad-hoc run modal -->
{#if showModal}
	<div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
		<div class="bg-navy-800 border border-navy-600 rounded-xl w-full max-w-2xl p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="adhoc-dialog-title">
			<h3 id="adhoc-dialog-title" class="font-serif text-gold text-lg font-bold mb-4">Run Ad-hoc Job</h3>
			<p class="text-slate-400 text-sm mb-4">
				Leave a section empty to include all entities or attributes.
			</p>

			<div class="grid grid-cols-2 gap-6 mb-6">
				<div>
					<h4 class="text-sm font-medium text-slate-300 mb-2">
						Entities
						{#if selectedEntities.size > 0}
							<span class="text-gold">({selectedEntities.size} selected)</span>
						{:else}
							<span class="text-slate-500">(all)</span>
						{/if}
					</h4>
					<div class="space-y-1 max-h-48 overflow-y-auto">
						{#each entities as e (e.id)}
							<label class="flex items-center gap-2 text-sm cursor-pointer hover:bg-navy-700 px-2 py-1 rounded">
								<input
									type="checkbox"
									checked={selectedEntities.has(e.id)}
									onchange={() => toggleEntity(e.id)}
									class="accent-gold"
								/>
								<span class="text-slate-300">{e.label}</span>
								{#if e.gwm_id}<span class="text-slate-500 text-xs">{e.gwm_id}</span>{/if}
							</label>
						{/each}
					</div>
				</div>

				<div>
					<h4 class="text-sm font-medium text-slate-300 mb-2">
						Attributes
						{#if selectedAttributes.size > 0}
							<span class="text-gold">({selectedAttributes.size} selected)</span>
						{:else}
							<span class="text-slate-500">(all)</span>
						{/if}
					</h4>
					<div class="space-y-1 max-h-48 overflow-y-auto">
						{#each attributes as a (a.id)}
							<label class="flex items-center gap-2 text-sm cursor-pointer hover:bg-navy-700 px-2 py-1 rounded">
								<input
									type="checkbox"
									checked={selectedAttributes.has(a.id)}
									onchange={() => toggleAttribute(a.id)}
									class="accent-gold"
								/>
								<span class="text-slate-300">{a.label}</span>
								<span class="text-slate-500 text-xs">w={a.weight}</span>
							</label>
						{/each}
					</div>
				</div>
			</div>

			<div class="flex gap-3">
				<button
					onclick={launchAdHoc}
					disabled={launching}
					class="bg-gold text-navy font-semibold px-5 py-2 rounded-lg hover:bg-gold-light
					       transition-colors disabled:opacity-50 text-sm"
				>
					{launching ? 'Launching…' : 'Launch Job'}
				</button>
				<button
					onclick={() => (showModal = false)}
					class="bg-navy-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-navy-600
					       transition-colors border border-navy-600 text-sm"
				>
					Cancel
				</button>
			</div>
		</div>
	</div>
{/if}
