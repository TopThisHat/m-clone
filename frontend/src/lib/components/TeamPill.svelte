<script lang="ts">
	const COLOR_CLASSES: readonly string[] = [
		'bg-gold/10 text-gold',
		'bg-blue-500/10 text-blue-300',
		'bg-green-500/10 text-green-300',
		'bg-purple-500/10 text-purple-300',
	] as const;

	const FALLBACK_CLASS = 'bg-slate-600/10 text-slate-400';

	let {
		teamName,
		teamIndex = 0,
	}: {
		teamName: string | null;
		teamIndex?: number;
	} = $props();

	let colorClasses = $derived(
		teamIndex < COLOR_CLASSES.length ? COLOR_CLASSES[teamIndex] : FALLBACK_CLASS,
	);
</script>

{#if teamName}
	<span
		class="inline-flex items-center gap-1 text-[10px] leading-none px-1.5 py-0.5 rounded {colorClasses}"
		aria-label="Posted from {teamName} team"
		title={teamName}
	>
		{teamName}
	</span>
{/if}
