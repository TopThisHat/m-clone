<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import ForceGraph from '$lib/components/ForceGraph.svelte';
	import { theme } from '$lib/stores/themeStore';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import { currentUser } from '$lib/stores/authStore';
	import {
		kgApi,
		type KGGraph,
		type DealPartnerGroup,
		type KGRelationship,
		type KGQueryResult,
	} from '$lib/api/knowledgeGraph';

	const ENTITY_TYPES = ['person', 'company', 'sports_team', 'location', 'product', 'other'];
	const PREDICATE_FAMILIES = ['ownership', 'employment', 'transaction', 'location', 'partnership'];

	const NODE_COLORS: Record<string, string> = {
		person: '#1B365D',
		company: '#1A5276',
		sports_team: '#8B6914',
		location: '#1E6E3E',
		product: '#5D6D7E',
		other: '#7B8794',
	};

	// --------------- Core state ---------------
	let graphData = $state<KGGraph>({ nodes: [], edges: [] });
	let dealPartners = $state<DealPartnerGroup[]>([]);
	let loading = $state(true);
	let error = $state('');
	let teamId = $state<string | null>(null);
	let user = $state<{ sid: string; display_name: string; email: string; is_super_admin?: boolean } | null>(null);

	// --------------- Filters ---------------
	let searchQuery = $state('');
	let selectedTypes = new SvelteSet<string>();
	let selectedFamilies = new SvelteSet<string>();
	let dealModeActive = $state(false);

	// Advanced filters
	let advancedOpen = $state(false);
	let metadataKey = $state('');
	let metadataValue = $state('');

	// --------------- Selection state ---------------
	let selectedNodeId = $state<string | null>(null);
	let focusNodeId = $state<string | null>(null);
	let selectedNodeRels = $state<KGRelationship[]>([]);
	let loadingRels = $state(false);

	// --------------- Edit state ---------------
	let editingEntity = $state(false);
	let editForm = $state({ name: '', entity_type: '', description: '', aliases: '' });
	let entitySaving = $state(false);
	let deleteConfirmEntity = $state(false);
	let entityDeleting = $state(false);

	// Relationship editing
	let editingRelId = $state<string | null>(null);
	let editRelPredicate = $state('');
	let relSaving = $state(false);
	let deleteConfirmRelId = $state<string | null>(null);
	let relDeleting = $state(false);

	// --------------- Query panel ---------------
	let queryPanelOpen = $state(false);
	let queryInput = $state('');
	let queryLoading = $state(false);
	let queryResult = $state<KGQueryResult | null>(null);
	let queryError = $state('');

	// --------------- Derived ---------------
	let isAdmin = $derived(user?.is_super_admin === true);

	let highlightedNodeIds = $derived.by(() => {
		if (!dealModeActive || dealPartners.length === 0) return null;
		const ids = new Set<string>();
		for (const dp of dealPartners) {
			ids.add(dp.person1.id);
			ids.add(dp.person2.id);
			for (const deal of dp.shared_deals) {
				ids.add(deal.entity_id);
			}
		}
		return ids;
	});

	let highlightedEdgeIds = $derived.by(() => {
		if (!dealModeActive || dealPartners.length === 0) return null;
		const dealEntityIds = new Set<string>();
		const personIds = new Set<string>();
		for (const dp of dealPartners) {
			personIds.add(dp.person1.id);
			personIds.add(dp.person2.id);
			for (const deal of dp.shared_deals) dealEntityIds.add(deal.entity_id);
		}
		const ids = new Set<string>();
		for (const e of graphData.edges) {
			if (e.predicate_family === 'transaction') {
				const s = e.source;
				const t = e.target;
				if (
					(personIds.has(s) && dealEntityIds.has(t)) ||
					(personIds.has(t) && dealEntityIds.has(s))
				) {
					ids.add(e.id);
				}
			}
		}
		return ids;
	});

	let selectedNode = $derived(
		selectedNodeId ? graphData.nodes.find((n) => n.id === selectedNodeId) ?? null : null
	);

	// --------------- Data fetching ---------------
	async function fetchGraph() {
		loading = true;
		error = '';
		try {
			const params: {
				entity_types?: string[];
				predicate_families?: string[];
				team_id?: string;
				search?: string;
				metadata_key?: string;
				metadata_value?: string;
			} = {};
			if (selectedTypes.size > 0) params.entity_types = [...selectedTypes];
			if (selectedFamilies.size > 0) params.predicate_families = [...selectedFamilies];
			if (teamId) params.team_id = teamId;
			if (searchQuery.trim()) params.search = searchQuery.trim();
			if (metadataKey.trim()) params.metadata_key = metadataKey.trim();
			if (metadataValue.trim()) params.metadata_value = metadataValue.trim();
			graphData = await kgApi.getGraph(params);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load graph';
		} finally {
			loading = false;
		}
	}

	function toggleType(type: string) {
		if (selectedTypes.has(type)) selectedTypes.delete(type);
		else selectedTypes.add(type);
		fetchGraph();
	}

	function toggleFamily(family: string) {
		if (selectedFamilies.has(family)) selectedFamilies.delete(family);
		else selectedFamilies.add(family);
		fetchGraph();
	}

	function handleSearch() {
		fetchGraph();
	}

	function applyAdvancedFilters() {
		fetchGraph();
	}

	function clearAdvancedFilters() {
		metadataKey = '';
		metadataValue = '';
		fetchGraph();
	}

	async function loadNodeRels(nodeId: string) {
		loadingRels = true;
		try {
			selectedNodeRels = await kgApi.getRelationships(nodeId);
		} catch {
			selectedNodeRels = [];
		} finally {
			loadingRels = false;
		}
	}

	function handleNodeClick(nodeId: string) {
		if (selectedNodeId === nodeId) {
			selectedNodeId = null;
			selectedNodeRels = [];
			editingEntity = false;
		} else {
			selectedNodeId = nodeId;
			editingEntity = false;
			editingRelId = null;
			loadNodeRels(nodeId);
		}
	}

	// --------------- Entity editing ---------------
	function startEditEntity() {
		if (!selectedNode) return;
		editForm = {
			name: selectedNode.name,
			entity_type: selectedNode.entity_type,
			description: selectedNode.description ?? '',
			aliases: selectedNode.aliases.join(', '),
		};
		editingEntity = true;
	}

	function cancelEditEntity() {
		editingEntity = false;
	}

	async function saveEntity() {
		if (!selectedNodeId) return;
		entitySaving = true;
		try {
			const aliasArray = editForm.aliases
				.split(',')
				.map((a) => a.trim())
				.filter(Boolean);
			await kgApi.updateEntity(selectedNodeId, {
				name: editForm.name,
				entity_type: editForm.entity_type,
				description: editForm.description,
				aliases: aliasArray,
			});
			editingEntity = false;
			await fetchGraph();
			if (selectedNodeId) loadNodeRels(selectedNodeId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to save entity';
		} finally {
			entitySaving = false;
		}
	}

	async function confirmDeleteEntity() {
		if (!selectedNodeId) return;
		entityDeleting = true;
		try {
			await kgApi.deleteEntity(selectedNodeId);
			selectedNodeId = null;
			selectedNodeRels = [];
			deleteConfirmEntity = false;
			editingEntity = false;
			await fetchGraph();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to delete entity';
		} finally {
			entityDeleting = false;
		}
	}

	// --------------- Relationship editing ---------------
	function startEditRel(rel: KGRelationship) {
		editingRelId = rel.id;
		editRelPredicate = rel.predicate;
	}

	function cancelEditRel() {
		editingRelId = null;
		editRelPredicate = '';
	}

	async function saveRel(relId: string) {
		relSaving = true;
		try {
			await kgApi.updateRelationship(relId, { predicate: editRelPredicate });
			editingRelId = null;
			if (selectedNodeId) loadNodeRels(selectedNodeId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to update relationship';
		} finally {
			relSaving = false;
		}
	}

	async function confirmDeleteRel(relId: string) {
		relDeleting = true;
		try {
			await kgApi.deleteRelationship(relId);
			deleteConfirmRelId = null;
			if (selectedNodeId) loadNodeRels(selectedNodeId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to delete relationship';
		} finally {
			relDeleting = false;
		}
	}

	// --------------- Query ---------------
	async function submitQuery() {
		if (!queryInput.trim()) return;
		queryLoading = true;
		queryError = '';
		queryResult = null;
		try {
			queryResult = await kgApi.queryGraph(queryInput.trim(), teamId ?? undefined);
		} catch (err: unknown) {
			queryError = err instanceof Error ? err.message : 'Query failed';
		} finally {
			queryLoading = false;
		}
	}

	// --------------- Helpers ---------------
	function typeColor(type: string): string {
		const colors: Record<string, string> = {
			person: 'bg-[#1B365D]',
			company: 'bg-[#1A5276]',
			sports_team: 'bg-[#8B6914]',
			location: 'bg-[#1E6E3E]',
			product: 'bg-[#5D6D7E]',
			other: 'bg-[#7B8794]',
		};
		return colors[type.toLowerCase()] ?? 'bg-[#7B8794]';
	}

	function typeLabel(type: string): string {
		const labels: Record<string, string> = {
			person: 'Person',
			company: 'Company',
			sports_team: 'Sports Team',
			location: 'Location',
			product: 'Product',
			other: 'Other',
		};
		return labels[type.toLowerCase()] ?? type;
	}

	function sourceBadgeClass(source: string): string {
		return source === 'team'
			? 'bg-gold/20 text-gold border-gold/30'
			: 'bg-slate-700/50 text-slate-300 border-slate-600';
	}

	// --------------- Lifecycle ---------------
	onMount(() => {
		const unsubTeam = scoutTeam.subscribe((v) => {
			teamId = v;
		});
		const unsubUser = currentUser.subscribe((v) => {
			user = v;
		});

		// Kick off data fetch (fire-and-forget from onMount's perspective)
		loadInitialData();

		return () => {
			unsubTeam();
			unsubUser();
		};
	});

	async function loadInitialData() {
		const params: { team_id?: string } = {};
		if (teamId) params.team_id = teamId;

		const [graphResult, dealResult] = await Promise.allSettled([
			kgApi.getGraph(params),
			kgApi.getDealPartners(),
		]);
		if (graphResult.status === 'fulfilled') graphData = graphResult.value;
		else error = 'Failed to load graph';
		if (dealResult.status === 'fulfilled') dealPartners = dealResult.value;
		loading = false;
	}
</script>

<svelte:head>
	<title>Graph Explorer — Knowledge Graph — Playbook Research</title>
</svelte:head>

<div class="flex flex-col h-[calc(100vh-4rem)]">
	<!-- Toolbar -->
	<div class="flex flex-wrap items-center gap-3 px-4 py-3 bg-navy-900 border-b border-navy-700">
		<a
			href="/knowledge-graph"
			class="text-xs text-slate-500 hover:text-gold transition-colors"
		>
			&larr; Back
		</a>

		<!-- Team scope indicator -->
		<span
			class="text-[10px] px-2 py-0.5 rounded border {teamId
				? 'border-gold/40 text-gold bg-gold/10'
				: 'border-slate-600 text-slate-400 bg-navy-800'}"
		>
			{teamId ? 'Team Graph' : 'All Graphs'}
		</span>

		<!-- Search -->
		<div class="flex items-center gap-1">
			<input
				bind:value={searchQuery}
				onkeydown={(e) => e.key === 'Enter' && handleSearch()}
				placeholder="Search name, alias, description..."
				class="bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-56"
			/>
			<button
				onclick={handleSearch}
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-2 py-1 rounded hover:bg-navy-600 transition-colors"
			>
				Find
			</button>
		</div>

		<!-- Type filters -->
		<div class="flex items-center gap-1">
			<span class="text-xs text-slate-500">Types:</span>
			{#each ENTITY_TYPES as type (type)}
				<button
					onclick={() => toggleType(type)}
					class="text-xs px-2 py-0.5 rounded border transition-colors {selectedTypes.has(type)
						? 'border-gold text-gold bg-gold/10'
						: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
				>
					{typeLabel(type)}
				</button>
			{/each}
		</div>

		<!-- Family filters -->
		<div class="flex items-center gap-1">
			<span class="text-xs text-slate-500">Relations:</span>
			{#each PREDICATE_FAMILIES as family (family)}
				<button
					onclick={() => toggleFamily(family)}
					class="text-xs px-2 py-0.5 rounded border transition-colors {selectedFamilies.has(family)
						? 'border-gold text-gold bg-gold/10'
						: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
				>
					{family}
				</button>
			{/each}
		</div>

		<!-- Deal Partners toggle -->
		<button
			onclick={() => (dealModeActive = !dealModeActive)}
			class="text-xs px-2.5 py-1 rounded border transition-colors {dealModeActive
				? 'border-[#C0922B] text-[#C0922B] bg-[#C0922B]/10'
				: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
		>
			Deal Partners {dealPartners.length > 0 ? `(${dealPartners.length})` : ''}
		</button>

		<!-- Advanced filter toggle -->
		<button
			onclick={() => (advancedOpen = !advancedOpen)}
			class="text-xs px-2.5 py-1 rounded border transition-colors {advancedOpen
				? 'border-gold text-gold bg-gold/10'
				: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
		>
			{advancedOpen ? 'Hide Filters' : 'More Filters'}
		</button>

		<!-- Query button -->
		<button
			onclick={() => (queryPanelOpen = !queryPanelOpen)}
			class="text-xs px-2.5 py-1 rounded border transition-colors {queryPanelOpen
				? 'border-gold text-gold bg-gold/10'
				: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
		>
			Query
		</button>

		<span class="text-xs text-slate-600 ml-auto">
			{graphData.nodes.length} nodes / {graphData.edges.length} edges
		</span>
	</div>

	<!-- Advanced Filters (collapsible) -->
	{#if advancedOpen}
		<div class="flex items-center gap-3 px-4 py-2 bg-navy-900/80 border-b border-navy-700">
			<span class="text-xs text-slate-500">Metadata:</span>
			<input
				bind:value={metadataKey}
				placeholder="Key"
				class="bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-32"
			/>
			<input
				bind:value={metadataValue}
				placeholder="Value"
				class="bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-32"
			/>
			<button
				onclick={applyAdvancedFilters}
				class="text-xs bg-navy-700 border border-navy-600 text-slate-300 px-2 py-1 rounded hover:bg-navy-600 transition-colors"
			>
				Apply
			</button>
			<button
				onclick={clearAdvancedFilters}
				class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
			>
				Clear
			</button>
		</div>
	{/if}

	<!-- Main content -->
	<div class="flex flex-1 min-h-0">
		<!-- Graph area -->
		<div class="flex-1 relative bg-navy-950">
			{#if loading}
				<div class="absolute inset-0 flex items-center justify-center">
					<p class="text-slate-500">Loading graph...</p>
				</div>
			{:else if error}
				<div class="absolute inset-0 flex items-center justify-center">
					<p class="text-red-400">{error}</p>
				</div>
			{:else if graphData.nodes.length === 0}
				<div class="absolute inset-0 flex items-center justify-center">
					<div class="text-center">
						<p class="text-slate-500">No graph data available.</p>
						<p class="text-xs text-slate-600 mt-1">
							Run some research sessions to populate the knowledge graph.
						</p>
					</div>
				</div>
			{:else}
				<ForceGraph
					nodes={graphData.nodes}
					edges={graphData.edges}
					{highlightedNodeIds}
					{highlightedEdgeIds}
					{focusNodeId}
					{selectedNodeId}
					theme={$theme}
					onNodeClick={handleNodeClick}
				/>
			{/if}
		</div>

		<!-- Query panel (slide-out) -->
		{#if queryPanelOpen}
			<div class="w-80 bg-navy-900 border-l border-navy-700 overflow-y-auto flex flex-col">
				<div class="flex items-center justify-between px-4 py-3 border-b border-navy-700">
					<h3 class="text-sm font-semibold text-slate-200">Graph Query</h3>
					<button
						onclick={() => (queryPanelOpen = false)}
						class="text-slate-500 hover:text-slate-300 text-xs"
					>
						&times;
					</button>
				</div>

				<div class="p-4 space-y-3 flex-1">
					<div class="flex gap-1">
						<input
							bind:value={queryInput}
							onkeydown={(e) => e.key === 'Enter' && submitQuery()}
							placeholder="Ask a question about the graph..."
							class="flex-1 bg-navy-800 border border-navy-600 rounded px-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
						/>
						<button
							onclick={submitQuery}
							disabled={queryLoading}
							class="text-xs px-3 py-1.5 rounded transition-colors {queryLoading
								? 'bg-navy-700 text-slate-500 cursor-not-allowed'
								: 'bg-gold/20 text-gold border border-gold/30 hover:bg-gold/30'}"
						>
							{queryLoading ? '...' : 'Ask'}
						</button>
					</div>

					{#if queryError}
						<p class="text-xs text-red-400">{queryError}</p>
					{/if}

					{#if queryResult}
						<!-- Sources used -->
						{#if queryResult.sources_used.length > 0}
							<div class="text-[10px] text-slate-500">
								Sources: {queryResult.sources_used.join(', ')}
							</div>
						{/if}

						<!-- Entities -->
						{#if queryResult.entities.length > 0}
							<div>
								<h4 class="text-xs font-semibold text-slate-400 mb-1.5">Entities</h4>
								<div class="space-y-1">
									{#each queryResult.entities as entity (entity.id)}
										<div class="text-xs bg-navy-800 rounded px-2 py-1.5 flex items-center gap-2">
											<span class="text-slate-200 truncate flex-1">{entity.name}</span>
											<span
												class="text-[10px] px-1.5 py-0.5 rounded border shrink-0 {sourceBadgeClass(entity.graph_source)}"
											>
												{entity.graph_source === 'team' ? 'Team' : 'Master'}
											</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}

						<!-- Relationships -->
						{#if queryResult.relationships.length > 0}
							<div>
								<h4 class="text-xs font-semibold text-slate-400 mb-1.5">
									Relationships
								</h4>
								<div class="space-y-1">
									{#each queryResult.relationships as rel (rel.id)}
										<div class="text-xs bg-navy-800 rounded px-2 py-1.5">
											<div class="flex items-center gap-1">
												<span class="text-slate-300 truncate">{rel.subject_name}</span>
												<span class="text-gold font-medium shrink-0">{rel.predicate}</span>
												<span class="text-slate-300 truncate">{rel.object_name}</span>
												<span
													class="text-[10px] px-1.5 py-0.5 rounded border shrink-0 ml-auto {sourceBadgeClass(rel.graph_source)}"
												>
													{rel.graph_source === 'team' ? 'Team' : 'Master'}
												</span>
											</div>
										</div>
									{/each}
								</div>
							</div>
						{/if}

						{#if queryResult.entities.length === 0 && queryResult.relationships.length === 0}
							<p class="text-xs text-slate-500">No results found.</p>
						{/if}
					{/if}
				</div>
			</div>
		{/if}

		<!-- Detail panel -->
		{#if selectedNode && !queryPanelOpen}
			<div class="w-80 bg-navy-900 border-l border-navy-700 overflow-y-auto p-4">
				<div class="flex items-center justify-between mb-3">
					<h3 class="text-sm font-semibold text-slate-200 truncate">{selectedNode.name}</h3>
					<button
						onclick={() => {
							selectedNodeId = null;
							selectedNodeRels = [];
							editingEntity = false;
						}}
						class="text-slate-500 hover:text-slate-300 text-xs"
					>
						&times;
					</button>
				</div>

				<span
					class="inline-block text-xs px-2 py-0.5 rounded text-white {typeColor(selectedNode.entity_type)}"
				>
					{typeLabel(selectedNode.entity_type)}
				</span>

				{#if selectedNode.description}
					<p class="text-xs text-slate-400 mt-2">{selectedNode.description}</p>
				{/if}

				{#if selectedNode.aliases.length > 0}
					<p class="text-xs text-slate-500 mt-2">
						Also known as: {selectedNode.aliases.join(', ')}
					</p>
				{/if}

				<!-- Admin actions -->
				{#if isAdmin && !editingEntity}
					<div class="flex gap-2 mt-3">
						<button
							onclick={startEditEntity}
							class="text-xs px-2 py-1 rounded border border-gold/30 text-gold hover:bg-gold/10 transition-colors"
						>
							Edit
						</button>
						<button
							onclick={() => (deleteConfirmEntity = true)}
							class="text-xs px-2 py-1 rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
						>
							Delete
						</button>
					</div>
				{/if}

				<!-- Delete confirmation dialog -->
				{#if deleteConfirmEntity}
					<div class="mt-2 p-2 bg-red-950/30 border border-red-500/30 rounded">
						<p class="text-xs text-red-300 mb-2">
							Delete "{selectedNode.name}"? This cannot be undone.
						</p>
						<div class="flex gap-2">
							<button
								onclick={confirmDeleteEntity}
								disabled={entityDeleting}
								class="text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50"
							>
								{entityDeleting ? 'Deleting...' : 'Confirm'}
							</button>
							<button
								onclick={() => (deleteConfirmEntity = false)}
								class="text-xs px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors"
							>
								Cancel
							</button>
						</div>
					</div>
				{/if}

				<!-- Entity edit form -->
				{#if editingEntity}
					<div class="mt-3 space-y-2">
						<div>
							<label for="edit-entity-name" class="text-[10px] text-slate-500 block mb-0.5">Name</label>
							<input
								id="edit-entity-name"
								bind:value={editForm.name}
								class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
							/>
						</div>
						<div>
							<label for="edit-entity-type" class="text-[10px] text-slate-500 block mb-0.5">Type</label>
							<select
								id="edit-entity-type"
								bind:value={editForm.entity_type}
								class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
							>
								{#each ENTITY_TYPES as t (t)}
									<option value={t}>{typeLabel(t)}</option>
								{/each}
							</select>
						</div>
						<div>
							<label for="edit-entity-desc" class="text-[10px] text-slate-500 block mb-0.5">Description</label>
							<textarea
								id="edit-entity-desc"
								bind:value={editForm.description}
								rows={2}
								class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold resize-none"
							></textarea>
						</div>
						<div>
							<label for="edit-entity-aliases" class="text-[10px] text-slate-500 block mb-0.5"
								>Aliases (comma-separated)</label
							>
							<input
								id="edit-entity-aliases"
								bind:value={editForm.aliases}
								class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
							/>
						</div>
						<div class="flex gap-2 pt-1">
							<button
								onclick={saveEntity}
								disabled={entitySaving}
								class="text-xs px-3 py-1 rounded bg-gold/20 text-gold border border-gold/30 hover:bg-gold/30 transition-colors disabled:opacity-50"
							>
								{entitySaving ? 'Saving...' : 'Save'}
							</button>
							<button
								onclick={cancelEditEntity}
								class="text-xs px-3 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors"
							>
								Cancel
							</button>
						</div>
					</div>
				{/if}

				<hr class="border-navy-700 my-3" />

				<h4 class="text-xs font-semibold text-slate-400 mb-2">Relationships</h4>
				{#if loadingRels}
					<p class="text-xs text-slate-500">Loading...</p>
				{:else if selectedNodeRels.length === 0}
					<p class="text-xs text-slate-600">No relationships.</p>
				{:else}
					<div class="space-y-1.5">
						{#each selectedNodeRels as rel (rel.id)}
							<div class="text-xs bg-navy-800 rounded px-2 py-1.5">
								<div class="flex items-center gap-1">
									<span class="text-slate-300 truncate">{rel.subject_name}</span>
									{#if editingRelId === rel.id}
										<input
											bind:value={editRelPredicate}
											onkeydown={(e) => {
												if (e.key === 'Enter') saveRel(rel.id);
												if (e.key === 'Escape') cancelEditRel();
											}}
											class="bg-navy-700 border border-gold/40 rounded px-1 py-0.5 text-[11px] text-gold w-24 focus:outline-none"
										/>
										<button
											onclick={() => saveRel(rel.id)}
											disabled={relSaving}
											class="text-[10px] text-gold hover:text-gold-light shrink-0"
										>
											{relSaving ? '...' : 'ok'}
										</button>
										<button
											onclick={cancelEditRel}
											class="text-[10px] text-slate-500 hover:text-slate-300 shrink-0"
										>
											esc
										</button>
									{:else}
										<button
											onclick={() => isAdmin && startEditRel(rel)}
											class="text-gold font-medium shrink-0 {isAdmin ? 'hover:underline cursor-pointer' : 'cursor-default'}"
										>
											{rel.predicate}
										</button>
									{/if}
									<span class="text-slate-300 truncate">{rel.object_name}</span>
									<!-- Source badge -->
									{#if rel.graph_source}
										<span
											class="text-[10px] px-1 py-0.5 rounded border shrink-0 ml-auto {sourceBadgeClass(rel.graph_source)}"
										>
											{rel.graph_source === 'team' ? 'Team' : 'Master'}
										</span>
									{/if}
									<!-- Admin delete button -->
									{#if isAdmin && editingRelId !== rel.id}
										{#if deleteConfirmRelId === rel.id}
											<button
												onclick={() => confirmDeleteRel(rel.id)}
												disabled={relDeleting}
												class="text-[10px] text-red-400 hover:text-red-300 shrink-0"
											>
												{relDeleting ? '...' : 'yes'}
											</button>
											<button
												onclick={() => (deleteConfirmRelId = null)}
												class="text-[10px] text-slate-500 hover:text-slate-300 shrink-0"
											>
												no
											</button>
										{:else}
											<button
												onclick={() => (deleteConfirmRelId = rel.id)}
												class="text-[10px] text-red-400/60 hover:text-red-400 shrink-0 ml-auto"
												title="Delete relationship"
											>
												&times;
											</button>
										{/if}
									{/if}
								</div>
								{#if rel.confidence < 1}
									<span class="text-slate-600 text-[10px]">
										{(rel.confidence * 100).toFixed(0)}% confidence
									</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}

				<!-- Deal partners for this node -->
				{#if dealPartners.some((dp) => dp.person1.id === selectedNodeId || dp.person2.id === selectedNodeId)}
					<hr class="border-navy-700 my-3" />
					<h4 class="text-xs font-semibold text-[#C0922B] mb-2">Deal Partners</h4>
					{#each dealPartners.filter((dp) => dp.person1.id === selectedNodeId || dp.person2.id === selectedNodeId) as dp (dp.person1.id + '-' + dp.person2.id)}
						{@const partner =
							dp.person1.id === selectedNodeId ? dp.person2 : dp.person1}
						<div class="text-xs bg-navy-800 rounded px-2 py-1.5 mb-1">
							<span class="text-slate-200">{partner.name}</span>
							<span class="text-slate-600 ml-1"
								>({dp.shared_deals.length} shared deal{dp.shared_deals.length !== 1
									? 's'
									: ''})</span
							>
							{#each dp.shared_deals as deal (deal.entity_id)}
								<div class="text-[10px] text-slate-500 mt-0.5 pl-2">
									{deal.entity_name}
								</div>
							{/each}
						</div>
					{/each}
				{/if}
			</div>
		{/if}
	</div>

	<!-- Legend -->
	<div class="flex items-center gap-5 px-4 py-2 bg-navy-900 border-t border-navy-700">
		{#each Object.entries(NODE_COLORS) as [type, color] (type)}
			<div class="flex items-center gap-1.5">
				<svg width="14" height="14" viewBox="-7 -7 14 14">
					<circle r="6" fill={color} stroke={color} stroke-opacity="0.5" stroke-width="1" />
				</svg>
				<span class="text-xs text-slate-400">{typeLabel(type)}</span>
			</div>
		{/each}
		<div class="flex items-center gap-1.5 ml-4 border-l border-navy-700 pl-4">
			<svg width="30" height="10" viewBox="0 0 30 10">
				<path d="M2,5 Q15,2 28,5" fill="none" stroke="#475569" stroke-width="1.5" />
				<polygon points="26,3 30,5 26,7" fill="#475569" />
			</svg>
			<span class="text-xs text-slate-500">relationship</span>
		</div>
		<div class="flex items-center gap-1.5 ml-2 border-l border-navy-700 pl-4">
			<svg width="30" height="10" viewBox="0 0 30 10">
				<path d="M2,5 Q15,2 28,5" fill="none" stroke="#C0922B" stroke-width="1.5" />
				<polygon points="26,3 30,5 26,7" fill="#C0922B" />
			</svg>
			<span class="text-xs text-slate-500">highlighted</span>
		</div>
	</div>
</div>
