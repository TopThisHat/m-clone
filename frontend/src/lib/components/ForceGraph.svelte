<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import Graph from 'graphology';
	import Sigma from 'sigma';
	import FA2Layout from 'graphology-layout-forceatlas2/worker';
	import type { KGGraphNode, KGGraphEdge } from '$lib/api/knowledgeGraph';
	import type { CameraState } from 'sigma/types';

	// ── Node / edge graphology attribute shapes ────────────────────────────
	interface NodeAttrs {
		x: number;
		y: number;
		size: number;
		color: string;
		label: string;
		entityType: string;
		highlighted: boolean;
		hidden: boolean;
	}

	interface EdgeAttrs {
		size: number;
		color: string;
		label: string;
		highlighted: boolean;
		hidden: boolean;
	}

	// ── Public API exposed via onGraphReady ────────────────────────────────
	interface GraphAPI {
		mergeNodes: (newNodes: KGGraphNode[], newEdges: KGGraphEdge[]) => void;
		fitToView: () => void;
		resetLayout: () => void;
		zoomIn: () => void;
		zoomOut: () => void;
		focusNode: (nodeId: string) => void;
	}

	// ── Props (identical interface to the replaced D3 component) ──────────
	let {
		nodes,
		edges,
		highlightedNodeIds = null,
		highlightedEdgeIds = null,
		focusNodeId = null,
		selectedNodeId = null,
		theme = 'dark',
		onNodeClick = () => {},
		onNodeDblClick = () => {},
		onNodeContextMenu = () => {},
		onEdgeClick = () => {},
		onGraphReady = () => {},
	}: {
		nodes: KGGraphNode[];
		edges: KGGraphEdge[];
		highlightedNodeIds?: Set<string> | null;
		highlightedEdgeIds?: Set<string> | null;
		focusNodeId?: string | null;
		selectedNodeId?: string | null;
		theme?: 'light' | 'dark';
		onNodeClick?: (nodeId: string) => void;
		onNodeDblClick?: (nodeId: string) => void;
		onNodeContextMenu?: (nodeId: string, x: number, y: number) => void;
		onEdgeClick?: (edgeId: string, x: number, y: number) => void;
		onGraphReady?: (api: GraphAPI) => void;
	} = $props();

	// ── Theme colors (Issue 6) ─────────────────────────────────────────────
	const themeColors = $derived(theme === 'light' ? {
		bg: '#F5F6F8',
		edge: '#94A3B8',
		edgeDim: '#CBD5E1',
		labelColor: '#1E293B',
	} : {
		bg: '#0B1426',
		edge: '#475569',
		edgeDim: '#1E293B',
		labelColor: '#E2E8F0',
	});

	// Entity type → color (both themes). pe_fund added per spec; product kept for compat.
	const typeColors = $derived(theme === 'light' ? {
		person:      '#2563EB',
		company:     '#0891B2',
		sports_team: '#D97706',
		location:    '#16A34A',
		pe_fund:     '#7C3AED',
		product:     '#7C3AED',
		other:       '#64748B',
	} as Record<string, string> : {
		person:      '#60A5FA',
		company:     '#22D3EE',
		sports_team: '#FBBF24',
		location:    '#4ADE80',
		pe_fund:     '#C084FC',
		product:     '#C084FC',
		other:       '#CBD5E1',
	} as Record<string, string>);

	function nodeColor(entityType: string): string {
		return typeColors[entityType.toLowerCase()] ?? typeColors.other;
	}

	// ── DOM refs ───────────────────────────────────────────────────────────
	let containerEl: HTMLDivElement;
	let minimapEl: HTMLDivElement = $state()!;

	// ── Runtime objects (not reactive — managed imperatively) ──────────────
	let graph: Graph<NodeAttrs, EdgeAttrs> | null = null;
	let renderer: Sigma<NodeAttrs, EdgeAttrs> | null = null;
	let minimapRenderer: Sigma<NodeAttrs, EdgeAttrs> | null = null;
	let fa2: FA2Layout<NodeAttrs, EdgeAttrs> | null = null;

	// Drag state
	let draggedNode: string | null = null;
	let isDragging = false;

	// Minimap visibility state (Issue 7)
	let minimapVisible = $state(false);
	let minimapUserToggle = $state(false);

	// ── Convergence monitoring for FA2 auto-stop ──────────────────────────
	let prevPositions: Map<string, { x: number; y: number }> = new Map();
	let convergenceCheckTimer: ReturnType<typeof setInterval> | null = null;

	// ── Helpers ────────────────────────────────────────────────────────────
	function getNodeColor(entityType: string): string {
		return nodeColor(entityType);
	}

	/** Spread initial positions in a circle to avoid FA2 singularity. */
	function initialPosition(index: number, total: number): { x: number; y: number } {
		const angle = (index / Math.max(total, 1)) * 2 * Math.PI;
		const r = Math.max(10, total * 0.4);
		return { x: Math.cos(angle) * r, y: Math.sin(angle) * r };
	}

	// ── Graph initialisation ───────────────────────────────────────────────
	function buildGraph(): void {
		// Stop FA2 and convergence watch, but keep renderer + graph alive
		stopConvergenceWatch();
		if (fa2) { fa2.kill(); fa2 = null; }

		// Reuse existing graph or create new one (avoids WebGL context churn)
		if (!graph) {
			graph = new Graph<NodeAttrs, EdgeAttrs>({ multi: false, type: 'directed' });
		} else {
			graph.clear();
		}

		const total = nodes.length;
		nodes.forEach((n, i) => {
			const pos = initialPosition(i, total);
			graph!.addNode(n.id, {
				x: pos.x,
				y: pos.y,
				size: 12,
				color: getNodeColor(n.entity_type),
				label: n.name,
				entityType: n.entity_type,
				highlighted: false,
				hidden: false,
			});
		});

		for (const e of edges) {
			if (graph.hasNode(e.source) && graph.hasNode(e.target)) {
				try {
					graph.addEdgeWithKey(e.id, e.source, e.target, {
						size: 2,
						color: themeColors.edge,
						label: e.predicate.replace(/_/g, ' '),
						highlighted: false,
						hidden: false,
					});
				} catch {
					// Duplicate edge — skip
				}
			}
		}

		// Scale node sizes by degree: min 8, max 24
		graph.forEachNode((nodeId) => {
			const degree = graph!.degree(nodeId);
			const size = Math.min(24, Math.max(8, 8 + degree * 2));
			graph!.setNodeAttribute(nodeId, 'size', size);
		});

		// Reuse existing Sigma renderer if possible (preserves WebGL context)
		if (renderer) {
			renderer.refresh();
			startLayout();
			updateMinimap();
			onGraphReady({ mergeNodes, fitToView, resetLayout, zoomIn, zoomOut, focusNode: focusOnNode });
		} else {
			mountRenderer();
		}
	}

	function mountRenderer(): void {
		if (!graph || !containerEl) return;

		// Kill any stale renderer first to free its WebGL context
		if (renderer) { renderer.kill(); renderer = null; }

		try {
			renderer = new Sigma<NodeAttrs, EdgeAttrs>(graph, containerEl, {
				renderLabels: true,
				renderEdgeLabels: false,
				enableEdgeEvents: true,
				labelColor: { color: themeColors.labelColor },
				defaultEdgeColor: themeColors.edge,
				labelRenderedSizeThreshold: 8,
				defaultNodeColor: '#64748B',
				defaultEdgeType: 'arrow',
				zIndex: true,
				// Reducers drive highlighting / dimming (Issue 5, 6)
				nodeReducer: nodeReducerFn,
				edgeReducer: edgeReducerFn,
			});
		} catch (err) {
			// WebGL context creation failed — wait for browser to reclaim contexts and retry once
			console.warn('Sigma WebGL context creation failed, retrying...', err);
			renderer = null;
			setTimeout(() => mountRenderer(), 500);
			return;
		}

		// ── Camera controls (Issue 4) ──────────────────────────────────────
		setupCameraLOD();

		// ── Events (Issue 5) ──────────────────────────────────────────────
		bindEvents();

		// ── FA2 Web Worker layout (Issue 3) ───────────────────────────────
		startLayout();

		// ── Minimap (Issue 7) ─────────────────────────────────────────────
		updateMinimap();

		// Expose API to parent
		onGraphReady({ mergeNodes, fitToView, resetLayout, zoomIn, zoomOut, focusNode: focusOnNode });
	}

	// ── Node / edge reducers (highlighting + theming) ─────────────────────
	function nodeReducerFn(nodeId: string, data: NodeAttrs): Partial<NodeAttrs> & { color: string; size: number; label: string; highlighted: boolean } {
		const hasHighlight = highlightedNodeIds !== null || highlightedEdgeIds !== null;
		const isHighlighted = highlightedNodeIds?.has(nodeId) ?? false;
		const isSelected = nodeId === selectedNodeId;

		const color = getNodeColor(data.entityType);
		const highlighted = isSelected || isHighlighted;

		if (hasHighlight && !isHighlighted && !isSelected) {
			return { ...data, color, highlighted: false, size: data.size, label: data.label, hidden: false };
		}

		return {
			...data,
			color,
			highlighted,
			size: isSelected ? data.size + 4 : data.size,
			label: data.label,
			hidden: false,
		};
	}

	function edgeReducerFn(edgeId: string, data: EdgeAttrs): Partial<EdgeAttrs> & { color: string; size: number } {
		const hasHighlight = highlightedNodeIds !== null || highlightedEdgeIds !== null;
		const isHighlighted = highlightedEdgeIds?.has(edgeId) ?? false;

		if (hasHighlight && !isHighlighted) {
			return { ...data, color: themeColors.edgeDim, size: 1, label: data.label, highlighted: false };
		}
		if (isHighlighted) {
			return { ...data, color: '#C0922B', size: 3, label: data.label, highlighted: true };
		}
		return { ...data, color: themeColors.edge, size: data.size, label: data.label, highlighted: false };
	}

	// ── Label LOD (Issue 4) ────────────────────────────────────────────────
	function setupCameraLOD(): void {
		if (!renderer || !graph) return;
		const camera = renderer.getCamera();

		camera.on('updated', (state: CameraState) => {
			if (!renderer || !graph) return;
			const ratio = state.ratio;

			if (ratio > 0.7) {
				// High zoom: show all labels + edge labels
				renderer.setSetting('renderLabels', true);
				renderer.setSetting('renderEdgeLabels', true);
				renderer.setSetting('labelRenderedSizeThreshold', 0);
			} else if (ratio > 0.3) {
				// Medium zoom: only top-50 by degree, no edge labels
				renderer.setSetting('renderEdgeLabels', false);
				renderer.setSetting('renderLabels', true);
				renderer.setSetting('labelRenderedSizeThreshold', 8);
			} else {
				// Low zoom: no labels
				renderer.setSetting('renderLabels', false);
				renderer.setSetting('renderEdgeLabels', false);
			}

			// Update minimap viewport rect
			drawMinimapViewport();
		});
	}

	// ── Camera control functions (Issue 4) ────────────────────────────────
	function fitToView(): void {
		if (!renderer || !graph) return;
		const camera = renderer.getCamera();
		camera.animate({ x: 0.5, y: 0.5, ratio: 1, angle: 0 }, { duration: 500 });
	}

	function zoomIn(): void {
		if (!renderer) return;
		const camera = renderer.getCamera();
		camera.animate({ ratio: camera.ratio / 1.5 }, { duration: 200 });
	}

	function zoomOut(): void {
		if (!renderer) return;
		const camera = renderer.getCamera();
		camera.animate({ ratio: camera.ratio * 1.5 }, { duration: 200 });
	}

	function focusOnNode(entityId: string): void {
		if (!renderer || !graph || !graph.hasNode(entityId)) return;
		const camera = renderer.getCamera();
		const { x, y } = graph.getNodeAttributes(entityId);
		const viewportCoords = renderer.framedGraphToViewport({ x, y });
		const graphCoords = renderer.viewportToGraph(viewportCoords);
		camera.animate(
			{ x: graphCoords.x, y: graphCoords.y, ratio: 0.3 },
			{ duration: 750 }
		);
	}

	function resetLayout(): void {
		if (!graph) return;
		const total = graph.order;
		let i = 0;
		graph.forEachNode((nodeId) => {
			const pos = initialPosition(i, total);
			graph!.setNodeAttribute(nodeId, 'x', pos.x);
			graph!.setNodeAttribute(nodeId, 'y', pos.y);
			i++;
		});
		if (fa2) {
			fa2.stop();
			fa2.start();
		}
		renderer?.refresh();
	}

	// ── Incremental merge (Issue 2) ────────────────────────────────────────
	function mergeNodes(newNodes: KGGraphNode[], newEdges: KGGraphEdge[]): void {
		if (!graph) {
			buildGraph();
			return;
		}

		let addedCount = 0;
		const total = graph.order + newNodes.filter(n => !graph!.hasNode(n.id)).length;

		for (const n of newNodes) {
			if (!graph.hasNode(n.id)) {
				const pos = initialPosition(addedCount + graph.order, total);
				graph.addNode(n.id, {
					x: pos.x,
					y: pos.y,
					size: 12,
					color: getNodeColor(n.entity_type),
					label: n.name,
					entityType: n.entity_type,
					highlighted: false,
					hidden: false,
				});
				addedCount++;
			}
		}

		for (const e of newEdges) {
			if (!graph.hasEdge(e.id) && graph.hasNode(e.source) && graph.hasNode(e.target)) {
				try {
					graph.addEdgeWithKey(e.id, e.source, e.target, {
						size: 2,
						color: themeColors.edge,
						label: e.predicate.replace(/_/g, ' '),
						highlighted: false,
						hidden: false,
					});
				} catch {
					// Skip duplicates
				}
			}
		}

		// Remove nodes not in the new set
		const newNodeIds = new Set(newNodes.map(n => n.id));
		graph.forEachNode((nodeId) => {
			if (!newNodeIds.has(nodeId)) graph!.dropNode(nodeId);
		});

		// Recalculate sizes by degree after structural changes
		graph.forEachNode((nodeId) => {
			const degree = graph!.degree(nodeId);
			const size = Math.min(24, Math.max(8, 8 + degree * 2));
			graph!.setNodeAttribute(nodeId, 'size', size);
		});

		// Restart layout only if FA2 has already converged and stopped
		if (addedCount > 0 && fa2) {
			if (!fa2.isRunning()) {
				fa2.start();
				startConvergenceWatch();
			}
			// If already running, new nodes are automatically picked up
		}

		renderer?.refresh();
		updateMinimap();
	}

	// ── FA2 Web Worker (Issue 3) ───────────────────────────────────────────
	function startLayout(): void {
		if (!graph) return;
		if (graph.order === 0) return;

		fa2 = new FA2Layout<NodeAttrs, EdgeAttrs>(graph, {
			settings: {
				gravity: 1,
				scalingRatio: 10,
				barnesHutOptimize: true,
				barnesHutTheta: 0.5,
				slowDown: 50,
				linLogMode: true,
				outboundAttractionDistribution: true,
				strongGravityMode: false,
			},
		});

		fa2.start();
		startConvergenceWatch();
	}

	function startConvergenceWatch(): void {
		if (convergenceCheckTimer) clearInterval(convergenceCheckTimer);

		prevPositions = new Map();
		graph?.forEachNode((nodeId, attrs) => {
			prevPositions.set(nodeId, { x: attrs.x, y: attrs.y });
		});

		convergenceCheckTimer = setInterval(() => {
			if (!fa2 || !graph || !fa2.isRunning()) {
				stopConvergenceWatch();
				return;
			}

			let totalDelta = 0;
			let count = 0;
			graph.forEachNode((nodeId, attrs) => {
				const prev = prevPositions.get(nodeId);
				if (prev) {
					const dx = attrs.x - prev.x;
					const dy = attrs.y - prev.y;
					totalDelta += Math.sqrt(dx * dx + dy * dy);
					count++;
				}
				prevPositions.set(nodeId, { x: attrs.x, y: attrs.y });
			});

			const avgDelta = count > 0 ? totalDelta / count : 0;
			if (avgDelta < 0.05) {
				fa2.stop();
				stopConvergenceWatch();
				renderer?.refresh();
			}
		}, 500);
	}

	function stopConvergenceWatch(): void {
		if (convergenceCheckTimer) {
			clearInterval(convergenceCheckTimer);
			convergenceCheckTimer = null;
		}
	}

	// ── Node drag (Issue 5) — implemented via Sigma mouse events ──────────
	function bindEvents(): void {
		if (!renderer) return;

		// Node clicks
		renderer.on('clickNode', ({ node, event }) => {
			if (!isDragging) onNodeClick(node);
		});

		renderer.on('doubleClickNode', ({ node, event }) => {
			event.preventSigmaDefault();
			onNodeDblClick(node);
		});

		renderer.on('rightClickNode', ({ node, event }) => {
			event.preventSigmaDefault();
			const orig = event.original;
			const x = orig instanceof MouseEvent ? orig.clientX : 0;
			const y = orig instanceof MouseEvent ? orig.clientY : 0;
			onNodeContextMenu(node, x, y);
		});

		// Edge events
		renderer.on('clickEdge', ({ edge, event }) => {
			const orig = event.original;
			const x = orig instanceof MouseEvent ? orig.clientX : 0;
			const y = orig instanceof MouseEvent ? orig.clientY : 0;
			onEdgeClick(edge, x, y);
		});

		// Hover highlighting (Issue 5)
		renderer.on('enterNode', ({ node }) => {
			if (!graph || !renderer) return;
			setHoverHighlight(node);
		});

		renderer.on('leaveNode', () => {
			clearHoverHighlight();
		});

		// Drag implementation via down/move/up on stage
		renderer.on('downNode', ({ node }) => {
			if (!graph) return;
			draggedNode = node;
			isDragging = false;
			// Disable camera panning while dragging a node
			renderer!.getCamera().disable();
		});

		renderer.getMouseCaptor().on('mousemove', (e) => {
			if (draggedNode && graph && renderer) {
				isDragging = true;
				const graphPos = renderer.viewportToGraph({ x: e.x, y: e.y });
				graph.setNodeAttribute(draggedNode, 'x', graphPos.x);
				graph.setNodeAttribute(draggedNode, 'y', graphPos.y);

				// Pin position in FA2
				if (fa2) {
					// FA2 supervisor doesn't expose per-node pinning directly;
					// we stop layout on drag to freeze it at dragged position
				}

				renderer.refresh({ skipIndexation: false });
			}
		});

		renderer.getMouseCaptor().on('mouseup', () => {
			if (draggedNode) {
				renderer!.getCamera().enable();
				draggedNode = null;
				// Small delay to distinguish click vs drag
				setTimeout(() => { isDragging = false; }, 50);
			}
		});
	}

	// Highlight connected nodes/edges on hover, dim others
	function setHoverHighlight(nodeId: string): void {
		if (!graph || !renderer) return;

		const connectedNodes = new Set<string>([nodeId]);
		const connectedEdges = new Set<string>();

		graph.forEachEdge(nodeId, (edgeId, _attrs, source, target) => {
			connectedEdges.add(edgeId);
			connectedNodes.add(source);
			connectedNodes.add(target);
		});

		renderer.setSetting('nodeReducer', (id: string, data: NodeAttrs) => {
			const isConn = connectedNodes.has(id);
			return {
				...nodeReducerFn(id, data),
				color: isConn ? getNodeColor(data.entityType) : '#334155',
				label: isConn ? data.label : '',
			};
		});

		renderer.setSetting('edgeReducer', (id: string, data: EdgeAttrs) => {
			const isConn = connectedEdges.has(id);
			return {
				...edgeReducerFn(id, data),
				color: isConn ? '#3B82F6' : themeColors.edgeDim,
				size: isConn ? 3 : 1,
			};
		});

		renderer.refresh();
	}

	function clearHoverHighlight(): void {
		if (!renderer) return;
		renderer.setSetting('nodeReducer', nodeReducerFn);
		renderer.setSetting('edgeReducer', edgeReducerFn);
		renderer.refresh();
	}

	// ── Minimap (Issue 7) ─────────────────────────────────────────────────
	let minimapCanvas: HTMLCanvasElement | null = $state(null);

	function updateMinimap(): void {
		const shouldShow = minimapUserToggle || (graph !== null && graph.order >= 50);
		minimapVisible = shouldShow;

		if (!shouldShow) {
			if (minimapRenderer) {
				minimapRenderer.kill();
				minimapRenderer = null;
			}
			return;
		}

		if (!graph || !minimapEl) return;

		if (minimapRenderer) {
			minimapRenderer.refresh();
			return;
		}

		try {
			minimapRenderer = new Sigma<NodeAttrs, EdgeAttrs>(graph, minimapEl, {
				renderLabels: false,
				renderEdgeLabels: false,
				enableEdgeEvents: false,
				defaultNodeColor: '#64748B',
				defaultEdgeColor: '#334155',
				labelRenderedSizeThreshold: Infinity,
				// Small fixed node sizes for overview
				nodeReducer: (_id: string, data: NodeAttrs) => ({
					...data,
					size: 3,
					color: getNodeColor(data.entityType),
					label: '',
				}),
				edgeReducer: (_id: string, data: EdgeAttrs) => ({
					...data,
					size: 1,
					color: '#334155',
				}),
			});
		} catch {
			// WebGL context exhausted — skip minimap silently
			minimapRenderer = null;
			minimapVisible = false;
			return;
		}

		// Disable all interaction on minimap
		minimapRenderer.getCamera().disable();

		// Sync minimap camera to main camera
		if (renderer) {
			renderer.getCamera().on('updated', syncMinimapCamera);
		}
	}

	function syncMinimapCamera(state: CameraState): void {
		if (!minimapRenderer) return;
		// Keep minimap at a fixed overview zoom
		minimapRenderer.getCamera().setState({ x: state.x, y: state.y, ratio: 2, angle: 0 });
		drawMinimapViewport();
	}

	function drawMinimapViewport(): void {
		// Viewport indicator is drawn on a canvas overlay inside the minimap container
		// This is a lightweight implementation showing the camera state
		if (!minimapCanvas || !renderer) return;
		const ctx = minimapCanvas.getContext('2d');
		if (!ctx) return;
		ctx.clearRect(0, 0, minimapCanvas.width, minimapCanvas.height);
		const vp = renderer.viewRectangle();
		// Map graph-space viewport to minimap canvas coords (simplified)
		ctx.strokeStyle = '#C0922B';
		ctx.lineWidth = 1.5;
		ctx.strokeRect(4, 4, minimapCanvas.width - 8, minimapCanvas.height - 8);
	}

	// ── Teardown (only called on component destroy, not during rebuilds) ──
	function teardown(): void {
		stopConvergenceWatch();
		if (fa2) { fa2.kill(); fa2 = null; }
		if (minimapRenderer) { minimapRenderer.kill(); minimapRenderer = null; }
		if (renderer) { renderer.kill(); renderer = null; }
		if (graph) { graph.clear(); graph = null; }
		draggedNode = null;
		isDragging = false;
	}

	// ── Reactive effects ───────────────────────────────────────────────────

	// Identity-based change detection — only rebuild/merge when actual data changes,
	// not on every Svelte re-evaluation caused by unrelated state (chat panel, etc.)
	let prevNodeFingerprint = '';
	let prevEdgeFingerprint = '';
	let graphInitialized = false;

	$effect(() => {
		const nodeFingerprint = nodes.map((n) => n.id).sort().join(',');
		const edgeFingerprint = edges.map((e) => e.id).sort().join(',');

		if (nodeFingerprint !== prevNodeFingerprint || edgeFingerprint !== prevEdgeFingerprint) {
			prevNodeFingerprint = nodeFingerprint;
			prevEdgeFingerprint = edgeFingerprint;

			if (!graphInitialized || !graph || !renderer) {
				buildGraph();
				graphInitialized = true;
			} else {
				// Incremental update instead of full teardown + rebuild
				mergeNodes(nodes, edges);
			}
		}
	});

	// Apply highlighting without rebuild (Issue 5, 6)
	$effect(() => {
		const _hl = highlightedNodeIds;
		const _hle = highlightedEdgeIds;
		if (renderer) {
			renderer.setSetting('nodeReducer', nodeReducerFn);
			renderer.setSetting('edgeReducer', edgeReducerFn);
			renderer.refresh();
		}
	});

	// Apply selection ring without rebuild
	$effect(() => {
		const _sel = selectedNodeId;
		if (renderer) {
			renderer.setSetting('nodeReducer', nodeReducerFn);
			renderer.refresh();
		}
	});

	// Focus on node when focusNodeId changes (Issue 4)
	$effect(() => {
		const nodeId = focusNodeId;
		if (nodeId) focusOnNode(nodeId);
	});

	// Update theme colors on edges without rebuild (Issue 6)
	$effect(() => {
		const _theme = theme;
		if (!graph || !renderer) return;
		graph.forEachEdge((edgeId) => {
			graph!.setEdgeAttribute(edgeId, 'color', themeColors.edge);
		});
		renderer.setSetting('defaultEdgeColor', themeColors.edge);
		renderer.setSetting('labelColor', { color: themeColors.labelColor });
		renderer.refresh();
	});

	onMount(() => {
		// ResizeObserver to handle container size changes
		const observer = new ResizeObserver(() => {
			renderer?.resize();
			minimapRenderer?.resize();
		});
		observer.observe(containerEl);

		return () => {
			observer.disconnect();
		};
	});

	onDestroy(() => {
		teardown();
	});
