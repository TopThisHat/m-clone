<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import CSVUpload from '$lib/components/CSVUpload.svelte';

	let campaignId = $derived($page.params.id as string);
	let entities = $state<Entity[]>([]);
	let loading = $state(true);
	let error = $state('');
	let showCSV = $state(false);
	let showAddForm = $state(false);
	let showImport = $state(false);

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

	async function load() {
		try {
			entities = await entitiesApi.list(campaignId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load entities';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function openImport() {
		showImport = true;
		showCSV = false;
		showAddForm = false;
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
			const imported = await entitiesApi.importFrom(campaignId, selectedSourceId);
			entities = await entitiesApi.list(campaignId);
			importResult = `Imported ${imported.length} new ${imported.length === 1 ? 'entity' : 'entities'}.`;
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
			const entity = await entitiesApi.create(campaignId, {
				label: newLabel.trim(),
				gwm_id: newGwmId.trim() || undefined,
				description: newDesc.trim() || undefined,
			});
			entities = [...entities, entity];
			newLabel = '';
			newGwmId = '';
			newDesc = '';
			showAddForm = false;
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
			entities = entities.filter((e) => e.id !== id);
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
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
			alert(err instanceof Error ? err.message : 'Failed to save');
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
			entities = entities.filter((e) => !selectedIds.has(e.id));
			selectedIds = new Set();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		} finally {
			bulkDeleting = false;
		}
	}

	let allSelected = $derived(entities.length > 0 && selectedIds.size === entities.length);
	let someSelected = $derived(selectedIds.size > 0 && selectedIds.size < entities.length);
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-6">
		<div class="flex items-center gap-3">
			<h2 class="font-serif text-gold text-xl font-bold">
				Entities
				<span class="text-slate-500 font-normal text-base ml-1">({entities.length})</span>
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
				onclick={openImport}
				aria-expanded={showImport}
				class="btn-secondary text-sm py-1.5"
			>
				↗ Import from Campaign
			</button>
			<button
				onclick={() => { showCSV = !showCSV; showAddForm = false; showImport = false; }}
				aria-expanded={showCSV}
				class="btn-secondary text-sm py-1.5"
			>
				<span aria-hidden="true">📄</span> Upload CSV
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showCSV = false; showImport = false; }}
				aria-expanded={showAddForm}
				class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-sm hover:bg-gold-light transition-colors"
			>
				+ Add Entity
			</button>
		</div>
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
					<input id="new-gwm" bind:value={newGwmId} placeholder="Optional identifier"
					       class="input-field w-full" />
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

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading…</p>
	{:else if entities.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No entities yet. Add them manually, upload a CSV, or import from another campaign.</p>
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
								aria-label="Select all entities"
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
								<td class="px-4 py-3 text-slate-500 truncate max-w-xs">{entity.description ?? '—'}</td>
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
		</div>
	{/if}
</div>
