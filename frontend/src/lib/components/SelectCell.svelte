<script lang="ts">
	export interface SelectOption {
		value: string;
		label: string;
		color?: string;
	}

	let {
		value = null,
		options = [],
		placeholder = 'Select...',
		disabled = false,
		searchable = true,
		conflict = false,
		onchange,
	}: {
		value?: string | null;
		options?: SelectOption[];
		placeholder?: string;
		disabled?: boolean;
		searchable?: boolean;
		conflict?: boolean;
		onchange?: (value: string | null) => void;
	} = $props();

	let open = $state(false);
	let search = $state('');
	let highlightIndex = $state(0);
	let dropdown: HTMLDivElement | undefined = $state();
	let searchInput: HTMLInputElement | undefined = $state();
	let triggerButton: HTMLButtonElement | undefined = $state();

	let selectedOption = $derived(
		options.find((o) => o.value === value) ?? null
	);

	let filteredOptions = $derived(
		search.trim()
			? options.filter((o) =>
					o.label.toLowerCase().includes(search.toLowerCase())
				)
			: options
	);

	// Reset highlight when filtered list changes
	$effect(() => {
		// Reference filteredOptions to track it
		filteredOptions;
		highlightIndex = 0;
	});

	function openDropdown() {
		if (disabled) return;
		open = true;
		search = '';
		highlightIndex = selectedOption
			? Math.max(0, filteredOptions.findIndex((o) => o.value === selectedOption!.value))
			: 0;
		queueMicrotask(() => {
			if (searchable && searchInput) {
				searchInput.focus();
			}
		});
	}

	function closeDropdown() {
		open = false;
		search = '';
		queueMicrotask(() => triggerButton?.focus());
	}

	function selectOption(opt: SelectOption) {
		if (onchange) {
			onchange(opt.value);
		}
		closeDropdown();
	}

	function clearSelection(e: Event) {
		e.stopPropagation();
		if (onchange) {
			onchange(null);
		}
	}

	function handleTriggerKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
			e.preventDefault();
			openDropdown();
		}
	}

	function handleDropdownKeydown(e: KeyboardEvent) {
		switch (e.key) {
			case 'ArrowDown':
				e.preventDefault();
				highlightIndex = Math.min(highlightIndex + 1, filteredOptions.length - 1);
				scrollToHighlighted();
				break;
			case 'ArrowUp':
				e.preventDefault();
				highlightIndex = Math.max(highlightIndex - 1, 0);
				scrollToHighlighted();
				break;
			case 'Enter':
				e.preventDefault();
				if (filteredOptions[highlightIndex]) {
					selectOption(filteredOptions[highlightIndex]);
				}
				break;
			case 'Escape':
				e.preventDefault();
				closeDropdown();
				break;
			case 'Home':
				e.preventDefault();
				highlightIndex = 0;
				scrollToHighlighted();
				break;
			case 'End':
				e.preventDefault();
				highlightIndex = filteredOptions.length - 1;
				scrollToHighlighted();
				break;
		}
	}

	function scrollToHighlighted() {
		queueMicrotask(() => {
			if (!dropdown) return;
			const el = dropdown.querySelector('[data-highlighted="true"]');
			if (el) {
				el.scrollIntoView({ block: 'nearest' });
			}
		});
	}

	function handleBackdropClick() {
		closeDropdown();
	}

	/** Default color palette for pills when no explicit color is set */
	const defaultColors: Record<string, string> = {};
	const palette = [
		'bg-blue-900/60 text-blue-300 border-blue-700',
		'bg-purple-900/60 text-purple-300 border-purple-700',
		'bg-emerald-900/60 text-emerald-300 border-emerald-700',
		'bg-amber-900/60 text-amber-300 border-amber-700',
		'bg-rose-900/60 text-rose-300 border-rose-700',
		'bg-cyan-900/60 text-cyan-300 border-cyan-700',
		'bg-indigo-900/60 text-indigo-300 border-indigo-700',
		'bg-teal-900/60 text-teal-300 border-teal-700',
	];

	function pillClasses(opt: SelectOption): string {
		if (opt.color) return opt.color;
		if (!defaultColors[opt.value]) {
			const idx = Object.keys(defaultColors).length % palette.length;
			defaultColors[opt.value] = palette[idx];
		}
		return defaultColors[opt.value];
	}
</script>

<!-- Backdrop to close dropdown on outside click -->
{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-40"
		onclick={handleBackdropClick}
		onkeydown={() => {}}
	></div>
{/if}

<div class="relative">
	<!-- Trigger row -->
	<div class="flex items-center gap-0.5">
		<button
			bind:this={triggerButton}
			type="button"
			class="flex-1 flex items-center gap-1.5 text-sm px-2 py-1.5 rounded-md h-8
				text-slate-300 hover:bg-navy-700 transition-colors text-left
				{disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}
				{open ? 'bg-navy-700 ring-1 ring-gold/40' : ''}
				{conflict ? 'conflict-flash' : ''}"
			onclick={openDropdown}
			onkeydown={handleTriggerKeydown}
			{disabled}
			aria-haspopup="listbox"
			aria-expanded={open}
			aria-label={selectedOption ? `Selected: ${selectedOption.label}` : placeholder}
		>
			{#if selectedOption}
				<span
					class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border
						{pillClasses(selectedOption)}"
				>
					{selectedOption.label}
				</span>
			{:else}
				<span class="text-slate-500 italic">{placeholder}</span>
			{/if}
		</button>
		{#if selectedOption && !disabled}
			<button
				type="button"
				class="text-slate-500 hover:text-slate-300 shrink-0 cursor-pointer min-w-[44px] min-h-[44px] flex items-center justify-center rounded hover:bg-navy-700 transition-colors"
				onclick={clearSelection}
				aria-label="Clear selection"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		{/if}
	</div>

	<!-- Dropdown -->
	{#if open}
		<div
			bind:this={dropdown}
			class="absolute z-50 mt-1 w-full min-w-[10rem] max-h-48 overflow-auto
				bg-navy-800 border border-navy-600 rounded-lg shadow-xl"
			role="listbox"
			aria-label="Options"
		>
			{#if searchable}
				<div class="p-1.5 border-b border-navy-700">
					<input
						bind:this={searchInput}
						bind:value={search}
						type="text"
						placeholder="Search..."
						class="w-full bg-navy-700 border border-navy-600 rounded px-2 py-1 text-xs text-slate-300
							placeholder-slate-500 focus:outline-none focus:border-gold/50"
						aria-label="Filter options"
						onkeydown={handleDropdownKeydown}
					/>
				</div>
			{/if}

			{#if filteredOptions.length === 0}
				<div class="px-3 py-2 text-xs text-slate-500 text-center">No options found</div>
			{:else}
				{#each filteredOptions as opt, i (opt.value)}
					<button
						type="button"
						class="w-full text-left px-2 py-1.5 text-sm flex items-center gap-2 transition-colors
							{i === highlightIndex ? 'bg-navy-700' : 'hover:bg-navy-700/50'}
							{opt.value === value ? 'text-gold' : 'text-slate-300'}"
						role="option"
						aria-selected={opt.value === value}
						data-highlighted={i === highlightIndex}
						onclick={() => selectOption(opt)}
						onmouseenter={() => (highlightIndex = i)}
					>
						<span
							class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border
								{pillClasses(opt)}"
						>
							{opt.label}
						</span>
						{#if opt.value === value}
							<svg class="w-3.5 h-3.5 ml-auto text-gold shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
							</svg>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	{/if}
</div>
