<script lang="ts">
	import { onMount } from 'svelte';
	import {
		kgApi,
		type KGEntity,
		type KGRelationship,
		type KGStats,
	} from '$lib/api/knowledgeGraph';

	let entities = $state<KGEntity[]>([]);
	let stats = $state<KGStats | null>(null);
	let total = $state(0);
	let loading = $state(true);
	let error = $state('');

	let searchQuery = $state('');
	let typeFilter = $state('');
	let currentPage = $state(0);
	const pageSize = 50;

	// Expanded entity relationships
	let expandedId = $state<string | null>(null);
	let relationships = $state<KGRelationship[]>([]);
	let loadingRels = $state(false);

	onMount(async () => {
		try {
			const [entitiesResult, statsResult] = await Promise.all([
				kgApi.listEntities({ limit: pageSize, offset: 0 }),
				kgApi.getStats(),
			]);
			entities = entitiesResult.items;
			total = entitiesResult.total;
			stats = statsResult;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load';
		} finally {
			loading = false;
		}
	});

	async function doSearch() {
		loading = true;
		currentPage = 0;
		try {
			const result = await kgApi.listEntities({
				search: searchQuery || undefined,
				entity_type: typeFilter || undefined,
				limit: pageSize,
				offset: 0,
			});
			entities = result.items;
			total = result.total;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Search failed';
		} finally {
			loading = false;
		}
	}

	async function goToPage(p: number) {
		loading = true;
		currentPage = p;
		try {
			const result = await kgApi.listEntities({
				search: searchQuery || undefined,
				entity_type: typeFilter || undefined,
				limit: pageSize,
				offset: p * pageSize,
			});
			entities = result.items;
			total = result.total;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load page';
		} finally {
			loading = false;
		}
	}

	async function toggleExpand(entityId: string) {
		if (expandedId === entityId) {
			expandedId = null;
			return;
		}
		expandedId = entityId;
		loadingRels = true;
		try {
			relationships = await kgApi.getRelationships(entityId);
		} catch {
			relationships = [];
		} finally {
			loadingRels = false;
		}
	}

	function typeColor(type: string): string {
		const colors: Record<string, string> = {
			PERSON: 'bg-blue-900 text-blue-300',
			ORGANIZATION: 'bg-purple-900 text-purple-300',
			COMPANY: 'bg-purple-900 text-purple-300',
			SPORTS_TEAM: 'bg-orange-900 text-orange-300',
			LOCATION: 'bg-green-900 text-green-300',
			EVENT: 'bg-gold/10 text-gold',
			PRODUCT: 'bg-yellow-900 text-yellow-300',
			CONCEPT: 'bg-slate-700 text-slate-300',
		};
		return colors[type.toUpperCase()] ?? 'bg-navy-700 text-slate-400';
	}

	let totalPages = $derived(Math.ceil(total / pageSize));
</script>

