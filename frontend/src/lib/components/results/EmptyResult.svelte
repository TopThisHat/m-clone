<script lang="ts">
	let {
		interpretation = '',
	}: {
		interpretation?: string;
	} = $props();
</script>

<div
	class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-8 text-center space-y-2"
	data-testid="result-empty"
>
	<svg
		class="w-8 h-8 text-slate-600 mx-auto"
		aria-hidden="true"
		fill="none"
		stroke="currentColor"
		viewBox="0 0 24 24"
	>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			stroke-width="1.5"
			d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
		/>
	</svg>
	<p class="text-slate-400 text-sm font-medium">No matches found</p>
	{#if interpretation}
		<p class="text-slate-500 text-xs max-w-xs mx-auto">{interpretation}</p>
	{/if}
	<p class="text-slate-600 text-xs max-w-xs mx-auto">
		Try rephrasing your query or using a different column name.
	</p>
</div>
