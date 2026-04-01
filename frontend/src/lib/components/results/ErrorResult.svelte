<script lang="ts">
	let {
		error,
		interpretation = '',
	}: {
		error: string;
		interpretation?: string;
	} = $props();

	function nextSteps(err: string): string[] {
		const lower = err.toLowerCase();
		if (lower.includes('not found') || lower.includes('session')) {
			return [
				'Re-upload your document to start a new session',
				'Check that the file was uploaded successfully',
			];
		}
		if (lower.includes('rate limit')) {
			return ['Wait a moment before trying again', 'Reduce the frequency of queries'];
		}
		if (lower.includes('timeout') || lower.includes('timed out')) {
			return ['Try a simpler query first', 'Break your query into smaller parts'];
		}
		return ['Try rephrasing the query', 'Check the document format is supported'];
	}

	const steps = $derived(nextSteps(error));
</script>

<div
	class="bg-red-950/60 border border-red-800/60 rounded-xl px-4 py-4 space-y-3"
	data-testid="result-error"
	role="alert"
	aria-live="assertive"
>
	<div class="flex items-start gap-3">
		<svg
			class="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0"
			aria-hidden="true"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
		>
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="2"
				d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
			/>
		</svg>
		<div class="space-y-0.5">
			<p class="text-red-300 text-sm">{error}</p>
			{#if interpretation}
				<p class="text-red-400/70 text-xs">{interpretation}</p>
			{/if}
		</div>
	</div>

	<div class="border-t border-red-800/40 pt-2 space-y-1">
		<p class="text-xs text-red-500 font-medium">Suggested next steps:</p>
		<ul class="space-y-0.5" aria-label="Suggested next steps">
			{#each steps as step}
				<li class="text-xs text-red-400/80 flex items-center gap-1.5">
					<span class="w-1 h-1 rounded-full bg-red-500/60 flex-shrink-0" aria-hidden="true"></span>
					{step}
				</li>
			{/each}
		</ul>
	</div>
</div>
