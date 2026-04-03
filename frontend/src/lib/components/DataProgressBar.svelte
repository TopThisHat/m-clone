<script lang="ts">
	import { cancelOperation, isCancelled } from '$lib/stores/reportStore';

	type Progress = {
		message: string;
		phase: string;
		current?: number;
		total?: number;
		percent?: number;
	};

	let { progress }: { progress: Progress } = $props();

	const isDeterminate = $derived(typeof progress.total === 'number' && progress.total > 0);

	const displayPercent = $derived(
		typeof progress.percent === 'number'
			? Math.min(100, Math.max(0, progress.percent))
			: isDeterminate && progress.total
			? Math.round(((progress.current ?? 0) / progress.total) * 100)
			: 0
	);

	const phaseLabel: Record<string, string> = {
		inventorying: 'Inventorying...',
		processing: 'Processing...',
		aggregating: 'Aggregating...',
		complete: 'Complete'
	};

	const displayPhase = $derived(phaseLabel[progress.phase] ?? progress.phase);
	const isComplete = $derived(progress.phase === 'complete');
</script>

<div class="my-2 space-y-1.5">
	<!-- Top row: message + phase -->
	<div class="flex items-center justify-between gap-2">
		<span class="text-xs text-slate-400 leading-snug truncate">{progress.message}</span>
		<span
			class="flex-shrink-0 text-xs font-medium {isComplete ? 'text-green-400' : 'text-gold-light'}"
		>
			{#if isComplete}
				Complete &#10003;
			{:else}
				{displayPhase}
			{/if}
		</span>
	</div>

	<!-- Progress bar track -->
	<div class="relative h-1.5 rounded-full bg-navy-700 overflow-hidden">
		{#if isDeterminate}
			<!-- Determinate fill -->
			<div
				class="h-full rounded-full bg-gold transition-[width] duration-300 ease-out"
				style="width: {displayPercent}%"
				role="progressbar"
				aria-valuenow={displayPercent}
				aria-valuemin={0}
				aria-valuemax={100}
			></div>
		{:else}
			<!-- Indeterminate shimmer -->
			<div
				class="absolute inset-0 bg-gold/60 rounded-full animate-pulse"
				role="progressbar"
				aria-label={progress.message}
			></div>
		{/if}
	</div>

	<!-- Bottom row: counts + percent + cancel -->
	<div class="flex items-center justify-between gap-2">
		{#if isDeterminate}
			<span class="text-xs text-slate-600">
				{progress.current ?? 0} / {progress.total}
			</span>
			<div class="flex items-center gap-3">
				<span class="text-xs text-slate-500">{displayPercent}%</span>
				{#if !isComplete && !$isCancelled}
					<button
						onclick={cancelOperation}
						class="text-xs text-slate-600 hover:text-red-400 transition-colors px-2 py-0.5 rounded border border-navy-600 hover:border-red-800/40 hover:bg-red-900/10"
						aria-label="Cancel operation"
					>
						Cancel
					</button>
				{/if}
			</div>
		{:else if !isComplete && !$isCancelled}
			<div class="flex-1"></div>
			<button
				onclick={cancelOperation}
				class="text-xs text-slate-600 hover:text-red-400 transition-colors px-2 py-0.5 rounded border border-navy-600 hover:border-red-800/40 hover:bg-red-900/10"
				aria-label="Cancel operation"
			>
				Cancel
			</button>
		{/if}
	</div>
</div>
