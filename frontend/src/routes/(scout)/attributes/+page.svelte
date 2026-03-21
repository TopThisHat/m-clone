<script lang="ts">
	import { libraryAttributesApi, type LibraryAttribute, type LibraryAttributeCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	let attributes = $state<LibraryAttribute[]>([]);
	let loading = $state(true);
	let error = $state('');
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
	});

	// Add form
	let showAddForm = $state(false);
	let showCSV = $state(false);
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Inline edit
	let editing = $state<Record<string, LibraryAttribute>>({});

	// Export
	let exporting = $state(false);

	async function loadAttributes(teamId: string | null, search: string, page: number, size: number) {
		loading = true;
		error = '';
		try {
			const resp = await libraryAttributesApi.list(teamId, {
				limit: size,
				offset: page * size,
				search: search || undefined,
				sort_by: sortBy,
				sort_dir: sortDir,
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
		loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize);
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
			loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to add attribute';
		} finally {
			adding = false;
		}
	}

	function startEdit(attr: LibraryAttribute) {
		editing[attr.id] = { ...attr };
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
			const updated = await libraryAttributesApi.update(id, {
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

	async function deleteAttribute(id: string) {
		if (!confirm('Delete this attribute from the library?')) return;
		try {
			await libraryAttributesApi.delete(id);
			loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
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
			alert(err instanceof Error ? err.message : 'Failed to export');
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
				<button
					onclick={() => { sortBy = 'label'; sortDir = sortDir === 'asc' && sortBy === 'label' ? 'desc' : 'asc'; }}
					class={`text-xs px-2 py-1 rounded border transition-colors ${
						sortBy === 'label'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					Label {sortBy === 'label' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
				</button>
				<button
					onclick={() => { sortBy = 'weight'; sortDir = sortDir === 'asc' && sortBy === 'weight' ? 'desc' : 'asc'; }}
					class={`text-xs px-2 py-1 rounded border transition-colors ${
						sortBy === 'weight'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					Weight {sortBy === 'weight' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
				</button>
				<button
					onclick={() => { sortBy = 'created_at'; sortDir = sortDir === 'asc' && sortBy === 'created_at' ? 'desc' : 'asc'; }}
					class={`text-xs px-2 py-1 rounded border transition-colors ${
						sortBy === 'created_at'
							? 'bg-gold/10 border-gold/40 text-gold'
							: 'border-navy-600 text-slate-400 hover:text-slate-300'
					}`}
				>
					Date {sortBy === 'created_at' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
				</button>
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
				<p class="text-slate-400 whitespace-nowrap">
					<span class="text-slate-200 font-semibold">{totalCount}</span> total
					{#if (minWeight > 0 || maxWeight < 10 || debouncedSearch)}
						<br class="sm:hidden" />
						<span class="sm:inline">• <span class="text-slate-200 font-semibold">{displayedCount()}</span> shown</span>
					{/if}
				</p>
			{/if}
		</div>

		<div class="flex items-center gap-1 sm:gap-2 w-full sm:w-auto text-xs sm:text-sm">
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
		</div>
	</div>

	<!-- CSV Upload Section -->
	{#if showCSV}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Upload Attributes to Library</h3>
				<button onclick={() => (showCSV = false)} class="text-slate-500 hover:text-slate-300 text-xs">✕ Close</button>
			</div>
			<AttributeCSVUpload
				onBulkCreate={libraryBulkCreate}
				onUploaded={async () => {
					showCSV = false;
					loadAttributes($scoutTeam, debouncedSearch, currentPage, pageSize);
				}}
			/>
		</div>
	{/if}

	<!-- Add form (collapsible) -->
	<div class="bg-navy-800 border border-navy-700 rounded-xl mb-6">
		<button
			onclick={() => (showAddForm = !showAddForm)}
			class={`w-full px-5 py-3 flex items-center justify-between transition-colors ${
				showAddForm ? 'bg-navy-700 border-b border-navy-700' : 'hover:bg-navy-700/50'
			}`}
		>
			<h3 class="font-medium text-slate-200">Add Attribute to Library</h3>
			<span class={`text-slate-400 transition-transform ${showAddForm ? 'rotate-180' : ''}`}>▼</span>
		</button>

		{#if showAddForm}
			<form onsubmit={addAttribute} class="px-5 py-4 space-y-4 border-t border-navy-700">
				<div class="grid grid-cols-4 gap-4">
					<div class="col-span-2">
						<label for="lib-attr-label" class="block text-xs text-slate-400 mb-1">Label *</label>
						<input id="lib-attr-label" bind:value={newLabel} required placeholder="e.g. Has board experience" class="input-field w-full" />
					</div>
					<div>
						<label for="lib-attr-weight" class="block text-xs text-slate-400 mb-1">Weight</label>
						<input id="lib-attr-weight" type="number" bind:value={newWeight} min="0" max="10" step="0.1" class="input-field w-full" />
					</div>
					<div>
						<label for="lib-attr-submit" class="block text-xs text-slate-400 mb-1">&nbsp;</label>
						<button id="lib-attr-submit" type="submit" disabled={adding} class="btn-gold w-full py-1.5 text-sm">
							{adding ? 'Adding…' : 'Add'}
						</button>
					</div>
				</div>
				<div>
					<label for="lib-attr-desc" class="block text-xs text-slate-400 mb-1">Description <span class="text-slate-600">(fed to LLM)</span></label>
					<input id="lib-attr-desc" bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate" class="input-field w-full" />
				</div>
			</form>
		{/if}
	</div>

	<!-- Error -->
	{#if error}
		<p class="text-red-400 mb-4 text-sm">{error}</p>
	{/if}

	<!-- Loading / Empty State -->
	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if displayedAttributes().length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No attributes match "{debouncedSearch}".</p>
			{:else if minWeight > 0 || maxWeight < 10}
				<p>No attributes in weight range {minWeight.toFixed(1)} – {maxWeight.toFixed(1)}.</p>
			{:else}
				<p>No attributes in the library yet. Add them above or upload a CSV.</p>
				<p class="text-sm mt-2">Attributes added here can be imported into any campaign.</p>
			{/if}
		</div>
	{:else}
		<!-- Table -->
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden flex flex-col">
			<div class="overflow-x-auto flex-1">
				<table class="w-full text-sm" aria-label="Attribute library">
					<thead class="sticky top-0 bg-navy-800 border-b border-navy-700">
						<tr class="text-slate-400">
							<th scope="col" class="text-left px-4 py-3 font-medium">Label</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden md:table-cell">Description</th>
							<th scope="col" class="text-left px-4 py-3 font-medium w-32">Weight</th>
							<th scope="col" class="text-left px-4 py-3 font-medium hidden sm:table-cell w-20">Created</th>
							<th scope="col" class="px-4 py-3 w-24"><span class="sr-only">Actions</span></th>
						</tr>
					</thead>
					<tbody>
						{#each displayedAttributes() as attr (attr.id)}
							{#if editing[attr.id]}
								{@const e = editing[attr.id]}
								<tr class="border-t border-navy-700 bg-navy-700/50">
									<td class="px-4 py-2">
										<label class="sr-only" for="lib-attr-label-{attr.id}">Label</label>
										<input id="lib-attr-label-{attr.id}" bind:value={e.label} class="input-field w-full text-sm" />
									</td>
									<td class="px-4 py-2 hidden md:table-cell">
										<label class="sr-only" for="lib-attr-desc-{attr.id}">Description</label>
										<input id="lib-attr-desc-{attr.id}" bind:value={e.description} class="input-field w-full text-sm" />
									</td>
									<td class="px-4 py-2">
										<label class="sr-only" for="lib-attr-weight-{attr.id}">Weight</label>
										<input id="lib-attr-weight-{attr.id}" type="number" bind:value={e.weight} min="0" step="0.1" class="input-field w-full text-sm" />
									</td>
									<td class="px-4 py-2 text-slate-500 text-xs hidden sm:table-cell">{formatDate(attr.created_at)}</td>
									<td class="px-4 py-2 text-right space-x-2">
										<button onclick={() => saveEdit(attr.id)} aria-label="Save changes to {attr.label}"
											class="text-green-400 hover:text-green-300 text-xs">Save</button>
										<button onclick={() => cancelEdit(attr.id)} aria-label="Cancel editing {attr.label}"
											class="text-slate-500 hover:text-slate-400 text-xs">Cancel</button>
									</td>
								</tr>
							{:else}
								<tr class="border-t border-navy-700 hover:bg-navy-700/50 transition-colors">
									<td class="px-4 py-3 text-slate-200 font-medium">{attr.label}</td>
									<td class="px-4 py-3 text-slate-500 max-w-xs hidden md:table-cell" title={attr.description ?? ''}>
										<span class="line-clamp-2">{attr.description ?? '—'}</span>
									</td>
									<td class="px-4 py-3">
										<div class="flex items-center gap-2">
											<div class="w-16 sm:w-20 h-2 bg-navy-700 rounded-full overflow-hidden">
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
										<button onclick={() => startEdit(attr)} aria-label="Edit {attr.label}"
											class="text-slate-400 hover:text-gold text-xs">Edit</button>
										<button onclick={() => deleteAttribute(attr.id)} aria-label="Delete {attr.label}"
											class="text-red-400/60 hover:text-red-400 text-xs">Delete</button>
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
				onPageChange={(p) => { currentPage = p; }}
				onPageSizeChange={(size) => { pageSize = size; currentPage = 0; }}
			/>
		</div>
	{/if}
</div>
