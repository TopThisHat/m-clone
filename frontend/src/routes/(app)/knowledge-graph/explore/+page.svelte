<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import ForceGraph from '$lib/components/ForceGraph.svelte';
	import TeamBadge from '$lib/components/TeamBadge.svelte';
	import ZoomRail from '$lib/components/ZoomRail.svelte';
	import FilterStrip from '$lib/components/FilterStrip.svelte';
	import KGEntityPanel from '$lib/components/KGEntityPanel.svelte';
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

	const NODE_COLORS: Record<string, string> = {
		person: '#60A5FA',
		company: '#22D3EE',
		sports_team: '#FBBF24',
		location: '#4ADE80',
		product: '#C084FC',
		other: '#CBD5E1',
	};

	// --------------- Core state ---------------
	let graphData = $state<KGGraph>({ nodes: [], edges: [] });
	let dealPartners = $state<DealPartnerGroup[]>([]);
	let loading = $state(true);
	let error = $state('');
	let graphOpacity = $state(1);
	let teams = $state<Team[]>([]);
	let user = $state<{ sid: string; display_name: string; email: string; is_super_admin?: boolean } | null>(null);

	let teamId = $derived($scoutTeam);
	let currentTeamName = $derived(
		teamId ? (teams.find((t) => t.id === teamId)?.display_name ?? null) : null
	);

	// --------------- Filters ---------------
	let selectedTypes = new SvelteSet<string>();
	let selectedFamilies = new SvelteSet<string>();
	let dealModeActive = $state(false);
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
	let loadedNodeIds = $state<Set<string>>(new Set());
	let toastMessage = $state('');
	let toastTimeout: ReturnType<typeof setTimeout> | null = null;

	// --------------- Graph API ref (from ForceGraph) ---------------
	let graphApi = $state<{
		mergeNodes: (n: KGGraphNode[], e: KGGraphEdge[]) => void;
		fitToView: () => void;
		resetLayout: () => void;
		zoomIn: () => void;
		zoomOut: () => void;
		focusNode: (nodeId: string) => void;
	} | null>(null);

	// --------------- Context menu state ---------------
	let contextMenu = $state<{ nodeId: string; x: number; y: number } | null>(null);

	// --------------- Edge tooltip state ---------------
	let edgeTooltip = $state<{ edgeId: string; x: number; y: number } | null>(null);

	// --------------- Command palette state ---------------
	let commandPaletteOpen = $state(false);

	// --------------- KG Chat state ---------------
	let chatPanelOpen = $state(false);
	let chatHighlightedNodeIds = $state<Set<string> | null>(null);
	let chatHighlightedEdgeIds = $state<Set<string> | null>(null);

	// --------------- Keyboard shortcut cheat sheet ---------------
	let shortcutSheetOpen = $state(false);

	// --------------- Derived ---------------
	let isAdmin = $derived(user?.is_super_admin === true);
	let nodeCount = $derived(graphData.nodes.length);
	let showWarningBanner = $derived(nodeCount >= WARN_THRESHOLD);
	let expansionBlocked = $derived(nodeCount >= BLOCK_THRESHOLD);

	let highlightedNodeIds = $derived.by(() => {
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

	let selectedEdge = $derived(
		edgeTooltip ? graphData.edges.find((e) => e.id === edgeTooltip!.edgeId) ?? null : null
	);

	let selectedEdgeSourceName = $derived(
		selectedEdge ? (graphData.nodes.find((n) => n.id === selectedEdge!.source)?.name ?? 'Unknown') : ''
	);

	let selectedEdgeTargetName = $derived(
		selectedEdge ? (graphData.nodes.find((n) => n.id === selectedEdge!.target)?.name ?? 'Unknown') : ''
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
				metadata_key?: string;
				metadata_value?: string;
				limit?: number;
			} = { limit: NODE_BUDGET };
			if (selectedTypes.size > 0) params.entity_types = [...selectedTypes];
			if (selectedFamilies.size > 0) params.predicate_families = [...selectedFamilies];
			if (teamId) params.team_id = teamId;
			if (metadataKey.trim()) params.metadata_key = metadataKey.trim();
			if (metadataValue.trim()) params.metadata_value = metadataValue.trim();
			graphData = await kgApi.getGraph(params);
			loadedNodeIds = new Set(graphData.nodes.map((n) => n.id));
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

	function clearAllFilters() {
		selectedTypes.clear();
		selectedFamilies.clear();
		dealModeActive = false;
		metadataKey = '';
		metadataValue = '';
		fetchGraph();
	}

	function handleMetadataChange(key: string, value: string) {
		metadataKey = key;
		metadataValue = value;
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

	// Double-click expansion
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
			const newNodes = neighbors.nodes.filter((n) => !loadedNodeIds.has(n.id));
			const newEdges = neighbors.edges.filter(
				(e) => !graphData.edges.some((ex) => ex.id === e.id)
			);
			if (newNodes.length === 0) {
				showToast('No new neighbors found');
				return;
			}
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
			nodes: graphData.nodes.filter((n) => n.id !== nodeId),
			edges: graphData.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
		};
		loadedNodeIds.delete(nodeId);
		loadedNodeIds = new Set(loadedNodeIds);
		if (selectedNodeId === nodeId) {
			selectedNodeId = null;
			selectedNodeRels = [];
		}
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

	// Graph API callback
	function handleGraphReady(api: {
		mergeNodes: (n: KGGraphNode[], e: KGGraphEdge[]) => void;
		fitToView: () => void;
		resetLayout: () => void;
		zoomIn: () => void;
		zoomOut: () => void;
		focusNode: (nodeId: string) => void;
	}) {
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

	function closeEntityPanel() {
		selectedNodeId = null;
		selectedNodeRels = [];
		editingEntity = false;
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
	function sourceBadgeClass(source: string): string {
		return source === 'team'
			? 'bg-gold/20 text-gold border-gold/30'
			: 'bg-slate-700/50 text-slate-300 border-slate-600';
	}

	// --------------- Command palette handlers ---------------
	function openCommandPalette() {
		commandPaletteOpen = true;
	}

	/** When the user picks an entity from the palette, fetch its neighborhood,
	 *  replace the graph with only that entity + neighbors, and center on it. */
	async function handlePaletteSelectEntity(entityId: string) {
		try {
			const neighbors = await kgApi.getNeighbors(entityId, {
				depth: 1,
				limit: NODE_BUDGET,
				team_id: teamId ?? undefined,
			});
			// Replace graph with just this entity's neighborhood
			graphData = { nodes: neighbors.nodes, edges: neighbors.edges };
			loadedNodeIds = new Set(neighbors.nodes.map((n) => n.id));
			// Select and focus
			selectedNodeId = entityId;
			editingEntity = false;
			editingRelId = null;
			loadNodeRels(entityId);
			// Center camera on the entity after graph rebuilds
			requestAnimationFrame(() => {
				graphApi?.focusNode(entityId);
			});
		} catch {
			// Fallback: just focus if entity is already in graph
			focusNodeId = entityId;
			selectedNodeId = entityId;
			editingEntity = false;
			editingRelId = null;
			loadNodeRels(entityId);
		}
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
		const firstInGraph = entityIds.find((id) => graphData.nodes.some((n) => n.id === id));
		if (firstInGraph) focusNodeId = firstInGraph;
	}

	function handleChatPath(
		paths: unknown[],
		_sourceId: string,
		_targetId: string
	) {
		const nodeIds = new Set<string>();
		const edgeIds = new Set<string>();
		for (const path of paths as Array<{ entities?: Array<{ id: string }>; relationships?: Array<{ id: string }> }>) {
			for (const entity of path.entities ?? []) nodeIds.add(entity.id);
			for (const rel of path.relationships ?? []) edgeIds.add(rel.id);
		}
		chatHighlightedNodeIds = nodeIds.size > 0 ? nodeIds : null;
		chatHighlightedEdgeIds = edgeIds.size > 0 ? edgeIds : null;
	}

	// --------------- Keyboard shortcuts ---------------
	function handleKeydown(e: KeyboardEvent) {
		const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
		const isInputFocused = tag === 'input' || tag === 'textarea' || tag === 'select';

		if (e.key === 'Escape') {
			if (shortcutSheetOpen) {
				shortcutSheetOpen = false;
			} else if (selectedNodeId) {
				closeEntityPanel();
			} else {
				closeContextMenu();
				closeEdgeTooltip();
			}
			return;
		}

		if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
			e.preventDefault();
			openCommandPalette();
			return;
		}

		if (e.key === '/' && !isInputFocused) {
			e.preventDefault();
			openCommandPalette();
		}

		if (e.key === '?' && !isInputFocused) {
			shortcutSheetOpen = !shortcutSheetOpen;
		}
	}

	// --------------- Lifecycle ---------------
	$effect(() => {
		const unsub = currentUser.subscribe((v) => {
			user = v;
		});
		return unsub;
	});

	$effect(() => {
		listTeams().then((t) => {
			teams = t;
		});
	});

	let graphFetchController: AbortController | null = null;

	$effect(() => {
		const currentTeamId = teamId;

		graphFetchController?.abort();
		graphFetchController = new AbortController();

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
				loadedNodeIds = new Set(graphData.nodes.map((n) => n.id));
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

<svelte:window onkeydown={handleKeydown} onclick={() => { closeContextMenu(); closeEdgeTooltip(); }} />

<div class="flex flex-col h-[calc(100vh-4rem)]">
	<!-- Top bar -->
	<div class="flex items-center gap-3 px-4 py-3.5 bg-gradient-to-r from-navy-900 via-navy-900 to-navy-950 border-b border-navy-700 shrink-0">
		<a
			href="/knowledge-graph"
			class="text-xs text-slate-500 hover:text-gold transition-colors shrink-0 px-2 py-1 rounded-md hover:bg-navy-800"
		>
			&larr; Back
		</a>

		<span data-testid="explorer-team-badge-wrapper">
			<TeamBadge
				teamName={currentTeamName ? `${currentTeamName} Graph` : null}
				size="sm"
			/>
		</span>

		<!-- Search pill -->
		<button
			onclick={openCommandPalette}
			class="flex items-center gap-2 bg-navy-800 border border-navy-600 rounded-full px-3 py-1.5 text-xs text-slate-500 hover:border-navy-500 hover:text-slate-400 transition-colors min-w-[200px] focus-within:ring-1 focus-within:ring-gold/30"
			aria-label="Search (Cmd+K)"
			data-testid="search-pill"
		>
			<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
			</svg>
			<span>Search</span>
			<kbd class="text-[10px] px-1 py-0.5 rounded bg-navy-700 border border-navy-600 text-slate-600 font-mono">⌘K</kbd>
		</button>

		<!-- Right-side action buttons with separator -->
		<div class="flex items-center gap-2 border-l border-navy-700 pl-3 ml-auto">
			<!-- Chat button -->
			<button
				onclick={() => (chatPanelOpen = !chatPanelOpen)}
				class="w-8 h-8 flex items-center justify-center rounded border transition-colors {chatPanelOpen
					? 'border-gold text-gold bg-gold/10'
					: 'border-navy-600 text-slate-400 hover:text-gold hover:border-gold/40'}"
				aria-label="Toggle chat"
				data-testid="chat-btn"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
				</svg>
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
				class="w-8 h-8 flex items-center justify-center rounded border border-navy-600 text-slate-400 hover:text-gold hover:border-gold/40 transition-colors"
				aria-label="Upload document"
				data-testid="upload-btn"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Warning banner -->
	{#if showWarningBanner}
		<div
			class="flex items-center gap-2 px-4 py-2 text-xs border-b shrink-0 {expansionBlocked
				? 'bg-red-950/40 border-red-800/40 text-red-300'
				: 'bg-amber-950/40 border-amber-800/40 text-amber-300'}"
		>
			<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
			</svg>
			{#if expansionBlocked}
				<span>Graph has {nodeCount} nodes (limit: {BLOCK_THRESHOLD}). Expansion blocked. Filter or reset to reduce.</span>
			{:else}
				<span>Graph has {nodeCount} nodes. Performance may degrade above {BLOCK_THRESHOLD}.</span>
			{/if}
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
			<!-- Ambient radial glow for depth -->
			<div class="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-navy-800/20 via-transparent to-transparent z-0"></div>
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

			<!-- Zoom rail (overlays graph, left edge) -->
			<ZoomRail
				disabled={graphData.nodes.length === 0}
				onzoomin={() => graphApi?.zoomIn()}
				onzoomout={() => graphApi?.zoomOut()}
				onfitview={() => graphApi?.fitToView()}
				onresetlayout={() => graphApi?.resetLayout()}
			/>

			<!-- Entity detail overlay (right edge) -->
			{#if selectedNode && !queryPanelOpen}
				<KGEntityPanel
					node={selectedNode}
					relationships={selectedNodeRels}
					{loadingRels}
					{dealPartners}
					{isAdmin}
					{editingEntity}
					{editForm}
					{entitySaving}
					{deleteConfirmEntity}
					{entityDeleting}
					{editingRelId}
					{editRelPredicate}
					{relSaving}
					{deleteConfirmRelId}
					{relDeleting}
					onclose={closeEntityPanel}
					onstarteditenity={startEditEntity}
					oncanceleditentity={cancelEditEntity}
					onsaveentity={saveEntity}
					ondeleteentityconfirm={confirmDeleteEntity}
					onsetdeleteconfirm={(val) => (deleteConfirmEntity = val)}
					onstarteditrel={startEditRel}
					oncanceleditrel={cancelEditRel}
					onsaverel={saveRel}
					ondeleterelconfirm={confirmDeleteRel}
					onsetdeleterelconfirm={(id) => (deleteConfirmRelId = id)}
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

		<!-- Query panel (slide-out right) -->
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
						{#if queryResult.sources_used?.length > 0}
							<div class="text-[10px] text-slate-500">
								Sources: {(queryResult.sources_used ?? []).join(', ')}
							</div>
						{/if}

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

						{#if queryResult.relationships?.length > 0}
							<div>
								<h4 class="text-xs font-semibold text-slate-400 mb-1.5">Relationships</h4>
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
	</div>

	<!-- Bottom filter strip -->
	<FilterStrip
		{nodeCount}
		edgeCount={graphData.edges.length}
		{selectedTypes}
		{selectedFamilies}
		{dealModeActive}
		dealPartnerCount={dealPartners.length}
		{metadataKey}
		{metadataValue}
		ontoggletype={toggleType}
		ontogglefamily={toggleFamily}
		ontoggledeal={() => (dealModeActive = !dealModeActive)}
		onmetadatachange={handleMetadataChange}
		onclearall={clearAllFilters}
	/>

	<!-- Color legend -->
	<div class="flex items-center gap-5 px-4 py-2 bg-gradient-to-r from-navy-900 to-navy-950 border-t border-navy-700 shrink-0">
		{#each Object.entries(NODE_COLORS) as [type, color] (type)}
			<div class="flex items-center gap-1.5">
				<svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
					<circle r="6" fill={color} stroke={color} stroke-opacity="0.5" stroke-width="1" />
				</svg>
				<span class="text-xs text-slate-400">{type === 'sports_team' ? 'Sports Team' : type.charAt(0).toUpperCase() + type.slice(1)}</span>
			</div>
		{/each}
		<div class="flex items-center gap-1.5 ml-4 border-l border-navy-700 pl-4">
			<svg width="30" height="10" viewBox="0 0 30 10" aria-hidden="true">
				<path d="M2,5 Q15,2 28,5" fill="none" stroke="#475569" stroke-width="1.5" />
				<polygon points="26,3 30,5 26,7" fill="#475569" />
			</svg>
			<span class="text-xs text-slate-500">relationship</span>
		</div>
		<div class="flex items-center gap-1.5 ml-2 border-l border-navy-700 pl-4">
			<svg width="30" height="10" viewBox="0 0 30 10" aria-hidden="true">
				<path d="M2,5 Q15,2 28,5" fill="none" stroke="#C0922B" stroke-width="1.5" />
				<polygon points="26,3 30,5 26,7" fill="#C0922B" />
			</svg>
			<span class="text-xs text-slate-500">highlighted</span>
		</div>
	</div>
</div>

<!-- Context menu -->
{#if contextMenu}
	<div
		class="fixed z-50 bg-navy-800/95 backdrop-blur-sm border border-navy-600/80 rounded-xl shadow-2xl py-1.5 min-w-[160px]"
		style="left: {contextMenu.x}px; top: {contextMenu.y}px;"
		role="menu"
	>
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700/80 hover:pl-4 hover:text-gold transition-all duration-150 disabled:opacity-40"
			role="menuitem"
			onclick={contextExpandNeighbors}
			disabled={expansionBlocked}
		>
			Expand neighbors
		</button>
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700/80 hover:pl-4 hover:text-gold transition-all duration-150"
			role="menuitem"
			onclick={contextHideNode}
		>
			Hide node
		</button>
		<hr class="border-navy-600/60 my-0.5" />
		<button
			class="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-navy-700/80 hover:pl-4 hover:text-gold transition-all duration-150"
			role="menuitem"
			onclick={() => { handleNodeClick(contextMenu!.nodeId); closeContextMenu(); }}
		>
			View entity details
		</button>
	</div>
{/if}

<!-- Edge detail tooltip -->
{#if edgeTooltip && selectedEdge}
	<div
		class="fixed z-50 backdrop-blur-sm bg-navy-800/95 border border-navy-600/80 rounded-xl shadow-2xl p-3 min-w-[200px] max-w-[280px]"
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

<!-- Keyboard shortcut cheat sheet -->
{#if shortcutSheetOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
		role="presentation"
		onclick={() => (shortcutSheetOpen = false)}
	>
		<div
			class="bg-navy-800 border border-navy-600 rounded-xl shadow-2xl p-6 min-w-[320px] max-w-[400px]"
			role="dialog"
			aria-modal="true"
			aria-label="Keyboard shortcuts"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-sm font-semibold text-slate-200">Keyboard Shortcuts</h2>
				<button
					onclick={() => (shortcutSheetOpen = false)}
					class="text-slate-500 hover:text-slate-300 transition-colors"
					aria-label="Close shortcuts"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			<div class="space-y-2">
				{#each [
					{ keys: 'Esc', desc: 'Close active panel' },
					{ keys: '?', desc: 'Show this shortcut sheet' },
					{ keys: '⌘K', desc: 'Open search / command palette' },
					{ keys: '/', desc: 'Open search / command palette' },
					{ keys: 'Dbl-click', desc: 'Expand node neighbors' },
					{ keys: 'Right-click', desc: 'Context menu' },
				] as shortcut (shortcut.keys)}
					<div class="flex items-center justify-between gap-4">
						<kbd class="text-xs px-2 py-1 rounded bg-navy-700 border border-navy-600 font-mono text-slate-300 shrink-0">
							{shortcut.keys}
						</kbd>
						<span class="text-xs text-slate-400 text-right">{shortcut.desc}</span>
					</div>
				{/each}
			</div>
		</div>
	</div>
{/if}

<!-- Toast notification -->
{#if toastMessage}
	<div class="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-navy-800/95 backdrop-blur-sm border border-gold/30 border-l-2 border-l-gold rounded-xl px-5 py-3 text-xs text-slate-200 shadow-2xl">
		{toastMessage}
	</div>
{/if}
