<script lang="ts">
	const MAX_LENGTH = 500;

	let {
		value = '',
		placeholder = 'Enter text...',
		disabled = false,
		onchange,
	}: {
		value?: string;
		placeholder?: string;
		disabled?: boolean;
		onchange?: (value: string) => void;
	} = $props();

	let editing = $state(false);
	let draft = $state('');
	let textarea: HTMLTextAreaElement | undefined = $state();

	// Sync draft when value prop changes externally
	$effect(() => {
		if (!editing) {
			draft = value;
		}
	});

	let remaining = $derived(MAX_LENGTH - draft.length);
	let overLimit = $derived(draft.length > MAX_LENGTH);

	function startEditing() {
		if (disabled) return;
		editing = true;
		draft = value;
		// Focus the textarea after it renders
		queueMicrotask(() => {
			if (textarea) {
				textarea.focus();
				autoResize();
			}
		});
	}

	function autoResize() {
		if (!textarea) return;
		textarea.style.height = 'auto';
		textarea.style.height = textarea.scrollHeight + 'px';
	}

	function save() {
		if (overLimit) return;
		const trimmed = draft.trim();
		editing = false;
		if (trimmed !== value && onchange) {
			onchange(trimmed);
		}
	}

	function cancel() {
		draft = value;
		editing = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			cancel();
		} else if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			save();
		}
	}

	function handleInput() {
		autoResize();
	}
</script>

{#if editing}
	<div class="relative">
		<textarea
			bind:this={textarea}
			bind:value={draft}
			{placeholder}
			maxlength={MAX_LENGTH}
			class="w-full input-base text-sm px-2 py-1.5 resize-none overflow-hidden min-h-[2rem]
				{overLimit ? 'border-red-500 focus:border-red-500' : ''}"
			oninput={handleInput}
			onblur={save}
			onkeydown={handleKeydown}
			rows={1}
			aria-label="Edit text"
		></textarea>
		<span
			class="absolute bottom-0.5 right-1.5 text-xs select-none
				{overLimit ? 'text-red-400' : remaining <= 50 ? 'text-yellow-400' : 'text-slate-500'}"
			aria-live="polite"
		>
			{remaining}
		</span>
	</div>
{:else}
	<button
		type="button"
		class="w-full text-left text-sm px-2 py-1.5 rounded-md min-h-[2rem]
			text-slate-300 hover:bg-navy-700 transition-colors truncate
			{disabled ? 'cursor-not-allowed opacity-60' : 'cursor-text'}
			{!value ? 'text-slate-500 italic' : ''}"
		onclick={startEditing}
		{disabled}
		title={value || placeholder}
		aria-label={value ? `Edit: ${value}` : placeholder}
	>
		{value || placeholder}
	</button>
{/if}
