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
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Upload
	let showUpload = $state(false);

	// Inline edit
	let editing = $state<Record<string, LibraryAttribute>>({});

	async function loadAttributes(teamId: string | null, search: string, page: number) {
		loading = true;
		error = '';
		try {
			const resp = await libraryAttributesApi.list(teamId, {
				limit: pageSize,
				offset: page * pageSize,
				search: search || undefined,
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

	$effect(() => { loadAttributes($scoutTeam, debouncedSearch, currentPage); });

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
			loadAttributes($scoutTeam, debouncedSearch, currentPage);
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
			loadAttributes($scoutTeam, debouncedSearch, currentPage);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		}
	}

	function libraryBulkCreate(rows: LibraryAttributeCreate[]) {
		return libraryAttributesApi.bulkCreate(rows, $scoutTeam);
	}
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-center justify-between mb-6">
		<div>
			<h1 class="font-serif text-gold text-2xl font-bold">Attribute Library</h1>
			<p class="text-slate-500 text-sm mt-1">Add attributes here to reuse them across campaigns.</p>
		</div>
	</div>

	<!-- Action bar -->
	<div class="flex items-center justify-between mb-4">
		{#if !loading}
			<p class="text-sm text-slate-400">
				<span class="text-slate-200 font-medium">{totalCount}</span>
				{totalCount === 1 ? 'attribute' : 'attributes'} in library
			</p>
		{:else}
			<span></span>
		{/if}
		<button onclick={() => (showUpload = !showUpload)}
			class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors">
			Upload CSV / Excel
		</button>
	</div>

	<!-- Search -->
	<div class="mb-4">
		<input
			bind:value={searchQuery}
			placeholder="Search attributes…"
			aria-label="Search attributes"
			class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
	</div>

	{#if showUpload}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<div class="flex items-center justify-between mb-4">
				<h3 class="font-medium text-slate-200">Upload Attributes to Library</h3>
				<button onclick={() => (showUpload = false)} class="text-slate-500 hover:text-slate-300 text-xs">✕ Close</button>
			</div>
			<AttributeCSVUpload
				onBulkCreate={libraryBulkCreate}
				onUploaded={async () => {
					showUpload = false;
					loadAttributes($scoutTeam, debouncedSearch, currentPage);
				}}
			/>
		</div>
	{/if}

	<!-- Add form -->
	<form onsubmit={addAttribute} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
		<h3 class="font-medium text-slate-200 mb-4">Add Attribute to Library</h3>
		<div class="grid grid-cols-4 gap-4 mb-4">
			<div class="col-span-2">
				<label for="lib-attr-label" class="block text-xs text-slate-400 mb-1">Label *</label>
				<input id="lib-attr-label" bind:value={newLabel} required placeholder="e.g. Has board experience" class="input-field w-full" />
			</div>
			<div>
				<label for="lib-attr-weight" class="block text-xs text-slate-400 mb-1">Weight</label>
				<input id="lib-attr-weight" type="number" bind:value={newWeight} min="0" max="10" step="0.1" class="input-field w-full" />
			</div>
			<div class="col-span-4">
				<label for="lib-attr-desc" class="block text-xs text-slate-400 mb-1">Description <span class="text-slate-600">(fed to LLM prompt)</span></label>
				<input id="lib-attr-desc" bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate" class="input-field w-full" />
			</div>
		</div>
		<button type="submit" disabled={adding}
			class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
			{adding ? 'Adding…' : '+ Add Attribute'}
		</button>
	</form>

	{#if error}
		<p class="text-red-400 mb-4 text-sm">{error}</p>
	{/if}

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if attributes.length === 0}
		<div class="text-center py-12 text-slate-500">
			{#if debouncedSearch}
				<p>No attributes match "{debouncedSearch}".</p>
			{:else}
				<p>No attributes in the library yet. Add them above or upload a CSV.</p>
				<p class="text-sm mt-2">Attributes added here can be imported into any campaign.</p>
			{/if}
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<table class="w-full text-sm" aria-label="Attribute library">
				<thead>
					<tr class="border-b border-navy-700 text-slate-400">
						<th scope="col" class="text-left px-4 py-3">Label</th>
						<th scope="col" class="text-left px-4 py-3">Description</th>
						<th scope="col" class="text-left px-4 py-3 w-20">Weight</th>
						<th scope="col" class="px-4 py-3 w-24"><span class="sr-only">Actions</span></th>
					</tr>
				</thead>
				<tbody>
					{#each attributes as attr (attr.id)}
						{#if editing[attr.id]}
							{@const e = editing[attr.id]}
							<tr class="border-t border-navy-700 bg-navy-700/50">
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-attr-label-{attr.id}">Label</label>
									<input id="lib-attr-label-{attr.id}" bind:value={e.label} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-attr-desc-{attr.id}">Description</label>
									<input id="lib-attr-desc-{attr.id}" bind:value={e.description} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<label class="sr-only" for="lib-attr-weight-{attr.id}">Weight</label>
									<input id="lib-attr-weight-{attr.id}" type="number" bind:value={e.weight} min="0" step="0.1" class="input-field w-20 text-sm" />
								</td>
								<td class="px-4 py-2 text-right space-x-2">
									<button onclick={() => saveEdit(attr.id)} aria-label="Save changes to {attr.label}"
										class="text-green-400 hover:text-green-300 text-xs">Save</button>
									<button onclick={() => cancelEdit(attr.id)} aria-label="Cancel editing {attr.label}"
										class="text-slate-500 hover:text-slate-400 text-xs">Cancel</button>
								</td>
							</tr>
						{:else}
							<tr class="border-t border-navy-700 hover:bg-navy-700/50">
								<td class="px-4 py-3 text-slate-200 font-medium">{attr.label}</td>
								<td class="px-4 py-3 text-slate-500 max-w-sm" title={attr.description ?? ''}><span class="line-clamp-2">{attr.description ?? '—'}</span></td>
								<td class="px-4 py-3 text-slate-300 font-mono text-xs">{attr.weight.toFixed(1)}</td>
								<td class="px-4 py-3 text-right space-x-2">
									<button onclick={() => startEdit(attr)} aria-label="Edit {attr.label}"
										class="text-slate-400 hover:text-gold text-xs">Edit</button>
									<button onclick={() => deleteAttribute(attr.id)} aria-label="Delete {attr.label}"
										class="text-red-400/60 hover:text-red-400 text-xs">Del</button>
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
				onPageChange={(p) => { currentPage = p; }}
			/>
		</div>
	{/if}
</div>
