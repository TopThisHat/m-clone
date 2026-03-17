<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { jobsApi, type TrendPoint } from '$lib/api/jobs';
	import { entitiesApi, type Entity } from '$lib/api/entities';

	let campaignId = $derived($page.params.id as string);
	let trends = $state<TrendPoint[]>([]);
	let entities = $state<Entity[]>([]);
	let loading = $state(true);
	let error = $state('');
	let selectedEntityId = $state<string>('');

	let chartEl = $state<HTMLCanvasElement | undefined>();
	let chartInstance: unknown = null;

	onMount(async () => {
		try {
			const [trendsResult, entitiesResult] = await Promise.all([
				jobsApi.getTrends(campaignId),
				entitiesApi.list(campaignId, { limit: 0 }),
			]);
			trends = trendsResult;
			entities = entitiesResult.items;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load trends';
		} finally {
			loading = false;
		}
	});

	async function renderChart(data: TrendPoint[], canvas: HTMLCanvasElement | undefined) {
		if (!canvas || data.length === 0) return;

		const { Chart, registerables } = await import('chart.js');
		Chart.register(...registerables);

		if (chartInstance) (chartInstance as { destroy: () => void }).destroy();

		// Group by entity
		const byEntity = new Map<string, TrendPoint[]>();
		for (const pt of data) {
			const key = pt.entity_label;
			if (!byEntity.has(key)) byEntity.set(key, []);
			byEntity.get(key)!.push(pt);
		}

		// Unique job dates as labels
		const jobDates = [...new Set(data.map((d) => d.completed_at))].sort();
		const labels = jobDates.map((d) => new Date(d).toLocaleDateString());

		const colors = [
			'#d4a843', '#60a5fa', '#34d399', '#f87171', '#a78bfa',
			'#fb923c', '#2dd4bf', '#e879f9', '#fbbf24', '#818cf8',
		];

		const datasets = [...byEntity.entries()].map(([entityLabel, points], idx) => {
			const jobMap = new Map(points.map((p) => [p.completed_at, p.score]));
			return {
				label: entityLabel,
				data: jobDates.map((d) => {
					const val = jobMap.get(d);
					return val !== undefined ? val * 100 : null;
				}),
				borderColor: colors[idx % colors.length],
				backgroundColor: colors[idx % colors.length] + '20',
				tension: 0.3,
				pointRadius: 3,
				spanGaps: true,
			};
		});

		// Add campaign average
		const avgData = jobDates.map((d) => {
			const jobPoints = data.filter((p) => p.completed_at === d);
			if (jobPoints.length === 0) return null;
			return (jobPoints.reduce((s, p) => s + p.score, 0) / jobPoints.length) * 100;
		});

		datasets.push({
			label: 'Campaign Average',
			data: avgData,
			borderColor: '#94a3b8',
			backgroundColor: '#94a3b820',
			tension: 0.3,
			pointRadius: 3,
			spanGaps: true,
		});

		chartInstance = new Chart(canvas, {
			type: 'line',
			data: { labels, datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				scales: {
					y: {
						min: 0,
						max: 100,
						title: { display: true, text: 'Score %', color: '#94a3b8' },
						ticks: { color: '#64748b' },
						grid: { color: '#1e293b' },
					},
					x: {
						ticks: { color: '#64748b' },
						grid: { color: '#1e293b' },
					},
				},
				plugins: {
					legend: { labels: { color: '#cbd5e1', boxWidth: 12 } },
				},
			},
		});
	}

	$effect(() => {
		const filtered = selectedEntityId
			? trends.filter((t) => t.entity_id === selectedEntityId)
			: trends;
		renderChart(filtered, chartEl);
	});

	async function handleEntityFilter(e: Event) {
		selectedEntityId = (e.target as HTMLSelectElement).value;
	}
</script>

<div class="max-w-5xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4">
		<h2 class="font-serif text-gold text-xl font-bold">Score Trends</h2>
		<div>
			<select
				onchange={handleEntityFilter}
				class="bg-navy-800 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-gold"
			>
				<option value="">All entities</option>
				{#each entities as entity (entity.id)}
					<option value={entity.id}>{entity.label}</option>
				{/each}
			</select>
		</div>
	</div>

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading...</p>
	{:else if trends.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No completed jobs yet. Run jobs to see score trends over time.</p>
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-4">
			<div class="h-96">
				<canvas bind:this={chartEl}></canvas>
			</div>
		</div>
	{/if}
</div>
