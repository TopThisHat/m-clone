<script lang="ts">
	let {
		value = null,
		min,
		max,
		step = 1,
		placeholder = '0',
		disabled = false,
		onchange,
	}: {
		value?: number | null;
		min?: number;
		max?: number;
		step?: number;
		placeholder?: string;
		disabled?: boolean;
		onchange?: (value: number | null) => void;
	} = $props();

	let editing = $state(false);
	let draft = $state('');
	let input: HTMLInputElement | undefined = $state();

	// Sync draft when value prop changes externally
	$effect(() => {
		if (!editing) {
			draft = value !== null ? String(value) : '';
		}
	});

	let parsedValue = $derived(() => {
		if (draft.trim() === '') return null;
		const n = Number(draft);
		return Number.isNaN(n) ? undefined : n;
	});

	let error = $derived(() => {
		const parsed = parsedValue();
		if (parsed === undefined) return 'Invalid number';
		if (parsed === null) return null;
		if (min !== undefined && parsed < min) return `Min: ${min}`;
		if (max !== undefined && parsed > max) return `Max: ${max}`;
		return null;
	});

	let hasError = $derived(error() !== null);

	function startEditing() {
		if (disabled) return;
		editing = true;
		draft = value !== null ? String(value) : '';
		queueMicrotask(() => {
			if (input) {
				input.focus();
				input.select();
			}
		});
	}

	function save() {
		const parsed = parsedValue();
		const err = error();
		if (err) {
			// Revert on invalid
			draft = value !== null ? String(value) : '';
			editing = false;
			return;
		}
		editing = false;
		const newVal = parsed === undefined ? null : parsed;
		if (newVal !== value && onchange) {
			onchange(newVal);
		}
	}

	function cancel() {
		draft = value !== null ? String(value) : '';
		editing = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			cancel();
		} else if (e.key === 'Enter') {
			e.preventDefault();
			save();
		}
	}

	function displayValue(): string {
		if (value === null || value === undefined) return '';
		return String(value);
	}
</script>

{#if editing}
	<div class="relative">
		<input
			bind:this={input}
			bind:value={draft}
			type="number"
			{placeholder}
			{step}
			min={min}
			max={max}
			class="w-full input-base text-sm px-2 py-1.5 text-right tabular-nums h-8
				{hasError ? 'border-red-500 focus:border-red-500' : ''}"
			onblur={save}
			onkeydown={handleKeydown}
			aria-label="Edit number"
			aria-invalid={hasError}
		/>
		{#if hasError}
			<span
				class="absolute -bottom-4 right-0 text-[10px] text-red-400 whitespace-nowrap"
				role="alert"
			>
				{error()}
			</span>
		{/if}
	</div>
{:else}
	<button
		type="button"
		class="w-full text-right text-sm px-2 py-1.5 rounded-md h-8 tabular-nums
			text-slate-300 hover:bg-navy-700 transition-colors
			{disabled ? 'cursor-not-allowed opacity-60' : 'cursor-text'}
			{!displayValue() ? 'text-slate-500 italic text-center' : ''}"
		onclick={startEditing}
		{disabled}
		aria-label={displayValue() ? `Edit: ${displayValue()}` : placeholder}
	>
		{displayValue() || placeholder}
	</button>
{/if}
