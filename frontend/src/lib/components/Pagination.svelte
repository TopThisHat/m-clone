<script lang="ts">
	let { total, pageSize, currentPage, onPageChange }: {
		total: number;
		pageSize: number;
		currentPage: number;
		onPageChange: (page: number) => void;
	} = $props();

	let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
	let startItem = $derived(total === 0 ? 0 : currentPage * pageSize + 1);
	let endItem = $derived(Math.min((currentPage + 1) * pageSize, total));
</script>

{#if total > pageSize}
	<div class="flex items-center justify-between px-4 py-3 text-sm">
		<span class="text-slate-500">
			Showing <span class="text-slate-300 font-mono">{startItem}–{endItem}</span> of <span class="text-slate-300 font-mono">{total}</span>
		</span>
		<div class="flex items-center gap-2">
			<button
				onclick={() => onPageChange(currentPage - 1)}
				disabled={currentPage === 0}
				class="px-2.5 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
			>
				← Prev
			</button>
			<span class="text-slate-400 px-2">
				Page <span class="text-slate-200 font-mono">{currentPage + 1}</span> of <span class="text-slate-200 font-mono">{totalPages}</span>
			</span>
			<button
				onclick={() => onPageChange(currentPage + 1)}
				disabled={currentPage >= totalPages - 1}
				class="px-2.5 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
			>
				Next →
			</button>
		</div>
	</div>
{/if}
