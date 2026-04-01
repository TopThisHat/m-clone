<script lang="ts">
	import type { MatchEntry } from '$lib/api/documents';

	let {
		matches,
		interpretation,
		totalMatches,
	}: {
		matches: MatchEntry[];
		interpretation: string;
		totalMatches: number;
	} = $props();

	const columns = $derived.by(() => {
		const first = matches[0];
		if (!first) return [] as string[];
		if (typeof first.value === 'object' && !Array.isArray(first.value)) {
			return Object.keys(first.value);
		}
		const sc = first.source_column;
		return Array.isArray(sc) ? sc : [sc];
	});

	function getCellValue(match: MatchEntry, col: string): string {
		if (typeof match.value === 'object' && !Array.isArray(match.value)) {
			return (match.value as Record<string, string>)[col] ?? '';
		}
		return String(match.value);
	}

	const showTruncation = $derived(totalMatches > matches.length);
</script>

<div class="space-y-2" data-testid="result-table">
	{#if interpretation}
		<p class="text-xs text-slate-500 uppercase tracking-wide">{interpretation}</p>
	{/if}

	<div class="overflow-x-auto rounded-lg border border-navy-700">
		<table class="w-full text-sm" aria-label="Query results table">
			<thead class="bg-navy-800">
				<tr>
					{#each columns as col}
						<th
							class="text-left px-3 py-2 text-xs text-slate-400 font-medium uppercase tracking-wide border-b border-navy-700"
							scope="col"
						>
							{col}
						</th>
					{/each}
					<th
						class="text-left px-3 py-2 text-xs text-slate-400 font-medium uppercase tracking-wide border-b border-navy-700"
						scope="col"
					>
						Row
					</th>
				</tr>
			</thead>
			<tbody>
				{#each matches as match, i (i)}
					<tr class="border-b border-navy-700/50 hover:bg-navy-800/50 transition-colors">
						{#each columns as col}
							<td class="px-3 py-2 text-slate-300 text-xs font-mono">
								{getCellValue(match, col)}
							</td>
						{/each}
						<td class="px-3 py-2 text-slate-500 text-xs">
							{match.row_numbers[0] ?? ''}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if showTruncation}
		<p class="text-xs text-slate-600 px-1">
			Showing {matches.length} of {totalMatches} rows
		</p>
	{/if}
</div>
