<script lang="ts">
	import { libraryEntitiesApi, type LibraryEntity, type LibraryEntityCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import CSVUpload from '$lib/components/CSVUpload.svelte';

	let entities = $state<LibraryEntity[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Add form
	let showAddForm = $state(false);
	let showCSV = $state(false);
	let newLabel = $state('');
	let newGwmId = $state('');
	let newDesc = $state('');
	let adding = $state(false);

	// Inline edit
	let editingId = $state<string | null>(null);
	let editForm = $state({ label: '', gwm_id: '', description: '' });
	let editSaving = $state(false);

	// Bulk select
	let selectedIds = $state<Set<string>>(new Set());
	let bulkDeleting = $state(false);

	async function loadEntities(teamId: string | null) {
		loading = true;
		error = '';
		try {
			entities = await libraryEntitiesApi.list(teamId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load library';
		} finally {
			loading = false;
		}
	}

	$effect(() => { loadEntities($scoutTeam); });

	async function addEntity(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			const entity = await libraryEntitiesApi.create({
				label: newLabel.trim(),
				gwm_id: newGwmId.trim() || undefined,
				description: newDesc.trim() || undefined,
				team_id: $scoutTeam ?? undefined,
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

	function startEdit(entity: LibraryEntity) {
		editingId = entity.id;
		editForm = { label: entity.label, gwm_id: entity.gwm_id ?? '', description: entity.description ?? '' };
	}

	function cancelEdit() { editingId = null; }

	async function saveEdit(entity: LibraryEntity) {
		editSaving = true;
		try {
			const updated = await libraryEntitiesApi.update(entity.id, {
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
		if (!confirm('Delete this entity from the library?')) return;
		try {
			await libraryEntitiesApi.delete(id);
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
		if (!confirm(`Delete ${selectedIds.size} selected entities from the library?`)) return;
		bulkDeleting = true;
		try {
			await Promise.all([...selectedIds].map((id) => libraryEntitiesApi.delete(id)));
			entities = entities.filter((e) => !selectedIds.has(e.id));
			selectedIds = new Set();
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		} finally {
			bulkDeleting = false;
		}
	}

	function libraryBulkCreate(rows: LibraryEntityCreate[]) {
		return libraryEntitiesApi.bulkCreate(rows, $scoutTeam);
	}
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-center justify-between mb-6">
		<div>
			<h1 class="font-serif text-gold text-2xl font-bold">Entity Library</h1>
			<p class="text-slate-500 text-sm mt-1">Add entities here to reuse them across campaigns.</p>
		</div>
	</div>

	<!-- Action bar -->
	<div class="flex items-center justify-between mb-4">
		<div class="flex items-center gap-3">
			{#if !loading}
				<p class="text-sm text-slate-400">
					<span class="text-slate-200 font-medium">{entities.length}</span>
					{entities.length === 1 ? 'entity' : 'entities'} in library
				</p>
			{/if}
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
				onclick={() => { showCSV = !showCSV; showAddForm = false; }}
				class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors"
			>
				Upload CSV
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showCSV = false; }}
				class="text-sm bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg hover:bg-gold-light transition-colors"
			>
				+ Add Entity
			</button>
		</div>
	</div>

	{#if showCSV}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Upload CSV / Excel to Library</h3>
				<button onclick={() => (showCSV = false)} class="text-slate-500 hover:text-slate-300 text-xs">✕ Close</button>
			</div>
			<CSVUpload
				onBulkCreate={libraryBulkCreate}
				onUploaded={async () => {
					showCSV = false;
					entities = await libraryEntitiesApi.list($scoutTeam);
				}}
			/>
		</div>
	{/if}

	{#if showAddForm}
		<form onsubmit={addEntity} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Add Entity to Library</h3>
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

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if entities.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No entities in the library yet. Add them manually or upload a CSV.</p>
			<p class="text-sm mt-2">Entities added here can be imported into any campaign.</p>
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
</div>

<style>
	.input-field {
		@apply bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
		       placeholder-slate-500 focus:outline-none focus:border-gold;
	}
</style>
