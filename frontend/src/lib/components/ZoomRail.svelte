<script lang="ts">
	let {
		onzoomin,
		onzoomout,
		onfitview,
		onresetlayout,
		disabled = false,
	}: {
		onzoomin: () => void;
		onzoomout: () => void;
		onfitview: () => void;
		onresetlayout: () => void;
		disabled?: boolean;
	} = $props();
</script>

<div
	class="absolute left-3 top-1/2 -translate-y-1/2 z-20 flex flex-col gap-1"
	aria-label="Zoom controls"
>
	<button
		onclick={onzoomin}
		{disabled}
		class="w-8 h-8 flex items-center justify-center rounded bg-navy-800 border border-navy-600 text-slate-300 hover:text-gold hover:border-gold/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
		title="Zoom in"
		aria-label="Zoom in"
	>
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
		</svg>
	</button>

	<button
		onclick={onzoomout}
		{disabled}
		class="w-8 h-8 flex items-center justify-center rounded bg-navy-800 border border-navy-600 text-slate-300 hover:text-gold hover:border-gold/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
		title="Zoom out"
		aria-label="Zoom out"
	>
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4" />
		</svg>
	</button>

	<div class="w-8 border-t border-navy-600 my-0.5"></div>

	<button
		onclick={onfitview}
		{disabled}
		class="w-8 h-8 flex items-center justify-center rounded bg-navy-800 border border-navy-600 text-slate-300 hover:text-gold hover:border-gold/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
		title="Fit to view"
		aria-label="Fit to view"
	>
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4" />
		</svg>
	</button>

	<button
		onclick={onresetlayout}
		{disabled}
		class="w-8 h-8 flex items-center justify-center rounded bg-navy-800 border border-navy-600 text-slate-300 hover:text-gold hover:border-gold/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
		title="Reset layout"
		aria-label="Reset layout"
	>
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
		</svg>
	</button>
</div>
