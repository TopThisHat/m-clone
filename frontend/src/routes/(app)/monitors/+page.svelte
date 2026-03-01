<script lang="ts">
	import { onMount } from 'svelte';
	import { listMonitors, createMonitor, deleteMonitor, type Monitor } from '$lib/api/monitors';

	let monitors = $state<Monitor[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Form state
	let label = $state('');
	let query = $state('');
	let frequency = $state<'daily' | 'weekly'>('daily');
	let submitting = $state(false);
	let formError = $state('');

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
		try {
			await deleteMonitor(id);
			monitors = monitors.filter((m) => m.id !== id);
		} catch {
			// ignore
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
				{submitting ? 'Creating…' : 'Create Monitor'}
			</button>
		</form>
	</div>

	<!-- Monitor list -->
	{#if loading}
		<p class="text-sm text-slate-500">Loading monitors…</p>
	{:else if error}
		<p class="text-sm text-red-400">{error}</p>
	{:else if monitors.length === 0}
		<p class="text-sm text-slate-600 text-center py-8">
			No monitors yet. Create one above to get started.
		</p>
	{:else}
		<div class="space-y-3">
			{#each monitors as monitor (monitor.id)}
				<div class="border border-navy-700 rounded-lg bg-navy-800/20 px-5 py-4 flex items-start gap-4">
					<div class="flex-1 min-w-0">
						<div class="flex items-center gap-2 mb-1">
							<span class="text-sm font-medium text-slate-200">{monitor.label}</span>
							<span
								class="text-[10px] px-1.5 py-0.5 rounded border border-navy-600 text-slate-500 uppercase tracking-wide"
							>
								{monitor.frequency}
							</span>
						</div>
						<p class="text-xs text-slate-500 truncate mb-2">{monitor.query}</p>
						<div class="flex gap-4 text-[10px] text-slate-600">
							<span>Last run: {formatDate(monitor.last_run_at)}</span>
							<span>Next run: {formatDate(monitor.next_run_at)}</span>
						</div>
					</div>
					<button
						onclick={() => handleDelete(monitor.id)}
						class="text-slate-600 hover:text-red-400 transition-colors text-xs leading-none p-1 flex-shrink-0"
						title="Delete monitor"
						aria-label="Delete monitor"
					>
						✕
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>
