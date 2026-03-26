<script lang="ts">
	import type { Attribute } from '$lib/api/attributes';
	import { templatesApi, type AttributeTemplate } from '$lib/api/templates';

	let {
		open = false,
		attributes,
		onclose,
		onsaved,
	}: {
		open?: boolean;
		attributes: Attribute[];
		onclose: () => void;
		onsaved?: (template: AttributeTemplate) => void;
	} = $props();

	let name = $state('');
	let saving = $state(false);
	let error = $state('');
	let dialogEl: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (open) {
			name = '';
			error = '';
			dialogEl?.showModal();
			queueMicrotask(() => document.getElementById('template-name')?.focus());
		} else {
			dialogEl?.close();
		}
	});

	function handleClose() {
		onclose();
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

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!name.trim() || attributes.length === 0) return;
		saving = true;
		error = '';
		try {
			const template = await templatesApi.create({
				name: name.trim(),
				attributes: attributes.map((a) => ({
					label: a.label,
					description: a.description ?? undefined,
					weight: a.weight,
				})),
			});
			onsaved?.(template);
			handleClose();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to save template';
		} finally {
			saving = false;
		}
	}
</script>

{#if open}
	<dialog
		bind:this={dialogEl}
		onclose={handleClose}
		onkeydown={handleKeydown}
		onclick={handleBackdropClick}
		class="fixed inset-0 z-50 m-auto w-full max-w-md rounded-xl border border-navy-600 bg-navy-900 shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm p-0"
	>
		<form onsubmit={handleSubmit} class="flex flex-col">
			<div class="flex items-center justify-between px-5 pt-5 pb-3">
				<h2 id="template-save-title" class="font-serif text-gold text-lg font-bold">Save as Template</h2>
				<button
					type="button"
					onclick={handleClose}
					aria-label="Close"
					class="min-w-[44px] min-h-[44px] flex items-center justify-center text-slate-500 hover:text-slate-300 transition-colors"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			{#if error}
				<div class="mx-5 mb-3 bg-red-950 border border-red-700 rounded-lg px-3 py-2 text-red-300 text-sm" role="alert">
					{error}
				</div>
			{/if}

			<div class="px-5 pb-4 space-y-4">
				<div>
					<label for="template-name" class="block text-xs text-slate-400 mb-1">Template Name *</label>
					<input
						id="template-name"
						bind:value={name}
						required
						placeholder="e.g. Due Diligence Checklist"
						class="input-field w-full"
					/>
				</div>

				<!-- Attribute preview -->
				<div>
					<p class="text-xs text-slate-500 mb-2">{attributes.length} attributes will be saved:</p>
					<div class="max-h-48 overflow-y-auto bg-navy-800 rounded-lg p-3 space-y-1.5">
						{#each attributes as attr (attr.id)}
							<div class="flex items-center justify-between text-sm">
								<span class="text-slate-300 truncate">{attr.label}</span>
								<span class="text-xs text-slate-600 font-mono flex-shrink-0 ml-2">w:{attr.weight.toFixed(1)}</span>
							</div>
						{:else}
							<p class="text-slate-600 text-sm italic">No attributes to save.</p>
						{/each}
					</div>
				</div>
			</div>

			<div class="flex items-center justify-end gap-2 px-5 pb-5">
				<button
					type="button"
					onclick={handleClose}
					class="btn-secondary py-1.5 px-4 text-sm"
				>
					Cancel
				</button>
				<button
					type="submit"
					disabled={saving || !name.trim() || attributes.length === 0}
					class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50 transition-colors"
				>
					{saving ? 'Saving...' : 'Save Template'}
				</button>
			</div>
		</form>
	</dialog>
{/if}
