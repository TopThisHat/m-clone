<script lang="ts">
	import { onMount } from 'svelte';
	import { onDestroy } from 'svelte';

	interface DashboardData {
		total_sessions: number;
		total_tokens: number;
		estimated_cost_usd: number;
		sessions_by_day: { date: string; count: number; tokens: number }[];
		top_queries: { query: string; tokens: number }[];
	}

	let data = $state<DashboardData | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let sessionsChartEl = $state<HTMLCanvasElement | undefined>();
	let tokensChartEl = $state<HTMLCanvasElement | undefined>();
	let sessionsChart: unknown = null;
	let tokensChart: unknown = null;

	async function load() {
		try {
			const res = await fetch('/api/usage/summary');
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail || `HTTP ${res.status}`);
			}
			data = await res.json();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load dashboard';
		} finally {
			loading = false;
		}
	}

	async function initCharts() {
		if (!data || !sessionsChartEl || !tokensChartEl) return;
		try {
			const { Chart, registerables } = await import('chart.js');
			Chart.register(...registerables);

			const labels = data.sessions_by_day.map((d) => d.date);
			const counts = data.sessions_by_day.map((d) => d.count);
			const tokens = data.sessions_by_day.map((d) => d.tokens);

			const gridColor = '#1a3660';
			const tickColor = '#64748b';

			sessionsChart = new Chart(sessionsChartEl, {
				type: 'line',
				data: {
					labels,
					datasets: [
						{
							label: 'Sessions',
							data: counts,
							borderColor: '#c9a84c',
							backgroundColor: '#c9a84c20',
							borderWidth: 1.5,
							pointRadius: 2,
							fill: true,
							tension: 0.3
						}
					]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: { legend: { display: false } },
					scales: {
						x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
						y: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }
					}
				}
			});

			tokensChart = new Chart(tokensChartEl, {
				type: 'bar',
				data: {
					labels,
					datasets: [
						{
							label: 'Tokens',
							data: tokens,
							backgroundColor: '#254d8580',
							borderColor: '#254d85',
							borderWidth: 1
						}
					]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: { legend: { display: false } },
					scales: {
						x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
						y: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }
					}
				}
			});
		} catch {
			// Chart.js unavailable
		}
	}

	onMount(async () => {
		await load();
		await initCharts();
	});

	onDestroy(() => {
		(sessionsChart as { destroy?: () => void })?.destroy?.();
		(tokensChart as { destroy?: () => void })?.destroy?.();
	});

	function formatTokens(n: number): string {
		if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
		if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
		return String(n);
	}
</script>

<svelte:head>
	<title>Usage Dashboard — Manus Research</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 py-8">
	<div class="mb-6">
		<h1 class="font-serif text-2xl text-gold tracking-wide">Usage Dashboard</h1>
		<p class="text-slate-500 text-sm mt-1">Research activity and token usage statistics</p>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-24 text-slate-500 text-sm">
			Loading statistics...
		</div>
	{:else if error}
		<div class="bg-red-900/20 border border-red-800/40 rounded-lg px-4 py-3 text-red-400 text-sm">
			{error}
		</div>
	{:else if data}
		<!-- Summary cards -->
		<div class="grid grid-cols-3 gap-4 mb-8">
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-4">
				<p class="text-xs text-slate-500 uppercase tracking-widest mb-1">Total Sessions</p>
				<p class="font-serif text-3xl text-gold">{data.total_sessions}</p>
			</div>
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-4">
				<p class="text-xs text-slate-500 uppercase tracking-widest mb-1">Total Tokens</p>
				<p class="font-serif text-3xl text-gold">{formatTokens(data.total_tokens)}</p>
			</div>
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-4">
				<p class="text-xs text-slate-500 uppercase tracking-widest mb-1">Est. Cost (USD)</p>
				<p class="font-serif text-3xl text-gold">${data.estimated_cost_usd.toFixed(2)}</p>
			</div>
		</div>

		<!-- Charts -->
		<div class="grid grid-cols-2 gap-4 mb-8">
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-4">
				<p class="text-xs text-slate-500 uppercase tracking-widest mb-3">Sessions / Day (30d)</p>
				<div class="h-40">
					<canvas bind:this={sessionsChartEl}></canvas>
				</div>
			</div>
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-4">
				<p class="text-xs text-slate-500 uppercase tracking-widest mb-3">Tokens / Day (30d)</p>
				<div class="h-40">
					<canvas bind:this={tokensChartEl}></canvas>
				</div>
			</div>
		</div>

		<!-- Top queries table -->
		{#if data.top_queries.length}
			<div class="border border-navy-600 rounded-lg bg-navy-800/60 overflow-hidden">
				<div class="px-4 py-3 border-b border-navy-600">
					<p class="text-xs text-slate-500 uppercase tracking-widest">Top Queries by Token Use</p>
				</div>
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-navy-700">
							<th class="text-left px-4 py-2 text-xs text-slate-600 font-medium">#</th>
							<th class="text-left px-4 py-2 text-xs text-slate-600 font-medium">Query</th>
							<th class="text-right px-4 py-2 text-xs text-slate-600 font-medium">Tokens</th>
						</tr>
					</thead>
					<tbody>
						{#each data.top_queries as q, i}
							<tr class="border-b border-navy-700/50 hover:bg-navy-700/20 transition-colors">
								<td class="px-4 py-2 text-slate-600 text-xs">{i + 1}</td>
								<td class="px-4 py-2 text-slate-300 max-w-0">
									<p class="truncate">{q.query}</p>
								</td>
								<td class="px-4 py-2 text-right text-gold/80 font-mono text-xs">
									{formatTokens(q.tokens)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
