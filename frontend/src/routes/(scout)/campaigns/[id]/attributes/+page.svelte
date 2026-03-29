<script lang="ts">
	import { tick } from 'svelte';
	import { page } from '$app/state';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { libraryAttributesApi, type LibraryAttribute } from '$lib/api/library';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let campaignId = $derived(page.params.id as string);
	let attributes = $state<Attribute[]>([]);
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

	$effect(() => {
		const q = searchQuery;
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			debouncedSearch = q;
			currentPage = 0;
		}, 300);
		return () => clearTimeout(debounceTimer);
	});

	// Sorting
	let sortBy = $state<'label' | 'weight' | 'created_at'>('created_at');
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(col: typeof sortBy) {
		if (sortBy === col) { sortDir = sortDir === 'asc' ? 'desc' : 'asc'; }
		else { sortBy = col; sortDir = 'asc'; }
		currentPage = 0;
	}

	// Weight range filter (client-side over current page)
	let minWeight = $state(0);
	let maxWeight = $state(10);

	function displayedAttributes() {
		return attributes.filter(a => a.weight >= minWeight && a.weight <= maxWeight);
	}

	function getWeightColor(weight: number) {
		if (weight < 0.5) return 'bg-slate-700';
		if (weight < 1.5) return 'bg-slate-600';
		if (weight < 2.5) return 'bg-slate-500';
		if (weight < 3.5) return 'bg-slate-400';
		return 'bg-slate-300';
	}

	// CSV export
	let exporting = $state(false);

	// Add form
	let showAddForm = $state(false);
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Inline edit state
	let editing = $state<Record<string, Attribute & { _orig: Attribute }>>({});

	// Upload modal state
	let showUpload = $state(false);

	// Import modal state
	let showImport = $state(false);
	let otherCampaigns = $state<Campaign[]>([]);
	let selectedSourceId = $state('');
	let importing = $state(false);
	let importResult = $state('');

	// Bulk select state
	let selectedIds = $state<Set<string>>(new Set());
	let bulkDeleting = $state(false);

	let allSelected = $derived(attributes.length > 0 && selectedIds.size === attributes.length);
	let someSelected = $derived(selectedIds.size > 0 && selectedIds.size < attributes.length);

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedIds = next;
	}

	function toggleSelectAll() {
		if (selectedIds.size === attributes.length) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(attributes.map((a) => a.id));
		}
	}

	async function bulkDelete() {
		if (!confirm(`Delete ${selectedIds.size} selected attributes?`)) return;
		bulkDeleting = true;
		try {
			await attributesApi.bulkDelete(campaignId, [...selectedIds]);
			selectedIds = new Set();
			load();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		} finally {
			bulkDeleting = false;
		}
	}

	async function load() {
		loading = true;
		try {
			const resp = await attributesApi.list(campaignId, {
				limit: pageSize,
				offset: currentPage * pageSize,
				search: debouncedSearch || undefined,
				sort_by: sortBy,
				order: sortDir,
			});
			attributes = resp.items;
			totalCount = resp.total;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load attributes';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		// Reactive re-load when search, page, or sort changes (also handles initial load)
		const _s = debouncedSearch;
		const _p = currentPage;
		const _sort = sortBy;
		const _dir = sortDir;
		load();
	});

	async function exportCsv() {
		exporting = true;
		try {
			const resp = await attributesApi.list(campaignId, {
				limit: 0,
				search: debouncedSearch || undefined,
				sort_by: sortBy,
				order: sortDir,
			});
			const rows = resp.items;
			const headers = ['Label', 'Description', 'Weight'];
			const csvLines = [
				headers.map(h => `"${h}"`).join(','),
				...rows.map(r => [
					`"${r.label.replace(/"/g, '""')}"`,
					`"${(r.description ?? '').replace(/"/g, '""')}"`,
					r.weight.toFixed(2),
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

	async function openImport() {
		showImport = true;
		showUpload = false;
		showAddForm = false;
		showLibrary = false;
		importResult = '';
		selectedSourceId = '';
		try {
			const all = await campaignsApi.list();
			otherCampaigns = all.filter((c) => c.id !== campaignId);
		} catch {
			otherCampaigns = [];
		}
	}

	async function doImport() {
		if (!selectedSourceId) return;
		importing = true;
		importResult = '';
		try {
			const imported = await attributesApi.importFrom(campaignId, selectedSourceId);
			const insertCount = imported.inserted.length;
			const skipCount = imported.skipped;
			importResult = `Imported ${insertCount} new ${insertCount === 1 ? 'attribute' : 'attributes'}.`;
			if (skipCount > 0) {
				importResult += ` ${skipCount} ${skipCount === 1 ? 'attribute' : 'attributes'} skipped (already exist).`;
			}
			load();
		} catch (err: unknown) {
			importResult = `Error: ${err instanceof Error ? err.message : 'Import failed'}`;
		} finally {
			importing = false;
		}
	}

	// Focus refs for panel management
	let addBtnEl = $state<HTMLButtonElement | undefined>(undefined);
	let uploadBtnEl = $state<HTMLButtonElement | undefined>(undefined);

	async function openAddPanel() {
		showAddForm = true;
		showUpload = false;
		showImport = false;
		showLibrary = false;
		await tick();
		document.getElementById('attr-label')?.focus();
	}

	async function closeAddPanel() {
		showAddForm = false;
		await tick();
		addBtnEl?.focus();
	}

	async function openUploadPanel() {
		showUpload = true;
		showAddForm = false;
		showImport = false;
		showLibrary = false;
		await tick();
		document.getElementById('camp-attr-upload-close')?.focus();
	}

	async function closeUploadPanel() {
		showUpload = false;
		await tick();
		uploadBtnEl?.focus();
	}

	async function addAttribute(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			await attributesApi.create(campaignId, {
				label: newLabel.trim(),
				description: newDesc.trim() || undefined,
				weight: newWeight,
			});
			newLabel = '';
			newDesc = '';
			newWeight = 1.0;
			showAddForm = false;
			load();
			await tick();
			addBtnEl?.focus();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to add attribute';
		} finally {
			adding = false;
		}
	}

	async function startEdit(attr: Attribute) {
		editing[attr.id] = { ...attr, _orig: attr };
		await tick();
		document.getElementById(`edit-attr-label-${attr.id}`)?.focus();
	}

	async function cancelEdit(id: string) {
		const e = { ...editing };
		delete e[id];
		editing = e;
		await tick();
		document.getElementById(`camp-attr-edit-${id}`)?.focus();
	}

	async function saveEdit(id: string) {
		const e = editing[id];
		if (!e) return;
		try {
			const updated = await attributesApi.update(campaignId, id, {
				label: e.label,
				description: e.description ?? undefined,
				weight: e.weight,
			});
			attributes = attributes.map((a) => (a.id === id ? updated : a));
			const next = { ...editing };
			delete next[id];
			editing = next;
			await tick();
			document.getElementById(`camp-attr-edit-${id}`)?.focus();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to save';
		}
	}

	async function deleteAttribute(id: string, label: string) {
		if (!confirm(`Delete "${label}"?`)) return;
		try {
			await attributesApi.delete(campaignId, id);
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
			load();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		}
	}

	// Library import state
	let showLibrary = $state(false);
	let libraryAttrs = $state<LibraryAttribute[]>([]);
	let librarySearch = $state('');
	let librarySelected = $state<Set<string>>(new Set());
	let libraryImporting = $state(false);
	let libraryResult = $state('');

	// Set of labels already in this campaign (for marking already-imported items)
	let existingLabels = $derived(new Set(attributes.map((a) => a.label.toLowerCase())));

	async function openLibraryImport() {
		showLibrary = true;
		showUpload = false;
		showImport = false;
		showAddForm = false;
		librarySearch = '';
		librarySelected = new Set();
		libraryResult = '';
		try {
			const res = await libraryAttributesApi.list(null, { limit: 0 });
			libraryAttrs = res.items;
		} catch {
			libraryAttrs = [];
		}
	}

	let filteredLibrary = $derived(
		librarySearch === ''
			? libraryAttrs
			: libraryAttrs.filter((a) => a.label.toLowerCase().includes(librarySearch.toLowerCase()))
	);

	// Library select all
	let selectableLibrary = $derived(filteredLibrary.filter((a) => !existingLabels.has(a.label.toLowerCase())));
	let allLibrarySelected = $derived(selectableLibrary.length > 0 && selectableLibrary.every((a) => librarySelected.has(a.id)));
	let someLibrarySelected = $derived(librarySelected.size > 0 && !allLibrarySelected);

	function toggleLibrarySelect(id: string) {
		const next = new Set(librarySelected);
		if (next.has(id)) next.delete(id); else next.add(id);
		librarySelected = next;
	}

	function toggleLibrarySelectAll() {
		if (allLibrarySelected) {
			librarySelected = new Set();
		} else {
			librarySelected = new Set(selectableLibrary.map((a) => a.id));
		}
	}

	async function doLibraryImport() {
		if (librarySelected.size === 0) return;
		libraryImporting = true;
		libraryResult = '';
		try {
			const imported = await attributesApi.importFromLibrary(campaignId, [...librarySelected]);
			const count = imported.inserted.length;
			libraryResult = `Imported ${count} ${count === 1 ? 'attribute' : 'attributes'}.${imported.skipped > 0 ? ` ${imported.skipped} skipped.` : ''}`;
			librarySelected = new Set();
			load();
		} catch (err: unknown) {
			libraryResult = `Error: ${err instanceof Error ? err.message : 'Import failed'}`;
		} finally {
			libraryImporting = false;
		}
	}
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-6">
		<div class="flex items-center gap-3">
			<h2 class="font-serif text-gold text-xl font-bold">
				Attributes
				<span class="text-slate-500 font-normal text-base ml-1">({totalCount})</span>
			</h2>
			{#if selectedIds.size > 0}
				<button
					onclick={bulkDelete}
					disabled={bulkDeleting}
					class="btn-danger"
				>
					{bulkDeleting ? 'Deleting...' : `Delete selected (${selectedIds.size})`}
				</button>
			{/if}
		</div>
		<div class="flex gap-2">
			<button
				onclick={openLibraryImport}
				aria-expanded={showLibrary}
				class="{showLibrary ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				Import from Library
			</button>
			<button
				onclick={openImport}
				aria-expanded={showImport}
				class="{showImport ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				&nearr; Import from Campaign
			</button>
			<button
				onclick={exportCsv}
				disabled={exporting}
				class="btn-secondary text-sm py-1.5 disabled:opacity-50"
			>
				{exporting ? 'Exporting…' : 'Export CSV'}
			</button>
			<button
				bind:this={uploadBtnEl}
				onclick={() => (showUpload ? closeUploadPanel() : openUploadPanel())}
				aria-expanded={showUpload}
				class="{showUpload ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				Upload CSV / Excel
			</button>
			<button
				bind:this={addBtnEl}
				onclick={() => (showAddForm ? closeAddPanel() : openAddPanel())}
				aria-expanded={showAddForm}
				class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-sm hover:bg-gold-light transition-colors"
			>
				+ Add Attribute
			</button>
		</div>
	</div>

	<!-- Filter & Sort Bar -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-6 space-y-3">
		<div>
			<input
				bind:value={searchQuery}
				placeholder="Search attributes..."
				aria-label="Search attributes"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
			/>
		</div>
		<div class="flex items-center gap-2 lg:gap-4 flex-wrap text-xs">
			<div class="flex items-center gap-2 flex-wrap">
				<span class="text-xs text-slate-400">Sort:</span>
				{#each [['label', 'Label'], ['weight', 'Weight'], ['created_at', 'Date']] as [col, lbl] (col)}
					<button
						onclick={() => toggleSort(col as typeof sortBy)}
						class={`text-xs px-2 py-1 rounded border transition-colors ${
							sortBy === col
								? 'bg-gold/10 border-gold/40 text-gold'
								: 'border-navy-600 text-slate-400 hover:text-slate-300'
						}`}
						aria-pressed={sortBy === col}
						aria-label="Sort by {lbl}{sortBy === col ? (sortDir === 'asc' ? ', ascending' : ', descending') : ''}"
					>
						{lbl} {sortBy === col ? (sortDir === 'asc' ? '↑' : '↓') : ''}
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

	<!-- Stats line -->
	{#if !loading}
		<p class="text-xs text-slate-400 mb-4" aria-live="polite">
			<span class="text-slate-200 font-semibold">{totalCount}</span> total
			{#if (minWeight > 0 || maxWeight < 10) || debouncedSearch}
				• <span class="text-slate-200 font-semibold">{displayedAttributes().length}</span> shown
			{/if}
			{#if selectedIds.size > 0}
				• <span class="text-gold font-semibold">{selectedIds.size}</span> selected
			{/if}
		</p>
	{/if}

	{#if showLibrary}
		<section aria-label="Import attributes from library" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Import from Library</h3>
				<button onclick={() => { showLibrary = false; libraryResult = ''; }} class="text-slate-500 hover:text-slate-300 text-xs">Close</button>
			</div>
			<input
				bind:value={librarySearch}
				placeholder="Search library attributes..."
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold mb-3"
			/>
			<!-- Select all header -->
			{#if selectableLibrary.length > 0}
				<div class="flex items-center gap-3 px-3 py-2 border-b border-navy-700">
					<input
						type="checkbox"
						checked={allLibrarySelected}
						indeterminate={someLibrarySelected}
						onchange={toggleLibrarySelectAll}
						class="accent-gold"
						aria-label="Select all library attributes"
					/>
					<span class="text-xs text-slate-400">
						Select all ({selectableLibrary.length})
						{#if librarySelected.size > 0}
							<span class="text-gold ml-1">{librarySelected.size} selected</span>
						{/if}
					</span>
				</div>
			{/if}
			<div class="max-h-64 overflow-y-auto border border-navy-700 rounded-lg mb-3">
				{#if filteredLibrary.length === 0}
					<p class="text-slate-500 text-sm text-center py-4">No library attributes found.</p>
				{:else}
					{#each filteredLibrary as la (la.id)}
						{@const alreadyAdded = existingLabels.has(la.label.toLowerCase())}
						<label class="flex items-center gap-3 px-3 py-2 hover:bg-navy-700/50 border-b border-navy-700 last:border-b-0 {alreadyAdded ? 'opacity-50 cursor-default' : 'cursor-pointer'}">
							<input
								type="checkbox"
								checked={librarySelected.has(la.id)}
								onchange={() => toggleLibrarySelect(la.id)}
								disabled={alreadyAdded}
								class="accent-gold"
							/>
							<div class="min-w-0 flex-1">
								<span class="text-sm text-slate-200">{la.label}</span>
								<span class="text-xs text-slate-500 ml-2">w:{la.weight.toFixed(1)}</span>
								{#if alreadyAdded}
									<span class="text-xs text-slate-500 ml-2 bg-navy-700 px-1.5 py-0.5 rounded">already added</span>
								{/if}
								{#if la.description}<p class="text-xs text-slate-500 line-clamp-1">{la.description}</p>{/if}
							</div>
						</label>
					{/each}
				{/if}
			</div>
			<div class="flex items-center gap-3">
				<button
					onclick={doLibraryImport}
					disabled={librarySelected.size === 0 || libraryImporting}
					class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50"
				>
					{libraryImporting ? 'Importing...' : `Import ${librarySelected.size} selected`}
				</button>
				{#if libraryResult}
					<span class="text-sm {libraryResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">{libraryResult}</span>
				{/if}
			</div>
		</section>
	{/if}

	{#if showUpload}
		<section aria-label="Upload attributes via CSV" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Upload Attributes</h3>
				<button
					id="camp-attr-upload-close"
					onclick={closeUploadPanel}
					aria-label="Close upload panel"
					class="text-slate-500 hover:text-slate-300 text-xs"
				>Close</button>
			</div>
			<AttributeCSVUpload
				{campaignId}
				onUploaded={async () => {
					load();
					await closeUploadPanel();
				}}
			/>
		</section>
	{/if}

	{#if showImport}
		<section aria-label="Import attributes from another campaign" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Import Attributes from Another Campaign</h3>
			<p class="text-slate-500 text-sm mb-4">
				Attributes are skipped if an attribute with the same label already exists in this campaign.
			</p>
			<div class="flex gap-3 items-end">
				<div class="flex-1">
					<label for="attr-import-source" class="block text-xs text-slate-400 mb-1">Source Campaign</label>
					<select id="attr-import-source" bind:value={selectedSourceId} class="input-field w-full">
						<option value="">-- Select a campaign --</option>
						{#each otherCampaigns as c (c.id)}
							<option value={c.id}>{c.name}</option>
						{/each}
					</select>
				</div>
				<button
					onclick={doImport}
					disabled={!selectedSourceId || importing}
					class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50"
				>
					{importing ? 'Importing...' : 'Import'}
				</button>
				<button onclick={() => { showImport = false; importResult = ''; }} class="btn-secondary py-1.5 text-sm">
					Cancel
				</button>
			</div>
			{#if importResult}
				<p
					aria-live="polite"
					class="mt-3 text-sm {importResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}"
				>{importResult}</p>
			{/if}
		</section>
	{/if}

	<!-- Add form panel -->
	{#if showAddForm}
		<form onsubmit={addAttribute} aria-label="Add attribute" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Add Attribute</h3>
				<button type="button" onclick={closeAddPanel} class="text-slate-500 hover:text-slate-300 text-xs" aria-label="Close add attribute panel">Close</button>
			</div>
			<div class="grid grid-cols-4 gap-4 mb-4">
				<div class="col-span-2">
					<label for="attr-label" class="block text-xs text-slate-400 mb-1">Label *</label>
					<input id="attr-label" bind:value={newLabel} required placeholder="e.g. Has board experience"
					       class="input-field w-full" />
				</div>
				<div>
					<label for="attr-weight" class="block text-xs text-slate-400 mb-1">Weight</label>
					<input id="attr-weight" type="number" bind:value={newWeight} min="0" max="10" step="0.1"
					       class="input-field w-full" />
				</div>
				<div class="col-span-4">
					<label for="attr-desc" class="block text-xs text-slate-400 mb-1">
						Description <span class="text-slate-500">(fed to LLM prompt)</span>
					</label>
					<input id="attr-desc" bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate"
					       class="input-field w-full" />
				</div>
			</div>
			<div class="flex gap-2">
				<button type="submit" disabled={adding}
				        class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
					{adding ? 'Adding...' : '+ Add Attribute'}
				</button>
				<button type="button" onclick={closeAddPanel} class="btn-secondary py-1.5 text-sm">
					Cancel
				</button>
			</div>
		</form>
	{/if}

	{#if error}
		<p class="text-red-400 mb-4" role="alert">{error}</p>
	{/if}

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
				<p>No attributes in the weight range {minWeight.toFixed(1)}–{maxWeight.toFixed(1)}.</p>
				<button onclick={() => { minWeight = 0; maxWeight = 10; }} class="text-gold/70 hover:text-gold text-sm mt-2 underline">
					Reset weight filter
				</button>
			{:else}
				<p class="text-slate-400 font-medium mb-2">No attributes yet.</p>
				<p class="text-sm">Add them manually or upload a CSV to get started.</p>
				<div class="flex items-center justify-center gap-3 mt-5">
					<button onclick={openAddPanel} class="btn-gold text-sm py-1.5">+ Add Attribute</button>
					<button onclick={openUploadPanel} class="btn-secondary text-sm py-1.5">Upload CSV</button>
				</div>
			{/if}
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<div class="max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-auto">
			<table class="w-full text-sm" aria-label="Attributes">
				<thead class="sticky top-0 bg-navy-800 border-b border-navy-700 z-10">
					<tr class="border-b border-navy-700 text-slate-400">
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
						<th scope="col" class="text-left px-4 py-3">Label</th>
						<th scope="col" class="text-left px-4 py-3">Description</th>
						<th scope="col" class="text-left px-4 py-3 w-20">Weight</th>
						<th scope="col" class="px-4 py-3 w-24">
							<span class="sr-only">Actions</span>
						</th>
					</tr>
				</thead>
				<tbody>
					{#each displayedAttributes() as attr (attr.id)}
						{#if editing[attr.id]}
							{@const e = editing[attr.id]}
							<tr class="border-t border-navy-700 bg-navy-700/50">
								<td class="px-4 py-2">
									<input
										type="checkbox"
										checked={selectedIds.has(attr.id)}
										onchange={() => toggleSelect(attr.id)}
										class="accent-gold"
										aria-label="Select {attr.label}"
									/>
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-attr-label-{attr.id}">Label</label>
									<input id="edit-attr-label-{attr.id}" bind:value={e.label} class="input-field w-full text-sm"
									onkeydown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); saveEdit(attr.id); } else if (ev.key === 'Escape') { cancelEdit(attr.id); } }} />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-attr-desc-{attr.id}">Description</label>
									<input id="edit-attr-desc-{attr.id}" bind:value={e.description} class="input-field w-full text-sm"
									onkeydown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); saveEdit(attr.id); } else if (ev.key === 'Escape') { cancelEdit(attr.id); } }} />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-attr-weight-{attr.id}">Weight</label>
									<input id="edit-attr-weight-{attr.id}" type="number" bind:value={e.weight} min="0" step="0.1"
									       class="input-field w-20 text-sm"
									onkeydown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); saveEdit(attr.id); } else if (ev.key === 'Escape') { cancelEdit(attr.id); } }} />
								</td>
								<td class="px-4 py-2 text-right space-x-2">
									<button
										onclick={() => saveEdit(attr.id)}
										aria-label="Save changes to {attr.label}"
										class="text-green-400 hover:text-green-300 text-xs"
									>Save</button>
									<button
										onclick={() => cancelEdit(attr.id)}
										aria-label="Cancel editing {attr.label}"
										class="text-slate-500 hover:text-slate-400 text-xs"
									>Cancel</button>
								</td>
							</tr>
						{:else}
							<tr class="border-t border-navy-700 hover:bg-navy-700/50">
								<td class="px-4 py-3">
									<input
										type="checkbox"
										checked={selectedIds.has(attr.id)}
										onchange={() => toggleSelect(attr.id)}
										class="accent-gold"
										aria-label="Select {attr.label}"
									/>
								</td>
								<td class="px-4 py-3 text-slate-200 font-medium">{attr.label}</td>
								<td class="px-4 py-3 text-slate-500 max-w-sm" title={attr.description ?? ''}><span class="line-clamp-2">{attr.description ?? '—'}</span></td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<div class="w-16 sm:w-20 h-2 bg-navy-700 rounded-full overflow-hidden" aria-hidden="true">
											<div class={`h-full ${getWeightColor(attr.weight)} transition-all`} style={`width: ${(attr.weight / 10) * 100}%`}></div>
										</div>
										<span class="text-slate-300 font-mono text-xs w-7 sm:w-8 text-right">{attr.weight.toFixed(1)}</span>
									</div>
								</td>
								<td class="px-4 py-3 text-right space-x-2">
									<button
										id="camp-attr-edit-{attr.id}"
										onclick={() => startEdit(attr)}
										aria-label="Edit {attr.label}"
										class="text-slate-400 hover:text-gold text-xs py-1 px-2 min-h-[44px] inline-flex items-center"
									>Edit</button>
									<button
										onclick={() => deleteAttribute(attr.id, attr.label)}
										aria-label="Delete {attr.label}"
										class="text-red-400/60 hover:text-red-400 text-xs py-1 px-2 min-h-[44px] inline-flex items-center"
									>Delete</button>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
			</div>
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
