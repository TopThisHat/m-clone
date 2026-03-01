<script lang="ts">
	import { marked } from 'marked';
	import type { PageData } from './$types';
	import ResearchSwimlane from '$lib/components/ResearchSwimlane.svelte';
	import ChartCard from '$lib/components/ChartCard.svelte';
	import type { TraceStep } from '$lib/stores/traceStore';
	import type { ChartPayload } from '$lib/stores/reportStore';

	let { data }: { data: PageData } = $props();
	const session = $derived(data.session);
	const chartPayloads = $derived(
		((session.trace_steps as TraceStep[]) ?? [])
			.filter((s) => s.chart)
			.map((s) => s.chart as ChartPayload)
	);

	let showSwimlane = $state(false);

	function renderMd(md: string): string {
		return md ? (marked.parse(md) as string) : '';
	}

	function downloadMarkdown() {
		const blob = new Blob([session.report_markdown], { type: 'text/markdown' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${session.title.slice(0, 60).replace(/[^a-z0-9]/gi, '-')}.md`;
		a.click();
		URL.revokeObjectURL(url);
	}

	async function downloadPdf() {
		const el = document.getElementById('share-report-content');
		if (!el) return;
		try {
			const html2pdf = (await import('html2pdf.js')).default;
			html2pdf()
				.set({
					margin: 12,
					filename: `${session.title.slice(0, 60).replace(/[^a-z0-9]/gi, '-')}.pdf`,
					image: { type: 'jpeg', quality: 0.98 },
					html2canvas: { scale: 2 },
					jsPDF: { unit: 'mm', format: 'a4' }
				})
				.from(el)
				.save();
		} catch {
			// ignore if html2pdf not available
		}
	}
</script>

<svelte:head>
	<title>{session.title} — Playbook Research</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-6 py-8">
	<!-- Header -->
	<div class="mb-6">
		<div class="flex items-center gap-2 mb-2">
			<div class="w-6 h-6 bg-gold rounded-sm flex items-center justify-center">
				<span class="text-navy font-serif font-bold text-xs">P</span>
			</div>
			<span class="text-xs text-gold font-medium tracking-wide uppercase">Playbook Research</span>
			<span class="text-xs text-slate-600 ml-auto">
				Shared report · {new Date(session.created_at).toLocaleDateString()}
			</span>
		</div>
		<h1 class="font-serif text-xl text-slate-100 leading-snug">{session.title}</h1>
		<p class="text-sm text-slate-500 mt-1">Query: {session.query}</p>
	</div>

	<!-- Export buttons -->
	{#if session.report_markdown}
		<div class="flex gap-2 mb-4">
			<button
				onclick={downloadPdf}
				class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 transition-colors"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h4a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
				</svg>
				Download PDF
			</button>
			<button
				onclick={downloadMarkdown}
				class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 transition-colors"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
				</svg>
				Download .md
			</button>
		</div>
	{/if}

	<!-- Report content -->
	{#if session.report_markdown}
		<div class="border border-navy-600 rounded-lg bg-navy-800/30 overflow-hidden mb-6">
			<div id="share-report-content" class="px-6 py-5">
				<article class="prose prose-sm max-w-none">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -->
					{@html renderMd(session.report_markdown)}
				</article>
			</div>
		</div>
	{:else}
		<div class="text-slate-500 text-sm italic mb-6">No report content available.</div>
	{/if}

	<!-- Persisted charts -->
	{#if chartPayloads.length > 0}
		<div class="mb-6 space-y-4">
			{#each chartPayloads as chart, i (i)}
				<ChartCard {chart} />
			{/each}
		</div>
	{/if}

	<!-- Research trace -->
	{#if session.trace_steps?.length}
		<div class="mb-4">
			<button
				onclick={() => (showSwimlane = !showSwimlane)}
				class="flex items-center gap-2 text-xs text-slate-500 hover:text-gold transition-colors"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"
					/>
				</svg>
				{showSwimlane ? 'Hide' : 'Show'} research trace ({session.trace_steps.length} steps)
			</button>

			{#if showSwimlane}
				<div class="mt-3">
					<ResearchSwimlane steps={session.trace_steps as TraceStep[]} />
				</div>
			{/if}
		</div>
	{/if}

	<!-- Footer notice -->
	<p class="text-xs text-slate-700 text-center mt-8">
		This is a read-only shared research report. For informational purposes only. Not investment advice.
	</p>
</div>
