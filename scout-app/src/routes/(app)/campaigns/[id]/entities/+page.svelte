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

	async function deleteEntity(id: string) {
		if (!confirm('Delete this entity?')) return;
		try {
			await entitiesApi.delete(campaignId, id);
			entities = entities.filter((e) => e.id !== id);
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
		<h2 class="font-serif text-gold text-xl font-bold">Entities ({entities.length})</h2>
		<div class="flex gap-2">
			<button
				onclick={openImport}
				class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg
				       hover:bg-navy-600 transition-colors"
			>
				↗ Import from Campaign
			</button>
			<button
				onclick={() => { showCSV = !showCSV; showAddForm = false; showImport = false; }}
				class="text-sm bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg
				       hover:bg-navy-600 transition-colors"
			>
				📄 Upload CSV
			</button>
			<button
				onclick={() => { showAddForm = !showAddForm; showCSV = false; showImport = false; }}
				class="text-sm bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg
				       hover:bg-gold-light transition-colors"
			>
				+ Add Entity
			</button>
		</div>
	</div>

	{#if showImport}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Import Entities from Another Campaign</h3>
			<p class="text-slate-500 text-sm mb-4">
				Entities with gwm_id will be skipped if the same gwm_id already exists. Entities without gwm_id will be skipped if the label already exists.
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

	{#if showCSV}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Upload CSV</h3>
			<CSVUpload
				{campaignId}
				onUploaded={() => { load(); showCSV = false; }}
			/>
		</div>
	{/if}

	{#if showAddForm}
		<form onsubmit={addEntity} class="bg-navy-800 border border-navy-700 rounded-xl p-5 mb-6">
			<h3 class="font-medium text-slate-200 mb-4">Add Entity</h3>
			<div class="grid grid-cols-3 gap-4 mb-4">
				<div>
					<label class="block text-xs text-slate-400 mb-1">Label *</label>
					<input bind:value={newLabel} required placeholder="Name or entity label"
					       class="input-field w-full" />
				</div>
				<div>
					<label class="block text-xs text-slate-400 mb-1">GWM ID</label>
					<input bind:value={newGwmId} placeholder="Optional identifier"
					       class="input-field w-full" />
				</div>
				<div>
					<label class="block text-xs text-slate-400 mb-1">Description</label>
					<input bind:value={newDesc} placeholder="Optional description"
					       class="input-field w-full" />
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
		<p class="text-red-400 mb-4">{error}</p>
	{/if}

	{#if loading}
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
						<th class="text-left px-4 py-3">Label</th>
						<th class="text-left px-4 py-3">GWM ID</th>
						<th class="text-left px-4 py-3">Description</th>
						<th class="px-4 py-3 w-16"></th>
					</tr>
				</thead>
				<tbody>
					{#each entities as entity (entity.id)}
						<tr class="border-t border-navy-700 hover:bg-navy-700/50">
							<td class="px-4 py-3 text-slate-200 font-medium">{entity.label}</td>
							<td class="px-4 py-3 text-slate-400 font-mono text-xs">{entity.gwm_id ?? '—'}</td>
							<td class="px-4 py-3 text-slate-500 truncate max-w-xs">{entity.description ?? '—'}</td>
							<td class="px-4 py-3 text-right">
								<button
									onclick={() => deleteEntity(entity.id)}
									class="text-red-400/60 hover:text-red-400 transition-colors text-xs"
								>
									Delete
								</button>
							</td>
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
