<script lang="ts">
	import { onMount } from 'svelte';
	import {
		listMonitors,
		createMonitor,
		deleteMonitor,
		updateMonitor,
		triggerMonitor,
		listMonitorRuns,
		type Monitor,
		type MonitorRun,
	} from '$lib/api/monitors';

	let monitors = $state<Monitor[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Form state
	let label = $state('');
	let query = $state('');
	let frequency = $state<'daily' | 'weekly'>('daily');
	let submitting = $state(false);
	let formError = $state('');

	// Edit state
	let editingId = $state<string | null>(null);
	let editLabel = $state('');
	let editQuery = $state('');
	let editFrequency = $state<'daily' | 'weekly'>('daily');
	let editSaving = $state(false);
	let editError = $state('');

	// Run history
	let expandedId = $state<string | null>(null);
	let runs = $state<MonitorRun[]>([]);
	let loadingRuns = $state(false);

	// Trigger state
	let triggering = $state<Set<string>>(new Set());

	async function load() {
		loading = true;
		error = '';
		try {
			monitors = await listMonitors();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load monitors';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!label.trim() || !query.trim()) return;
		submitting = true;
		formError = '';
		try {
			const m = await createMonitor({ label: label.trim(), query: query.trim(), frequency });
			monitors = [m, ...monitors];
			label = '';
			query = '';
			frequency = 'daily';
		} catch (e) {
			formError = e instanceof Error ? e.message : 'Failed to create monitor';
		} finally {
			submitting = false;
		}
	}

	async function handleDelete(id: string) {
		if (!confirm('Delete this monitor?')) return;
		try {
			await deleteMonitor(id);
			monitors = monitors.filter((m) => m.id !== id);
		} catch {
			// ignore
		}
	}

	function startEdit(m: Monitor) {
		editingId = m.id;
		editLabel = m.label;
		editQuery = m.query;
		editFrequency = m.frequency;
		editError = '';
	}

	async function saveEdit(e: Event) {
		e.preventDefault();
		if (!editingId) return;
		editSaving = true;
		editError = '';
		try {
			const updated = await updateMonitor(editingId, {
				label: editLabel,
				query: editQuery,
				frequency: editFrequency,
			});
			monitors = monitors.map((m) => (m.id === updated.id ? updated : m));
			editingId = null;
		} catch (e) {
			editError = e instanceof Error ? e.message : 'Failed to save';
		} finally {
			editSaving = false;
		}
	}

	async function togglePause(m: Monitor) {
		try {
			const updated = await updateMonitor(m.id, { is_active: !m.is_active });
			monitors = monitors.map((x) => (x.id === updated.id ? updated : x));
		} catch {
			// ignore
		}
	}

	async function handleTrigger(id: string) {
		triggering = new Set([...triggering, id]);
		try {
			await triggerMonitor(id);
		} catch (e) {
			alert(e instanceof Error ? e.message : 'Failed to trigger');
		} finally {
			triggering = new Set([...triggering].filter((x) => x !== id));
		}
	}

	async function toggleRuns(id: string) {
		if (expandedId === id) {
			expandedId = null;
			return;
		}
		expandedId = id;
		loadingRuns = true;
		try {
			runs = await listMonitorRuns(id);
		} catch {
			runs = [];
		} finally {
			loadingRuns = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		return new Date(iso).toLocaleString();
	}
</script>

<svelte:head>
	<title>Monitors — Playbook Research</title>
</svelte:head>

<div class="max-w-3xl mx-auto px-6 py-8">
	<div class="mb-6">
		<h1 class="font-serif text-xl text-slate-100">Scheduled Monitors</h1>
		<p class="text-sm text-slate-500 mt-1">
			Monitors automatically re-run a research query on a schedule and save the results as new
			sessions.
		</p>
	</div>

	<!-- Add monitor form -->
	<div class="border border-navy-700 rounded-lg bg-navy-800/30 p-5 mb-8">
		<h2 class="text-sm font-medium text-slate-300 mb-4">Add Monitor</h2>
		<form onsubmit={handleSubmit} class="space-y-3">
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="mon-label">Label</label>
				<input
					id="mon-label"
					bind:value={label}
					type="text"
					placeholder="e.g. TSLA weekly earnings update"
					class="w-full bg-navy-900 border border-navy-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
					required
				/>
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="mon-query">Research Query</label>
				<textarea
					id="mon-query"
					bind:value={query}
					placeholder="e.g. Analyze TSLA quarterly earnings and guidance"
					rows="2"
					class="w-full bg-navy-900 border border-navy-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40 resize-none"
					required
				></textarea>
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="mon-freq">Frequency</label>
				<select
					id="mon-freq"
					bind:value={frequency}
					class="bg-navy-900 border border-navy-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-gold/40"
				>
					<option value="daily">Daily</option>
					<option value="weekly">Weekly</option>
				</select>
			</div>
			{#if formError}
				<p class="text-xs text-red-400">{formError}</p>
			{/if}
			<button
				type="submit"
				disabled={submitting}
				class="px-4 py-2 rounded bg-gold text-navy text-xs font-medium hover:bg-gold/90 disabled:opacity-50 transition-colors"
			>
				{submitting ? 'Creating...' : 'Create Monitor'}
			</button>
		</form>
	</div>

	<!-- Monitor list -->
	{#if loading}
		<p class="text-sm text-slate-500">Loading monitors...</p>
	{:else if error}
		<p class="text-sm text-red-400">{error}</p>
	{:else if monitors.length === 0}
		<p class="text-sm text-slate-600 text-center py-8">
			No monitors yet. Create one above to get started.
		</p>
	{:else}
		<div class="space-y-3">
			{#each monitors as monitor (monitor.id)}
				<div class="border border-navy-700 rounded-lg bg-navy-800/20 px-5 py-4">
					{#if editingId === monitor.id}
						<!-- Edit form -->
						<form onsubmit={saveEdit} class="space-y-3">
							<div>
								<label class="block text-xs text-slate-400 mb-1" for="edit-label-{monitor.id}">Label</label>
								<input id="edit-label-{monitor.id}" bind:value={editLabel} required
									class="w-full bg-navy-900 border border-navy-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-gold/40" />
							</div>
							<div>
								<label class="block text-xs text-slate-400 mb-1" for="edit-query-{monitor.id}">Query</label>
								<textarea id="edit-query-{monitor.id}" bind:value={editQuery} rows="2" required
									class="w-full bg-navy-900 border border-navy-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-gold/40 resize-none"></textarea>
							</div>
							<div>
								<label class="block text-xs text-slate-400 mb-1" for="edit-freq-{monitor.id}">Frequency</label>
								<select id="edit-freq-{monitor.id}" bind:value={editFrequency}
									class="bg-navy-900 border border-navy-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-gold/40">
									<option value="daily">Daily</option>
									<option value="weekly">Weekly</option>
								</select>
							</div>
							{#if editError}
								<p class="text-xs text-red-400">{editError}</p>
							{/if}
							<div class="flex gap-2">
								<button type="submit" disabled={editSaving}
									class="px-3 py-1 rounded bg-gold text-navy text-xs font-medium hover:bg-gold/90 disabled:opacity-50 transition-colors">
									{editSaving ? 'Saving...' : 'Save'}
								</button>
								<button type="button" onclick={() => (editingId = null)}
									class="px-3 py-1 rounded border border-navy-600 text-slate-400 text-xs hover:text-slate-300 transition-colors">
									Cancel
								</button>
							</div>
						</form>
					{:else}
						<!-- Display -->
						<div class="flex items-start gap-4">
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2 mb-1">
									<span class="text-sm font-medium text-slate-200">{monitor.label}</span>
									<span class="text-[10px] px-1.5 py-0.5 rounded border border-navy-600 text-slate-500 uppercase tracking-wide">
										{monitor.frequency}
									</span>
									{#if !monitor.is_active}
										<span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500 uppercase tracking-wide">
											Paused
										</span>
									{/if}
								</div>
								<p class="text-xs text-slate-500 truncate mb-2">{monitor.query}</p>
								<div class="flex gap-4 text-[10px] text-slate-600">
									<span>Last run: {formatDate(monitor.last_run_at)}</span>
									<span>Next run: {formatDate(monitor.next_run_at)}</span>
								</div>
							</div>

							<div class="flex items-center gap-1 flex-shrink-0">
								<button
									onclick={() => togglePause(monitor)}
									class="text-[10px] px-2 py-1 rounded border transition-colors
										{monitor.is_active
											? 'border-navy-600 text-slate-500 hover:text-gold hover:border-gold/30'
											: 'border-green-900 text-green-500 hover:text-green-400'}"
									title={monitor.is_active ? 'Pause' : 'Resume'}
								>
									{monitor.is_active ? 'Pause' : 'Resume'}
								</button>
								<button
									onclick={() => handleTrigger(monitor.id)}
									disabled={triggering.has(monitor.id)}
									class="text-[10px] px-2 py-1 rounded border border-navy-600 text-slate-500 hover:text-gold hover:border-gold/30 transition-colors disabled:opacity-50"
									title="Run now"
								>
									{triggering.has(monitor.id) ? '...' : 'Run Now'}
								</button>
								<button
									onclick={() => startEdit(monitor)}
									class="text-[10px] px-2 py-1 rounded border border-navy-600 text-slate-500 hover:text-gold hover:border-gold/30 transition-colors"
									title="Edit"
								>
									Edit
								</button>
								<button
									onclick={() => toggleRuns(monitor.id)}
									class="text-[10px] px-2 py-1 rounded border transition-colors
										{expandedId === monitor.id
											? 'border-gold/30 text-gold'
											: 'border-navy-600 text-slate-500 hover:text-gold hover:border-gold/30'}"
									title="Run history"
								>
									History
								</button>
								<button
									onclick={() => handleDelete(monitor.id)}
									class="text-slate-600 hover:text-red-400 transition-colors text-xs leading-none p-1"
									title="Delete monitor"
									aria-label="Delete monitor"
								>
									&times;
								</button>
							</div>
						</div>

						<!-- Run history -->
						{#if expandedId === monitor.id}
							<div class="mt-3 border-t border-navy-700 pt-3">
								{#if loadingRuns}
									<p class="text-xs text-slate-500">Loading runs...</p>
								{:else if runs.length === 0}
									<p class="text-xs text-slate-600">No runs yet.</p>
								{:else}
									<div class="space-y-1">
										{#each runs as run (run.id)}
											<a
												href="/session/{run.id}"
												class="flex items-center gap-3 text-xs px-2 py-1.5 rounded hover:bg-navy-700/40 transition-colors"
											>
												<span class="text-slate-400 flex-1 truncate">{run.title ?? run.query ?? 'Untitled'}</span>
												<span class="text-slate-600 flex-shrink-0">{formatDate(run.created_at)}</span>
											</a>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
