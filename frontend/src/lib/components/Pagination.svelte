<script lang="ts">
	let { total, pageSize, currentPage, onPageChange, onPageSizeChange }: {
		total: number;
		pageSize: number;
		currentPage: number;
		onPageChange: (page: number) => void;
		onPageSizeChange?: (size: number) => void;
	} = $props();

	let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
	let startItem = $derived(total === 0 ? 0 : currentPage * pageSize + 1);
	let endItem = $derived(Math.min((currentPage + 1) * pageSize, total));
	let jumpToPageInput = $state('');

	function handlePageJump() {
		const page = parseInt(jumpToPageInput) - 1;
		if (!isNaN(page) && page >= 0 && page < totalPages) {
			onPageChange(page);
			jumpToPageInput = '';
		}
	}

	function handlePageSizeChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		const newSize = parseInt(target.value);
		if (onPageSizeChange) {
			onPageSizeChange(newSize);
		}
	}
</script>

{#if total > 0}
	<div class="flex items-center justify-between px-4 py-3 text-sm border-t border-navy-700">
		<div class="flex items-center gap-4">
			<span class="text-slate-500">
				Showing <span class="text-slate-300 font-mono">{startItem}–{endItem}</span> of <span class="text-slate-300 font-mono">{total}</span>
			</span>
			<select onchange={handlePageSizeChange} value={pageSize} class="bg-navy-700 border border-navy-600 rounded px-2 py-1 text-xs text-slate-300">
				<option value="25">25 / page</option>
				<option value="50">50 / page</option>
				<option value="100">100 / page</option>
				<option value="250">250 / page</option>
			</select>
		</div>
		<div class="flex items-center gap-2">
			<button
				onclick={() => onPageChange(0)}
				disabled={currentPage === 0}
				class="px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed text-xs"
				title="First page"
			>
				⟨⟨
			</button>
			<button
				onclick={() => onPageChange(currentPage - 1)}
				disabled={currentPage === 0}
				class="px-2.5 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
			>
				← Prev
			</button>
			<div class="flex items-center gap-1 px-2 text-slate-400">
				<span>Page</span>
				<input
					type="number"
					bind:value={jumpToPageInput}
					onkeydown={(e) => e.key === 'Enter' && handlePageJump()}
					placeholder={String(currentPage + 1)}
					class="w-12 bg-navy-700 border border-navy-600 rounded px-1 py-0.5 text-center text-xs text-slate-300"
					min="1"
					max={totalPages}
					title="Jump to page"
				/>
				<span>of <span class="text-slate-200 font-mono">{totalPages}</span></span>
			</div>
			<button
				onclick={() => onPageChange(currentPage + 1)}
				disabled={currentPage >= totalPages - 1}
				class="px-2.5 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
			>
				Next →
			</button>
			<button
				onclick={() => onPageChange(totalPages - 1)}
				disabled={currentPage >= totalPages - 1}
				class="px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed text-xs"
				title="Last page"
			>
				⟩⟩
			</button>
		</div>
	</div>
{/if}
