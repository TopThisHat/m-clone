<script lang="ts">
	import { goto } from '$app/navigation';
	import { campaignsApi, type Campaign } from '$lib/api/campaigns';
	import { entitiesApi, type EntityCreate } from '$lib/api/entities';
	import { attributesApi, type AttributeCreate } from '$lib/api/attributes';
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

	// Step 3 — attributes
	let attrLabel = $state('');
	let attrDesc = $state('');
	let attrWeight = $state(1.0);
	let attrCount = $state(0);
	let addingAttr = $state(false);
	let attrError = $state('');
	let showAttrUpload = $state(false);

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
			const attrs = await attributesApi.list(campaign.id);
			await templatesApi.create({ name: templateName.trim(), attributes: attrs.map((a) => ({ label: a.label, description: a.description ?? undefined, weight: a.weight })) });
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
					<span class="text-xs {active ? 'text-slate-200 font-medium' : done ? 'text-slate-400' : 'text-slate-600'}">{label}</span>
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
					<div class="flex flex-wrap gap-2">
						<button type="button" onclick={() => (selectedTeamId = null)}
							class="text-xs px-3 py-1.5 rounded-full border transition-colors
								{selectedTeamId === null ? 'bg-gold text-navy border-gold font-semibold' : 'border-navy-600 text-slate-400 hover:border-navy-500'}">
							Personal
						</button>
						{#each data.teams as team (team.id)}
							<button type="button" onclick={() => (selectedTeamId = team.id)}
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
						class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
						       placeholder-slate-500 focus:outline-none focus:border-gold" />
					<input bind:value={entityDesc} placeholder="Description (optional)"
						class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
						       placeholder-slate-500 focus:outline-none focus:border-gold" />
					<button type="submit" disabled={addingEntity || !entityLabel.trim()}
						class="bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg text-sm hover:bg-navy-600 disabled:opacity-50 shrink-0">
						{addingEntity ? '…' : '+ Add'}
					</button>
				</form>
				{#if entityError}<p class="text-red-400 text-xs mb-2">{entityError}</p>{/if}

				<!-- CSV upload toggle -->
				<button onclick={() => (showEntityUpload = !showEntityUpload)}
					class="text-xs text-gold hover:text-gold-light underline transition-colors">
					{showEntityUpload ? 'Hide' : '↑ Upload CSV / Excel instead'}
				</button>

				{#if showEntityUpload}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<CSVUpload
							campaignId={campaign.id}
							onUploaded={async () => {
								showEntityUpload = false;
								const all = await entitiesApi.list(campaign!.id);
								entityCount = all.length;
							}}
						/>
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
							class="flex-1 bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
							       placeholder-slate-500 focus:outline-none focus:border-gold" />
						<input bind:value={attrDesc} placeholder="Description / LLM prompt (optional)"
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
							<input bind:value={templateName} placeholder="Template name…" class="bg-navy-700 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold w-36" />
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

				<!-- CSV upload toggle -->
				<button onclick={() => (showAttrUpload = !showAttrUpload)}
					class="text-xs text-gold hover:text-gold-light underline transition-colors">
					{showAttrUpload ? 'Hide' : '↑ Upload CSV / Excel instead'}
				</button>

				{#if showAttrUpload}
					<div class="mt-3 border-t border-navy-700 pt-3">
						<AttributeCSVUpload
							campaignId={campaign.id}
							onUploaded={async () => {
								showAttrUpload = false;
								const all = await attributesApi.list(campaign!.id);
								attrCount = all.length;
							}}
						/>
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
