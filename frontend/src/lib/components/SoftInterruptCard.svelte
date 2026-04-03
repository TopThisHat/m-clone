<script lang="ts">
	type Confirmation = {
		message: string;
		options?: string[];
	};

	let {
		confirmation,
		onConfirm,
		onOverride,
		onCancel
	}: {
		confirmation: Confirmation;
		onConfirm: () => void;
		onOverride: () => void;
		onCancel: () => void;
	} = $props();

	const TOTAL_MS = 30_000;
	const TICK_MS = 100;

	let elapsed = $state(0);
	let intervalId = $state<ReturnType<typeof setInterval> | null>(null);
	let expired = $state(false);

	const remaining = $derived(Math.max(0, TOTAL_MS - elapsed));
	const remainingSecs = $derived(Math.ceil(remaining / 1000));
	const fillPercent = $derived(Math.min(100, (elapsed / TOTAL_MS) * 100));

	function startTimer() {
		if (intervalId !== null) return;
		intervalId = setInterval(() => {
			if (document.visibilityState === 'hidden') return;
			elapsed = Math.min(elapsed + TICK_MS, TOTAL_MS);
			if (elapsed >= TOTAL_MS && !expired) {
				expired = true;
				stopTimer();
				onConfirm();
			}
		}, TICK_MS);
	}

	function stopTimer() {
		if (intervalId !== null) {
			clearInterval(intervalId);
			intervalId = null;
		}
	}

	function handleVisibilityChange() {
		if (document.visibilityState === 'visible') {
			startTimer();
		}
	}

	$effect(() => {
		startTimer();
		return () => stopTimer();
	});

	function handleConfirm() {
		stopTimer();
		onConfirm();
	}

	function handleOverride() {
		stopTimer();
		onOverride();
	}

	function handleCancel() {
		stopTimer();
		onCancel();
	}
</script>

<svelte:document onvisibilitychange={handleVisibilityChange} />

<div class="my-3 border border-gold/30 rounded-lg bg-navy-800/60 overflow-hidden">
	<!-- Countdown progress bar at top -->
	<div class="h-1 bg-navy-700 relative overflow-hidden">
		<div
			class="absolute inset-y-0 left-0 bg-gold transition-[width] duration-100 ease-linear"
			style="width: {100 - fillPercent}%"
			role="progressbar"
			aria-valuenow={remainingSecs}
			aria-valuemin={0}
			aria-valuemax={30}
		></div>
	</div>

	<!-- Header -->
	<div class="flex items-center gap-2 px-4 py-3 border-b border-navy-700 bg-navy-800/80">
		<div class="w-6 h-6 rounded-sm bg-gold/10 border border-gold/30 flex items-center justify-center flex-shrink-0">
			<svg class="w-3.5 h-3.5 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
		</div>
		<span class="text-xs font-medium text-gold tracking-wide uppercase">Autonomous Decision</span>
		<span class="ml-auto text-xs text-slate-500 tabular-nums">
			Continuing in {remainingSecs}s
		</span>
	</div>

	<div class="px-4 py-4 space-y-4">
		<!-- Assumption message -->
		<p class="text-sm text-slate-200 leading-relaxed">{confirmation.message}</p>

		<!-- Options (if provided) -->
		{#if confirmation.options && confirmation.options.length > 0}
			<div class="space-y-1">
				{#each confirmation.options as option (option)}
					<div class="flex items-start gap-2 text-xs text-slate-400">
						<span class="text-gold/60 mt-0.5">&#8250;</span>
						<span>{option}</span>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Action buttons -->
		<div class="flex items-center gap-2">
			<button
				onclick={handleConfirm}
				class="px-4 py-1.5 rounded bg-gold text-navy text-xs font-medium hover:bg-gold-light transition-colors"
			>
				Continue
			</button>
			<button
				onclick={handleOverride}
				class="px-4 py-1.5 rounded border border-navy-600 text-slate-300 text-xs hover:text-gold hover:border-gold/40 hover:bg-navy-700 transition-all"
			>
				Override
			</button>
			<button
				onclick={handleCancel}
				class="px-4 py-1.5 rounded border border-navy-600 text-slate-500 text-xs hover:text-red-400 hover:border-red-800/40 hover:bg-red-900/10 transition-all ml-auto"
			>
				Cancel
			</button>
		</div>
	</div>
</div>
