<script lang="ts">
	import { onMount } from 'svelte';
	import ForceGraph from '$lib/components/ForceGraph.svelte';
	import {
		kgApi,
		type KGGraphNode,
		type KGGraphEdge,
		type KGGraph,
		type DealPartnerGroup,
		type KGRelationship,
	} from '$lib/api/knowledgeGraph';

	const ENTITY_TYPES = ['person', 'company', 'sports_team', 'location', 'product', 'other'];
	const PREDICATE_FAMILIES = ['ownership', 'employment', 'transaction', 'location', 'partnership'];

	let graphData = $state<KGGraph>({ nodes: [], edges: [] });
	let dealPartners = $state<DealPartnerGroup[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Filters
	let searchQuery = $state('');
	let selectedTypes = $state<Set<string>>(new Set());
	let selectedFamilies = $state<Set<string>>(new Set());
	let dealModeActive = $state(false);

	// Selection state
	let selectedNodeId = $state<string | null>(null);
	let focusNodeId = $state<string | null>(null);
	let selectedNodeRels = $state<KGRelationship[]>([]);
	let loadingRels = $state(false);

	// Derived highlight sets for deal mode
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
				if ((personIds.has(s) && dealEntityIds.has(t)) || (personIds.has(t) && dealEntityIds.has(s))) {
					ids.add(e.id);
				}
			}
		}
		return ids;
	});

	let selectedNode = $derived(
		selectedNodeId ? graphData.nodes.find((n) => n.id === selectedNodeId) ?? null : null,
	);

	async function fetchGraph() {
		loading = true;
		error = '';
		try {
			const params: { entity_types?: string[]; predicate_families?: string[] } = {};
			if (selectedTypes.size > 0) params.entity_types = [...selectedTypes];
			if (selectedFamilies.size > 0) params.predicate_families = [...selectedFamilies];
			graphData = await kgApi.getGraph(params);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load graph';
		} finally {
			loading = false;
		}
	}

	function toggleType(type: string) {
		const next = new Set(selectedTypes);
		if (next.has(type)) next.delete(type);
		else next.add(type);
		selectedTypes = next;
		fetchGraph();
	}

	function toggleFamily(family: string) {
		const next = new Set(selectedFamilies);
		if (next.has(family)) next.delete(family);
		else next.add(family);
		selectedFamilies = next;
		fetchGraph();
	}

	function handleSearch() {
		if (!searchQuery.trim()) return;
		const q = searchQuery.toLowerCase();
		const found = graphData.nodes.find(
			(n) =>
				n.name.toLowerCase().includes(q) ||
				n.aliases.some((a) => a.toLowerCase().includes(q)),
		);
		if (found) {
			focusNodeId = found.id;
			selectedNodeId = found.id;
			loadNodeRels(found.id);
		}
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
		} else {
			selectedNodeId = nodeId;
			loadNodeRels(nodeId);
		}
	}

	function typeColor(type: string): string {
		const colors: Record<string, string> = {
			person: 'bg-blue-500',
			company: 'bg-purple-500',
			sports_team: 'bg-orange-500',
			location: 'bg-green-500',
			product: 'bg-yellow-500',
			other: 'bg-slate-500',
		};
		return colors[type.toLowerCase()] ?? 'bg-slate-500';
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

	onMount(async () => {
		const [graphResult, dealResult] = await Promise.allSettled([
			kgApi.getGraph(),
			kgApi.getDealPartners(),
		]);
		if (graphResult.status === 'fulfilled') graphData = graphResult.value;
		else error = 'Failed to load graph';
		if (dealResult.status === 'fulfilled') dealPartners = dealResult.value;
		loading = false;
	});
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

		<!-- Search -->
		<div class="flex items-center gap-1">
			<input
				bind:value={searchQuery}
				onkeydown={(e) => e.key === 'Enter' && handleSearch()}
				placeholder="Search nodes..."
				class="bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-48"
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
			{#each ENTITY_TYPES as type}
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
			{#each PREDICATE_FAMILIES as family}
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
				? 'border-orange-500 text-orange-400 bg-orange-500/10'
				: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
		>
			Deal Partners {dealPartners.length > 0 ? `(${dealPartners.length})` : ''}
		</button>

		<span class="text-xs text-slate-600 ml-auto">
			{graphData.nodes.length} nodes / {graphData.edges.length} edges
		</span>
	</div>

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
						<p class="text-xs text-slate-600 mt-1">Run some research sessions to populate the knowledge graph.</p>
					</div>
				</div>
			{:else}
				<ForceGraph
					nodes={graphData.nodes}
					edges={graphData.edges}
					{highlightedNodeIds}
					{highlightedEdgeIds}
					focusNodeId={focusNodeId}
					selectedNodeId={selectedNodeId}
					onNodeClick={handleNodeClick}
				/>
			{/if}
		</div>

		<!-- Detail panel -->
		{#if selectedNode}
			<div class="w-80 bg-navy-900 border-l border-navy-700 overflow-y-auto p-4">
				<div class="flex items-center justify-between mb-3">
					<h3 class="text-sm font-semibold text-slate-200 truncate">{selectedNode.name}</h3>
					<button
						onclick={() => { selectedNodeId = null; selectedNodeRels = []; }}
						class="text-slate-500 hover:text-slate-300 text-xs"
					>
						&times;
					</button>
				</div>

				<span class="inline-block text-xs px-2 py-0.5 rounded text-white {typeColor(selectedNode.entity_type)}">
					{typeLabel(selectedNode.entity_type)}
				</span>

				{#if selectedNode.aliases.length > 0}
					<p class="text-xs text-slate-500 mt-2">
						Also known as: {selectedNode.aliases.join(', ')}
					</p>
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
									<span class="text-gold font-medium shrink-0">{rel.predicate}</span>
									<span class="text-slate-300 truncate">{rel.object_name}</span>
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
					<h4 class="text-xs font-semibold text-orange-400 mb-2">Deal Partners</h4>
					{#each dealPartners.filter((dp) => dp.person1.id === selectedNodeId || dp.person2.id === selectedNodeId) as dp}
						{@const partner = dp.person1.id === selectedNodeId ? dp.person2 : dp.person1}
						<div class="text-xs bg-navy-800 rounded px-2 py-1.5 mb-1">
							<span class="text-slate-200">{partner.name}</span>
							<span class="text-slate-600 ml-1">({dp.shared_deals.length} shared deal{dp.shared_deals.length !== 1 ? 's' : ''})</span>
							{#each dp.shared_deals as deal}
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
		{#each Object.entries({ person: '#4C8BF5', company: '#9B59B6', sports_team: '#E67E22', location: '#2ECC71', product: '#F1C40F', other: '#7F8C8D' }) as [type, color]}
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
	</div>
</div>
