<script lang="ts">
	import {
		kgApi,
		type KGEntity,
		type KGRelationship,
		type KGStats,
	} from '$lib/api/knowledgeGraph';
	import { listTeams, type Team } from '$lib/api/teams';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import Pagination from '$lib/components/Pagination.svelte';
	import TeamBadge from '$lib/components/TeamBadge.svelte';

	let entities = $state<KGEntity[]>([]);
	let stats = $state<KGStats | null>(null);
	let total = $state(0);
	let loading = $state(true);
	let error = $state('');
	let teams = $state<Team[]>([]);

	let searchQuery = $state('');
	let typeFilter = $state('');
	let currentPage = $state(0);
	let pageSize = $state(50);

	// Expanded entity relationships
	let expandedId = $state<string | null>(null);
	let relationships = $state<KGRelationship[]>([]);
	let loadingRels = $state(false);

	// Derive the current team's display name from the teams list
	let currentTeamName = $derived(
		$scoutTeam
			? (teams.find((t) => t.id === $scoutTeam)?.display_name ?? null)
			: null
	);

	// Derive whether the user has any teams at all
	let hasTeams = $derived(teams.length > 0);

	// Load teams list once on mount (teams don't change mid-session)
	$effect(() => {
		listTeams().then((t) => {
			teams = t;
		});
	});

	// Reactive data fetching — re-runs whenever scoutTeam changes
	let controller: AbortController | null = null;

	$effect(() => {
		const teamId = $scoutTeam ?? undefined;

		controller?.abort();
		controller = new AbortController();

		loading = true;
		error = '';
		entities = [];
		stats = null;
		currentPage = 0;

		Promise.all([
			kgApi.listEntities({ team_id: teamId, limit: pageSize, offset: 0 }),
			kgApi.getStats(teamId),
		])
			.then(([entitiesResult, statsResult]) => {
				entities = entitiesResult.items;
				total = entitiesResult.total;
				stats = statsResult;
			})
			.catch((err: unknown) => {
				if (err instanceof Error && err.name === 'AbortError') return;
				error = err instanceof Error ? err.message : 'Failed to load';
			})
			.finally(() => {
				loading = false;
			});
	});

	async function doSearch() {
		loading = true;
		currentPage = 0;
		try {
			const result = await kgApi.listEntities({
				search: searchQuery || undefined,
				entity_type: typeFilter || undefined,
				team_id: $scoutTeam ?? undefined,
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
				team_id: $scoutTeam ?? undefined,
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
			PERSON: 'bg-[#1B365D] text-blue-200',
			ORGANIZATION: 'bg-[#1A5276] text-teal-200',
			COMPANY: 'bg-[#1A5276] text-teal-200',
			SPORTS_TEAM: 'bg-[#8B6914]/20 text-amber-300',
			LOCATION: 'bg-[#1E6E3E] text-green-200',
			EVENT: 'bg-gold/10 text-gold',
			PRODUCT: 'bg-[#5D6D7E] text-slate-200',
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
	<div class="flex items-center justify-between mb-2">
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

	<!-- Team badge -->
	<div class="mb-6" data-testid="kg-team-badge-wrapper">
		<TeamBadge teamName={currentTeamName} size="sm" />
	</div>

	<!-- Team gate: users with no team see a prompt -->
	{#if !loading && !hasTeams}
		<div class="text-center py-16 border border-navy-700 rounded-xl bg-navy-800/50">
			<svg class="w-10 h-10 text-slate-600 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
					d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
			</svg>
			<p class="text-slate-400 font-medium mb-1">Join or create a team to access Knowledge Graph data.</p>
			<p class="text-sm text-slate-600 mb-4">Knowledge Graph data is scoped to teams.</p>
			<a href="/teams" class="inline-flex items-center gap-1.5 text-sm bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors">
				Go to Teams
			</a>
		</div>
	{:else}
		<!-- Stats -->
		<dl class="grid grid-cols-4 gap-4 mb-6">
			{#if loading || stats === null}
				{#each [0, 1, 2, 3] as i (i)}
					<div class="bg-navy-800 border border-navy-700 rounded-lg p-3 text-center animate-pulse">
						<dd class="text-xl font-bold text-slate-700">--</dd>
						<dt class="text-xs text-slate-600 mt-0.5">Loading</dt>
					</div>
				{/each}
			{:else}
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
			{/if}
		</dl>

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
			<!-- Skeleton rows during team switch -->
			<div class="space-y-2" aria-busy="true" aria-label="Loading entities">
				{#each [0, 1, 2, 3, 4] as i (i)}
					<div class="bg-navy-800 border border-navy-700 rounded-xl px-4 py-3 flex items-center gap-3 animate-pulse">
						<span class="w-16 h-4 bg-navy-700 rounded"></span>
						<span class="flex-1 h-4 bg-navy-700 rounded"></span>
						<span class="w-12 h-3 bg-navy-700 rounded"></span>
					</div>
				{/each}
			</div>
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
							{#if entity.aliases?.length > 0}
								<span class="text-xs text-slate-600">aka {(entity.aliases ?? []).slice(0, 2).join(', ')}</span>
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
			<div class="mt-4 bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
				<Pagination
					{total}
					{pageSize}
					{currentPage}
					onPageChange={(p) => goToPage(p)}
					onPageSizeChange={(size) => { pageSize = size; goToPage(0); }}
				/>
			</div>
		{/if}
	{/if}
</div>
