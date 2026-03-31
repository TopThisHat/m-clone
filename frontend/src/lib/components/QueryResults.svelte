<script lang="ts">
	import type { QueryResult, MatchEntry } from '$lib/api/documents';
	import { confidenceColor, confidenceBarColor } from '$lib/utils/confidence';

	let {
		results,
		loading = false,
	}: {
		results: QueryResult;
		loading?: boolean;
	} = $props();

	/** Formats a MatchEntry value for display */
	function formatValue(entry: MatchEntry): string {
		if (typeof entry.value === 'string') return entry.value;
		// Multi-column paired value: show as "col: val, col: val"
		return Object.entries(entry.value)
			.map(([col, val]) => `${col}: ${val}`)
			.join(' · ');
	}

	/** Formats source column(s) for display */
	function formatSourceColumn(entry: MatchEntry): string {
		if (Array.isArray(entry.source_column)) return entry.source_column.join(', ');
		return entry.source_column;
	}

	/** Formats row numbers for display */
	function formatRowNumbers(rows: number[]): string {
		if (rows.length === 1) return `Row ${rows[0]}`;
		if (rows.length <= 3) return `Rows ${rows.join(', ')}`;
		return `Rows ${rows[0]}–${rows[rows.length - 1]} (+${rows.length - 2} more)`;
	}

	let hasError = $derived(results?.error != null && results.error !== '');
	let hasMatches = $derived((results?.matches?.length ?? 0) > 0);
	let showTruncationNotice = $derived(
		results.total_matches > results.matches.length
	);
</script>

<div class="space-y-3">
	<!-- Loading state -->
	{#if loading}
		<div class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-8 text-center space-y-3 animate-pulse">
			<div class="h-3 bg-navy-700 rounded w-1/3 mx-auto"></div>
			<div class="h-2 bg-navy-700 rounded w-2/3 mx-auto"></div>
			<div class="h-2 bg-navy-700 rounded w-1/2 mx-auto"></div>
		</div>
	{:else}

	<!-- Query interpretation header -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-3">
		<p class="text-xs text-slate-500 uppercase tracking-wide mb-1">Query interpretation</p>
		<p class="text-slate-300 text-sm">{results.query_interpretation}</p>
	</div>

	<!-- Error state -->
	{#if hasError}
		<div class="bg-red-950 border border-red-800 rounded-xl px-4 py-3 flex items-start gap-3"
			role="alert" aria-live="assertive">
			<svg class="w-4 h-4 text-red-400 mt-0.5 shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
					d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
			</svg>
			<p class="text-red-300 text-sm">{results.error}</p>
		</div>
	{/if}

	<!-- Empty state (no error, no matches) -->
	{#if !hasError && !hasMatches}
		<div class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-8 text-center space-y-2">
			<svg class="w-8 h-8 text-slate-500 mx-auto" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
					d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
			<p class="text-slate-400 text-sm">No matches found</p>
			<p class="text-slate-500 text-xs max-w-xs mx-auto">
				Try rephrasing your query or using a different column name.
			</p>
		</div>
	{/if}

	<!-- Results list -->
	{#if hasMatches}
		<div class="space-y-1.5" role="list" aria-label="Query results">
			{#each results.matches as match (String(match.source_column) + ':' + (match.row_numbers[0] ?? match.confidence))}
				<div
					class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-3 space-y-2"
					role="listitem"
				>
					<!-- Value -->
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-200 font-medium text-sm leading-snug break-words min-w-0">
							{formatValue(match)}
						</span>

						<!-- Confidence badge -->
						<span
							class="shrink-0 text-xs px-2 py-0.5 rounded border font-mono {confidenceColor(match.confidence)}"
							aria-label="Extraction confidence {(match.confidence * 100).toFixed(0)}%"
						>
							{(match.confidence * 100).toFixed(0)}%
						</span>
					</div>

					<!-- Confidence bar -->
					<div
						class="w-full bg-navy-700 rounded-full h-1"
						role="progressbar"
						aria-valuenow={Math.round(match.confidence * 100)}
						aria-valuemin={0}
						aria-valuemax={100}
						aria-label="Confidence: {(match.confidence * 100).toFixed(0)}%"
					>
						<div
							class="h-1 rounded-full transition-all {confidenceBarColor(match.confidence)}"
							style="width: {match.confidence * 100}%"
						></div>
					</div>

					<!-- Provenance metadata -->
					<div class="flex items-center gap-3 flex-wrap">
						<span class="flex items-center gap-1 text-xs text-slate-500">
							<svg class="w-3 h-3" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
									d="M3 10h18M3 14h18M10 3v18M14 3v18" />
							</svg>
							<span class="text-slate-400 font-mono">{formatSourceColumn(match)}</span>
						</span>
						<span class="flex items-center gap-1 text-xs text-slate-500">
							<svg class="w-3 h-3" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
									d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14" />
							</svg>
							{formatRowNumbers(match.row_numbers)}
						</span>
					</div>
				</div>
			{/each}
		</div>

		<!-- Match count / truncation notice -->
		<div class="flex items-center justify-between text-xs text-slate-500 px-1">
			<span>
				{#if showTruncationNotice}
					Showing {results.matches.length} of {results.total_matches} matches
				{:else}
					{results.total_matches} {results.total_matches === 1 ? 'match' : 'matches'} found
				{/if}
			</span>
			{#if showTruncationNotice}
				<span class="text-slate-500">Narrow your query to see remaining results</span>
			{/if}
		</div>
	{/if}

	{/if}
</div>
