<script lang="ts">
	import type { MatchEntry } from '$lib/api/documents';

	let {
		matches,
		interpretation,
	}: {
		matches: MatchEntry[];
		interpretation: string;
	} = $props();

	function sourceRef(match: MatchEntry): string {
		const col = Array.isArray(match.source_column)
			? match.source_column.join(', ')
			: match.source_column;
		if (match.text_positions?.length) {
			const pos = match.text_positions[0];
			return `${col} @ char ${pos.start}–${pos.end}`;
		}
		if (match.row_numbers.length > 0) return `${col}, row ${match.row_numbers[0]}`;
		return col;
	}
</script>

<div class="space-y-3" data-testid="result-prose">
	{#if interpretation}
		<p class="text-xs text-slate-500 uppercase tracking-wide">{interpretation}</p>
	{/if}

	{#each matches as match, i (i)}
		<blockquote class="border-l-2 border-gold/40 pl-4 space-y-1.5">
			<p class="text-slate-200 text-sm leading-relaxed">
				"{String(match.value)}"
			</p>
			<cite class="block text-xs text-slate-500 not-italic font-mono">{sourceRef(match)}</cite>
		</blockquote>
	{/each}
</div>
