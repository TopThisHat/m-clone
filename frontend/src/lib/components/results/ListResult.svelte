<script lang="ts">
	import type { MatchEntry } from '$lib/api/documents';
	import { confidenceColor } from '$lib/utils/confidence';

	let {
		matches,
		interpretation,
		totalMatches,
	}: {
		matches: MatchEntry[];
		interpretation: string;
		totalMatches: number;
	} = $props();

	function formatRowNums(rows: number[]): string {
		if (rows.length === 1) return `Row ${rows[0]}`;
		if (rows.length <= 3) return `Rows ${rows.join(', ')}`;
		return `Rows ${rows[0]}–${rows[rows.length - 1]}`;
	}

	function sourceLabel(entry: MatchEntry): string {
		return Array.isArray(entry.source_column)
			? entry.source_column.join(', ')
			: entry.source_column;
	}

	const showTruncation = $derived(totalMatches > matches.length);
</script>

<div class="space-y-2" data-testid="result-list">
	{#if interpretation}
		<p class="text-xs text-slate-500 uppercase tracking-wide">{interpretation}</p>
	{/if}

	<ul class="space-y-1.5" role="list" aria-label="Query results">
		{#each matches as match (String(match.source_column) + ':' + (match.row_numbers[0] ?? match.confidence))}
			<li class="flex items-start gap-3 bg-navy-800 border border-navy-700 rounded-lg px-3 py-2.5">
				<span
					class="mt-1.5 w-1.5 h-1.5 rounded-full bg-gold/60 flex-shrink-0"
					aria-hidden="true"
				></span>
				<div class="flex-1 min-w-0">
					<span class="text-slate-200 text-sm break-words">{String(match.value)}</span>
					<div class="flex flex-wrap gap-2 mt-1 text-xs text-slate-500">
						<span class="font-mono text-slate-400">{sourceLabel(match)}</span>
						{#if match.row_numbers.length}
							<span aria-hidden="true">·</span>
							<span>{formatRowNums(match.row_numbers)}</span>
						{/if}
					</div>
				</div>
				<span
					class="text-xs px-1.5 py-0.5 rounded border font-mono flex-shrink-0 {confidenceColor(match.confidence)}"
					aria-label="Confidence {(match.confidence * 100).toFixed(0)}%"
				>
					{(match.confidence * 100).toFixed(0)}%
				</span>
			</li>
		{/each}
	</ul>

	{#if showTruncation}
		<p class="text-xs text-slate-600 px-1">
			Showing {matches.length} of {totalMatches} matches — narrow your query to see remaining results
		</p>
	{:else}
		<p class="text-xs text-slate-600 px-1">
			{totalMatches}
			{totalMatches === 1 ? 'match' : 'matches'} found
		</p>
	{/if}
</div>
