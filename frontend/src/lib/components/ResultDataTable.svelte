<script lang="ts">
	let {
		data,
		columns
	}: {
		data: Record<string, unknown>[];
		columns: string[];
	} = $props();

	// ── Search ────────────────────────────────────────────────────────────────
	let searchQuery = $state('');

	const filteredData = $derived.by(() => {
		const q = searchQuery.trim().toLowerCase();
		if (!q) return data;
		return data.filter((row) =>
			columns.some((col) => {
				const val = row[col];
				return val != null && String(val).toLowerCase().includes(q);
			})
		);
	});

	// ── Sorting ───────────────────────────────────────────────────────────────
	let sortCol = $state<string | null>(null);
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(col: string) {
		if (sortCol === col) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortCol = col;
			sortDir = 'asc';
		}
	}

	const sortedData = $derived.by(() => {
		if (!sortCol) return filteredData;
		const col = sortCol;
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...filteredData].sort((a, b) => {
			const av = a[col] ?? '';
			const bv = b[col] ?? '';
			if (av < bv) return -1 * dir;
			if (av > bv) return 1 * dir;
			return 0;
		});
	});

	// ── Pagination ────────────────────────────────────────────────────────────
	let pageSize = $state(25);
	let currentPage = $state(1);

	const totalPages = $derived(Math.max(1, Math.ceil(sortedData.length / pageSize)));

	// Reset to page 1 when filters/sort change
	$effect(() => {
		// Touch sortedData to register dependency
		sortedData;
		currentPage = 1;
	});

	const pageData = $derived(sortedData.slice((currentPage - 1) * pageSize, currentPage * pageSize));

	function prevPage() {
		if (currentPage > 1) currentPage--;
	}

	function nextPage() {
		if (currentPage < totalPages) currentPage++;
	}

	// ── CSV Export ────────────────────────────────────────────────────────────
	function exportCsv() {
		const escape = (v: unknown) => {
			const s = v == null ? '' : String(v);
			return s.includes(',') || s.includes('"') || s.includes('\n')
				? `"${s.replace(/"/g, '""')}"`
				: s;
		};
		const header = columns.map(escape).join(',');
		const rows = filteredData.map((row) => columns.map((c) => escape(row[c])).join(','));
		const csv = [header, ...rows].join('\n');
		const blob = new Blob([csv], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'results.csv';
		a.click();
		URL.revokeObjectURL(url);
	}

	// ── Cell rendering ────────────────────────────────────────────────────────
	function cellText(val: unknown): string {
		if (val == null) return '';
		if (typeof val === 'object') return JSON.stringify(val);
		return String(val);
	}
</script>

<div class="my-3 border border-navy-600 rounded-lg bg-navy-800/60 overflow-hidden">
	<!-- Toolbar -->
	<div class="flex items-center gap-3 px-3 py-2.5 border-b border-navy-700 bg-navy-800/80 flex-wrap">
		<!-- Search -->
		<input
			type="search"
			bind:value={searchQuery}
			placeholder="Search all columns..."
			class="flex-1 min-w-0 bg-navy-900 border border-navy-600 rounded px-2.5 py-1 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
		/>

		<!-- Row count label -->
		<span class="text-xs text-slate-600 flex-shrink-0">
			{filteredData.length} row{filteredData.length !== 1 ? 's' : ''}
		</span>

		<!-- Page size selector -->
		<select
			bind:value={pageSize}
			class="bg-navy-900 border border-navy-600 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-gold/40"
		>
			<option value={25}>25 / page</option>
			<option value={50}>50 / page</option>
			<option value={100}>100 / page</option>
		</select>

		<!-- CSV export -->
		<button
			onclick={exportCsv}
			class="flex-shrink-0 flex items-center gap-1.5 text-xs px-3 py-1 border border-navy-600 rounded text-slate-400 hover:text-gold hover:border-gold/30 hover:bg-navy-700 transition-all"
			title="Download CSV"
		>
			<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
			</svg>
			Download CSV ({filteredData.length})
		</button>
	</div>

	<!-- Table wrapper -->
	<div class="overflow-x-auto">
		<table class="w-full text-xs border-collapse">
			<thead>
				<tr class="bg-navy-800 border-b border-navy-600">
					{#each columns as col (col)}
						<th
							class="px-3 py-2 text-left font-medium text-gold-light cursor-pointer select-none whitespace-nowrap hover:bg-navy-700 transition-colors"
							onclick={() => toggleSort(col)}
						>
							<span class="flex items-center gap-1">
								<span class="truncate max-w-[140px]" title={col}>{col}</span>
								{#if sortCol === col}
									<span class="text-gold text-[10px] flex-shrink-0">
										{sortDir === 'asc' ? '▲' : '▼'}
									</span>
								{:else}
									<span class="text-slate-700 text-[10px] flex-shrink-0">⇅</span>
								{/if}
							</span>
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#if pageData.length === 0}
					<tr>
						<td colspan={columns.length} class="px-3 py-8 text-center text-slate-600">
							No results found
						</td>
					</tr>
				{:else}
					{#each pageData as row, i (i)}
						<tr
							class="border-b border-navy-700/50 {i % 2 === 0 ? 'bg-navy-900' : 'bg-navy-800/40'} hover:bg-navy-700/30 transition-colors"
						>
							{#each columns as col (col)}
								{@const text = cellText(row[col])}
								<td
									class="px-3 py-1.5 text-slate-300 max-w-[220px]"
									title={text}
								>
									<span class="block truncate">{text}</span>
								</td>
							{/each}
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	<!-- Pagination footer -->
	{#if totalPages > 1}
		<div class="flex items-center justify-between gap-3 px-3 py-2 border-t border-navy-700 bg-navy-800/80">
			<button
				onclick={prevPage}
				disabled={currentPage === 1}
				class="text-xs px-2.5 py-1 border border-navy-600 rounded text-slate-400 hover:text-gold hover:border-gold/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
			>
				&#8592; Prev
			</button>

			<span class="text-xs text-slate-600 tabular-nums">
				Page {currentPage} of {totalPages}
			</span>

			<button
				onclick={nextPage}
				disabled={currentPage === totalPages}
				class="text-xs px-2.5 py-1 border border-navy-600 rounded text-slate-400 hover:text-gold hover:border-gold/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
			>
				Next &#8594;
			</button>
		</div>
	{/if}
</div>
