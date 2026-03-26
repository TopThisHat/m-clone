<script lang="ts">
	import type { ImportErrorDetail } from '$lib/api/importExport';

	let {
		errors,
		ondownload,
	}: {
		errors: ImportErrorDetail[];
		ondownload?: () => void | Promise<void>;
	} = $props();

	const MAX_VISIBLE = 10;
	let showAll = $state(false);

	let visibleErrors = $derived(showAll ? errors : errors.slice(0, MAX_VISIBLE));
	let hasMore = $derived(errors.length > MAX_VISIBLE);
</script>

<div class="rounded-xl border border-red-900/60 bg-red-950/30 p-4 space-y-3">
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-2 text-red-400">
			<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
					d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
			</svg>
			<span class="font-medium text-sm">
				{errors.length} validation {errors.length === 1 ? 'error' : 'errors'}
			</span>
		</div>
		{#if ondownload}
			<button
				onclick={ondownload}
				class="text-xs text-gold hover:text-gold-light underline transition-colors"
			>
				Download error report
			</button>
		{/if}
	</div>

	<p class="text-xs text-slate-400">
		Rows with errors will be skipped. You can still proceed to import the valid rows.
	</p>

	<div class="space-y-1 max-h-48 overflow-y-auto">
		{#each visibleErrors as err (err.row + ':' + err.field)}
			<div class="flex items-start gap-2 text-xs py-1 border-t border-red-900/30">
				<span class="text-red-500 font-mono shrink-0 w-12">row {err.row}</span>
				{#if err.field}
					<span class="text-slate-400 font-mono shrink-0">{err.field}:</span>
				{/if}
				<span class="text-red-300">{err.message}</span>
			</div>
		{/each}
	</div>

	{#if hasMore}
		<button
			onclick={() => (showAll = !showAll)}
			class="text-xs text-slate-500 hover:text-slate-300 underline transition-colors"
		>
			{showAll ? 'Show fewer' : `Show all ${errors.length} errors`}
		</button>
	{/if}
</div>
