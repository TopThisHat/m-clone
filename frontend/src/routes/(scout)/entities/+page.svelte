<script lang="ts">
	import { libraryEntitiesApi, type LibraryEntity, type LibraryEntityCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import CSVUpload from '$lib/components/CSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	let entities = $state<LibraryEntity[]>([]);
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
	});

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

	async function loadEntities(teamId: string | null, search: string, page: number) {
		loading = true;
		error = '';
		try {
			const resp = await libraryEntitiesApi.list(teamId, {
				limit: pageSize,
				offset: page * pageSize,
				search: search || undefined,
			});
			entities = resp.items;
			totalCount = resp.total;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load library';
		} finally {
			loading = false;
		}
	}

	$effect(() => { loadEntities($scoutTeam, debouncedSearch, currentPage); });

	async function addEntity(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			await libraryEntitiesApi.create({
				label: newLabel.trim(),
				gwm_id: newGwmId.trim() || undefined,
				description: newDesc.trim() || undefined,
				team_id: $scoutTeam ?? undefined,
			});
			newLabel = '';
			newGwmId = '';
			newDesc = '';
			showAddForm = false;
			loadEntities($scoutTeam, debouncedSearch, currentPage);
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
			const next = new Set(selectedIds);
			next.delete(id);
			selectedIds = next;
			loadEntities($scoutTeam, debouncedSearch, currentPage);
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
			selectedIds = new Set();
			loadEntities($scoutTeam, debouncedSearch, currentPage);
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
					<span class="text-slate-200 font-medium">{totalCount}</span>
					{totalCount === 1 ? 'entity' : 'entities'} in library
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

	<!-- Search -->
	<div class="mb-4">
		<input
			bind:value={searchQuery}
			placeholder="Search entities…"
			aria-label="Search entities"
			class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
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
					loadEntities($scoutTeam, debouncedSearch, currentPage);
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
			{#if debouncedSearch}
				<p>No entities match "{debouncedSearch}".</p>
			{:else}
				<p>No entities in the library yet. Add them manually or upload a CSV.</p>
				<p class="text-sm mt-2">Entities added here can be imported into any campaign.</p>
			{/if}
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<table class="w-full text-sm" aria-label="Entity library">
				<thead>
					<tr class="border-b border-navy-700 text-slate-400">
						<th scope="col" class="px-4 py-3 w-8">
							<input type="checkbox"
								checked={selectedIds.size === entities.length && entities.length > 0}
								onchange={toggleSelectAll}
								class="accent-gold"
								aria-label="Select all entities on this page" />
						</th>
						<th scope="col" class="text-left px-4 py-3">Label</th>
						<th scope="col" class="text-left px-4 py-3">GWM ID</th>
						<th scope="col" class="text-left px-4 py-3">Description</th>
						<th scope="col" class="px-4 py-3 w-24"><span class="sr-only">Actions</span></th>
					</tr>
				</thead>
				<tbody>
					{#each entities as entity (entity.id)}
						<tr class="border-t border-navy-700 hover:bg-navy-700/50">
							<td class="px-4 py-3">
								<input type="checkbox" checked={selectedIds.has(entity.id)}
									onchange={() => toggleSelect(entity.id)} class="accent-gold"
									aria-label="Select {entity.label}" />
							</td>
							{#if editingId === entity.id}
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-edit-label-{entity.id}">Label</label>
									<input id="lib-edit-label-{entity.id}" bind:value={editForm.label} class="input-field w-full" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-edit-gwm-{entity.id}">GWM ID</label>
									<input id="lib-edit-gwm-{entity.id}" bind:value={editForm.gwm_id} class="input-field w-full font-mono text-xs" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-edit-desc-{entity.id}">Description</label>
									<input id="lib-edit-desc-{entity.id}" bind:value={editForm.description} class="input-field w-full" />
								</td>
								<td class="px-4 py-2 text-right whitespace-nowrap">
									<button onclick={() => saveEdit(entity)} disabled={editSaving}
										aria-label="Save changes to {entity.label}"
										class="text-gold hover:text-gold-light text-xs mr-2 disabled:opacity-50">
										{editSaving ? '…' : 'Save'}
									</button>
									<button onclick={cancelEdit} aria-label="Cancel editing {entity.label}"
										class="text-slate-500 hover:text-slate-300 text-xs">Cancel</button>
								</td>
							{:else}
								<td class="px-4 py-3 text-slate-200 font-medium">{entity.label}</td>
								<td class="px-4 py-3 text-slate-400 font-mono text-xs">{entity.gwm_id ?? '—'}</td>
								<td class="px-4 py-3 text-slate-500 truncate max-w-xs">{entity.description ?? '—'}</td>
								<td class="px-4 py-3 text-right whitespace-nowrap">
									<button onclick={() => startEdit(entity)} aria-label="Edit {entity.label}"
										class="text-slate-500 hover:text-slate-300 text-xs mr-2">Edit</button>
									<button onclick={() => deleteEntity(entity.id)} aria-label="Delete {entity.label}"
										class="text-red-400/60 hover:text-red-400 text-xs">Delete</button>
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