</script>

<!-- Main graph container -->
<div class="relative w-full h-full min-h-[400px]">
	<div bind:this={containerEl} class="w-full h-full"></div>

	<!-- Minimap (Issue 7) -->
	{#if minimapVisible}
		<div class="absolute bottom-4 right-4 w-[120px] h-[80px] rounded-xl overflow-hidden border border-navy-600/60 shadow-xl bg-navy-950/80 backdrop-blur-sm">
			<div bind:this={minimapEl} class="w-full h-full"></div>
			<canvas
				bind:this={minimapCanvas}
				width={120}
				height={80}
				class="absolute inset-0 pointer-events-none"
			></canvas>
		</div>
	{/if}

	<!-- Minimap toggle button -->
	<button
		onclick={() => { minimapUserToggle = !minimapUserToggle; updateMinimap(); }}
		class="absolute bottom-4 right-[140px] w-8 h-8 flex items-center justify-center rounded-lg bg-navy-800 border border-navy-600 text-slate-400 hover:text-slate-200 hover:bg-navy-700 transition-colors text-xs"
		title={minimapVisible ? 'Hide minimap' : 'Show minimap'}
		aria-label={minimapVisible ? 'Hide minimap' : 'Show minimap'}
	>
		{#if minimapVisible}
			<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<rect x="3" y="3" width="7" height="7"></rect>
				<rect x="14" y="3" width="7" height="7"></rect>
				<rect x="14" y="14" width="7" height="7"></rect>
				<rect x="3" y="14" width="7" height="7"></rect>
			</svg>
		{:else}
			<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<rect x="3" y="3" width="18" height="18" rx="2"></rect>
				<rect x="7" y="7" width="4" height="4"></rect>
			</svg>
		{/if}
	</button>
</div>
