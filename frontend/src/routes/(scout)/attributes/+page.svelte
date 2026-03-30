<script lang="ts">
	import { tick } from 'svelte';
	import { libraryAttributesApi, type LibraryAttribute, type LibraryAttributeCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let attributes = $state<LibraryAttribute[]>([]);
	let loading = $state(true);
	let error = $state('');
	let actionError = $state('');
	let totalCount = $state(0);

	// Pagination & search
	let pageSize = $state(50);
	let currentPage = $state(0);
	let searchQuery = $state('');
	let debouncedSearch = $state('');
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	// Sorting
	let sortBy = $state<'label' | 'weight' | 'created_at'>('created_at');
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(col: typeof sortBy) {
		if (sortBy === col) { sortDir = sortDir === 'asc' ? 'desc' : 'asc'; }
		else { sortBy = col; sortDir = 'asc'; }
		currentPage = 0;
	}

	// Filtering
	let minWeight = $state(0);
	let maxWeight = $state(10);

	$effect(() => {
		const q = searchQuery;
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			debouncedSearch = q;
			currentPage = 0;
		}, 300);
		return () => clearTimeout(debounceTimer);
	});

	// Panel visibility
	let showAddForm = $state(false);
	let showCSV = $state(false);

	// Add form fields
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Inline edit
	let editing = $state<Record<string, LibraryAttribute>>({});

	// Bulk select
	let selectedIds = $state<Set<string>>(new Set());
	let bulkDeleting = $state(false);

	let allSelected = $derived(
		displayedAttributes().length > 0 && selectedIds.size === displayedAttributes().length
	);
	let someSelected = $derived(
		selectedIds.size > 0 && selectedIds.size < displayedAttributes().length
	);

	// Export
	let exporting = $state(false);

	// Focus refs for panel management
	let addBtnEl = $state<HTMLButtonElement | undefined>(undefined);
	let uploadBtnEl = $state<HTMLButtonElement | undefined>(undefined);

	async function openAddPanel() {
		showAddForm = true;
		showCSV = false;
		await tick();
		document.getElementById('lib-attr-label')?.focus();
	}

	async function closeAddPanel() {
		showAddForm = false;
		await tick();
		addBtnEl?.focus();
	}

	async function openUploadPanel() {
		showCSV = true;
		showAddForm = false;
		await tick();
		document.getElementById('lib-attr-upload-close')?.focus();
	}

	async function closeUploadPanel() {
		showCSV = false;
		await tick();
		uploadBtnEl?.focus();
	}

	async function loadAttributes(teamId: string | null, search: string, page: number, size: number, sort: string = 'created_at', dir: 'asc' | 'desc' = 'asc') {
		loading = true;
		error = '';
		try {
			const resp = await libraryAttributesApi.list(teamId, {
				limit: size,
				offset: page * size,
				search: search || undefined,
				sort_by: sort,
				sort_dir: dir,
			});
			attributes = resp.items;
			totalCount = resp.total;
		} catch (err: unknown) {
			attributes = [];
			totalCount = 0;
			error = err instanceof Error ? err.message : 'Failed to load library';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const team = $scoutTeam;
		const search = debouncedSearch;
		const page = currentPage;
		const size = pageSize;
		const sort = sortBy;
		const dir = sortDir;
		loadAttributes(team, search, page, size, sort, dir);
	});

	function displayedAttributes() {
		return attributes.filter(a => a.weight >= minWeight && a.weight <= maxWeight);
	}

	function displayedCount() {
		const displayed = displayedAttributes();
		return displayed.length;
	}

	function formatDate(isoString: string) {
		const date = new Date(isoString);
		const now = new Date();
		const days = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
		if (days === 0) return 'today';
		if (days === 1) return 'yesterday';
		if (days < 7) return `${days}d ago`;
		if (days < 30) return `${Math.floor(days / 7)}w ago`;
		if (days < 365) return `${Math.floor(days / 30)}mo ago`;
		return `${Math.floor(days / 365)}y ago`;
	}

	function getWeightColor(weight: number) {
		if (weight < 0.5) return 'bg-slate-700';
		if (weight < 1.5) return 'bg-slate-600';
		if (weight < 2.5) return 'bg-slate-500';
		if (weight < 3.5) return 'bg-slate-400';
		return 'bg-slate-300';
	}

	async function addAttribute(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			await libraryAttributesApi.create({
				label: newLabel.trim(),
				description: newDesc.trim() || undefined,
				weight: newWeight,
				team_id: $scoutTeam ?? undefined,
			});
			newLabel = '';
			newDesc = '';
			newWeight = 1.0;
			showAddForm = false;
			loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
			await tick();
			addBtnEl?.focus();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to add attribute';
		} finally {
			adding = false;
		}
	}

	async function startEdit(attr: LibraryAttribute) {
		editing[attr.id] = { ...attr };
		await tick();
		document.getElementById(`lib-attr-label-${attr.id}`)?.focus();
	}

	async function cancelEdit(id: string) {
		const e = { ...editing };
		delete e[id];
		editing = e;
		await tick();
		document.getElementById(`lib-attr-edit-${id}`)?.focus();
	}

	function handleEditKeydown(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter') {
			e.preventDefault();
			saveEdit(id);
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancelEdit(id);
		}
	}

	async function saveEdit(id: string) {
		const e = editing[id];
		if (!e) return;
		try {
			const updated = await libraryAttributesApi.update(id, {
				label: e.label,
				description: e.description ?? undefined,
				weight: e.weight,
			});
			attributes = attributes.map((a) => (a.id === id ? updated : a));
			const next = { ...editing };
			delete next[id];
			editing = next;
			await tick();
			document.getElementById(`lib-attr-edit-${id}`)?.focus();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to save';
		}
	}

	async function deleteAttribute(id: string) {
		if (!confirm('Delete this attribute from the library?')) return;
		try {
			await libraryAttributesApi.delete(id);
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
			loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		}
	}

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedIds = next;
	}

	function toggleSelectAll() {
		selectedIds = selectedIds.size === displayedAttributes().length
			? new Set()
			: new Set(displayedAttributes().map((a) => a.id));
	}

	async function bulkDelete() {
		if (!confirm(`Delete ${selectedIds.size} selected attributes from the library?`)) return;
		bulkDeleting = true;
		try {
			await libraryAttributesApi.bulkDelete([...selectedIds]);
			selectedIds = new Set();
			loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		} finally {
			bulkDeleting = false;
		}
	}

	async function exportCsv() {
		exporting = true;
		try {
			const resp = await libraryAttributesApi.list($scoutTeam, {
				limit: 0,
				search: debouncedSearch || undefined,
				sort_by: sortBy,
				sort_dir: sortDir,
			});
			const rows = resp.items;

			// Build CSV
			const headers = ['Label', 'Description', 'Weight', 'Created'];
			const csvLines = [
				headers.map(h => `"${h}"`).join(','),
				...rows.map(r => [
					`"${r.label.replace(/"/g, '""')}"`,
					`"${(r.description ?? '').replace(/"/g, '""')}"`,
					r.weight.toFixed(2),
					`"${r.created_at}"`,
				].join(','))
			];

			const blob = new Blob([csvLines.join('\n')], { type: 'text/csv' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `attributes-${new Date().toISOString().split('T')[0]}.csv`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(url);
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to export';
		} finally {
			exporting = false;
		}
	}

	function libraryBulkCreate(rows: LibraryAttributeCreate[]) {
		return libraryAttributesApi.bulkCreate(rows, $scoutTeam);
	}
</script>

<div class="max-w-7xl mx-auto">
	<!-- Header -->
	<div class="flex items-center justify-between mb-6">
		<div>
			<h1 class="font-serif text-gold text-3xl font-bold">Attribute Library</h1>
			<p class="text-slate-500 text-sm mt-2">Reusable attributes for entity evaluation</p>
		</div>
	</div>

	<!-- Filter & Sort Bar -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-6 space-y-3">
		<!-- Search input -->
		<div>
			<input
				bind:value={searchQuery}
				placeholder="Search label or description…"
				aria-label="Search attributes"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
			/>
		</div>

		<!-- Sort & filter buttons -->
		<div class="flex items-center gap-2 lg:gap-4 flex-wrap text-xs">
			<div class="flex items-center gap-2 flex-wrap">
				<span class="text-xs text-slate-400 w-full lg:w-auto mb-2 lg:mb-0">Sort:</span>
				{#each [['label', 'Label'], ['weight', 'Weight'], ['created_at', 'Date']] as [col, label]}
					<button
						onclick={() => toggleSort(col as typeof sortBy)}
						class={`text-xs px-2 py-1 rounded border transition-colors ${
							sortBy === col
								? 'bg-gold/10 border-gold/40 text-gold'
								: 'border-navy-600 text-slate-400 hover:text-slate-300'
						}`}
					>
						{label} {sortBy === col ? (sortDir === 'asc' ? '↑' : '↓') : ''}
					</button>
				{/each}
			</div>

			<div class="flex-1"></div>

			<div class="flex items-center gap-1 w-full lg:w-auto">
				<span class="text-xs text-slate-400 whitespace-nowrap">Weight:</span>
				<input
					type="range"
					bind:value={minWeight}
					min="0"
					max="10"
					step="0.1"
					class="w-16 sm:w-20 h-1 bg-navy-700 rounded-lg appearance-none cursor-pointer accent-gold"
					title="Minimum weight"
				/>
				<span class="text-xs text-slate-400 w-6 text-center">{minWeight.toFixed(1)}</span>
				<span class="text-xs text-slate-500">–</span>
				<input
					type="range"
					bind:value={maxWeight}
					min="0"
					max="10"
					step="0.1"
					class="w-16 sm:w-20 h-1 bg-navy-700 rounded-lg appearance-none cursor-pointer accent-gold"
					title="Maximum weight"
				/>
				<span class="text-xs text-slate-400 w-6 text-center">{maxWeight.toFixed(1)}</span>
			</div>
		</div>
	</div>

	<!-- Stats & Actions -->
	<div class="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-4 gap-3">
		<div class="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-4 text-xs sm:text-sm w-full sm:w-auto">
			{#if !loading}
				<p class="text-slate-400 whitespace-nowrap" aria-live="polite">
					<span class="text-slate-200 font-semibold">{totalCount}</span> total
					{#if (minWeight > 0 || maxWeight < 10 || debouncedSearch)}
						<br class="sm:hidden" />
						<span class="sm:inline">• <span class="text-slate-200 font-semibold">{displayedCount()}</span> shown</span>
					{/if}
					{#if selectedIds.size > 0}
						<br class="sm:hidden" />
						<span class="sm:inline">• <span class="text-gold font-semibold">{selectedIds.size}</span> selected</span>
					{/if}
				</p>
			{/if}
		</div>

		<div class="flex items-center gap-1 sm:gap-2 flex-wrap justify-end w-full sm:w-auto text-xs sm:text-sm">
			{#if selectedIds.size > 0}
				<button
					onclick={bulkDelete}
					disabled={bulkDeleting}
					class="bg-red-950 border border-red-800 text-red-400 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-red-900 disabled:opacity-50 transition-colors"
				>
					{bulkDeleting ? 'Deleting…' : `Delete (${selectedIds.size})`}
				</button>
			{/if}
			<button
				onclick={exportCsv}
				disabled={exporting}
				class="bg-navy-700 border border-navy-600 text-slate-300 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-navy-600 disabled:opacity-50 transition-colors"
			>
				{exporting ? 'Exporting…' : 'Export CSV'}
			</button>
			<button
				bind:this={uploadBtnEl}
				onclick={() => (showCSV ? closeUploadPanel() : openUploadPanel())}
				aria-expanded={showCSV}
				class={showCSV
					? 'bg-gold/10 border border-gold/40 text-gold font-medium px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg text-xs sm:text-sm'
					: 'bg-navy-700 border border-navy-600 text-slate-300 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-navy-600 transition-colors'}
			>
				Upload
			</button>
			<button
				bind:this={addBtnEl}
				onclick={() => (showAddForm ? closeAddPanel() : openAddPanel())}
				aria-expanded={showAddForm}
				class="bg-gold text-navy font-semibold px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-gold-light transition-colors"
			>
				+ Add Attribute
			</button>
		</div>
	</div>

	<!-- CSV Upload Panel -->
	{#if showCSV}
		<section aria-label="Upload CSV to library" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Upload CSV / Excel to Library</h3>
				<button id="lib-attr-upload-close" onclick={closeUploadPanel} class="text-slate-500 hover:text-slate-300 text-xs" aria-label="Close upload panel">Close</button>
			</div>
			<AttributeCSVUpload
				onBulkCreate={libraryBulkCreate}
				onUploaded={async () => {
					await closeUploadPanel();
					loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
				}}
			/>
		</section>
	{/if}

	<!-- Add Form Panel -->
	{#if showAddForm}
		<section aria-label="Add attribute to library" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Add Attribute to Library</h3>
				<button onclick={closeAddPanel} class="text-slate-500 hover:text-slate-300 text-xs" aria-label="Close add attribute panel">Close</button>
			</div>
			<form onsubmit={addAttribute} class="space-y-4">
				<div class="grid grid-cols-4 gap-4">
					<div class="col-span-2">
						<label for="lib-attr-label" class="block text-xs text-slate-400 mb-1">Label *</label>
						<input id="lib-attr-label" bind:value={newLabel} required placeholder="e.g. Has board experience" class="input-field w-full" />
					</div>
					<div>
						<label for="lib-attr-weight" class="block text-xs text-slate-400 mb-1">Weight</label>
						<input id="lib-attr-weight" type="number" bind:value={newWeight} min="0" max="10" step="0.1" class="input-field w-full" />
					</div>
				</div>
				<div>
					<label for="lib-attr-desc" class="block text-xs text-slate-400 mb-1">Description <span class="text-slate-600">(fed to LLM)</span></label>
					<input id="lib-attr-desc" bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate" class="input-field w-full" />
				</div>
				<div class="flex gap-2">
					<button type="submit" disabled={adding} class="btn-gold py-1.5 text-sm disabled:opacity-50">
						{adding ? 'Adding…' : 'Add Attribute'}
					</button>
					<button type="button" onclick={closeAddPanel} class="bg-navy-700 text-slate-300 px-4 py-1.5 rounded-lg text-sm border border-navy-600">
						Cancel
					</button>
				</div>
			</form>
		</section>
	{/if}

	<!-- Load error -->
	{#if error}
		<div class="bg-red-950 border border-red-700 rounded-xl px-4 py-3 text-red-300 text-sm mb-4" role="alert">
			<p>{error}</p>
		</div>
	{/if}

	<!-- Action error -->
	{#if actionError}
		<div class="bg-red-950 border border-red-700 rounded-xl px-4 py-3 text-red-300 text-sm mb-4 flex items-center justify-between" role="alert">
			<span>{actionError}</span>
			<button onclick={() => (actionError = '')} class="text-red-400 hover:text-red-200 min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label="Dismiss error">✕</button>
		</div>
	{/if}

	{#if loading}
		<LoadingSpinner />
	{:else if displayedAttributes().length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No attributes match "{debouncedSearch}".</p>
				<button onclick={() => { searchQuery = ''; debouncedSearch = ''; }} class="text-gold/70 hover:text-gold text-sm mt-2 underline">
					Clear search
				</button>
			{:else if minWeight > 0 || maxWeight < 10}
				<p>No attributes in weight range {minWeight.toFixed(1)} – {maxWeight.toFixed(1)}.</p>
				<button onclick={() => { minWeight = 0; maxWeight = 10; }} class="text-gold/70 hover:text-gold text-sm mt-2 underline">
					Reset filter
				</button>
			{:else}
				<p class="text-slate-400 font-medium mb-2">No attributes in the library yet.</p>
				<p class="text-sm mb-4">Items added here can be imported into any campaign.</p>
				<p class="text-sm">Add them manually or upload a CSV to get started.</p>
				<div class="flex items-center justify-center gap-3 mt-5">
					<button onclick={openAddPanel} class="btn-gold text-sm py-1.5">+ Add Attribute</button>
					<button onclick={openUploadPanel} class="btn-secondary text-sm py-1.5">Upload CSV</button>
				</div>
			{/if}
		</div>
	{:else}
		<!-- Table -->
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<div class="max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-auto">
				<table class="w-full text-sm" aria-label="Attribute library">
					<thead class="sticky top-0 bg-navy-800 border-b border-navy-700 z-10">
						<tr class="text-slate-400">
							<th scope="col" class="px-4 py-3 w-8">
								<input
									type="checkbox"
									checked={allSelected}
									indeterminate={someSelected}
									onchange={toggleSelectAll}
									class="accent-gold"
									aria-label="Select all attributes on this page"
								/>
							</th>
							<th scope="col" class="text-left px-4 py-3 font-medium" aria-sort={sortBy === 'label' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>Label</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden md:table-cell">Description</th>
							<th scope="col" class="text-left px-4 py-3 font-medium w-32" aria-sort={sortBy === 'weight' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>Weight</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden sm:table-cell w-20" aria-sort={sortBy === 'created_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>Created</th>
							<th scope="col" class="px-4 py-3 w-24"><span class="sr-only">Actions</span></th>
						</tr>
					</thead>
					<tbody>
						{#each displayedAttributes() as attr (attr.id)}
							{#if editing[attr.id]}
								{@const e = editing[attr.id]}
								<tr class="border-t border-navy-700 bg-navy-700/50">
									<td class="px-4 py-2">
										<input type="checkbox" checked={selectedIds.has(attr.id)}
											onchange={() => toggleSelect(attr.id)} class="accent-gold"
											aria-label="Select {attr.label}" />
									</td>
									<td class="px-4 py-2">
										<label class="sr-only" for="lib-attr-label-{attr.id}">Label</label>
										<input id="lib-attr-label-{attr.id}" bind:value={e.label} class="input-field w-full text-sm"
											onkeydown={(ev) => handleEditKeydown(ev, attr.id)} />
									</td>
									<td class="px-4 py-2 hidden md:table-cell">
										<label class="sr-only" for="lib-attr-desc-{attr.id}">Description</label>
										<input id="lib-attr-desc-{attr.id}" bind:value={e.description} class="input-field w-full text-sm"
											onkeydown={(ev) => handleEditKeydown(ev, attr.id)} />
									</td>
									<td class="px-4 py-2">
										<label class="sr-only" for="lib-attr-weight-{attr.id}">Weight</label>
										<input id="lib-attr-weight-{attr.id}" type="number" bind:value={e.weight} min="0" step="0.1" class="input-field w-full text-sm"
											onkeydown={(ev) => handleEditKeydown(ev, attr.id)} />
									</td>
									<td class="px-4 py-2 text-slate-500 text-xs hidden sm:table-cell">{formatDate(attr.created_at)}</td>
									<td class="px-4 py-2 text-right space-x-2">
										<button onclick={() => saveEdit(attr.id)} aria-label="Save changes to {attr.label}"
											class="text-gold hover:text-gold-light text-xs">Save</button>
										<button onclick={() => cancelEdit(attr.id)} aria-label="Cancel editing {attr.label}"
											class="text-slate-500 hover:text-slate-300 text-xs">Cancel</button>
									</td>
								</tr>
							{:else}
								<tr class="border-t border-navy-700 hover:bg-navy-700/50 transition-colors">
									<td class="px-4 py-3">
										<input type="checkbox" checked={selectedIds.has(attr.id)}
											onchange={() => toggleSelect(attr.id)} class="accent-gold"
											aria-label="Select {attr.label}" />
									</td>
									<td class="px-4 py-3 text-slate-200 font-medium">{attr.label}</td>
									<td class="px-4 py-3 text-slate-500 max-w-xs hidden md:table-cell" title={attr.description ?? ''}>
										<span class="line-clamp-2">{attr.description ?? '—'}</span>
									</td>
									<td class="px-4 py-3">
										<div class="flex items-center gap-2">
											<div class="w-16 sm:w-20 h-2 bg-navy-700 rounded-full overflow-hidden" aria-hidden="true">
												<div
													class={`h-full ${getWeightColor(attr.weight)} transition-all`}
													style={`width: ${(attr.weight / 10) * 100}%`}
												></div>
											</div>
											<span class="text-slate-300 font-mono text-xs w-7 sm:w-8 text-right">{attr.weight.toFixed(1)}</span>
										</div>
									</td>
									<td class="px-4 py-3 text-slate-500 text-xs hidden sm:table-cell">{formatDate(attr.created_at)}</td>
									<td class="px-4 py-3 text-right space-x-2">
										<button id="lib-attr-edit-{attr.id}" onclick={() => startEdit(attr)} aria-label="Edit {attr.label}"
											class="text-slate-400 hover:text-gold text-xs py-1 px-2 min-h-[44px] inline-flex items-center">Edit</button>
										<button onclick={() => deleteAttribute(attr.id)} aria-label="Delete {attr.label}"
											class="text-red-400/60 hover:text-red-400 text-xs py-1 px-2 min-h-[44px] inline-flex items-center">Delete</button>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Pagination -->
			<Pagination
				total={totalCount}
				{pageSize}
				{currentPage}
				onPageChange={(p) => { currentPage = p; selectedIds = new Set(); }}
				onPageSizeChange={(size) => { pageSize = size; currentPage = 0; selectedIds = new Set(); }}
			/>
		</div>
	{/if}
</div>
