<script lang="ts">
	let {
		value = null,
		disabled = false,
		label = '',
		onchange,
	}: {
		value?: boolean | null;
		disabled?: boolean;
		label?: string;
		onchange?: (value: boolean | null) => void;
	} = $props();

	// Tri-state cycle: null -> true -> false -> null
	function toggle() {
		if (disabled) return;
		let next: boolean | null;
		if (value === null) {
			next = true;
		} else if (value === true) {
			next = false;
		} else {
			next = null;
		}
		if (onchange) {
			onchange(next);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === ' ' || e.key === 'Enter') {
			e.preventDefault();
			toggle();
		}
	}

	let ariaChecked = $derived<'true' | 'false' | 'mixed'>(
		value === null ? 'mixed' : value ? 'true' : 'false'
	);

	let stateLabel = $derived(
		value === null ? 'indeterminate' : value ? 'checked' : 'unchecked'
	);

	let nextStateLabel = $derived(
		value === null ? 'checked' : value ? 'unchecked' : 'indeterminate'
	);
</script>

<button
	type="button"
	role="checkbox"
	aria-checked={ariaChecked}
	aria-label={label ? `${label}: ${stateLabel}` : stateLabel}
	title="Click to cycle: {stateLabel} → {nextStateLabel}"
	class="flex items-center justify-center w-8 h-8 rounded-md transition-all
		focus-visible:ring-2 focus-visible:ring-gold/60 focus-visible:outline-none
		{disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-navy-700'}"
	onclick={toggle}
	onkeydown={handleKeydown}
	{disabled}
>
	{#if value === true}
		<!-- Checked: filled gold checkbox -->
		<div
			class="w-5 h-5 rounded border-2 border-gold bg-gold flex items-center justify-center"
		>
			<svg class="w-3 h-3 text-navy" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="3">
				<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
			</svg>
		</div>
	{:else if value === false}
		<!-- Unchecked: empty bordered checkbox with X -->
		<div
			class="w-5 h-5 rounded border-2 border-red-500 flex items-center justify-center"
		>
			<svg class="w-3 h-3 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="3">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</div>
	{:else}
		<!-- Null/indeterminate: dash -->
		<div
			class="w-5 h-5 rounded border-2 border-slate-500 flex items-center justify-center"
		>
			<div class="w-2.5 h-0.5 bg-slate-400 rounded-full"></div>
		</div>
	{/if}
</button>
