<script lang="ts">
	import { progressData, cancelOperation, isCancelled } from '$lib/stores/reportStore';

	/**
	 * The element to observe. When it leaves the viewport the sticky bar appears.
	 * Pass the progress area root (DataProgressBar / ExecutionPlanCard wrapper).
	 */
	let { observeTarget }: { observeTarget?: Element | null } = $props();

	let progressAreaVisible = $state(true);
	let observer: IntersectionObserver | null = null;

	// Lightning bolt: a generic "processing" icon for the sticky bar
	const progressIcon = 'M13 10V3L4 14h7v7l9-11h-7z';

	const current = $derived($progressData);

	const displayPercent = $derived(() => {
		if (!current) return 0;
		if (typeof current.percent === 'number') return Math.min(100, Math.max(0, current.percent));
		if (typeof current.total === 'number' && current.total > 0) {
			return Math.round(((current.current ?? 0) / current.total) * 100);
		}
		return 0;
	});

	const briefLabel = $derived(() => {
		if (!current) return '';
		if (typeof current.total === 'number' && current.total > 0) {
			return `Processing ${current.current ?? 0}/${current.total}...`;
		}
		return current.message || current.phase || 'Processing...';
	});

	// Observe the target element with IntersectionObserver
	$effect(() => {
		observer?.disconnect();
		observer = null;

		if (!observeTarget) {
			progressAreaVisible = true;
			return;
		}

		observer = new IntersectionObserver(
			([entry]) => {
				progressAreaVisible = entry.isIntersecting;
			},
			{ threshold: 0.1 }
		);
		observer.observe(observeTarget);

		return () => {
			observer?.disconnect();
			observer = null;
		};
	});

	const visible = $derived(!!current && !progressAreaVisible && !$isCancelled);
</script>

{#if visible && current}
	<div
		class="sticky top-0 z-20 flex items-center gap-3 px-4 h-10 bg-navy-900/95 border-b border-gold/20 backdrop-blur-sm"
		role="status"
		aria-live="polite"
		aria-label="Operation progress"
	>
		<!-- Mode icon -->
		<svg class="w-4 h-4 text-gold flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d={progressIcon} />
		</svg>

		<!-- Label -->
		<span class="text-xs text-slate-300 truncate flex-1 min-w-0">
			{briefLabel()}
		</span>

		<!-- Percent -->
		{#if displayPercent() > 0}
			<span class="text-xs text-gold font-medium flex-shrink-0">{displayPercent()}%</span>
		{/if}

		<!-- Inline mini progress track -->
		<div class="w-20 h-1 rounded-full bg-navy-700 overflow-hidden flex-shrink-0" aria-hidden="true">
			{#if displayPercent() > 0}
				<div
					class="h-full rounded-full bg-gold transition-[width] duration-300 ease-out"
					style="width: {displayPercent()}%"
				></div>
			{:else}
				<div class="absolute inset-0 bg-gold/50 rounded-full animate-pulse"></div>
			{/if}
		</div>

		<!-- Cancel -->
		<button
			onclick={cancelOperation}
			class="flex-shrink-0 text-xs text-slate-500 hover:text-red-400 transition-colors px-2 py-0.5 rounded hover:bg-red-900/20 border border-transparent hover:border-red-800/40"
			title="Cancel operation"
			aria-label="Cancel operation"
		>
			Cancel
		</button>
	</div>
{/if}
