<script lang="ts">
	interface Props {
		teamNames: string[];
		maxVisible?: number;
	}

	let { teamNames, maxVisible = 2 }: Props = $props();

	let expanded = $state(false);

	const visible = $derived(expanded ? teamNames : teamNames.slice(0, maxVisible));
	const remaining = $derived(teamNames.length - maxVisible);
	const hasOverflow = $derived(teamNames.length > maxVisible);
</script>

{#if teamNames.length > 0}
	<div class="ml-auto flex items-center gap-1 flex-wrap">
		{#each visible as name (name)}
			<span
				class="inline-flex items-center gap-1 text-[10px] px-2 py-0.5
				       rounded-full border border-gold/30 text-gold-light bg-gold/5"
			>
				<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
						d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
				</svg>
				{name}
			</span>
		{/each}
		{#if hasOverflow && !expanded}
			<button
				onclick={() => { expanded = true; }}
				class="text-[10px] text-slate-500 hover:text-gold cursor-pointer transition-colors"
				aria-label="Show {remaining} more team{remaining === 1 ? '' : 's'}"
			>
				+{remaining} more
			</button>
		{/if}
	</div>
{/if}
