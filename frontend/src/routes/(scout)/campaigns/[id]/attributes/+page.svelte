<script lang="ts">
	import { page } from '$app/state';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { libraryAttributesApi, type LibraryAttribute } from '$lib/api/library';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	let campaignId = $derived(page.params.id as string);
	let attributes = $state<Attribute[]>([]);
	let loading = $state(true);
	let error = $state('');
	let totalCount = $state(0);

	// Pagination & search
	const pageSize = 50;
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
			await Promise.all([...selectedIds].map((id) => attributesApi.delete(campaignId, id)));
			selectedIds = new Set();
			load();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
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
		// Reactive re-load when search or page changes (also handles initial load)
		const _s = debouncedSearch;
		const _p = currentPage;
		load();
	});

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
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to add attribute';
		} finally {
			adding = false;
		}
	}

	function startEdit(attr: Attribute) {
		editing[attr.id] = { ...attr, _orig: attr };
	}

	function cancelEdit(id: string) {
		const e = { ...editing };
		delete e[id];
		editing = e;
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
			cancelEdit(id);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to save');
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
			alert(err instanceof Error ? err.message : 'Failed to delete');
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
				onclick={() => { showUpload = !showUpload; showAddForm = false; showImport = false; showLibrary = false; }}
				aria-expanded={showUpload}
				class="{showUpload ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				Upload CSV / Excel
			</button>
			<button
				onclick={openImport}
				aria-expanded={showImport}
				class="{showImport ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				&nearr; Import from Campaign
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showUpload = false; showImport = false; showLibrary = false; }}
				aria-expanded={showAddForm}
				class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-sm hover:bg-gold-light transition-colors"
			>
				+ Add Attribute
			</button>
		</div>
	</div>

	<!-- Search -->
	<div class="mb-4">
		<input
			bind:value={searchQuery}
			placeholder="Search attributes..."
			aria-label="Search attributes"
			class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
	</div>

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
					onclick={() => (showUpload = false)}
					aria-label="Close upload panel"
					class="text-slate-500 hover:text-slate-300 text-xs"
				>Close</button>
			</div>
			<AttributeCSVUpload
				{campaignId}
				onUploaded={async () => {
					showUpload = false;
					load();
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

	<!-- Add form (collapsible) -->
	{#if showAddForm}
		<form onsubmit={addAttribute} aria-label="Add attribute" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Add Attribute</h3>
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
				<button type="button" onclick={() => (showAddForm = false)} class="btn-secondary py-1.5 text-sm">
					Cancel
				</button>
			</div>
		</form>
	{/if}

	{#if error}
		<p class="text-red-400 mb-4" role="alert">{error}</p>
	{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading...</p>
	{:else if attributes.length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No attributes match "{debouncedSearch}".</p>
			{:else}
				<p>No attributes yet. Add them above or import from another campaign.</p>
			{/if}
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<table class="w-full text-sm" aria-label="Attributes">
				<thead>
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
					{#each attributes as attr (attr.id)}
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
									<input id="edit-attr-label-{attr.id}" bind:value={e.label} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-attr-desc-{attr.id}">Description</label>
									<input id="edit-attr-desc-{attr.id}" bind:value={e.description} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-attr-weight-{attr.id}">Weight</label>
									<input id="edit-attr-weight-{attr.id}" type="number" bind:value={e.weight} min="0" step="0.1"
									       class="input-field w-20 text-sm" />
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
								<td class="px-4 py-3 text-slate-300 font-mono text-xs">{attr.weight.toFixed(1)}</td>
								<td class="px-4 py-3 text-right space-x-2">
									<button
										onclick={() => startEdit(attr)}
										aria-label="Edit {attr.label}"
										class="text-slate-400 hover:text-gold text-xs"
									>Edit</button>
									<button
										onclick={() => deleteAttribute(attr.id, attr.label)}
										aria-label="Delete {attr.label}"
										class="text-red-400/60 hover:text-red-400 text-xs"
									>Del</button>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
			<Pagination
				total={totalCount}
				{pageSize}
				{currentPage}
				onPageChange={(p) => { currentPage = p; selectedIds = new Set(); }}
			/>
		</div>
	{/if}
</div>
