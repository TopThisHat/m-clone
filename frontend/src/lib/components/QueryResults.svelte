<script lang="ts">
	import type { QueryResult } from '$lib/api/documents';
	import { detectResultType } from '$lib/utils/resultTypeDetection';
	import CountResult from './results/CountResult.svelte';
	import ListResult from './results/ListResult.svelte';
	import TableResult from './results/TableResult.svelte';
	import ProseResult from './results/ProseResult.svelte';
	import EmptyResult from './results/EmptyResult.svelte';
	import ErrorResult from './results/ErrorResult.svelte';

	let {
		results,
		loading = false,
	}: {
		results: QueryResult;
		loading?: boolean;
	} = $props();

	const resultType = $derived(loading ? 'list' : detectResultType(results));
	const matches = $derived(results?.matches ?? []);
</script>

<div class="space-y-3" data-testid="query-results">
	<!-- Loading skeleton -->
	{#if loading}
		<div
			class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-8 text-center space-y-3 animate-pulse"
			aria-busy="true"
			aria-label="Loading results"
		>
			<div class="h-3 bg-navy-700 rounded w-1/3 mx-auto"></div>
			<div class="h-2 bg-navy-700 rounded w-2/3 mx-auto"></div>
			<div class="h-2 bg-navy-700 rounded w-1/2 mx-auto"></div>
		</div>
	{:else}
		<!-- Query interpretation header -->
		{#if results?.query_interpretation}
			<div class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-3">
				<p class="text-xs text-slate-500 uppercase tracking-wide mb-1">Query interpretation</p>
				<p class="text-slate-300 text-sm">{results.query_interpretation}</p>
			</div>
		{/if}

		<!-- Adaptive result component -->
		{#if resultType === 'error'}
			<ErrorResult
				error={results.error ?? 'An unknown error occurred'}
				interpretation={results.query_interpretation}
			/>
		{:else if resultType === 'empty'}
			<EmptyResult interpretation={results.query_interpretation} />
		{:else if resultType === 'count'}
			<CountResult
				match={matches[0]}
				interpretation={results.query_interpretation}
			/>
		{:else if resultType === 'table'}
			<TableResult
				{matches}
				interpretation={results.query_interpretation}
				totalMatches={results.total_matches}
			/>
		{:else if resultType === 'prose'}
			<ProseResult
				{matches}
				interpretation={results.query_interpretation}
			/>
		{:else}
			<ListResult
				{matches}
				interpretation={results.query_interpretation}
				totalMatches={results.total_matches}
			/>
		{/if}
	{/if}
</div>
