<script lang="ts">
	import { onMount } from 'svelte';
	import { campaignsApi, type Campaign, type CampaignStats } from '$lib/api/campaigns';
	import { jobsApi, type Job } from '$lib/api/jobs';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';

	let campaigns = $state<Campaign[]>([]);
	let latestJobs = $state<Record<string, Job | null>>({});
	let stats = $state<CampaignStats | null>(null);
	let loading = $state(true);
	let error = $state('');
	let cloning = $state<Set<string>>(new Set());
	let runningIds = $state<Set<string>>(new Set());

	// Inline edit state
	let editingId = $state<string | null>(null);
	let editName = $state('');
	let editDesc = $state('');
	let savingEdit = $state(false);

	function startEdit(c: Campaign, e: Event) {
		e.preventDefault();
		e.stopPropagation();
		editingId = c.id;
		editName = c.name;
		editDesc = c.description ?? '';
	}

	function cancelEdit() {
		editingId = null;
	}

	async function saveEdit(id: string) {
		savingEdit = true;
		try {
			const updated = await campaignsApi.update(id, {
				name: editName,
				description: editDesc || undefined,
			});
			campaigns = campaigns.map((c) => (c.id === id ? updated : c));
			editingId = null;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to save');
		} finally {
			savingEdit = false;
		}
	}

	async function loadCampaigns(teamId: string | null) {
		loading = true;
		error = '';
		try {
			[campaigns, stats] = await Promise.all([
				campaignsApi.list(teamId),
				campaignsApi.getStats(teamId).catch(() => null),
			]);
			// Fetch latest job per campaign in parallel
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
	}

	$effect(() => { loadCampaigns($scoutTeam); });
	onMount(() => { /* effect handles initial load */ });

	async function runNow(campaignId: string, e: Event) {
		e.preventDefault();
		runningIds = new Set([...runningIds, campaignId]);
		try {
			const job = await jobsApi.create(campaignId, {});
			latestJobs[campaignId] = job;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to start job');
		} finally {
			runningIds = new Set([...runningIds].filter((x) => x !== campaignId));
		}
	}

	async function toggleActive(c: Campaign, e: Event) {
		e.preventDefault();
		e.stopPropagation();
		const updated = await campaignsApi.update(c.id, { is_active: !c.is_active });
		campaigns = campaigns.map((x) => (x.id === c.id ? updated : x));
	}

	async function cloneCampaign(id: string, e: Event) {
		e.preventDefault();
		e.stopPropagation();
		cloning = new Set([...cloning, id]);
		try {
			const newCampaign = await campaignsApi.clone(id);
			campaigns = [newCampaign, ...campaigns];
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to clone');
		} finally {
			cloning = new Set([...cloning].filter((x) => x !== id));
		}
	}

	async function deleteCampaign(id: string, name: string, e: Event) {
		e.preventDefault();
		e.stopPropagation();
		if (!confirm(`Delete campaign "${name}"? This cannot be undone.`)) return;
		try {
			await campaignsApi.delete(id);
			campaigns = campaigns.filter((c) => c.id !== id);
			if (stats) stats = { ...stats, campaigns: stats.campaigns - 1 };
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		}
	}

	function statusColor(status: string) {
		return { queued: 'text-slate-400', running: 'text-gold', done: 'text-green-400', failed: 'text-red-400', cancelled: 'text-slate-500' }[status] ?? 'text-slate-400';
	}

	function statusDot(status: string) {
		return { queued: 'bg-slate-500', running: 'bg-gold animate-pulse', done: 'bg-green-500', failed: 'bg-red-500', cancelled: 'bg-slate-600' }[status] ?? 'bg-slate-600';
	}

	function timeAgo(iso: string | null): string {
		if (!iso) return '';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 2) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		if (days < 30) return `${days}d ago`;
		return `${Math.floor(days / 30)}mo ago`;
	}

	function friendlySchedule(cron: string): string {
		if (!cron) return '';
		const m = cron.match(/^0 (\d+) (\S+) \* (\S+)$/);
		if (!m) return cron;
		const [, h, domPart, dowPart] = m;
		const hour = parseInt(h);
		const hLabel = hour === 0 ? '12 AM' : hour < 12 ? `${hour} AM` : hour === 12 ? '12 PM' : `${hour - 12} PM`;
		if (dowPart === '*' && domPart !== '*') return `Monthly · ${hLabel}`;
		if (domPart === '*') {
			if (dowPart === '*') return `Daily · ${hLabel}`;
			if (dowPart === '1-5') return `Weekdays · ${hLabel}`;
			const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
			return `Weekly ${days[+dowPart] ?? dowPart} · ${hLabel}`;
		}
		return cron;
	}

	function resultFreshness(c: Campaign): { label: string; cls: string } {
		if (c.result_count === 0) return { label: 'No results', cls: 'text-slate-600' };
		if (!c.last_completed_at) return { label: 'No results', cls: 'text-slate-600' };
		const days = (Date.now() - new Date(c.last_completed_at).getTime()) / 86400000;
		if (days < 1) return { label: 'Fresh', cls: 'text-green-400' };
		if (days < 7) return { label: `${Math.floor(days)}d old`, cls: 'text-gold' };
		if (days < 30) return { label: `${Math.floor(days)}d old`, cls: 'text-orange-400' };
		return { label: `${Math.floor(days / 30)}mo old`, cls: 'text-red-400' };
	}
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-center justify-between mb-5">
		<h1 class="font-serif text-gold text-2xl font-bold">Campaigns</h1>
		<a
			href="/campaigns/new"
			class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm"
		>
			+ New Campaign
		</a>
	</div>

	<!-- Stats bar -->
	{#if stats && !loading}
		<div class="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
			{#each [
				{ label: 'Campaigns', value: stats.campaigns, icon: '◈' },
				{ label: 'Entities', value: stats.entities, icon: '⬡' },
				{ label: 'Results', value: stats.results, icon: '✓' },
				{ label: 'Jobs (7d)', value: stats.jobs_last_7_days, icon: '▶' },
				{ label: 'Knowledge', value: stats.knowledge_entries, icon: '⚡' },
			] as s}
				<div class="bg-navy-800 border border-navy-700 rounded-lg px-4 py-3">
					<div class="flex items-center gap-1.5 mb-1">
						<span class="text-slate-600 text-xs" aria-hidden="true">{s.icon}</span>
						<span class="text-[10px] text-slate-500 uppercase tracking-widest">{s.label}</span>
					</div>
					<p class="text-xl font-mono font-semibold text-slate-200">{s.value.toLocaleString()}</p>
				</div>
			{/each}
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center py-16" aria-live="polite" aria-busy="true" aria-label="Loading campaigns">
			<span class="flex gap-1" aria-hidden="true">{#each [0,1,2] as j}<span class="w-2 h-2 bg-gold/40 rounded-full animate-bounce" style="animation-delay:{j*0.15}s"></span>{/each}</span>
		</div>
	{:else if error}
		<p class="text-red-400" role="alert">{error}</p>
	{:else if campaigns.length === 0}
		<div class="text-center py-20 text-slate-500">
			<div class="w-16 h-16 bg-navy-800 border border-navy-700 rounded-xl flex items-center justify-center mx-auto mb-4">
				<span class="text-2xl text-slate-600" aria-hidden="true">◈</span>
			</div>
			<p class="text-lg mb-2">No campaigns yet.</p>
			<a href="/campaigns/new" class="text-gold hover:underline text-sm">Create your first campaign →</a>
		</div>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each campaigns as c (c.id)}
				{@const fresh = resultFreshness(c)}
				{@const job = latestJobs[c.id]}
				<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 hover:border-navy-600 transition-all flex flex-col gap-3">
					{#if editingId === c.id}
						<!-- Inline edit mode -->
						<div class="space-y-2">
							<input
								bind:value={editName}
								placeholder="Campaign name"
								class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
							/>
							<textarea
								bind:value={editDesc}
								placeholder="Description (optional)"
								rows="2"
								class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold resize-none"
							></textarea>
							<div class="flex gap-2">
								<button
									onclick={() => saveEdit(c.id)}
									disabled={savingEdit || !editName.trim()}
									class="bg-gold text-navy font-semibold px-3 py-1 rounded-lg text-xs hover:bg-gold-light disabled:opacity-50"
								>
									{savingEdit ? 'Saving…' : 'Save'}
								</button>
								<button
									onclick={cancelEdit}
									class="text-xs text-slate-400 hover:text-slate-300 px-3 py-1 border border-navy-600 rounded-lg"
								>
									Cancel
								</button>
							</div>
						</div>
					{:else}
					<!-- Top row: name + status pill -->
					<div class="flex items-start justify-between gap-2">
						<a href="/campaigns/{c.id}" class="font-medium text-slate-200 hover:text-gold transition-colors leading-snug flex-1">
							{c.name}
						</a>
						<button
							onclick={(e) => toggleActive(c, e)}
							aria-label="{c.is_active ? 'Pause' : 'Activate'} campaign {c.name}"
							aria-pressed={c.is_active}
							class="text-[10px] px-2 py-0.5 rounded-full cursor-pointer border transition-all flex-shrink-0
								{c.is_active ? 'bg-green-950 text-green-400 border-green-800' : 'bg-navy-700 text-slate-500 border-navy-600'}"
						>
							{c.is_active ? 'active' : 'paused'}
						</button>
					</div>

					{#if c.description}
						<p class="text-slate-500 text-xs line-clamp-2">{c.description}</p>
					{/if}

					<!-- Counts row -->
					<div class="flex items-center gap-3 text-xs">
						<span class="text-slate-400"><span class="text-slate-200 font-mono">{c.entity_count}</span> entities</span>
						<span class="text-slate-600">·</span>
						<span class="text-slate-400"><span class="text-slate-200 font-mono">{c.attribute_count}</span> attrs</span>
						{#if c.result_count > 0}
							<span class="text-slate-600">·</span>
							<span class="{fresh.cls} font-medium">{fresh.label}</span>
						{/if}
					</div>

					<!-- Result progress bar -->
					{#if c.entity_count > 0 && c.attribute_count > 0}
						{@const total = c.entity_count * c.attribute_count}
						{@const pct = Math.min(100, (c.result_count / total) * 100)}
						<div>
							<div class="flex items-center justify-between mb-1">
								<span class="text-[10px] text-slate-600">Coverage</span>
								<span class="text-[10px] text-slate-500 font-mono">{c.result_count}/{total}</span>
							</div>
							<div class="h-1 bg-navy-700 rounded-full">
								<div class="h-1 rounded-full bg-gold transition-all" style="width:{pct}%"></div>
							</div>
						</div>
					{/if}

					<!-- Schedule -->
					{#if c.schedule}
						<p class="text-xs text-slate-500 flex items-center gap-1">
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
							{friendlySchedule(c.schedule)}
						</p>
					{/if}

					<!-- Latest job -->
					{#if job}
						<div class="flex items-center gap-1.5 text-xs">
							<span class="w-1.5 h-1.5 rounded-full {statusDot(job.status)}" aria-hidden="true"></span>
							<span class="{statusColor(job.status)}">{job.status}</span>
							{#if job.status === 'running'}
								<span class="text-slate-500">{job.completed_pairs}/{job.total_pairs} pairs</span>
							{:else if job.completed_at}
								<span class="text-slate-600">{timeAgo(job.completed_at)}</span>
							{/if}
						</div>
					{/if}

					{/if}
					<!-- Footer actions -->
					<div class="flex items-center gap-1 pt-1 border-t border-navy-700 mt-auto">
						<a href="/campaigns/{c.id}/results" class="text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded hover:bg-navy-700">
							Results
						</a>
						<a href="/campaigns/{c.id}/jobs" class="text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded hover:bg-navy-700">
							Jobs
						</a>
						<div class="flex-1"></div>
						<button
							onclick={(e) => startEdit(c, e)}
							aria-label="Edit campaign {c.name}"
							title="Edit campaign"
							class="text-xs text-slate-600 hover:text-gold p-1.5 rounded hover:bg-navy-700 transition-colors"
						>
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
						</button>
						<button
							onclick={(e) => cloneCampaign(c.id, e)}
							disabled={cloning.has(c.id)}
							aria-label="Clone campaign {c.name}"
							title="Clone campaign"
							class="text-xs text-slate-600 hover:text-slate-300 p-1.5 rounded hover:bg-navy-700 transition-colors disabled:opacity-50"
						>
							{#if cloning.has(c.id)}
								<span class="animate-spin">↻</span>
							{:else}
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
							{/if}
						</button>
						<button
							onclick={(e) => deleteCampaign(c.id, c.name, e)}
							aria-label="Delete campaign {c.name}"
							title="Delete campaign"
							class="text-xs text-slate-600 hover:text-red-400 p-1.5 rounded hover:bg-navy-700 transition-colors"
						>
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
						</button>
						<button
							onclick={(e) => runNow(c.id, e)}
							aria-label="Run campaign {c.name} now"
							disabled={runningIds.has(c.id) || job?.status === 'running'}
							class="text-xs bg-navy-700 hover:bg-navy-600 text-slate-300 hover:text-gold px-3 py-1.5 rounded-lg transition-all border border-navy-600 hover:border-gold/30 disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{runningIds.has(c.id) ? '…' : '▶ Run'}
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
