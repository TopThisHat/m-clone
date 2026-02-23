<script lang="ts">
	let { context }: { context: string } = $props();
	let expanded = $state(false);

	const lines = $derived(
		context
			.split('\n')
			.filter((l) => l.trim())
			.slice(1) // skip "Prior research context:" header
	);
</script>

{#if context}
	<div class="border border-gold/20 rounded-lg bg-gold/5 overflow-hidden mb-3">
		<button
			onclick={() => (expanded = !expanded)}
			class="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gold/5 transition-colors"
		>
			<div class="flex items-center gap-2">
				<svg class="w-3.5 h-3.5 text-gold/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
					/>
				</svg>
				<span class="text-xs text-gold/70 font-medium uppercase tracking-widest">
					Memory used ({lines.length})
				</span>
			</div>
			<svg
				class="w-3 h-3 text-gold/50 transition-transform {expanded ? 'rotate-180' : ''}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>

		{#if expanded}
			<div class="px-3 pb-3 space-y-1">
				{#each lines as line}
					<p class="text-xs text-slate-400 font-light leading-relaxed">{line.trim()}</p>
				{/each}
			</div>
		{/if}
	</div>
{/if}
