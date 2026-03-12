<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { attributesApi, type Attribute } from '$lib/api/attributes';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';

	let campaignId = $derived($page.params.id as string);
	let attributes = $state<Attribute[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Add form
	let newLabel = $state('');
	let newDesc = $state('');
	let newWeight = $state(1.0);
	let adding = $state(false);

	// Inline edit state: attributeId → editing flag
	let editing = $state<Record<string, Attribute & { _orig: Attribute }>>({});

	// Import modal state
	let showImport = $state(false);
	let otherCampaigns = $state<Campaign[]>([]);
	let selectedSourceId = $state('');
	let importing = $state(false);
	let importResult = $state('');

	async function load() {
		try {
			attributes = await attributesApi.list(campaignId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load attributes';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function openImport() {
		showImport = true;
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
			attributes = await attributesApi.list(campaignId);
			importResult = `Imported ${imported.length} new ${imported.length === 1 ? 'attribute' : 'attributes'}.`;
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
			const attr = await attributesApi.create(campaignId, {
				label: newLabel.trim(),
				description: newDesc.trim() || undefined,
				weight: newWeight,
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

	async function deleteAttribute(id: string) {
		if (!confirm('Delete this attribute?')) return;
		try {
			await attributesApi.delete(campaignId, id);
			attributes = attributes.filter((a) => a.id !== id);
		} catch (err: unknown) {
			alert(err instanceof Error ? err.message : 'Failed to delete');
		}
	}
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-6">
		<h2 class="font-serif text-gold text-xl font-bold">Attributes ({attributes.length})</h2>
		<button
			onclick={openImport}
			class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg
			       hover:bg-navy-600 transition-colors"
		>
			↗ Import from Campaign
		</button>
	</div>

	{#if showImport}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Import Attributes from Another Campaign</h3>
			<p class="text-slate-500 text-sm mb-4">
				Attributes are skipped if an attribute with the same label already exists in this campaign.
			</p>
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
				<button
					onclick={doImport}
					disabled={!selectedSourceId || importing}
					class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50"
				>
					{importing ? 'Importing…' : 'Import'}
				</button>
				<button
					onclick={() => { showImport = false; importResult = ''; }}
					class="bg-navy-700 text-slate-300 px-4 py-1.5 rounded-lg text-sm border border-navy-600"
				>
					Cancel
				</button>
			</div>
			{#if importResult}
				<p class="mt-3 text-sm {importResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">{importResult}</p>
			{/if}
		</div>
	{/if}

	<!-- Add form -->
	<form onsubmit={addAttribute} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
		<h3 class="font-medium text-slate-200 mb-4">Add Attribute</h3>
		<div class="grid grid-cols-4 gap-4 mb-4">
			<div class="col-span-2">
				<label class="block text-xs text-slate-400 mb-1">Label *</label>
				<input bind:value={newLabel} required placeholder="e.g. Has board experience"
				       class="input-field w-full" />
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1">Weight</label>
				<input type="number" bind:value={newWeight} min="0" max="10" step="0.1"
				       class="input-field w-full" />
			</div>
			<div class="col-span-4">
				<label class="block text-xs text-slate-400 mb-1">Description <span class="text-slate-600">(fed to LLM prompt)</span></label>
				<input bind:value={newDesc} placeholder="Detailed description for the LLM to evaluate"
				       class="input-field w-full" />
			</div>
		</div>
		<button type="submit" disabled={adding}
		        class="bg-gold text-navy font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-gold-light disabled:opacity-50">
			{adding ? 'Adding…' : '+ Add Attribute'}
		</button>
	</form>

	{#if error}
		<p class="text-red-400 mb-4">{error}</p>
	{/if}

	{#if loading}
		<p class="text-slate-500">Loading…</p>
	{:else if attributes.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No attributes yet. Add them above or import from another campaign.</p>
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
								<td class="px-4 py-2">
									<input bind:value={e.label} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<input bind:value={e.description} class="input-field w-full text-sm" />
								</td>
								<td class="px-4 py-2">
									<input type="number" bind:value={e.weight} min="0" step="0.1"
									       class="input-field w-20 text-sm" />
								</td>
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
