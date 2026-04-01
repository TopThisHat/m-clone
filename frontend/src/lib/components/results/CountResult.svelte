<script lang="ts">
	import type { MatchEntry } from '$lib/api/documents';

	let {
		match,
		interpretation,
	}: {
		match: MatchEntry;
		interpretation: string;
	} = $props();

	const sourceColumn = $derived(
		Array.isArray(match.source_column) ? match.source_column.join(', ') : match.source_column,
	);
</script>

<div
	class="bg-navy-800 border border-navy-700 rounded-xl px-6 py-8 text-center space-y-3"
	data-testid="result-count"
>
	<p class="text-4xl font-bold text-gold font-mono tracking-tight">
		{String(match.value)}
	</p>
	{#if interpretation}
		<p class="text-sm text-slate-300">{interpretation}</p>
	{/if}
	<p class="text-xs text-slate-500 font-mono">
		from column: <span class="text-slate-400">{sourceColumn}</span>
	</p>
</div>
