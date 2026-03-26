<script lang="ts">
	import { page } from '$app/state';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { libraryEntitiesApi, type LibraryEntity } from '$lib/api/library';
	import CSVUpload from '$lib/components/CSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let campaignId = $derived(page.params.id as string);
	let entities = $state<Entity[]>([]);
	let loading = $state(true);
	let error = $state('');
	let actionError = $state('');
	let totalCount = $state(0);
	let showCSV = $state(false);
	let showAddForm = $state(false);
	let showImport = $state(false);

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

	// Add form state
	let newLabel = $state('');
	let newGwmId = $state('');
	let newDesc = $state('');
	let adding = $state(false);

	// Import modal state
	let otherCampaigns = $state<Campaign[]>([]);
	let selectedSourceId = $state('');
	let importing = $state(false);
	let importResult = $state('');

	// Inline edit state
	let editingId = $state<string | null>(null);
	let editForm = $state({ label: '', gwm_id: '', description: '' });
	let editSaving = $state(false);

	// Bulk select state
	let selectedIds = $state<Set<string>>(new Set());
	let bulkDeleting = $state(false);

	// Library import state
	let showLibrary = $state(false);
	let libraryEntities = $state<LibraryEntity[]>([]);
	let librarySearch = $state('');
	let librarySelected = $state<Set<string>>(new Set());
	let libraryImporting = $state(false);
	let libraryResult = $state('');

	async function load() {
		loading = true;
		try {
			const resp = await entitiesApi.list(campaignId, {
				limit: pageSize,
				offset: currentPage * pageSize,
				search: debouncedSearch || undefined,
			});
			entities = resp.items;
			totalCount = resp.total;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load entities';
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
		showCSV = false;
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
			const result = await entitiesApi.importFrom(campaignId, selectedSourceId);
			const insertCount = result.inserted.length;
			const skipCount = result.skipped;
			importResult = `Imported ${insertCount} new ${insertCount === 1 ? 'entity' : 'entities'}.`;
			if (skipCount > 0) {
				importResult += ` ${skipCount} ${skipCount === 1 ? 'entity' : 'entities'} skipped (already exist).`;
			}
			load();
		} catch (err: unknown) {
			importResult = `Error: ${err instanceof Error ? err.message : 'Import failed'}`;
		} finally {
			importing = false;
		}
	}

	async function addEntity(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			await entitiesApi.create(campaignId, {
				label: newLabel.trim(),
				gwm_id: newGwmId.trim() || undefined,
				description: newDesc.trim() || undefined,
			});
			newLabel = '';
			newGwmId = '';
			newDesc = '';
			showAddForm = false;
			load();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to add entity';
		} finally {
			adding = false;
		}
	}

	async function deleteEntity(id: string, label: string) {
		if (!confirm(`Delete "${label}"?`)) return;
		try {
			await entitiesApi.delete(campaignId, id);
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
			load();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		}
	}

	function startEdit(entity: Entity) {
		editingId = entity.id;
		editForm = { label: entity.label, gwm_id: entity.gwm_id ?? '', description: entity.description ?? '' };
	}

	function cancelEdit() {
		editingId = null;
	}

	async function saveEdit(entity: Entity) {
		editSaving = true;
		try {
			const updated = await entitiesApi.update(campaignId, entity.id, {
				label: editForm.label,
				gwm_id: editForm.gwm_id || undefined,
				description: editForm.description || undefined,
			});
			entities = entities.map((e) => (e.id === entity.id ? updated : e));
			editingId = null;
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to save';
		} finally {
			editSaving = false;
		}
	}

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedIds = next;
	}

	function toggleSelectAll() {
		if (selectedIds.size === entities.length) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(entities.map((e) => e.id));
		}
	}

	async function bulkDelete() {
		if (!confirm(`Delete ${selectedIds.size} selected entities?`)) return;
		bulkDeleting = true;
		try {
			await Promise.all([...selectedIds].map((id) => entitiesApi.delete(campaignId, id)));
			selectedIds = new Set();
			load();
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		} finally {
			bulkDeleting = false;
		}
	}

	let allSelected = $derived(entities.length > 0 && selectedIds.size === entities.length);
	let someSelected = $derived(selectedIds.size > 0 && selectedIds.size < entities.length);

	async function openLibraryImport() {
		showLibrary = true;
		showCSV = false;
		showAddForm = false;
		showImport = false;
		librarySearch = '';
		librarySelected = new Set();
		libraryResult = '';
		try {
			const res = await libraryEntitiesApi.list(null, { limit: 0 });
			libraryEntities = res.items;
		} catch {
			libraryEntities = [];
		}
	}

	// Set of labels already in this campaign (for marking already-imported items)
	let existingLabels = $derived(new Set(entities.map((e) => e.label.toLowerCase())));

	let filteredLibrary = $derived(
		librarySearch === ''
			? libraryEntities
			: libraryEntities.filter((e) => e.label.toLowerCase().includes(librarySearch.toLowerCase()))
	);

	// Library select all
	let selectableLibrary = $derived(filteredLibrary.filter((e) => !existingLabels.has(e.label.toLowerCase())));
	let allLibrarySelected = $derived(selectableLibrary.length > 0 && selectableLibrary.every((e) => librarySelected.has(e.id)));
	let someLibrarySelected = $derived(librarySelected.size > 0 && !allLibrarySelected);

	function toggleLibrarySelectAll() {
		if (allLibrarySelected) {
			librarySelected = new Set();
		} else {
			librarySelected = new Set(selectableLibrary.map((e) => e.id));
		}
	}

	function toggleLibrarySelect(id: string) {
		const next = new Set(librarySelected);
		if (next.has(id)) next.delete(id); else next.add(id);
		librarySelected = next;
	}

	async function doLibraryImport() {
		if (librarySelected.size === 0) return;
		libraryImporting = true;
		libraryResult = '';
		try {
			const result = await entitiesApi.importFromLibrary(campaignId, [...librarySelected]);
			const insertCount = result.inserted.length;
			const skipCount = result.skipped;
			libraryResult = `Imported ${insertCount} ${insertCount === 1 ? 'entity' : 'entities'}.`;
			if (skipCount > 0) {
				libraryResult += ` ${skipCount} skipped (already exist).`;
			}
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
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-6">
		<div class="flex items-center gap-3">
			<h2 class="font-serif text-gold text-xl font-bold">
				Entities
				<span class="text-slate-500 font-normal text-base ml-1">({totalCount})</span>
			</h2>
			{#if selectedIds.size > 0}
				<button
					onclick={bulkDelete}
					disabled={bulkDeleting}
					class="btn-danger"
				>
					{bulkDeleting ? 'Deleting…' : `Delete selected (${selectedIds.size})`}
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
				onclick={() => { showCSV = !showCSV; showAddForm = false; showImport = false; showLibrary = false; }}
				aria-expanded={showCSV}
				class="{showCSV ? 'bg-gold/10 border border-gold/40 text-gold font-medium px-3 py-1.5 rounded-lg text-sm' : 'btn-secondary text-sm py-1.5'}"
			>
				Upload CSV
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showCSV = false; showImport = false; showLibrary = false; }}
				aria-expanded={showAddForm}
				class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-sm hover:bg-gold-light transition-colors"
			>
				+ Add Entity
			</button>
		</div>
	</div>

	<!-- Search -->
	<div class="mb-4">
		<input
			bind:value={searchQuery}
			placeholder="Search entities…"
			aria-label="Search entities"
			class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
	</div>

	{#if showImport}
		<section aria-label="Import entities from another campaign" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Import Entities from Another Campaign</h3>
			<p class="text-slate-500 text-sm mb-4">
				Entities with gwm_id will be skipped if the same gwm_id already exists.
				Entities without gwm_id will be skipped if the label already exists.
			</p>
			<div class="flex gap-3 items-end">
				<div class="flex-1">
					<label for="import-source" class="block text-xs text-slate-400 mb-1">Source Campaign</label>
					<select id="import-source" bind:value={selectedSourceId} class="input-field w-full">
						<option value="">— Select a campaign —</option>
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
					{importing ? 'Importing…' : 'Import'}
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

	{#if showLibrary}
		<section aria-label="Import entities from library" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Import from Library</h3>
				<button onclick={() => { showLibrary = false; libraryResult = ''; }} class="text-slate-500 hover:text-slate-300 text-xs">Close</button>
			</div>
			<input
				bind:value={librarySearch}
				placeholder="Search library entities..."
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
						aria-label="Select all library entities"
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
					<p class="text-slate-500 text-sm text-center py-4">No library entities found.</p>
				{:else}
					{#each filteredLibrary as le (le.id)}
						{@const alreadyAdded = existingLabels.has(le.label.toLowerCase())}
						<label class="flex items-center gap-3 px-3 py-2 hover:bg-navy-700/50 border-b border-navy-700 last:border-b-0 {alreadyAdded ? 'opacity-50 cursor-default' : 'cursor-pointer'}">
							<input
								type="checkbox"
								checked={librarySelected.has(le.id)}
								onchange={() => toggleLibrarySelect(le.id)}
								disabled={alreadyAdded}
								class="accent-gold"
							/>
							<div class="min-w-0 flex-1">
								<span class="text-sm text-slate-200">{le.label}</span>
								{#if le.gwm_id}<span class="text-xs text-slate-500 ml-2 font-mono">{le.gwm_id}</span>{/if}
								{#if alreadyAdded}
									<span class="text-xs text-slate-500 ml-2 bg-navy-700 px-1.5 py-0.5 rounded">already added</span>
								{/if}
								{#if le.description}<p class="text-xs text-slate-500 line-clamp-1">{le.description}</p>{/if}
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
					{libraryImporting ? 'Importing…' : `Import ${librarySelected.size} selected`}
				</button>
				{#if libraryResult}
					<span class="text-sm {libraryResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">{libraryResult}</span>
				{/if}
			</div>
		</section>
	{/if}

	{#if showCSV}
		<section aria-label="Upload entities via CSV" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Upload CSV</h3>
			<CSVUpload
				{campaignId}
				onUploaded={() => { load(); showCSV = false; }}
			/>
		</section>
	{/if}

	{#if showAddForm}
		<form onsubmit={addEntity} aria-label="Add entity" class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Add Entity</h3>
			<div class="grid grid-cols-3 gap-4 mb-4">
				<div>
					<label for="new-label" class="block text-xs text-slate-400 mb-1">Label *</label>
					<input id="new-label" bind:value={newLabel} required placeholder="Name or entity label"
					       class="input-field w-full" />
				</div>
				<div>
					<label for="new-gwm" class="block text-xs text-slate-400 mb-1">GWM ID</label>
					<input id="new-gwm" bind:value={newGwmId} placeholder="e.g. GWM-12345"
					       class="input-field w-full font-mono" />
				</div>
				<div>
					<label for="new-desc" class="block text-xs text-slate-400 mb-1">Description</label>
					<input id="new-desc" bind:value={newDesc} placeholder="Optional description"
					       class="input-field w-full" />
				</div>
			</div>
			<div class="flex gap-2">
				<button type="submit" disabled={adding}
				        class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
					{adding ? 'Adding…' : 'Add'}
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

	{#if actionError}
	<div class="bg-red-950 border border-red-700 rounded-xl px-4 py-3 text-red-300 text-sm mb-4 flex items-center justify-between" role="alert">
		<span>{actionError}</span>
		<button onclick={() => (actionError = '')} class="text-red-400 hover:text-red-200 min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label="Dismiss error">✕</button>
	</div>
{/if}

{#if loading}
		<LoadingSpinner />
	{:else if entities.length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No entities match "{debouncedSearch}".</p>
			{:else}
				<p>No entities yet. Add them manually, upload a CSV, or import from another campaign.</p>
			{/if}
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<table class="w-full text-sm" aria-label="Entities">
				<thead>
					<tr class="border-b border-navy-700 text-slate-400">
						<th scope="col" class="px-4 py-3 w-8">
							<input
								type="checkbox"
								checked={allSelected}
								indeterminate={someSelected}
								onchange={toggleSelectAll}
								class="accent-gold"
								aria-label="Select all entities on this page"
							/>
						</th>
						<th scope="col" class="text-left px-4 py-3">Label</th>
						<th scope="col" class="text-left px-4 py-3">GWM ID</th>
						<th scope="col" class="text-left px-4 py-3">Description</th>
						<th scope="col" class="px-4 py-3 w-24">
							<span class="sr-only">Actions</span>
						</th>
					</tr>
				</thead>
				<tbody>
					{#each entities as entity (entity.id)}
						<tr class="border-t border-navy-700 hover:bg-navy-700/50">
							<td class="px-4 py-3">
								<input
									type="checkbox"
									checked={selectedIds.has(entity.id)}
									onchange={() => toggleSelect(entity.id)}
									class="accent-gold"
									aria-label="Select {entity.label}"
								/>
							</td>
							{#if editingId === entity.id}
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-label-{entity.id}">Label</label>
									<input id="edit-label-{entity.id}" bind:value={editForm.label} class="input-field w-full" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-gwm-{entity.id}">GWM ID</label>
									<input id="edit-gwm-{entity.id}" bind:value={editForm.gwm_id} class="input-field w-full font-mono text-xs" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="edit-desc-{entity.id}">Description</label>
									<input id="edit-desc-{entity.id}" bind:value={editForm.description} class="input-field w-full" />
								</td>
								<td class="px-4 py-2 text-right whitespace-nowrap">
									<button
										onclick={() => saveEdit(entity)}
										disabled={editSaving}
										aria-label="Save changes to {entity.label}"
										class="text-gold hover:text-gold-light text-xs mr-2 disabled:opacity-50"
									>
										{editSaving ? '…' : 'Save'}
									</button>
									<button
										onclick={cancelEdit}
										aria-label="Cancel editing {entity.label}"
										class="text-slate-500 hover:text-slate-300 text-xs"
									>
										Cancel
									</button>
								</td>
							{:else}
								<td class="px-4 py-3 text-slate-200 font-medium">{entity.label}</td>
								<td class="px-4 py-3 text-slate-400 font-mono text-xs">{entity.gwm_id ?? '—'}</td>
								<td class="px-4 py-3 text-slate-500 max-w-sm" title={entity.description ?? ''}><span class="line-clamp-2">{entity.description ?? '—'}</span></td>
								<td class="px-4 py-3 text-right whitespace-nowrap">
									<button
										onclick={() => startEdit(entity)}
										aria-label="Edit {entity.label}"
										class="text-slate-500 hover:text-slate-300 transition-colors text-xs mr-2"
									>
										Edit
									</button>
									<button
										onclick={() => deleteEntity(entity.id, entity.label)}
										aria-label="Delete {entity.label}"
										class="text-red-400/60 hover:text-red-400 transition-colors text-xs"
									>
										Delete
									</button>
								</td>
							{/if}
						</tr>
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
