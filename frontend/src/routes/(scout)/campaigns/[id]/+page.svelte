<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { entitiesApi } from '$lib/api/entities';
	import { attributesApi } from '$lib/api/attributes';
	import { jobsApi, type Job } from '$lib/api/jobs';
	import JobProgress from '$lib/components/JobProgress.svelte';
	import SchedulePicker from '$lib/components/SchedulePicker.svelte';

	let campaignId = $derived($page.params.id as string);
	let campaign = $state<Campaign | null>(null);
	let entityCount = $state(0);
	let attributeCount = $state(0);
	let jobs = $state<Job[]>([]);
	let loading = $state(true);
	let error = $state('');
	let runError = $state('');
	let runningJobId = $state<string | null>(null);

	// Edit panel
	let showEdit = $state(false);
	let editName = $state('');
	let editDesc = $state('');
	let editSchedule = $state('');
	let editActive = $state(true);
	let saving = $state(false);
	let saveError = $state('');

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

	function openEdit() {
		if (!campaign) return;
		editName = campaign.name;
		editDesc = campaign.description ?? '';
		editSchedule = campaign.schedule ?? '';
		editActive = campaign.is_active;
		saveError = '';
		showEdit = true;
	}

	async function saveEdit(e: Event) {
		e.preventDefault();
		if (!campaign) return;
		saving = true;
		saveError = '';
		try {
			campaign = await campaignsApi.update(campaign.id, {
				name: editName,
				description: editDesc || undefined,
				schedule: editSchedule || undefined,
				is_active: editActive,
			});
			showEdit = false;
		} catch (err: unknown) {
			saveError = err instanceof Error ? err.message : 'Failed to save';
		} finally {
			saving = false;
		}
	}

	async function deleteCampaign() {
		if (!campaign) return;
		if (!confirm(`Delete campaign "${campaign.name}"? This cannot be undone.`)) return;
		try {
			await campaignsApi.delete(campaign.id);
			goto('/campaigns');
		} catch (err: unknown) {
			saveError = err instanceof Error ? err.message : 'Failed to delete';
		}
	}

	async function runNow() {
		runError = '';
		if (entityCount === 0 || attributeCount === 0) {
			runError = 'Add entities and attributes before running.';
			return;
		}
		try {
			const job = await jobsApi.create(campaignId, {});
			jobs = [job, ...jobs];
			runningJobId = job.id;
		} catch (err: unknown) {
			runError = err instanceof Error ? err.message : 'Failed to start job';
		}
	}

	function onJobDone(job: Job) {
		jobs = jobs.map((j) => (j.id === job.id ? job : j));
		runningJobId = null;
	}

	let latestJob = $derived(jobs[0] ?? null);

	function friendlySchedule(cron: string): string {
		if (!cron) return '';
		const m = cron.match(/^0 (\d+) (\S+) \* (\S+)$/);
		if (!m) return cron;
		const [, h, domPart, dowPart] = m;
		const hour = parseInt(h);
		const hLabel = hour === 0 ? '12 AM' : hour < 12 ? `${hour} AM` : hour === 12 ? '12 PM' : `${hour - 12} PM`;
		if (dowPart === '*' && domPart !== '*') return `Monthly on the ${domPart}${['st','nd','rd'][+domPart-1]||'th'} at ${hLabel}`;
		if (domPart === '*') {
			if (dowPart === '*') return `Daily at ${hLabel}`;
			if (dowPart === '1-5') return `Weekdays at ${hLabel}`;
			const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
			return `Weekly on ${days[+dowPart] ?? dowPart} at ${hLabel}`;
		}
		return cron;
	}

	let nextRunCountdown = $derived(() => {
		if (!campaign?.next_run_at) return null;
		const diff = new Date(campaign.next_run_at).getTime() - Date.now();
		if (diff <= 0) return 'soon';
		const h = Math.floor(diff / 3600000);
		const m = Math.floor((diff % 3600000) / 60000);
		return h > 0 ? `${h}h ${m}m` : `${m}m`;
	});

	const tabs = [
		{ label: 'Entities', href: 'entities' },
		{ label: 'Attributes', href: 'attributes' },
		{ label: 'Jobs', href: 'jobs' },
		{ label: 'Results', href: 'results' },
		{ label: 'Knowledge', href: 'knowledge' },
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
		<div class="flex items-start justify-between mb-4">
			<div>
				<h1 class="font-serif text-gold text-2xl font-bold">{campaign.name}</h1>
				{#if campaign.description}
					<p class="text-slate-400 mt-1">{campaign.description}</p>
				{/if}
				{#if campaign.schedule}
					<p class="text-xs text-slate-500 mt-1">⏰ {friendlySchedule(campaign.schedule)}
						{#if nextRunCountdown()}
							<span class="ml-2 text-slate-400">· Next run in {nextRunCountdown()}</span>
						{/if}
					</p>
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<button
					onclick={openEdit}
					class="text-slate-500 hover:text-slate-300 p-1.5 rounded transition-colors"
					title="Edit campaign"
				>
					⚙
				</button>
				<button
					onclick={runNow}
					disabled={runningJobId !== null}
					class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light
					       transition-colors disabled:opacity-50 text-sm"
				>
					{runningJobId ? 'Running…' : 'Run Now'}
				</button>
			</div>
		</div>

		{#if runError}
			<p class="text-red-400 text-sm mb-4">{runError}</p>
		{/if}

		<!-- Edit panel -->
		{#if showEdit}
			<form onsubmit={saveEdit} class="bg-navy-800 border border-navy-600 rounded-xl p-5 mb-6">
				<h3 class="font-medium text-slate-200 mb-4">Edit Campaign</h3>
				{#if saveError}
					<p class="text-red-400 text-sm mb-3">{saveError}</p>
				{/if}
				<div class="space-y-4 mb-4">
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs text-slate-400 mb-1">Name *</label>
							<input bind:value={editName} required class="input-field w-full" />
						</div>
						<div>
							<label class="block text-xs text-slate-400 mb-1">Description</label>
							<input bind:value={editDesc} class="input-field w-full" />
						</div>
					</div>
					<div>
						<label class="block text-xs text-slate-400 mb-2">Schedule <span class="text-slate-600">(optional)</span></label>
						<SchedulePicker bind:value={editSchedule} />
					</div>
				</div>
				<div class="flex items-center gap-4 mb-4">
					<label class="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
						<input type="checkbox" bind:checked={editActive} class="accent-gold" />
						Active
					</label>
				</div>
				<div class="flex items-center justify-between">
					<div class="flex gap-2">
						<button type="submit" disabled={saving}
						        class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
							{saving ? 'Saving…' : 'Save'}
						</button>
						<button type="button" onclick={() => (showEdit = false)}
						        class="bg-navy-700 text-slate-300 px-4 py-1.5 rounded-lg text-sm border border-navy-600">
							Cancel
						</button>
					</div>
					<button type="button" onclick={deleteCampaign}
					        class="text-red-400 hover:text-red-300 text-sm px-3 py-1.5 rounded-lg border border-red-900 hover:bg-red-950 transition-colors">
						Delete Campaign
					</button>
				</div>
			</form>
		{/if}

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

<style>
	.input-field {
		@apply bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
		       placeholder-slate-500 focus:outline-none focus:border-gold;
	}
</style>