<svelte:head>
	<title>Knowledge Graph — Playbook Research</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 py-8">
	<div class="flex items-center justify-between mb-6">
		<div>
			<h1 class="font-serif text-xl text-slate-100">Knowledge Graph</h1>
			<p class="text-sm text-slate-500 mt-1">Entities and relationships extracted from research sessions.</p>
		</div>
		<div class="flex items-center gap-2">
			<a href="/knowledge-graph/explore"
				class="text-xs bg-gold text-navy font-semibold px-3 py-1.5 rounded-lg hover:bg-gold-light transition-colors">
				Explore Graph
			</a>
			<a href="/knowledge-graph/conflicts"
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-navy-600 transition-colors">
				View Conflicts
			</a>
		</div>
	</div>

	<!-- Stats -->
	{#if stats}
		<dl class="grid grid-cols-4 gap-4 mb-6">
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-3 text-center">
				<dd class="text-xl font-bold text-slate-200">{stats.total_entities}</dd>
				<dt class="text-xs text-slate-500 mt-0.5">Entities</dt>
			</div>
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-3 text-center">
				<dd class="text-xl font-bold text-slate-200">{stats.total_relationships}</dd>
				<dt class="text-xs text-slate-500 mt-0.5">Relationships</dt>
			</div>
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-3 text-center">
				<dd class="text-xl font-bold text-slate-200">{stats.entity_types}</dd>
				<dt class="text-xs text-slate-500 mt-0.5">Entity Types</dt>
			</div>
			<div class="bg-navy-800 border border-navy-700 rounded-lg p-3 text-center">
				<dd class="text-xl font-bold text-slate-200">{stats.total_conflicts}</dd>
				<dt class="text-xs text-slate-500 mt-0.5">Conflicts</dt>
			</div>
		</dl>
	{/if}

	<!-- Search bar -->
	<div class="flex gap-3 mb-6">
		<input
			bind:value={searchQuery}
			onkeydown={(e) => e.key === 'Enter' && doSearch()}
			placeholder="Search entities..."
			class="flex-1 bg-navy-800 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
		<input
			bind:value={typeFilter}
			onkeydown={(e) => e.key === 'Enter' && doSearch()}
			placeholder="Type filter"
			class="w-40 bg-navy-800 border border-navy-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
		/>
		<button onclick={doSearch}
			class="bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm">
			Search
		</button>
	</div>

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading...</p>
	{:else if entities.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No knowledge graph entities found.</p>
		</div>
	{:else}
		<div class="space-y-2">
			{#each entities as entity (entity.id)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl">
					<button
						onclick={() => toggleExpand(entity.id)}
						class="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-navy-700/40 transition-colors rounded-xl"
					>
						<span class="text-xs px-2 py-0.5 rounded font-medium {typeColor(entity.entity_type)}">
							{entity.entity_type}
						</span>
						<span class="text-sm font-medium text-slate-200 flex-1">{entity.name}</span>
						{#if entity.aliases.length > 0}
							<span class="text-xs text-slate-600">aka {entity.aliases.slice(0, 2).join(', ')}</span>
						{/if}
						<span class="text-xs text-slate-500">{entity.relationship_count} rels</span>
						<span class="text-slate-600 text-xs">{expandedId === entity.id ? '−' : '+'}</span>
					</button>

					{#if expandedId === entity.id}
						<div class="px-4 pb-3 border-t border-navy-700">
							{#if loadingRels}
								<p class="text-xs text-slate-500 py-2">Loading relationships...</p>
							{:else if relationships.length === 0}
								<p class="text-xs text-slate-600 py-2">No relationships.</p>
							{:else}
								<div class="space-y-1 mt-2">
									{#each relationships as rel (rel.id)}
										<div class="flex items-center gap-2 text-xs py-1">
											<span class="text-slate-300">{rel.subject_name}</span>
											<span class="text-gold font-medium px-1.5 py-0.5 bg-gold/5 rounded">{rel.predicate}</span>
											<span class="text-slate-300">{rel.object_name}</span>
											{#if rel.confidence < 1}
												<span class="text-slate-600">({(rel.confidence * 100).toFixed(0)}%)</span>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Pagination -->
		{#if totalPages > 1}
			<div class="flex items-center justify-center gap-2 mt-6">
				<button
					onclick={() => goToPage(currentPage - 1)}
					disabled={currentPage === 0}
					class="text-xs px-3 py-1.5 rounded border border-navy-600 text-slate-400 hover:text-gold disabled:opacity-30 transition-colors"
				>
					Previous
				</button>
				<span class="text-xs text-slate-500">
					Page {currentPage + 1} of {totalPages} ({total} entities)
				</span>
				<button
					onclick={() => goToPage(currentPage + 1)}
					disabled={currentPage >= totalPages - 1}
					class="text-xs px-3 py-1.5 rounded border border-navy-600 text-slate-400 hover:text-gold disabled:opacity-30 transition-colors"
				>
					Next
				</button>
			</div>
		{/if}
	{/if}
</div>
