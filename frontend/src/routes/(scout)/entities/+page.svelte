<script lang="ts">
	import { libraryEntitiesApi, type LibraryEntity, type LibraryEntityCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import CSVUpload from '$lib/components/CSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let entities = $state<LibraryEntity[]>([]);
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
	let sortBy = $state<'label' | 'gwm_id' | 'created_at'>('created_at');
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(col: typeof sortBy) {
		if (sortBy === col) { sortDir = sortDir === 'asc' ? 'desc' : 'asc'; }
		else { sortBy = col; sortDir = 'asc'; }
		currentPage = 0;
	}

	// Filtering
	let gwmIdFilter = $state<'all' | 'has' | 'missing'>('all');

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

	// Export
	let exporting = $state(false);

	async function loadEntities(teamId: string | null, search: string, page: number, size: number, sort: string = 'created_at', dir: 'asc' | 'desc' = 'asc') {
		loading = true;
		error = '';
		try {
			const resp = await libraryEntitiesApi.list(teamId, {
				limit: size,
				offset: page * size,
				search: search || undefined,
				sort_by: sort,
				sort_dir: dir,
			});
			entities = resp.items;
			totalCount = resp.total;
		} catch (err: unknown) {
			entities = [];
			totalCount = 0;
			error = err instanceof Error ? err.message : 'Failed to load library';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		// Read all reactive deps in the effect body so Svelte tracks them
		const team = $scoutTeam;
		const search = debouncedSearch;
		const page = currentPage;
		const size = pageSize;
		const sort = sortBy;
		const dir = sortDir;
		loadEntities(team, search, page, size, sort, dir);
	});

	function displayedEntities() {
		if (gwmIdFilter === 'has') return entities.filter(e => !!e.gwm_id);
		if (gwmIdFilter === 'missing') return entities.filter(e => !e.gwm_id);
		return entities;
	}

	function displayedCount() {
		if (gwmIdFilter === 'all') return totalCount;
		const displayed = displayedEntities();
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
			loadEntities($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
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

	function cancelEdit() {
		editingId = null;
	}

	function handleEditKeydown(e: KeyboardEvent, entity: LibraryEntity) {
		if (e.key === 'Enter') {
			e.preventDefault();
			saveEdit(entity);
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancelEdit();
		}
	}

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
			actionError = err instanceof Error ? err.message : 'Failed to save';
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
			loadEntities($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
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
		selectedIds = selectedIds.size === displayedEntities().length
			? new Set()
			: new Set(displayedEntities().map((e) => e.id));
	}

	async function bulkDelete() {
		if (!confirm(`Delete ${selectedIds.size} selected entities from the library?`)) return;
		bulkDeleting = true;
		try {
			await Promise.all([...selectedIds].map((id) => libraryEntitiesApi.delete(id)));
			selectedIds = new Set();
			loadEntities($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
		} catch (err: unknown) {
			actionError = err instanceof Error ? err.message : 'Failed to delete';
		} finally {
			bulkDeleting = false;
		}
	}

	async function exportCsv() {
		exporting = true;
		try {
			const resp = await libraryEntitiesApi.list($scoutTeam, {
				limit: 0,
				search: debouncedSearch || undefined,
				sort_by: sortBy,
				sort_dir: sortDir,
			});
			const rows = resp.items;

			// Build CSV
			const headers = ['Label', 'GWM ID', 'Description', 'Metadata Keys', 'Created'];
			const csvLines = [
				headers.map(h => `"${h}"`).join(','),
				...rows.map(r => [
					`"${r.label.replace(/"/g, '""')}"`,
					`"${(r.gwm_id ?? '').replace(/"/g, '""')}"`,
					`"${(r.description ?? '').replace(/"/g, '""')}"`,
					`"${Object.keys(r.metadata || {}).join(', ')}"`,
					`"${r.created_at}"`,
				].join(','))
			];

			const blob = new Blob([csvLines.join('\n')], { type: 'text/csv' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `entities-${new Date().toISOString().split('T')[0]}.csv`;
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

	function libraryBulkCreate(rows: LibraryEntityCreate[]) {
		return libraryEntitiesApi.bulkCreate(rows, $scoutTeam);
	}
</script>

<div class="max-w-7xl mx-auto">
	<!-- Header -->
	<div class="flex items-center justify-between mb-6">
		<div>
			<h1 class="font-serif text-gold text-3xl font-bold">Entity Library</h1>
			<p class="text-slate-500 text-sm mt-2">Reusable entities across your campaigns</p>
		</div>
	</div>

	<!-- Filter & Sort Bar -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 mb-6 space-y-3">
		<!-- Search input -->
		<div>
			<input
				bind:value={searchQuery}
				placeholder="Search label, GWM ID, description…"
				aria-label="Search entities"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
			/>
		</div>

		<!-- Sort & filter buttons -->
		<div class="flex items-center gap-2 flex-wrap text-xs">
			<div class="flex items-center gap-2 flex-wrap">
				<span class="text-xs text-slate-400 w-full sm:w-auto mb-2 sm:mb-0">Sort:</span>
				{#each [['label', 'Label'], ['gwm_id', 'GWM ID'], ['created_at', 'Date']] as [col, label]}
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

			<div class="flex items-center gap-2">
				<span class="text-xs text-slate-400">Filter:</span>
				<button
					onclick={() => (gwmIdFilter = 'all')}
					class={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
						gwmIdFilter === 'all'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					All
				</button>
				<button
					onclick={() => (gwmIdFilter = 'has')}
					class={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
						gwmIdFilter === 'has'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					Has GWM ID
				</button>
				<button
					onclick={() => (gwmIdFilter = 'missing')}
					class={`text-xs px-2.5 py-0.5 rounded-full border transition-colors ${
						gwmIdFilter === 'missing'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					Missing GWM ID
				</button>
			</div>
		</div>
	</div>

	<!-- Stats & Actions -->
	<div class="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-4 gap-3">
		<div class="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-4 text-xs sm:text-sm w-full sm:w-auto">
			{#if !loading}
				<p class="text-slate-400 whitespace-nowrap">
					<span class="text-slate-200 font-semibold">{totalCount}</span> total
					{#if gwmIdFilter !== 'all' || debouncedSearch}
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
					{bulkDeleting ? 'Del…' : `Delete`}
				</button>
			{/if}
			<button
				onclick={exportCsv}
				disabled={exporting}
				class="bg-navy-700 border border-navy-600 text-slate-300 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-navy-600 disabled:opacity-50 transition-colors"
			>
				{exporting ? 'Export…' : 'CSV'}
			</button>
			<button
				onclick={() => { showCSV = !showCSV; showAddForm = false; }}
				class="bg-navy-700 border border-navy-600 text-slate-300 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-navy-600 transition-colors"
			>
				Upload
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showCSV = false; }}
				class="bg-gold text-navy font-semibold px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg hover:bg-gold-light transition-colors"
			>
				+ Add
			</button>
		</div>
	</div>

	<!-- CSV Upload Section -->
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
					loadEntities($scoutTeam, debouncedSearch, currentPage, pageSize, sortBy, sortDir);
				}}
			/>
		</div>
	{/if}

	<!-- Add Form Section -->
	{#if showAddForm}
		<form onsubmit={addEntity} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Add Entity to Library</h3>
			<div class="grid grid-cols-3 gap-4 mb-4">
				<div>
					<label for="lib-ent-label" class="block text-xs text-slate-400 mb-1">Label *</label>
					<input id="lib-ent-label" bind:value={newLabel} required placeholder="Name or entity label" class="input-field w-full" />
				</div>
				<div>
					<label for="lib-ent-gwmid" class="block text-xs text-slate-400 mb-1">GWM ID</label>
					<input id="lib-ent-gwmid" bind:value={newGwmId} placeholder="e.g. GWM-12345" class="input-field w-full font-mono" />
				</div>
				<div>
					<label for="lib-ent-desc" class="block text-xs text-slate-400 mb-1">Description</label>
					<input id="lib-ent-desc" bind:value={newDesc} placeholder="Optional description" class="input-field w-full" />
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

	<!-- Error -->
	{#if error}
		<p class="text-red-400 mb-4 text-sm">{error}</p>
	{/if}

	<!-- Loading / Empty State -->
	{#if actionError}
	<div class="bg-red-950 border border-red-700 rounded-xl px-4 py-3 text-red-300 text-sm mb-4 flex items-center justify-between" role="alert">
		<span>{actionError}</span>
		<button onclick={() => (actionError = '')} class="text-red-400 hover:text-red-200 min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label="Dismiss error">✕</button>
	</div>
{/if}

{#if loading}
		<LoadingSpinner />
	{:else if displayedEntities().length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No entities match "{debouncedSearch}".</p>
			{:else if gwmIdFilter !== 'all'}
				<p>No entities {gwmIdFilter === 'has' ? 'with GWM ID' : 'without GWM ID'}.</p>
			{:else}
				<p>No entities in the library yet. Add them manually or upload a CSV.</p>
				<p class="text-sm mt-2">Entities added here can be imported into any campaign.</p>
			{/if}
		</div>
	{:else}
		<!-- Table -->
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<div class="max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-auto">
				<table class="w-full text-sm" aria-label="Entity library">
					<thead class="sticky top-0 bg-navy-800 border-b border-navy-700">
						<tr class="text-slate-400">
							<th scope="col" class="px-4 py-3 w-8">
								<input type="checkbox"
									checked={selectedIds.size === displayedEntities().length && displayedEntities().length > 0}
									onchange={toggleSelectAll}
									class="accent-gold"
									aria-label="Select all entities on this page" />
							</th>
							<th scope="col" class="text-left px-4 py-3 font-medium">Label</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden sm:table-cell">GWM ID</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden md:table-cell">Description</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden lg:table-cell">Metadata</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden md:table-cell w-20">Created</th>
							<th scope="col" class="px-4 py-3 w-24"><span class="sr-only">Actions</span></th>
						</tr>
					</thead>
					<tbody>
						{#each displayedEntities() as entity (entity.id)}
							<tr class="border-t border-navy-700 hover:bg-navy-700/50 transition-colors">
								<td class="px-4 py-3">
									<input type="checkbox" checked={selectedIds.has(entity.id)}
										onchange={() => toggleSelect(entity.id)} class="accent-gold"
										aria-label="Select {entity.label}" />
								</td>
								{#if editingId === entity.id}
									<td class="px-4 py-2">
										<label class="sr-only" for="lib-edit-label-{entity.id}">Label</label>
										<input id="lib-edit-label-{entity.id}" bind:value={editForm.label} class="input-field w-full"
											onkeydown={(e) => handleEditKeydown(e, entity)} />
									</td>
									<td class="px-4 py-2 hidden sm:table-cell">
										<label class="sr-only" for="lib-edit-gwm-{entity.id}">GWM ID</label>
										<input id="lib-edit-gwm-{entity.id}" bind:value={editForm.gwm_id} class="input-field w-full font-mono text-xs"
											onkeydown={(e) => handleEditKeydown(e, entity)} />
									</td>
									<td class="px-4 py-2 hidden md:table-cell">
										<label class="sr-only" for="lib-edit-desc-{entity.id}">Description</label>
										<input id="lib-edit-desc-{entity.id}" bind:value={editForm.description} class="input-field w-full"
											onkeydown={(e) => handleEditKeydown(e, entity)} />
									</td>
									<td colspan="3" class="px-4 py-2 text-right whitespace-nowrap space-x-2">
										<button onclick={() => saveEdit(entity)} disabled={editSaving}
											aria-label="Save changes to {entity.label}"
											class="text-gold hover:text-gold-light text-xs disabled:opacity-50">
											{editSaving ? '…' : 'Save'}
										</button>
										<button onclick={cancelEdit} aria-label="Cancel editing {entity.label}"
											class="text-slate-500 hover:text-slate-300 text-xs">Cancel</button>
									</td>
								{:else}
									<td class="px-4 py-3 text-slate-200 font-medium">{entity.label}</td>
									<td class="px-4 py-3 text-slate-400 font-mono text-xs hidden sm:table-cell">{entity.gwm_id ?? '—'}</td>
									<td class="px-4 py-3 text-slate-500 max-w-xs hidden md:table-cell" title={entity.description ?? ''}>
										<span class="line-clamp-2">{entity.description ?? '—'}</span>
									</td>
									<td class="px-4 py-3 hidden lg:table-cell">
										{#if Object.keys(entity.metadata || {}).length > 0}
											<span class="inline-block text-xs bg-gold/10 border border-gold/30 text-gold px-2 py-0.5 rounded-full">
												{Object.keys(entity.metadata).length} keys
											</span>
										{:else}
											<span class="text-slate-600 text-xs">—</span>
										{/if}
									</td>
									<td class="px-4 py-3 text-slate-500 text-xs hidden md:table-cell">{formatDate(entity.created_at)}</td>
									<td class="px-4 py-3 text-right whitespace-nowrap space-x-2">
										<button onclick={() => startEdit(entity)} aria-label="Edit {entity.label}"
											class="text-slate-500 hover:text-slate-300 text-xs">Edit</button>
										<button onclick={() => deleteEntity(entity.id)} aria-label="Delete {entity.label}"
											class="text-red-400/60 hover:text-red-400 text-xs">Delete</button>
									</td>
								{/if}
							</tr>
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
