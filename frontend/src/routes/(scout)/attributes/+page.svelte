<script lang="ts">
	import { libraryAttributesApi, type LibraryAttribute, type LibraryAttributeCreate } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';

	let attributes = $state<LibraryAttribute[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Add form
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Upload
	let showUpload = $state(false);

	// Inline edit
	let editing = $state<Record<string, LibraryAttribute>>({});

	async function loadAttributes(teamId: string | null) {
		loading = true;
		error = '';
		try {
			attributes = await libraryAttributesApi.list(teamId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load library';
		} finally {
			loading = false;
		}
	}

	$effect(() => { loadAttributes($scoutTeam); });

	async function addAttribute(e: Event) {
		e.preventDefault();
		if (!newLabel.trim()) return;
		adding = true;
		try {
			const attr = await libraryAttributesApi.create({
				label: newLabel.trim(),
				description: newDesc.trim() || undefined,
				weight: newWeight,
				team_id: $scoutTeam ?? undefined,
			});
			attributes = [...attributes, attr];
			newLabel = '';
			newDesc = '';
			newWeight = 1.0;
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
			attributes = attributes.filter((a) => a.id !== id);
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
				<span class="text-slate-200 font-medium">{attributes.length}</span>
				{attributes.length === 1 ? 'attribute' : 'attributes'} in library
			</p>
		{:else}
			<span></span>
		{/if}
		<button onclick={() => (showUpload = !showUpload)}
			class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors">
			Upload CSV / Excel
		</button>
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
					attributes = await libraryAttributesApi.list($scoutTeam);
				}}
			/>
		</div>
	{/if}

	<!-- Add form -->
	<form onsubmit={addAttribute} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
		<h3 class="font-medium text-slate-200 mb-4">Add Attribute to Library</h3>
		<div class="grid grid-cols-4 gap-4 mb-4">
			<div class="col-span-2">
				<label class="block text-xs text-slate-400 mb-1">Label *</label>
				<input bind:value={newLabel} required placeholder="e.g. Has board experience" class="input-field w-full" />
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1">Weight</label>
				<input type="number" bind:value={newWeight} min="0" max="10" step="0.1" class="input-field w-full" />
			</div>
			<div class="col-span-4">
				<label class="block text-xs text-slate-400 mb-1">Description <span class="text-slate-600">(fed to LLM prompt)</span></label>
				<input bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate" class="input-field w-full" />
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
			<p>No attributes in the library yet. Add them above or upload a CSV.</p>
			<p class="text-sm mt-2">Attributes added here can be imported into any campaign.</p>
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-navy-700 text-slate-400">
						<th class="text-left px-4 py-3">Label</th>
						<th class="text-left px-4 py-3">Description</th>
						<th class="text-left px-4 py-3 w-20">Weight</th>
						<th class="px-4 py-3 w-24"></th>
					</tr>
				</thead>
				<tbody>
					{#each attributes as attr (attr.id)}
						{#if editing[attr.id]}
							{@const e = editing[attr.id]}
							<tr class="border-t border-navy-700 bg-navy-700/50">
								<td class="px-4 py-2"><input bind:value={e.label} class="input-field w-full text-sm" /></td>
								<td class="px-4 py-2"><input bind:value={e.description} class="input-field w-full text-sm" /></td>
								<td class="px-4 py-2"><input type="number" bind:value={e.weight} min="0" step="0.1" class="input-field w-20 text-sm" /></td>
								<td class="px-4 py-2 text-right space-x-2">
									<button onclick={() => saveEdit(attr.id)} class="text-green-400 hover:text-green-300 text-xs">Save</button>
									<button onclick={() => cancelEdit(attr.id)} class="text-slate-500 hover:text-slate-400 text-xs">Cancel</button>
								</td>
							</tr>
						{:else}
							<tr class="border-t border-navy-700 hover:bg-navy-700/50">
								<td class="px-4 py-3 text-slate-200 font-medium">{attr.label}</td>
								<td class="px-4 py-3 text-slate-500 truncate max-w-xs">{attr.description ?? '—'}</td>
								<td class="px-4 py-3 text-slate-300 font-mono text-xs">{attr.weight.toFixed(1)}</td>
								<td class="px-4 py-3 text-right space-x-2">
									<button onclick={() => startEdit(attr)} class="text-slate-400 hover:text-gold text-xs">Edit</button>
									<button onclick={() => deleteAttribute(attr.id)} class="text-red-400/60 hover:text-red-400 text-xs">Del</button>
								</td>
							</tr>
						{/if}
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
