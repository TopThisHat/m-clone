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

	const navBtnClass = 'px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed text-xs';
</script>

{#if total > 0}
	<div class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs border-t border-navy-700 bg-navy-800">
		<!-- Left: showing X-Y of Z + page size -->
		<div class="flex items-center gap-3">
			<span class="text-slate-500">
				<span class="text-slate-300 font-mono">{startItem}–{endItem}</span> of <span class="text-slate-300 font-mono">{total}</span>
			</span>
			{#if onPageSizeChange}
				<select onchange={handlePageSizeChange} value={pageSize} class="bg-navy-700 border border-navy-600 rounded px-1.5 py-0.5 text-slate-300">
					<option value={25}>25</option>
					<option value={50}>50</option>
					<option value={100}>100</option>
					<option value={250}>250</option>
				</select>
			{/if}
		</div>

		<!-- Right: navigation -->
		{#if totalPages > 1}
			<div class="flex items-center gap-1">
				<button onclick={() => onPageChange(0)} disabled={currentPage === 0} class={navBtnClass} title="First page" aria-label="First page">
					&laquo;
				</button>
				<button onclick={() => onPageChange(currentPage - 1)} disabled={currentPage === 0} class={navBtnClass} aria-label="Previous page">
					&lsaquo; Prev
				</button>

				<div class="flex items-center gap-1 px-1 text-slate-400">
					<input
						type="number"
						bind:value={jumpToPageInput}
						onkeydown={(e) => e.key === 'Enter' && handlePageJump()}
						placeholder={String(currentPage + 1)}
						class="w-10 bg-navy-700 border border-navy-600 rounded px-1 py-0.5 text-center text-slate-300"
						min="1"
						max={totalPages}
						aria-label="Jump to page number"
					/>
					<span>/ {totalPages}</span>
				</div>

				<button onclick={() => onPageChange(currentPage + 1)} disabled={currentPage >= totalPages - 1} class={navBtnClass} aria-label="Next page">
					Next &rsaquo;
				</button>
				<button onclick={() => onPageChange(totalPages - 1)} disabled={currentPage >= totalPages - 1} class={navBtnClass} title="Last page" aria-label="Last page">
					&raquo;
				</button>
			</div>
		{/if}
	</div>
{/if}
