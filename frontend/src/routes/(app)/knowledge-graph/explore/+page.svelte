<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import ForceGraph from '$lib/components/ForceGraph.svelte';
	import TeamBadge from '$lib/components/TeamBadge.svelte';
	import { theme } from '$lib/stores/themeStore';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import { currentUser } from '$lib/stores/authStore';
	import { listTeams, type Team } from '$lib/api/teams';
	import {
		kgApi,
		type KGGraph,
		type KGGraphNode,
		type KGGraphEdge,
		type DealPartnerGroup,
		type KGRelationship,
		type KGQueryResult,
	} from '$lib/api/knowledgeGraph';
	import UploadWizard from '$lib/components/UploadWizard.svelte';
	import CommandPalette from '$lib/components/CommandPalette.svelte';
	import KGChat from '$lib/components/KGChat.svelte';

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
	let graphOpacity = $state(1);
	let teams = $state<Team[]>([]);
	let user = $state<{ sid: string; display_name: string; email: string; is_super_admin?: boolean } | null>(null);

	// Derive team ID and display name from the store
	let teamId = $derived($scoutTeam);
	let currentTeamName = $derived(
		teamId
			? (teams.find((t) => t.id === teamId)?.display_name ?? null)
			: null
	);

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

	// --------------- Upload state ---------------
	let uploadWizardOpen = $state(false);

	// --------------- Smart rendering state ---------------
	const NODE_BUDGET = 150;
	const WARN_THRESHOLD = 300;
	const BLOCK_THRESHOLD = 500;
	let totalServerNodes = $state(0);
	let loadedNodeIds = $state<Set<string>>(new Set());
	let toastMessage = $state('');
	let toastTimeout: ReturnType<typeof setTimeout> | null = null;

	// --------------- Graph API ref (from ForceGraph) ---------------
	let graphApi = $state<{ mergeNodes: (n: KGGraphNode[], e: KGGraphEdge[]) => void; fitToView: () => void; resetLayout: () => void } | null>(null);

	// --------------- Context menu state ---------------
	let contextMenu = $state<{ nodeId: string; x: number; y: number } | null>(null);
	let pinnedNodes = $state<Set<string>>(new Set());

	// --------------- Edge tooltip state ---------------
	let edgeTooltip = $state<{ edgeId: string; x: number; y: number } | null>(null);

	// --------------- Minimap state ---------------
	let minimapVisible = $state(true);

	// --------------- Command palette state ---------------
	let commandPaletteOpen = $state(false);

	// --------------- KG Chat state ---------------
	let chatPanelOpen = $state(false);
	let chatHighlightedNodeIds = $state<Set<string> | null>(null);
	let chatHighlightedEdgeIds = $state<Set<string> | null>(null);

	// --------------- Derived ---------------
	let isAdmin = $derived(user?.is_super_admin === true);
	let nodeCount = $derived(graphData.nodes.length);
	let showWarningBanner = $derived(nodeCount >= WARN_THRESHOLD);
	let expansionBlocked = $derived(nodeCount >= BLOCK_THRESHOLD);

	let highlightedNodeIds = $derived.by(() => {
		// Chat highlights take priority when active
		if (chatHighlightedNodeIds && chatHighlightedNodeIds.size > 0) return chatHighlightedNodeIds;
		if (!dealModeActive || dealPartners.length === 0) return null;
		const ids = new Set<string>();
		for (const dp of dealPartners) {
			ids.add(dp.person1.id);
			ids.add(dp.person2.id);
			for (const deal of (dp.shared_deals ?? [])) {
				ids.add(deal.entity_id);
			}
		}
		return ids;
	});

	let highlightedEdgeIds = $derived.by(() => {
		// Chat path highlights take priority
		if (chatHighlightedEdgeIds && chatHighlightedEdgeIds.size > 0) return chatHighlightedEdgeIds;
		if (!dealModeActive || dealPartners.length === 0) return null;
		const dealEntityIds = new Set<string>();
		const personIds = new Set<string>();
		for (const dp of dealPartners) {
			personIds.add(dp.person1.id);
			personIds.add(dp.person2.id);
			for (const deal of (dp.shared_deals ?? [])) dealEntityIds.add(deal.entity_id);
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
				limit?: number;
			} = { limit: NODE_BUDGET };
			if (selectedTypes.size > 0) params.entity_types = [...selectedTypes];
			if (selectedFamilies.size > 0) params.predicate_families = [...selectedFamilies];
			if (teamId) params.team_id = teamId;
			if (searchQuery.trim()) params.search = searchQuery.trim();
			if (metadataKey.trim()) params.metadata_key = metadataKey.trim();
			if (metadataValue.trim()) params.metadata_value = metadataValue.trim();
			graphData = await kgApi.getGraph(params);
			// Track loaded node IDs for expansion dedup
			loadedNodeIds = new Set(graphData.nodes.map(n => n.id));
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

	function showToast(msg: string) {
		toastMessage = msg;
		if (toastTimeout) clearTimeout(toastTimeout);
		toastTimeout = setTimeout(() => { toastMessage = ''; }, 3000);
	}

	// Double-click expansion with exclude_ids
	async function handleNodeDblClick(nodeId: string) {
		if (expansionBlocked) {
			showToast(`Cannot expand: ${nodeCount} nodes loaded (limit: ${BLOCK_THRESHOLD})`);
			return;
		}
		try {
			const exclude = [...loadedNodeIds];
			const neighbors = await kgApi.getNeighbors(nodeId, {
				depth: 1,
				limit: 50,
				exclude_ids: exclude,
				team_id: teamId ?? undefined,
			});
			const newNodes = neighbors.nodes.filter(n => !loadedNodeIds.has(n.id));
			const newEdges = neighbors.edges.filter(e =>
				!graphData.edges.some(ex => ex.id === e.id)
			);
			if (newNodes.length === 0) {
				showToast('No new neighbors found');
				return;
			}
			// Merge into graph data
			graphData = {
				nodes: [...graphData.nodes, ...newNodes],
				edges: [...graphData.edges, ...newEdges],
			};
			for (const n of newNodes) loadedNodeIds.add(n.id);
			loadedNodeIds = new Set(loadedNodeIds);
			showToast(`Added ${newNodes.length} node${newNodes.length !== 1 ? 's' : ''}`);
		} catch {
			showToast('Failed to expand neighbors');
		}
	}

	// Context menu
	function handleNodeContextMenu(nodeId: string, x: number, y: number) {
		contextMenu = { nodeId, x, y };
		edgeTooltip = null;
	}

	function closeContextMenu() {
		contextMenu = null;
	}

	function contextExpandNeighbors() {
		if (contextMenu) handleNodeDblClick(contextMenu.nodeId);
		closeContextMenu();
	}

	function contextHideNode() {
		if (!contextMenu) return;
		const nodeId = contextMenu.nodeId;
		graphData = {
			nodes: graphData.nodes.filter(n => n.id !== nodeId),
			edges: graphData.edges.filter(e => e.source !== nodeId && e.target !== nodeId),
		};
		loadedNodeIds.delete(nodeId);
		loadedNodeIds = new Set(loadedNodeIds);
		if (selectedNodeId === nodeId) {
			selectedNodeId = null;
			selectedNodeRels = [];
		}
		closeContextMenu();
	}

	function contextTogglePin() {
		if (!contextMenu) return;
		const nodeId = contextMenu.nodeId;
		const next = new Set(pinnedNodes);
		if (next.has(nodeId)) next.delete(nodeId);
		else next.add(nodeId);
		pinnedNodes = next;
		closeContextMenu();
	}

	function contextViewEntityPage() {
		if (!contextMenu) return;
		handleNodeClick(contextMenu.nodeId);
		closeContextMenu();
	}

	// Edge tooltip
	function handleEdgeClick(edgeId: string, x: number, y: number) {
		edgeTooltip = { edgeId, x, y };
		contextMenu = null;
	}

	function closeEdgeTooltip() {
		edgeTooltip = null;
	}

	let selectedEdge = $derived(
		edgeTooltip ? graphData.edges.find(e => e.id === edgeTooltip!.edgeId) ?? null : null
	);

	let selectedEdgeSourceName = $derived(
		selectedEdge ? (graphData.nodes.find(n => n.id === selectedEdge!.source)?.name ?? 'Unknown') : ''
	);

	let selectedEdgeTargetName = $derived(
		selectedEdge ? (graphData.nodes.find(n => n.id === selectedEdge!.target)?.name ?? 'Unknown') : ''
	);

	// Graph API callback
	function handleGraphReady(api: { mergeNodes: (n: KGGraphNode[], e: KGGraphEdge[]) => void; fitToView: () => void; resetLayout: () => void }) {
		graphApi = api;
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
			aliases: (selectedNode.aliases ?? []).join(', '),
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

	// --------------- Command palette handlers ---------------

	function openCommandPalette() {
		commandPaletteOpen = true;
	}

	function handlePaletteSelectEntity(entityId: string) {
		// Focus the node in the graph
		focusNodeId = entityId;
		// Open entity detail panel
		selectedNodeId = entityId;
		editingEntity = false;
		editingRelId = null;
		loadNodeRels(entityId);
	}

	function handlePaletteSelectFilter(kind: 'entity_type' | 'predicate_family', value: string) {
		if (kind === 'entity_type') {
			toggleType(value);
		} else {
			toggleFamily(value);
		}
	}

	// --------------- KG Chat handlers ---------------

	function handleChatFocusNode(entityId: string) {
		focusNodeId = entityId;
	}

	function handleChatHighlight(entityIds: string[]) {
		chatHighlightedNodeIds = new Set(entityIds);
		// Focus on first entity if it's in the graph
		const firstInGraph = entityIds.find((id) => graphData.nodes.some((n) => n.id === id));
		if (firstInGraph) focusNodeId = firstInGraph;
	}

	function handleChatPath(
		paths: unknown[],
		_sourceId: string,
		_targetId: string
	) {
		// Highlight all nodes and edges along the paths
		const nodeIds = new Set<string>();
		const edgeIds = new Set<string>();
		for (const path of paths as Array<{ entities?: Array<{ id: string }>; relationships?: Array<{ id: string }> }>) {
			for (const entity of path.entities ?? []) nodeIds.add(entity.id);
			for (const rel of path.relationships ?? []) edgeIds.add(rel.id);
		}
		chatHighlightedNodeIds = nodeIds.size > 0 ? nodeIds : null;
		chatHighlightedEdgeIds = edgeIds.size > 0 ? edgeIds : null;
	}

	// --------------- Lifecycle ---------------

	// Sync user store
	$effect(() => {
		const unsub = currentUser.subscribe((v) => {
			user = v;
		});
		return unsub;
	});

	// Load teams list once so we can resolve display names
	$effect(() => {
		listTeams().then((t) => {
			teams = t;
		});
	});

	// Reactive graph fetch — re-runs whenever teamId (scoutTeam) changes
	let graphFetchController: AbortController | null = null;

	$effect(() => {
		// Read the reactive dependency so this effect re-runs on team change
		const currentTeamId = teamId;

		graphFetchController?.abort();
		graphFetchController = new AbortController();

		// Fade the graph out while loading
		graphOpacity = 0.3;
		loading = true;
		error = '';

		const params: { team_id?: string; limit?: number } = { limit: NODE_BUDGET };
		if (currentTeamId) params.team_id = currentTeamId;

		Promise.allSettled([
			kgApi.getGraph(params),
			kgApi.getDealPartners(),
		]).then(([graphResult, dealResult]) => {
			if (graphResult.status === 'fulfilled') {
				graphData = graphResult.value;
				loadedNodeIds = new Set(graphData.nodes.map(n => n.id));
			} else {
				error = 'Failed to load graph';
			}
			if (dealResult.status === 'fulfilled') dealPartners = dealResult.value;
			loading = false;
			graphOpacity = 1;
		});
	});
</script>

<svelte:head>
	<title>Graph Explorer — Knowledge Graph — Playbook Research</title>
</svelte:head>

<svelte:window onkeydown={(e) => {
	if (e.key === 'Escape') {
		closeContextMenu();
		closeEdgeTooltip();
	}
	// Cmd+K (Mac) or Ctrl+K (Windows/Linux) opens command palette
	if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
		e.preventDefault();
		openCommandPalette();
	}
	// "/" opens palette when no input element is focused
	if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
		e.preventDefault();
		openCommandPalette();
	}
}} onclick={() => {
	closeContextMenu();
	closeEdgeTooltip();
}} />

<div class="flex flex-col h-[calc(100vh-4rem)]">
	<!-- Toolbar -->
	<div class="flex flex-wrap items-center gap-3 px-4 py-3 bg-navy-900 border-b border-navy-700">
		<a
			href="/knowledge-graph"
			class="text-xs text-slate-500 hover:text-gold transition-colors"
		>
			&larr; Back
		</a>

		<!-- Team badge -->
		<span data-testid="explorer-team-badge-wrapper">
			<TeamBadge
				teamName={currentTeamName ? `${currentTeamName} Graph` : null}
				size="sm"
			/>
		</span>

		<!-- Search pill — opens command palette -->
		<button
			onclick={openCommandPalette}
			class="flex items-center gap-2 bg-navy-800 border border-navy-600 rounded px-3 py-1 text-xs text-slate-400 hover:text-slate-200 hover:border-gold transition-colors"
			title="Search (Cmd+K)"
		>
			<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
			</svg>
			Search Knowledge Graph...
			<kbd class="hidden sm:block bg-navy-700 border border-navy-600 rounded px-1 py-0.5 text-[10px] text-slate-500">⌘K</kbd>
		</button>

		<!-- Graph text search -->
		<div class="flex items-center gap-1">
			<input
				bind:value={searchQuery}
				onkeydown={(e) => e.key === 'Enter' && handleSearch()}
				placeholder="Filter graph..."
				class="bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-40"
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

		<!-- Upload button -->
		<button
			onclick={() => (uploadWizardOpen = true)}
			class="text-xs px-2.5 py-1 rounded border transition-colors border-navy-600 text-slate-400 hover:text-slate-200"
		>
			Upload
		</button>

		<!-- Chat button -->
		<button
			onclick={() => (chatPanelOpen = !chatPanelOpen)}
			class="text-xs px-2.5 py-1 rounded border transition-colors {chatPanelOpen
				? 'border-gold text-gold bg-gold/10'
				: 'border-navy-600 text-slate-400 hover:text-slate-200'}"
			title="KG Chat"
		>
			<svg class="w-3.5 h-3.5 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
			</svg>
			Chat
		</button>

		<!-- Layout controls (task 6uw.11) -->
		<button
			onclick={() => graphApi?.fitToView()}
			disabled={!graphApi || graphData.nodes.length === 0}
			class="text-xs px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-30"
			title="Fit graph to view"
		>
			Fit View
		</button>
		<button
			onclick={() => graphApi?.resetLayout()}
			disabled={!graphApi || graphData.nodes.length === 0}
			class="text-xs px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-30"
			title="Reset layout: unpin all, randomize"
		>
			Reset
		</button>

		<span class="text-xs text-slate-600 ml-auto">
			Showing {graphData.nodes.length} nodes / {graphData.edges.length} edges
		</span>
	</div>

	<!-- Warning banner (task 6uw.6) -->
	{#if showWarningBanner}
		<div class="flex items-center gap-2 px-4 py-2 text-xs border-b {expansionBlocked ? 'bg-red-950/40 border-red-800/40 text-red-300' : 'bg-amber-950/40 border-amber-800/40 text-amber-300'}">
			<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
			</svg>
			{#if expansionBlocked}
				<span>Graph has {nodeCount} nodes (limit: {BLOCK_THRESHOLD}). Expansion is blocked. Filter or reset to reduce node count.</span>
			{:else}
				<span>Graph has {nodeCount} nodes. Performance may be impacted above {BLOCK_THRESHOLD} nodes.</span>
			{/if}
		</div>
	{/if}

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
		<!-- KG Chat sidebar (left) -->
		{#if chatPanelOpen}
			<div class="w-72 shrink-0 flex flex-col min-h-0">
				<KGChat
					teamId={teamId}
					onHighlight={handleChatHighlight}
					onPath={handleChatPath}
					onFocusNode={handleChatFocusNode}
					lookupEntityName={(id) => graphData.nodes.find((n) => n.id === id)?.name ?? null}
				/>
			</div>
		{/if}

		<!-- Graph area -->
		<div
			class="flex-1 relative bg-navy-950 transition-opacity duration-200"
			style="opacity: {graphOpacity};"
			data-testid="graph-area"
		>
			{#if loading}
				<div class="absolute inset-0 flex items-center justify-center">
					<div class="flex items-center gap-2 text-slate-500">
						<svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
						</svg>
						<span>Loading graph...</span>
					</div>
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
					onNodeDblClick={handleNodeDblClick}
					onNodeContextMenu={handleNodeContextMenu}
					onEdgeClick={handleEdgeClick}
					onGraphReady={handleGraphReady}
				/>
			{/if}
		</div>

		<!-- Upload Wizard modal -->
		<UploadWizard
			open={uploadWizardOpen}
			onClose={() => (uploadWizardOpen = false)}
			teamId={teamId}
			onComplete={async () => { await fetchGraph(); graphApi?.fitToView(); }}
		/>

		<!-- Command palette -->
		<CommandPalette
			bind:open={commandPaletteOpen}
			{teamId}
			onSelectEntity={handlePaletteSelectEntity}
			onSelectFilter={handlePaletteSelectFilter}
		/>

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
						{#if queryResult.sources_used?.length > 0}
							<div class="text-[10px] text-slate-500">
								Sources: {(queryResult.sources_used ?? []).join(', ')}
							</div>
						{/if}

						<!-- Entities -->
						{#if queryResult.entities?.length > 0}
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
						{#if queryResult.relationships?.length > 0}
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

						{#if (queryResult.entities?.length ?? 0) === 0 && (queryResult.relationships?.length ?? 0) === 0}
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

				{#if selectedNode.aliases?.length > 0}
					<p class="text-xs text-slate-500 mt-2">
						Also known as: {(selectedNode.aliases ?? []).join(', ')}
					</p>
				{/if}

				<!-- Metadata section (task 6uw.7) -->
				{#if selectedNode.metadata && Object.keys(selectedNode.metadata).length > 0}
					<div class="mt-3">
						<h4 class="text-[10px] text-slate-600 uppercase tracking-widest mb-1.5">Metadata</h4>
						<div class="space-y-1">
							{#each Object.entries(selectedNode.metadata) as [key, value] (key)}
								<div class="flex items-start gap-2 text-xs">
									<span class="text-slate-500 font-mono shrink-0">{key}:</span>
									<span class="text-slate-300 break-all">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
								</div>
							{/each}
						</div>
					</div>
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

<!-- Context menu (task 6uw.8) -->
{#if contextMenu}
	<div
		class="fixed z-50 bg-navy-800 border border-navy-600 rounded-lg shadow-xl py-1 min-w-[160px]"
		style="left: {contextMenu.x}px; top: {contextMenu.y}px;"
		role="menu"
	>
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700 hover:text-gold transition-colors disabled:opacity-40"
			role="menuitem"
			onclick={contextExpandNeighbors}
			disabled={expansionBlocked}
		>
			Expand neighbors
		</button>
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700 hover:text-gold transition-colors"
			role="menuitem"
			onclick={contextHideNode}
		>
			Hide node
		</button>
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700 hover:text-gold transition-colors"
			role="menuitem"
			onclick={contextTogglePin}
		>
			{pinnedNodes.has(contextMenu.nodeId) ? 'Unpin position' : 'Pin position'}
		</button>
		<hr class="border-navy-700 my-0.5" />
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700 hover:text-gold transition-colors"
			role="menuitem"
			onclick={() => { handleNodeClick(contextMenu!.nodeId); closeContextMenu(); }}
		>
			View entity details
		</button>
	</div>
{/if}

<!-- Edge detail tooltip (task 6uw.9) -->
{#if edgeTooltip && selectedEdge}
	<div
		class="fixed z-50 bg-navy-800 border border-navy-600 rounded-lg shadow-xl p-3 min-w-[200px] max-w-[280px]"
		style="left: {edgeTooltip.x + 8}px; top: {edgeTooltip.y + 8}px;"
		role="tooltip"
	>
		<div class="space-y-1.5">
			<div class="text-xs text-slate-200 font-medium">
				{selectedEdgeSourceName}
				<span class="text-gold mx-1">{selectedEdge.predicate.replace(/_/g, ' ')}</span>
				{selectedEdgeTargetName}
			</div>
			<div class="flex items-center gap-2 text-[10px] text-slate-400">
				<span>Confidence: {(selectedEdge.confidence * 100).toFixed(0)}%</span>
				{#if selectedEdge.predicate_family}
					<span class="px-1.5 py-0.5 rounded bg-navy-700 border border-navy-600">
						{selectedEdge.predicate_family}
					</span>
				{/if}
			</div>
			{#if selectedEdge.graph_source}
				<div class="text-[10px] text-slate-500">
					Source: {selectedEdge.graph_source === 'team' ? 'Team Graph' : 'Master Graph'}
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Minimap (task 6uw.10) -->
{#if minimapVisible && graphData.nodes.length > 0 && !loading}
	<div class="fixed bottom-16 right-4 z-30 bg-navy-900/90 border border-navy-700 rounded-lg overflow-hidden shadow-lg">
		<svg width="150" height="100" viewBox="0 0 150 100" class="block">
			<rect width="150" height="100" fill="transparent" />
			{#each graphData.nodes as node (node.id)}
				{@const nx = ((graphData.nodes.indexOf(node) % 15) / 15) * 140 + 5}
				{@const ny = (Math.floor(graphData.nodes.indexOf(node) / 15) / Math.max(1, Math.ceil(graphData.nodes.length / 15))) * 90 + 5}
				<circle
					cx={nx}
					cy={ny}
					r="2"
					fill={NODE_COLORS[node.entity_type.toLowerCase()] ?? '#7B8794'}
				/>
			{/each}
		</svg>
	</div>
{/if}

<!-- Toast notification -->
{#if toastMessage}
	<div class="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-navy-800 border border-navy-600 rounded-lg px-4 py-2 text-xs text-slate-200 shadow-lg">
		{toastMessage}
	</div>
{/if}
