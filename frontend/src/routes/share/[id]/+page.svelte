<script lang="ts">
	import { marked } from 'marked';
	import type { PageData } from './$types';
	import ResearchSwimlane from '$lib/components/ResearchSwimlane.svelte';
	import type { TraceStep } from '$lib/stores/traceStore';

	let { data }: { data: PageData } = $props();
	const session = $derived(data.session);

	let showSwimlane = $state(false);

	function renderMd(md: string): string {
		return md ? (marked.parse(md) as string) : '';
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
				<span class="text-navy font-serif font-bold text-xs">M</span>
			</div>
			<span class="text-xs text-gold font-medium tracking-wide uppercase">Playbook Research</span>
			<span class="text-xs text-slate-600 ml-auto">
				Shared report · {new Date(session.created_at).toLocaleDateString()}
			</span>
		</div>
		<h1 class="font-serif text-xl text-slate-100 leading-snug">{session.title}</h1>
		<p class="text-sm text-slate-500 mt-1">Query: {session.query}</p>
	</div>

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
