<script lang="ts">
	import { onMount } from 'svelte';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { entitiesApi, type Entity } from '$lib/api/entities';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import CSVUpload from '$lib/components/CSVUpload.svelte';

	let campaigns = $state<Campaign[]>([]);
	let selectedCampaignId = $state<string | null>(null);
	let entities = $state<Entity[]>([]);
	let loadingCampaigns = $state(true);
	let loadingEntities = $state(false);
	let error = $state('');

	// Add form
	let showAddForm = $state(false);
	let showCSV = $state(false);
	let showImport = $state(false);
	let newLabel = $state('');
	let newGwmId = $state('');
	let newDesc = $state('');
	let adding = $state(false);

	// Import
	let selectedSourceId = $state('');
	let importing = $state(false);
	let importResult = $state('');

	// Inline edit
	let editingId = $state<string | null>(null);
	let editForm = $state({ label: '', gwm_id: '', description: '' });
	let editSaving = $state(false);

	// Bulk select
	let selectedIds = $state<Set<string>>(new Set());
	let bulkDeleting = $state(false);

	async function loadCampaigns(teamId: string | null) {
		loadingCampaigns = true;
		try {
			campaigns = await campaignsApi.list(teamId);
			// Re-validate selected campaign is still in list
			if (selectedCampaignId && !campaigns.some((c) => c.id === selectedCampaignId)) {
				selectedCampaignId = null;
				entities = [];
			}
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load campaigns';
		} finally {
			loadingCampaigns = false;
		}
	}

	$effect(() => { loadCampaigns($scoutTeam); });

	async function selectCampaign(id: string) {
		selectedCampaignId = id;
		entities = [];
		error = '';
		showAddForm = false;
		showCSV = false;
		showImport = false;
		selectedIds = new Set();
		loadingEntities = true;
		try {
			entities = await entitiesApi.list(id);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load entities';
		} finally {
			loadingEntities = false;
		}
	}

	async function addEntity(e: Event) {
		e.preventDefault();
		if (!selectedCampaignId || !newLabel.trim()) return;
		adding = true;
		try {
			const entity = await entitiesApi.create(selectedCampaignId, {
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

	async function openImport() {
		showImport = true;
		showCSV = false;
		showAddForm = false;
		importResult = '';
		selectedSourceId = '';
	}

	async function doImport() {
		if (!selectedCampaignId || !selectedSourceId) return;
		importing = true;
		importResult = '';
		try {
			const imported = await entitiesApi.importFrom(selectedCampaignId, selectedSourceId);
			entities = await entitiesApi.list(selectedCampaignId);
			importResult = `Imported ${imported.length} new ${imported.length === 1 ? 'entity' : 'entities'}.`;
		} catch (err: unknown) {
			importResult = `Error: ${err instanceof Error ? err.message : 'Import failed'}`;
		} finally {
			importing = false;
		}
	}

	function startEdit(entity: Entity) {
		editingId = entity.id;
		editForm = { label: entity.label, gwm_id: entity.gwm_id ?? '', description: entity.description ?? '' };
	}

	function cancelEdit() { editingId = null; }

	async function saveEdit(entity: Entity) {
		if (!selectedCampaignId) return;
		editSaving = true;
		try {
			const updated = await entitiesApi.update(selectedCampaignId, entity.id, {
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

	async function deleteEntity(id: string) {
		if (!selectedCampaignId || !confirm('Delete this entity?')) return;
		try {
			await entitiesApi.delete(selectedCampaignId, id);
			entities = entities.filter((e) => e.id !== id);
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		}
	}

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedIds = next;
	}

	function toggleSelectAll() {
		selectedIds = selectedIds.size === entities.length
			? new Set()
			: new Set(entities.map((e) => e.id));
	}

	async function bulkDelete() {
		if (!selectedCampaignId || !confirm(`Delete ${selectedIds.size} selected entities?`)) return;
		bulkDeleting = true;
		try {
			await Promise.all([...selectedIds].map((id) => entitiesApi.delete(selectedCampaignId!, id)));
			entities = entities.filter((e) => !selectedIds.has(e.id));
			selectedIds = new Set();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		} finally {
			bulkDeleting = false;
		}
	}

	let otherCampaigns = $derived(campaigns.filter((c) => c.id !== selectedCampaignId));
	let selectedCampaign = $derived(campaigns.find((c) => c.id === selectedCampaignId) ?? null);
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-center justify-between mb-6">
		<h1 class="font-serif text-gold text-2xl font-bold">Entities</h1>
	</div>

	<!-- Campaign picker -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-6">
		<label class="block text-xs text-slate-400 mb-2">Campaign</label>
		{#if loadingCampaigns}
			<p class="text-slate-500 text-sm">Loading campaigns…</p>
		{:else if campaigns.length === 0}
			<p class="text-slate-500 text-sm">No campaigns yet. <a href="/campaigns/new" class="text-gold hover:underline">Create one first →</a></p>
		{:else}
			<div class="flex flex-wrap gap-2">
				{#each campaigns as c (c.id)}
					<button
						onclick={() => selectCampaign(c.id)}
						class="text-sm px-3 py-1.5 rounded-lg border transition-colors
							{selectedCampaignId === c.id
								? 'bg-gold text-navy border-gold font-semibold'
								: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
					>
						{c.name}
					</button>
				{/each}
			</div>
		{/if}
	</div>

	{#if selectedCampaignId}
		<!-- Action bar -->
		<div class="flex items-center justify-between mb-4">
			<div class="flex items-center gap-3">
				<p class="text-sm text-slate-400">
					<span class="text-slate-200 font-medium">{entities.length}</span> {entities.length === 1 ? 'entity' : 'entities'} in
					<a href="/campaigns/{selectedCampaignId}" class="text-gold hover:underline">{selectedCampaign?.name}</a>
				</p>
				{#if selectedIds.size > 0}
					<button
						onclick={bulkDelete}
						disabled={bulkDeleting}
						class="text-xs bg-red-950 border border-red-800 text-red-400 px-3 py-1 rounded-lg hover:bg-red-900 disabled:opacity-50"
					>
						{bulkDeleting ? 'Deleting…' : `Delete selected (${selectedIds.size})`}
					</button>
				{/if}
			</div>
			<div class="flex gap-2">
				<button
					onclick={openImport}
					class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors"
				>
					↗ Import from Campaign
				</button>
				<button
					onclick={() => { showCSV = !showCSV; showAddForm = false; showImport = false; }}
					class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors"
				>
					📄 Upload CSV
				</button>
				<button
					onclick={() => { showAddForm = !showAddForm; showCSV = false; showImport = false; }}
					class="text-sm bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg hover:bg-gold-light transition-colors"
				>
					+ Add Entity
				</button>
			</div>
		</div>

		{#if showImport}
			<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
				<h3 class="font-medium text-slate-200 mb-3">Import Entities from Another Campaign</h3>
				<p class="text-slate-500 text-sm mb-4">Entities with gwm_id will be skipped if the same gwm_id already exists. Entities without gwm_id will be skipped if the label already exists.</p>
				<div class="flex gap-3 items-end">
					<div class="flex-1">
						<label class="block text-xs text-slate-400 mb-1">Source Campaign</label>
						<select bind:value={selectedSourceId} class="input-field w-full">
							<option value="">— Select a campaign —</option>
							{#each otherCampaigns as c (c.id)}
								<option value={c.id}>{c.name}</option>
							{/each}
						</select>
					</div>
					<button onclick={doImport} disabled={!selectedSourceId || importing}
						class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
						{importing ? 'Importing…' : 'Import'}
					</button>
					<button onclick={() => { showImport = false; importResult = ''; }}
						class="bg-navy-700 text-slate-300 px-4 py-1.5 rounded-lg text-sm border border-navy-600">
						Cancel
					</button>
				</div>
				{#if importResult}
					<p class="mt-3 text-sm {importResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">{importResult}</p>
				{/if}
			</div>
		{/if}

		{#if showCSV}
			<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
				<div class="flex items-center justify-between mb-4">
					<h3 class="font-medium text-slate-200">Upload CSV / Excel</h3>
					<button onclick={() => (showCSV = false)} class="text-slate-500 hover:text-slate-300 text-xs">✕ Close</button>
				</div>
				<CSVUpload
					campaignId={selectedCampaignId}
					onUploaded={async () => {
						showCSV = false;
						entities = await entitiesApi.list(selectedCampaignId!);
					}}
				/>
			</div>
		{/if}

		{#if showAddForm}
			<form onsubmit={addEntity} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
				<h3 class="font-medium text-slate-200 mb-4">Add Entity</h3>
				<div class="grid grid-cols-3 gap-4 mb-4">
					<div>
						<label class="block text-xs text-slate-400 mb-1">Label *</label>
						<input bind:value={newLabel} required placeholder="Name or entity label" class="input-field w-full" />
					</div>
					<div>
						<label class="block text-xs text-slate-400 mb-1">GWM ID</label>
						<input bind:value={newGwmId} placeholder="Optional identifier" class="input-field w-full" />
					</div>
					<div>
						<label class="block text-xs text-slate-400 mb-1">Description</label>
						<input bind:value={newDesc} placeholder="Optional description" class="input-field w-full" />
					</div>
				</div>
				<div class="flex gap-2">
					<button type="submit" disabled={adding}
						class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
						{adding ? 'Adding…' : 'Add'}
					</button>
					<button type="button" onclick={() => (showAddForm = false)}
						class="bg-navy-700 text-slate-300 px-4 py-1.5 rounded-lg text-sm border border-navy-600">
						Cancel
					</button>
				</div>
			</form>
		{/if}

		{#if error}
			<p class="text-red-400 mb-4 text-sm">{error}</p>
		{/if}

		{#if loadingEntities}
			<p class="text-slate-500">Loading…</p>
		{:else if entities.length === 0}
			<div class="text-center py-12 text-slate-500">
				<p>No entities yet. Add them manually, upload a CSV, or import from another campaign.</p>
			</div>
		{:else}
			<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-navy-700 text-slate-400">
							<th class="px-4 py-3 w-8">
								<input type="checkbox"
									checked={selectedIds.size === entities.length && entities.length > 0}
									onchange={toggleSelectAll}
									class="accent-gold" />
							</th>
							<th class="text-left px-4 py-3">Label</th>
							<th class="text-left px-4 py-3">GWM ID</th>
							<th class="text-left px-4 py-3">Description</th>
							<th class="px-4 py-3 w-24"></th>
						</tr>
					</thead>
					<tbody>
						{#each entities as entity (entity.id)}
							<tr class="border-t border-navy-700 hover:bg-navy-700/50">
								<td class="px-4 py-3">
									<input type="checkbox" checked={selectedIds.has(entity.id)}
										onchange={() => toggleSelect(entity.id)} class="accent-gold" />
								</td>
								{#if editingId === entity.id}
									<td class="px-4 py-2"><input bind:value={editForm.label} class="input-field w-full" /></td>
									<td class="px-4 py-2"><input bind:value={editForm.gwm_id} class="input-field w-full font-mono text-xs" /></td>
									<td class="px-4 py-2"><input bind:value={editForm.description} class="input-field w-full" /></td>
									<td class="px-4 py-2 text-right whitespace-nowrap">
										<button onclick={() => saveEdit(entity)} disabled={editSaving}
											class="text-gold hover:text-gold-light text-xs mr-2 disabled:opacity-50">
											{editSaving ? '…' : 'Save'}
										</button>
										<button onclick={cancelEdit} class="text-slate-500 hover:text-slate-300 text-xs">Cancel</button>
									</td>
								{:else}
									<td class="px-4 py-3 text-slate-200 font-medium">{entity.label}</td>
									<td class="px-4 py-3 text-slate-400 font-mono text-xs">{entity.gwm_id ?? '—'}</td>
									<td class="px-4 py-3 text-slate-500 truncate max-w-xs">{entity.description ?? '—'}</td>
									<td class="px-4 py-3 text-right whitespace-nowrap">
										<button onclick={() => startEdit(entity)} class="text-slate-500 hover:text-slate-300 text-xs mr-2">Edit</button>
										<button onclick={() => deleteEntity(entity.id)} class="text-red-400/60 hover:text-red-400 text-xs">Delete</button>
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>

<style>
	.input-field {
		@apply bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
		       placeholder-slate-500 focus:outline-none focus:border-gold;
	}
</style>
