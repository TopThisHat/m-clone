<script lang="ts">
	import { goto } from '$app/navigation';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { entitiesApi, type EntityCreate } from '$lib/api/entities';
	import { attributesApi, type AttributeCreate } from '$lib/api/attributes';
	import { libraryEntitiesApi, libraryAttributesApi, type LibraryEntity, type LibraryAttribute } from '$lib/api/library';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import SchedulePicker from '$lib/components/SchedulePicker.svelte';
	import CSVUpload from '$lib/components/CSVUpload.svelte';
	import AttributeCSVUpload from '$lib/components/AttributeCSVUpload.svelte';
	import { templatesApi, type AttributeTemplate } from '$lib/api/templates';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	type Step = 1 | 2 | 3;
	let step = $state<Step>(1);
	let campaign = $state<Campaign | null>(null);

	// Step 1 — details
	let name = $state('');
	let description = $state('');
	let schedule = $state('');
	let selectedTeamId = $state<string | null>($scoutTeam);
	let creating = $state(false);
	let createError = $state('');

	// Step 2 — entities
	let entityLabel = $state('');
	let entityDesc = $state('');
	let entityCount = $state(0);
	let addingEntity = $state(false);
	let entityError = $state('');
	let showEntityUpload = $state(false);
	let showEntityLibrary = $state(false);
	let libraryEntities = $state<LibraryEntity[]>([]);
	let libraryEntitySelectedIds = $state<Set<string>>(new Set());
	let importingEntityLib = $state(false);
	let _libEntitiesLoaded = false;

	// Step 3 — attributes
	let attrLabel = $state('');
	let attrDesc = $state('');
	let attrWeight = $state(1.0);
	let attrCount = $state(0);
	let addingAttr = $state(false);
	let attrError = $state('');
	let showAttrUpload = $state(false);
	let showAttrLibrary = $state(false);
	let libraryAttrs = $state<LibraryAttribute[]>([]);
	let libraryAttrSelectedIds = $state<Set<string>>(new Set());
	let importingAttrLib = $state(false);
	let _libAttrsLoaded = false;

	// Templates
	let templates = $state<AttributeTemplate[]>([]);
	let showTemplates = $state(false);
	let savingTemplate = $state(false);
	let templateName = $state('');
	let _tplLoaded = false;

	async function loadTemplates() {
		if (_tplLoaded) return;
		_tplLoaded = true;
		try { templates = await templatesApi.list(); } catch { /* ignore */ }
	}

	async function applyTemplate(tpl: AttributeTemplate) {
		if (!campaign) return;
		for (const a of tpl.attributes) {
			try {
				await attributesApi.create(campaign.id, { label: a.label, description: a.description, weight: a.weight ?? 1 });
				attrCount++;
			} catch { /* skip duplicate */ }
		}
		showTemplates = false;
	}

	async function saveTemplate() {
		if (!campaign || !templateName.trim()) return;
		savingTemplate = true;
		try {
			const resp = await attributesApi.list(campaign.id, { limit: 0 });
			await templatesApi.create({ name: templateName.trim(), attributes: resp.items.map((a) => ({ label: a.label, description: a.description ?? undefined, weight: a.weight })) });
			templateName = '';
			alert('Template saved!');
		} catch { /* ignore */ } finally { savingTemplate = false; }
	}

	async function createCampaign(e: Event) {
		e.preventDefault();
		if (!name.trim()) { createError = 'Campaign name is required'; return; }
		creating = true;
		createError = '';
		try {
			campaign = await campaignsApi.create({
				name: name.trim(),
				description: description.trim() || undefined,
				schedule: schedule || undefined,
				team_id: selectedTeamId ?? undefined,
			});
			step = 2;
		} catch (err: unknown) {
			createError = err instanceof Error ? err.message : 'Failed to create campaign';
		} finally {
			creating = false;
		}
	}

	async function quickAddEntity(e: Event) {
		e.preventDefault();
		if (!campaign || !entityLabel.trim()) return;
		addingEntity = true;
		entityError = '';
		try {
			await entitiesApi.create(campaign.id, {
				label: entityLabel.trim(),
				description: entityDesc.trim() || undefined,
			});
			entityCount++;
			entityLabel = '';
			entityDesc = '';
		} catch (err: unknown) {
			entityError = err instanceof Error ? err.message : 'Failed to add entity';
		} finally {
			addingEntity = false;
		}
	}

	async function quickAddAttr(e: Event) {
		e.preventDefault();
		if (!campaign || !attrLabel.trim()) return;
		addingAttr = true;
		attrError = '';
		try {
			await attributesApi.create(campaign.id, {
				label: attrLabel.trim(),
				description: attrDesc.trim() || undefined,
				weight: attrWeight,
			});
			attrCount++;
			attrLabel = '';
			attrDesc = '';
			attrWeight = 1.0;
		} catch (err: unknown) {
			attrError = err instanceof Error ? err.message : 'Failed to add attribute';
		} finally {
			addingAttr = false;
		}
	}

	// Library entity search + pagination
	let libEntitySearch = $state('');
	let libEntityPage = $state(0);
	let libEntityTotal = $state(0);
	const libPageSize = 50;

	async function openEntityLibrary() {
		showEntityLibrary = !showEntityLibrary;
		showEntityUpload = false;
		if (showEntityLibrary && !_libEntitiesLoaded) {
			_libEntitiesLoaded = true;
			await loadLibraryEntities();
		}
	}

	async function loadLibraryEntities() {
		try {
			const resp = await libraryEntitiesApi.list($scoutTeam, {
				limit: libPageSize,
				offset: libEntityPage * libPageSize,
				search: libEntitySearch || undefined,
			});
			libraryEntities = resp.items;
			libEntityTotal = resp.total;
		} catch { /* ignore */ }
	}

	function toggleLibraryEntity(id: string) {
		const next = new Set(libraryEntitySelectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		libraryEntitySelectedIds = next;
	}

	async function importFromEntityLibrary() {
		if (!campaign || libraryEntitySelectedIds.size === 0) return;
		importingEntityLib = true;
		try {
			const imported = await entitiesApi.importFromLibrary(campaign.id, [...libraryEntitySelectedIds]);
			entityCount += imported.length;
			libraryEntitySelectedIds = new Set();
			showEntityLibrary = false;
		} catch { /* ignore */ } finally {
			importingEntityLib = false;
		}
	}

	// Library attribute search + pagination
	let libAttrSearch = $state('');
	let libAttrPage = $state(0);
	let libAttrTotal = $state(0);

	async function openAttrLibrary() {
		showAttrLibrary = !showAttrLibrary;
		showAttrUpload = false;
		if (showAttrLibrary && !_libAttrsLoaded) {
			_libAttrsLoaded = true;
			await loadLibraryAttrs();
		}
	}

	async function loadLibraryAttrs() {
		try {
			const resp = await libraryAttributesApi.list($scoutTeam, {
				limit: libPageSize,
				offset: libAttrPage * libPageSize,
				search: libAttrSearch || undefined,
			});
			libraryAttrs = resp.items;
			libAttrTotal = resp.total;
		} catch { /* ignore */ }
	}

	function toggleLibraryAttr(id: string) {
		const next = new Set(libraryAttrSelectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		libraryAttrSelectedIds = next;
	}

	async function importFromAttrLibrary() {
		if (!campaign || libraryAttrSelectedIds.size === 0) return;
		importingAttrLib = true;
		try {
			const imported = await attributesApi.importFromLibrary(campaign.id, [...libraryAttrSelectedIds]);
			attrCount += imported.length;
			libraryAttrSelectedIds = new Set();
			showAttrLibrary = false;
		} catch { /* ignore */ } finally {
			importingAttrLib = false;
		}
	}

	function finish() {
		goto(`/campaigns/${campaign!.id}`);
	}

	const STEP_LABELS = ['Campaign Details', 'Add Entities', 'Add Attributes'];
</script>

<div class="max-w-2xl mx-auto">
	<div class="mb-6">
		<a href="/campaigns" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaigns</a>
		<h1 class="font-serif text-gold text-2xl font-bold mt-2">New Campaign</h1>
	</div>

	<!-- Step indicator -->
	<div class="flex items-center gap-0 mb-8">
		{#each STEP_LABELS as label, i}
			{@const s = (i + 1) as Step}
			{@const done = step > s}
			{@const active = step === s}
			<div class="flex items-center {i < STEP_LABELS.length - 1 ? 'flex-1' : ''}">
				<div class="flex items-center gap-2 shrink-0">
					<div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
						{done ? 'bg-green-600 text-white' : active ? 'bg-gold text-navy' : 'bg-navy-700 text-slate-500 border border-navy-600'}">
						{#if done}✓{:else}{s}{/if}
					</div>
					<span class="text-xs {active ? 'text-slate-200 font-medium' : done ? 'text-slate-400' : 'text-slate-600'}" aria-current={active ? 'step' : undefined}>{label}</span>
				</div>
				{#if i < STEP_LABELS.length - 1}
					<div class="flex-1 h-px mx-3 {done ? 'bg-green-800' : 'bg-navy-700'}"></div>
				{/if}
			</div>
		{/each}
	</div>

	<!-- ── Step 1: Details ─────────────────────────────────────────────────── -->
	{#if step === 1}
		<form onsubmit={createCampaign} class="bg-navy-800 border border-navy-700 rounded-xl p-6 space-y-5">

			{#if data.teams?.length > 0}
				<div>
					<p class="text-sm text-slate-400 mb-2">Team <span class="text-slate-600">(optional)</span></p>
					<div class="flex flex-wrap gap-2" role="group" aria-label="Select team">
						<button type="button" onclick={() => (selectedTeamId = null)}
							aria-pressed={selectedTeamId === null}
							class="text-xs px-3 py-1.5 rounded-full border transition-colors
								{selectedTeamId === null ? 'bg-gold text-navy border-gold font-semibold' : 'border-navy-600 text-slate-400 hover:border-navy-500'}">
							Personal
						</button>
						{#each data.teams as team (team.id)}
							<button type="button" onclick={() => (selectedTeamId = team.id)}
								aria-pressed={selectedTeamId === team.id}
								class="text-xs px-3 py-1.5 rounded-full border transition-colors
									{selectedTeamId === team.id ? 'bg-gold text-navy border-gold font-semibold' : 'border-navy-600 text-slate-400 hover:border-navy-500'}">
								{team.display_name}
							</button>
						{/each}
					</div>
					{#if selectedTeamId}
						<p class="text-xs text-slate-500 mt-1.5">All team members will have access.</p>
					{/if}
				</div>
			{/if}

			<div>
				<label class="block text-sm text-slate-400 mb-1" for="name">Campaign Name *</label>
				<input id="name" type="text" bind:value={name} required placeholder="e.g. Q1 Portfolio Review"
					class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-slate-200
					       placeholder-slate-500 focus:outline-none focus:border-gold" />
			</div>

			<div>
				<label class="block text-sm text-slate-400 mb-1" for="desc">Description <span class="text-slate-600">(optional)</span></label>
				<textarea id="desc" bind:value={description} rows="2" placeholder="What is this campaign validating?"
					class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-slate-200
					       placeholder-slate-500 focus:outline-none focus:border-gold resize-none"></textarea>
			</div>

			<div>
				<p class="text-sm text-slate-400 mb-2">Schedule <span class="text-slate-600">(optional)</span></p>
				<SchedulePicker bind:value={schedule} />
			</div>

			{#if createError}
				<p class="text-red-400 text-sm">{createError}</p>
			{/if}

			<div class="flex gap-3 pt-1">
				<button type="submit" disabled={creating}
					class="bg-gold text-navy font-semibold px-5 py-2 rounded-lg hover:bg-gold-light transition-colors disabled:opacity-50">
					{creating ? 'Creating…' : 'Create & Continue →'}
				</button>
				<a href="/campaigns" class="bg-navy-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-navy-600 transition-colors border border-navy-600">
					Cancel
				</a>
			</div>
		</form>

	<!-- ── Step 2: Entities ────────────────────────────────────────────────── -->
	{:else if step === 2 && campaign}
		<div class="space-y-4">
			<div class="bg-navy-800 border border-navy-700 rounded-xl p-5">
				<div class="flex items-center justify-between mb-4">
					<div>
						<h2 class="font-medium text-slate-200">Add Entities</h2>
						<p class="text-xs text-slate-500 mt-0.5">The companies, people, or funds you want to research.</p>
					</div>
					{#if entityCount > 0}
						<span class="text-sm text-green-400 font-medium">{entityCount} added</span>
					{/if}
				</div>

				<!-- Quick add -->
				<form onsubmit={quickAddEntity} class="flex gap-2 mb-4">
					<input bind:value={entityLabel} placeholder="Entity name *" required
						aria-label="Entity name"
						class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
						       placeholder-slate-500 focus:outline-none focus:border-gold" />
					<input bind:value={entityDesc} placeholder="Description (optional)"
						aria-label="Entity description"
						class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
						       placeholder-slate-500 focus:outline-none focus:border-gold" />
					<button type="submit" disabled={addingEntity || !entityLabel.trim()}
						class="bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg text-sm hover:bg-navy-600 disabled:opacity-50 shrink-0">
						{addingEntity ? '…' : '+ Add'}
					</button>
				</form>
				{#if entityError}<p class="text-red-400 text-xs mb-2">{entityError}</p>{/if}

				<!-- Import options -->
				<div class="flex items-center gap-4">
					<button onclick={() => (showEntityUpload = !showEntityUpload)}
						class="text-xs text-gold hover:text-gold-light underline transition-colors">
						{showEntityUpload ? 'Hide' : '↑ Upload CSV / Excel instead'}
					</button>
					<button onclick={openEntityLibrary}
						class="text-xs text-gold hover:text-gold-light underline transition-colors">
						{showEntityLibrary ? 'Hide library' : '↗ Import from Library'}
					</button>
				</div>

				{#if showEntityUpload}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<CSVUpload
							campaignId={campaign.id}
							onUploaded={async () => {
								showEntityUpload = false;
								const resp = await entitiesApi.list(campaign!.id, { limit: 0 });
								entityCount = resp.total;
							}}
						/>
					</div>
				{/if}

				{#if showEntityLibrary}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<input
							bind:value={libEntitySearch}
							oninput={() => { libEntityPage = 0; _libEntitiesLoaded = false; loadLibraryEntities(); _libEntitiesLoaded = true; }}
							placeholder="Search library entities…"
							aria-label="Search library entities"
							class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold mb-2"
						/>
						{#if libraryEntities.length === 0}
							<p class="text-xs text-slate-500 italic">
								{libEntitySearch ? 'No matches.' : 'No entities in your library yet.'} <a href="/entities" class="text-gold hover:underline">Add some →</a>
							</p>
						{:else}
							<p class="text-xs text-slate-400 mb-2">Showing {libraryEntities.length} of {libEntityTotal} — select entities to import:</p>
							<div class="max-h-48 overflow-y-auto space-y-1 mb-3">
								{#each libraryEntities as lib (lib.id)}
									<label class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-navy-700 cursor-pointer">
										<input type="checkbox" checked={libraryEntitySelectedIds.has(lib.id)}
											onchange={() => toggleLibraryEntity(lib.id)} class="accent-gold" />
										<span class="text-slate-200 text-sm">{lib.label}</span>
										{#if lib.gwm_id}<span class="text-slate-500 font-mono text-xs">{lib.gwm_id}</span>{/if}
										{#if lib.description}<span class="text-slate-500 text-xs truncate">{lib.description}</span>{/if}
									</label>
								{/each}
							</div>
							{#if libEntityTotal > libPageSize}
								<div class="flex items-center gap-2 mb-3">
									<button onclick={() => { libEntityPage = Math.max(0, libEntityPage - 1); loadLibraryEntities(); }}
										disabled={libEntityPage === 0}
										class="text-xs px-2 py-1 border border-navy-600 rounded text-slate-400 hover:text-slate-200 disabled:opacity-30">← Prev</button>
									<span class="text-xs text-slate-500">Page {libEntityPage + 1} of {Math.ceil(libEntityTotal / libPageSize)}</span>
									<button onclick={() => { libEntityPage++; loadLibraryEntities(); }}
										disabled={libEntityPage >= Math.ceil(libEntityTotal / libPageSize) - 1}
										class="text-xs px-2 py-1 border border-navy-600 rounded text-slate-400 hover:text-slate-200 disabled:opacity-30">Next →</button>
								</div>
							{/if}
							<button onclick={importFromEntityLibrary}
								disabled={libraryEntitySelectedIds.size === 0 || importingEntityLib}
								class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-xs hover:bg-gold-light disabled:opacity-50">
								{importingEntityLib ? 'Importing…' : `Import Selected (${libraryEntitySelectedIds.size})`}
							</button>
						{/if}
					</div>
				{/if}
			</div>

			<div class="flex items-center justify-between">
				<p class="text-xs text-slate-500">You can always add more entities from the campaign page.</p>
				<div class="flex gap-2">
					<button onclick={() => (step = 3)}
						class="text-slate-400 hover:text-slate-300 text-sm px-4 py-2 rounded-lg border border-navy-700 hover:border-navy-600 transition-colors">
						{entityCount === 0 ? 'Skip for now' : 'Next →'}
					</button>
				</div>
			</div>
		</div>

	<!-- ── Step 3: Attributes ──────────────────────────────────────────────── -->
	{:else if step === 3 && campaign}
		<div class="space-y-4">
			<div class="bg-navy-800 border border-navy-700 rounded-xl p-5">
				<div class="flex items-center justify-between mb-4">
					<div>
						<h2 class="font-medium text-slate-200">Add Attributes</h2>
						<p class="text-xs text-slate-500 mt-0.5">The criteria to validate for each entity (e.g. "Has board experience").</p>
					</div>
					{#if attrCount > 0}
						<span class="text-sm text-green-400 font-medium">{attrCount} added</span>
					{/if}
				</div>

				<!-- Quick add -->
				<form onsubmit={quickAddAttr} class="mb-4 space-y-2">
					<div class="flex gap-2">
						<input bind:value={attrLabel} placeholder="Attribute name *" required
							aria-label="Attribute name"
							class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
							       placeholder-slate-500 focus:outline-none focus:border-gold" />
						<input bind:value={attrDesc} placeholder="Description / LLM prompt (optional)"
							aria-label="Attribute description"
							class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
							       placeholder-slate-500 focus:outline-none focus:border-gold" />
						<input type="number" bind:value={attrWeight} min="0" step="0.1" placeholder="Weight"
							class="w-20 bg-navy-700 border border-navy-600 rounded-lg px-2 py-1.5 text-sm text-slate-200
							       focus:outline-none focus:border-gold" />
						<button type="submit" disabled={addingAttr || !attrLabel.trim()}
							class="bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg text-sm hover:bg-navy-600 disabled:opacity-50 shrink-0">
							{addingAttr ? '…' : '+ Add'}
						</button>
					</div>
				</form>
				{#if attrError}<p class="text-red-400 text-xs mb-2">{attrError}</p>{/if}

				<!-- Templates -->
				<div class="flex items-center gap-3 mb-3">
					<button
						onclick={() => { showTemplates = !showTemplates; loadTemplates(); }}
						class="text-xs text-gold hover:text-gold-light transition-colors underline"
					>
						{showTemplates ? 'Hide templates' : '📋 Load from template'}
					</button>
					{#if attrCount > 0}
						<div class="flex items-center gap-1.5 ml-auto">
							<input bind:value={templateName} placeholder="Template name…" aria-label="Template name" class="bg-navy-700 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold w-36" />
							<button onclick={saveTemplate} disabled={savingTemplate || !templateName.trim()} class="text-xs text-slate-400 hover:text-gold border border-navy-600 px-2 py-1 rounded transition-colors disabled:opacity-50">
								{savingTemplate ? '…' : 'Save as template'}
							</button>
						</div>
					{/if}
				</div>

				{#if showTemplates}
					<div class="mb-3 bg-navy-900 border border-navy-700 rounded-lg p-3">
						{#if templates.length === 0}
							<p class="text-xs text-slate-500 italic">No templates saved yet. Add attributes and save them as a template.</p>
						{:else}
							<div class="space-y-1.5">
								{#each templates as tpl (tpl.id)}
									<button onclick={() => applyTemplate(tpl)} class="w-full flex items-center justify-between px-3 py-2 bg-navy-800 border border-navy-700 rounded-lg hover:border-gold/30 hover:text-gold text-left transition-all group">
										<div>
											<p class="text-sm text-slate-200 group-hover:text-gold">{tpl.name}</p>
											<p class="text-xs text-slate-500">{tpl.attributes.length} attributes</p>
										</div>
										<span class="text-xs text-slate-600 group-hover:text-gold">Apply →</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Import options -->
				<div class="flex items-center gap-4">
					<button onclick={() => (showAttrUpload = !showAttrUpload)}
						class="text-xs text-gold hover:text-gold-light underline transition-colors">
						{showAttrUpload ? 'Hide' : '↑ Upload CSV / Excel instead'}
					</button>
					<button onclick={openAttrLibrary}
						class="text-xs text-gold hover:text-gold-light underline transition-colors">
						{showAttrLibrary ? 'Hide library' : '↗ Import from Library'}
					</button>
				</div>

				{#if showAttrUpload}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<AttributeCSVUpload
							campaignId={campaign.id}
							onUploaded={async () => {
								showAttrUpload = false;
								const resp = await attributesApi.list(campaign!.id, { limit: 0 });
								attrCount = resp.total;
							}}
						/>
					</div>
				{/if}

				{#if showAttrLibrary}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<input
							bind:value={libAttrSearch}
							oninput={() => { libAttrPage = 0; _libAttrsLoaded = false; loadLibraryAttrs(); _libAttrsLoaded = true; }}
							placeholder="Search library attributes…"
							aria-label="Search library attributes"
							class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold mb-2"
						/>
						{#if libraryAttrs.length === 0}
							<p class="text-xs text-slate-500 italic">
								{libAttrSearch ? 'No matches.' : 'No attributes in your library yet.'} <a href="/attributes" class="text-gold hover:underline">Add some →</a>
							</p>
						{:else}
							<p class="text-xs text-slate-400 mb-2">Showing {libraryAttrs.length} of {libAttrTotal} — select attributes to import:</p>
							<div class="max-h-48 overflow-y-auto space-y-1 mb-3">
								{#each libraryAttrs as lib (lib.id)}
									<label class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-navy-700 cursor-pointer">
										<input type="checkbox" checked={libraryAttrSelectedIds.has(lib.id)}
											onchange={() => toggleLibraryAttr(lib.id)} class="accent-gold" />
										<span class="text-slate-200 text-sm">{lib.label}</span>
										<span class="text-slate-500 font-mono text-xs">×{lib.weight.toFixed(1)}</span>
										{#if lib.description}<span class="text-slate-500 text-xs truncate">{lib.description}</span>{/if}
									</label>
								{/each}
							</div>
							{#if libAttrTotal > libPageSize}
								<div class="flex items-center gap-2 mb-3">
									<button onclick={() => { libAttrPage = Math.max(0, libAttrPage - 1); loadLibraryAttrs(); }}
										disabled={libAttrPage === 0}
										class="text-xs px-2 py-1 border border-navy-600 rounded text-slate-400 hover:text-slate-200 disabled:opacity-30">← Prev</button>
									<span class="text-xs text-slate-500">Page {libAttrPage + 1} of {Math.ceil(libAttrTotal / libPageSize)}</span>
									<button onclick={() => { libAttrPage++; loadLibraryAttrs(); }}
										disabled={libAttrPage >= Math.ceil(libAttrTotal / libPageSize) - 1}
										class="text-xs px-2 py-1 border border-navy-600 rounded text-slate-400 hover:text-slate-200 disabled:opacity-30">Next →</button>
								</div>
							{/if}
							<button onclick={importFromAttrLibrary}
								disabled={libraryAttrSelectedIds.size === 0 || importingAttrLib}
								class="bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg text-xs hover:bg-gold-light disabled:opacity-50">
								{importingAttrLib ? 'Importing…' : `Import Selected (${libraryAttrSelectedIds.size})`}
							</button>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Summary -->
			{#if entityCount > 0 && attrCount > 0}
				<div class="bg-navy-800/50 border border-navy-700 rounded-lg px-4 py-3 text-sm text-slate-400">
					Running this campaign will validate
					<span class="text-slate-200 font-medium">{entityCount} {entityCount === 1 ? 'entity' : 'entities'}</span>
					×
					<span class="text-slate-200 font-medium">{attrCount} {attrCount === 1 ? 'attribute' : 'attributes'}</span>
					=
					<span class="text-gold font-semibold">{entityCount * attrCount} pairs</span>
					(all included by default).
				</div>
			{/if}

			<div class="flex items-center justify-between">
				<button onclick={() => (step = 2)} class="text-slate-500 hover:text-slate-400 text-sm transition-colors">← Back</button>
				<div class="flex gap-2">
					<button onclick={finish}
						class="bg-gold text-navy font-semibold px-5 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm">
						{attrCount === 0 ? 'Skip & Go to Campaign →' : 'Done →'}
					</button>
				</div>
			</div>
		</div>
	{/if}
</div>
