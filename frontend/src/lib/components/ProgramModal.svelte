<script lang="ts">
	import type { Program } from './ProgramsSidebar.svelte';

	let {
		program = null,
		open = false,
		saving = false,
		onclose,
		onsave,
	}: {
		program?: Program | null;
		open?: boolean;
		saving?: boolean;
		onclose?: () => void;
		onsave?: (data: { name: string; description: string }) => void;
	} = $props();

	let name = $state('');
	let description = $state('');
	let touched = $state(false);

	let isEdit = $derived(program !== null);
	let title = $derived(isEdit ? 'Edit Program' : 'New Program');
	let nameError = $derived(touched && !name.trim() ? 'Program name is required' : '');
	let canSave = $derived(name.trim().length > 0 && !saving);

	let dialogEl: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (open) {
			name = program?.name ?? '';
			description = '';
			touched = false;
			dialogEl?.showModal();
			queueMicrotask(() => document.getElementById('program-name')?.focus());
		} else {
			dialogEl?.close();
		}
	});

	function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		touched = true;
		if (!canSave) return;
		onsave?.({ name: name.trim(), description: description.trim() });
	}

	function handleClose() {
		onclose?.();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			handleClose();
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === dialogEl) {
			handleClose();
		}
	}
</script>

{#if open}
	<dialog
		bind:this={dialogEl}
		onclose={handleClose}
		onkeydown={handleKeydown}
		onclick={handleBackdropClick}
		aria-labelledby="program-modal-title"
		class="fixed inset-0 z-50 m-auto w-full max-w-md rounded-xl border border-navy-600 bg-navy-900 shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm p-0"
	>
		<form onsubmit={handleSubmit} class="flex flex-col">
			<!-- Header -->
			<div class="flex items-center justify-between px-5 py-4 border-b border-navy-700">
				<h2 id="program-modal-title" class="text-sm font-medium text-slate-200">{title}</h2>
				<button
					type="button"
					onclick={handleClose}
					class="text-slate-500 hover:text-slate-300 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
					aria-label="Close"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<!-- Body -->
			<div class="px-5 py-4 space-y-4">
				<!-- Name field -->
				<div>
					<label for="program-name" class="block text-xs text-slate-400 mb-1.5">
						Name <span class="text-red-400">*</span>
					</label>
					<input
						id="program-name"
						bind:value={name}
						oninput={() => { touched = true; }}
						type="text"
						placeholder="e.g. Q1 Research Pipeline"
						maxlength="100"
						class="w-full input-field"
						aria-required="true"
						aria-invalid={!!nameError}
						aria-describedby={nameError ? 'name-error' : undefined}
					/>
					{#if nameError}
						<p id="name-error" class="text-xs text-red-400 mt-1" role="alert">{nameError}</p>
					{/if}
				</div>

				<!-- Description field -->
				<div>
					<label for="program-desc" class="block text-xs text-slate-400 mb-1.5">
						Description
					</label>
					<textarea
						id="program-desc"
						bind:value={description}
						placeholder="Optional description..."
						rows="3"
						maxlength="500"
						class="w-full input-field resize-none"
					></textarea>
					<p class="text-xs text-slate-600 mt-1 text-right">{description.length}/500</p>
				</div>
			</div>

			<!-- Footer -->
			<div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-navy-700">
				<button
					type="button"
					onclick={handleClose}
					class="btn-secondary"
					disabled={saving}
				>
					Cancel
				</button>
				<button
					type="submit"
					class="btn-gold"
					disabled={!canSave}
				>
					{#if saving}
						<span class="flex items-center gap-2">
							<span class="w-3 h-3 border-2 border-navy border-t-transparent rounded-full animate-spin"></span>
							Saving...
						</span>
					{:else}
						{isEdit ? 'Update' : 'Create'}
					{/if}
				</button>
			</div>
		</form>
	</dialog>
{/if}
