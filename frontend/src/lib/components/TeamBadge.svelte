<script lang="ts">
	let {
		teamName = null,
		size = 'sm',
		showTooltip = true,
	}: {
		teamName: string | null;
		size?: 'sm' | 'md';
		showTooltip?: boolean;
	} = $props();

	let tooltipText = $derived(
		teamName
			? `Showing data for ${teamName}. Switch teams in the header.`
			: 'Showing personal data. Switch teams in the header.'
	);

	let sizeClasses = $derived(
		size === 'md'
			? 'text-xs px-3 py-1 gap-2'
			: 'text-xs px-2.5 py-0.5 gap-1.5'
	);

	let iconSize = $derived(size === 'md' ? 'w-3.5 h-3.5' : 'w-3 h-3');
</script>

<span
	class="inline-flex items-center rounded-full border border-navy-600 bg-navy-800/80 {sizeClasses}"
	title={showTooltip ? tooltipText : undefined}
	aria-label={tooltipText}
>
	{#if teamName}
		<!-- People / team icon -->
		<svg
			class="{iconSize} text-slate-500 shrink-0"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
			aria-hidden="true"
		>
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="2"
				d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
			/>
		</svg>
		<span class="text-gold-light font-medium">{teamName}</span>
	{:else}
		<!-- Single user / personal icon -->
		<svg
			class="{iconSize} text-slate-500 shrink-0"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
			aria-hidden="true"
		>
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="2"
				d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
			/>
		</svg>
		<span class="text-slate-400 font-medium">Personal</span>
	{/if}
</span>
