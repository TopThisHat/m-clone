<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { theme } from '$lib/stores/themeStore';

	export interface ChartPayload {
		ticker: string;
		period: string;
		type: string;
		labels: string[];
		values: number[];
		pct_change: number;
	}

	let { chart }: { chart: ChartPayload } = $props();

	let canvasEl = $state<HTMLCanvasElement | undefined>();
	let chartInstance: unknown = null;

	const gridColor = $derived($theme === 'light' ? '#e2e8f0' : '#1a3660');
	const tickColor = $derived($theme === 'light' ? '#475569' : '#64748b');

	$effect(() => {
		if (!chartInstance) return;
		const c = chartInstance as {
			options: { scales: { x: { ticks: { color: string }; grid: { color: string } }; y: { ticks: { color: string }; grid: { color: string } } } };
			update: () => void;
		};
		c.options.scales.x.ticks.color = tickColor;
		c.options.scales.x.grid.color = gridColor;
		c.options.scales.y.ticks.color = tickColor;
		c.options.scales.y.grid.color = gridColor;
		c.update();
	});

	onMount(async () => {
		try {
			const { Chart, registerables } = await import('chart.js');
			Chart.register(...registerables);

			if (!canvasEl) return;

			// Sample labels to avoid crowding (show ~20 points)
			const step = Math.max(1, Math.floor(chart.labels.length / 20));
			const sampledLabels = chart.labels.filter((_, i) => i % step === 0);
			const sampledValues = chart.values.filter((_, i) => i % step === 0);

			const color = chart.pct_change >= 0 ? '#4ade80' : '#f87171';

			chartInstance = new Chart(canvasEl, {
				type: 'line',
				data: {
					labels: sampledLabels,
					datasets: [
						{
							label: `${chart.ticker} Close`,
							data: sampledValues,
							borderColor: color,
							backgroundColor: color + '20',
							borderWidth: 1.5,
							pointRadius: 0,
							fill: true,
							tension: 0.3
						}
					]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						tooltip: {
							callbacks: {
								label: (ctx) => `$${Number(ctx.raw).toFixed(2)}`
							}
						}
					},
					scales: {
						x: {
							ticks: {
								color: tickColor,
								maxTicksLimit: 6,
								font: { size: 10 }
							},
							grid: { color: gridColor }
						},
						y: {
							ticks: {
								color: tickColor,
								font: { size: 10 },
								callback: (v) => `$${v}`
							},
							grid: { color: gridColor }
						}
					}
				}
			});
		} catch {
			// Chart.js not available
		}
	});

	onDestroy(() => {
		if (chartInstance && typeof (chartInstance as { destroy?: () => void }).destroy === 'function') {
			(chartInstance as { destroy: () => void }).destroy();
		}
	});
</script>

<div class="border border-navy-600 rounded-lg bg-navy-800/60 p-3 my-2">
	<div class="flex items-center justify-between mb-2">
		<span class="text-xs font-medium text-gold/80 uppercase tracking-widest">
			{chart.ticker} · {chart.period.toUpperCase()} Price
		</span>
		<span
			class="text-xs font-mono {chart.pct_change >= 0 ? 'text-green-400' : 'text-red-400'}"
		>
			{chart.pct_change >= 0 ? '+' : ''}{chart.pct_change.toFixed(1)}%
		</span>
	</div>
	<div class="h-36">
		<canvas bind:this={canvasEl}></canvas>
	</div>
</div>
