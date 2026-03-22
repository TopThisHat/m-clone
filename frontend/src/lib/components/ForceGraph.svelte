<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import * as d3 from 'd3';
	import type { KGGraphNode, KGGraphEdge } from '$lib/api/knowledgeGraph';

	interface SimNode extends KGGraphNode, d3.SimulationNodeDatum {}
	interface SimEdge {
		id: string;
		source: SimNode | string;
		target: SimNode | string;
		predicate: string;
		predicate_family: string;
		confidence: number;
	}

	let {
		nodes,
		edges,
		highlightedNodeIds = null,
		highlightedEdgeIds = null,
		focusNodeId = null,
		selectedNodeId = null,
		theme = 'dark',
		onNodeClick = () => {},
	}: {
		nodes: KGGraphNode[];
		edges: KGGraphEdge[];
		highlightedNodeIds?: Set<string> | null;
		highlightedEdgeIds?: Set<string> | null;
		focusNodeId?: string | null;
		selectedNodeId?: string | null;
		theme?: 'light' | 'dark';
		onNodeClick?: (nodeId: string) => void;
	} = $props();

	// Theme-dependent colors
	const themeColors = $derived(theme === 'light' ? {
		bg: '#F5F6F8',
		edgeStroke: '#94A3B8',
		edgeDim: '#CBD5E1',
		arrowFill: '#94A3B8',
		pillFill: '#FFFFFF',
		pillStroke: '#CBD5E1',
		edgeText: '#475569',
		nodeText: '#FFFFFF',
		typeBadgeText: '#475569',
		typeBadgeOpacity: 0.9,
	} : {
		bg: '#0B1426',
		edgeStroke: '#475569',
		edgeDim: '#1E293B',
		arrowFill: '#64748B',
		pillFill: '#1E293B',
		pillStroke: '#334155',
		edgeText: '#94A3B8',
		nodeText: '#FFFFFF',
		typeBadgeText: '#94A3B8',
		typeBadgeOpacity: 0.85,
	});

	let containerEl: HTMLDivElement;
	let simulation: d3.Simulation<SimNode, SimEdge> | null = null;

	// Theme-aware node colors — vivid fills with clear contrast in both modes
	const typeColors = $derived(theme === 'light' ? {
		person:      { fill: '#2563EB', stroke: '#1D4ED8' },
		company:     { fill: '#0891B2', stroke: '#0E7490' },
		sports_team: { fill: '#D97706', stroke: '#B45309' },
		location:    { fill: '#16A34A', stroke: '#15803D' },
		product:     { fill: '#7C3AED', stroke: '#6D28D9' },
		other:       { fill: '#64748B', stroke: '#475569' },
	} as Record<string, { fill: string; stroke: string }> : {
		person:      { fill: '#3B82F6', stroke: '#2563EB' },
		company:     { fill: '#06B6D4', stroke: '#0891B2' },
		sports_team: { fill: '#F59E0B', stroke: '#D97706' },
		location:    { fill: '#22C55E', stroke: '#16A34A' },
		product:     { fill: '#A78BFA', stroke: '#7C3AED' },
		other:       { fill: '#94A3B8', stroke: '#64748B' },
	} as Record<string, { fill: string; stroke: string }>);

	function getColors(type: string) {
		return typeColors[type.toLowerCase()] ?? typeColors.other;
	}

	const NODE_RADIUS = 26;
	const FONT_SIZE = 10;

	// Truncate label to fit inside circle
	function truncLabel(name: string, maxChars = 12): string {
		if (name.length <= maxChars) return name;
		return name.slice(0, maxChars - 1) + '\u2026';
	}

	// Split name into at most 2 lines for inside-node display
	function splitLabel(name: string): string[] {
		if (name.length <= 10) return [name];
		// Try to split on space near middle
		const mid = Math.floor(name.length / 2);
		let splitAt = name.lastIndexOf(' ', mid + 3);
		if (splitAt <= 2) splitAt = name.indexOf(' ', mid - 3);
		if (splitAt > 2 && splitAt < name.length - 2) {
			const line1 = name.slice(0, splitAt);
			const line2 = name.slice(splitAt + 1);
			return [truncLabel(line1, 12), truncLabel(line2, 12)];
		}
		return [truncLabel(name, 12)];
	}

	// Compute curved path for an edge (slight arc so parallel edges don't overlap)
	function edgePath(d: SimEdge): string {
		const s = d.source as SimNode;
		const t = d.target as SimNode;
		const dx = t.x! - s.x!;
		const dy = t.y! - s.y!;
		const dist = Math.sqrt(dx * dx + dy * dy) || 1;
		// Offset from center to circle border
		const offS = NODE_RADIUS / dist;
		const offT = (NODE_RADIUS + 6) / dist; // extra for arrowhead
		const x1 = s.x! + dx * offS;
		const y1 = s.y! + dy * offS;
		const x2 = t.x! - dx * offT;
		const y2 = t.y! - dy * offT;
		// Slight curve
		const curvature = 0.15;
		const cx = (x1 + x2) / 2 - dy * curvature;
		const cy = (y1 + y2) / 2 + dx * curvature;
		return `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`;
	}

	// Midpoint of the curved edge for label placement
	function edgeMidpoint(d: SimEdge): { x: number; y: number; angle: number } {
		const s = d.source as SimNode;
		const t = d.target as SimNode;
		const dx = t.x! - s.x!;
		const dy = t.y! - s.y!;
		const curvature = 0.15;
		// Quadratic bezier midpoint at t=0.5
		const mx = (s.x! + t.x!) / 2;
		const my = (s.y! + t.y!) / 2;
		const cx = mx - dy * curvature;
		const cy = my + dx * curvature;
		// Point on curve at t=0.5: (1-t)^2*P0 + 2(1-t)t*C + t^2*P1
		const px = 0.25 * s.x! + 0.5 * cx + 0.25 * t.x!;
		const py = 0.25 * s.y! + 0.5 * cy + 0.25 * t.y!;
		let angle = Math.atan2(dy, dx) * (180 / Math.PI);
		// Keep text upright
		if (angle > 90) angle -= 180;
		if (angle < -90) angle += 180;
		return { x: px, y: py, angle };
	}

	function buildGraph() {
		if (!containerEl) return;
		if (simulation) simulation.stop();
		d3.select(containerEl).select('svg').remove();

		const rect = containerEl.getBoundingClientRect();
		const width = rect.width || 800;
		const height = rect.height || 600;

		const simNodes: SimNode[] = nodes.map((n) => ({ ...n }));
		const nodeMap = new Map(simNodes.map((n) => [n.id, n]));
		const simEdges: SimEdge[] = edges
			.filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
			.map((e) => ({ ...e }));

		const svgEl = d3
			.select(containerEl)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.style('background', themeColors.bg);

		// Defs: arrow marker + glow filter
		const defs = svgEl.append('defs');

		defs.append('marker')
			.attr('id', 'neo-arrow')
			.attr('viewBox', '0 0 12 12')
			.attr('refX', 10)
			.attr('refY', 6)
			.attr('markerWidth', 8)
			.attr('markerHeight', 8)
			.attr('orient', 'auto')
			.append('path')
			.attr('d', 'M2,2 L10,6 L2,10 Z')
			.attr('fill', themeColors.arrowFill);

		defs.append('marker')
			.attr('id', 'neo-arrow-hl')
			.attr('viewBox', '0 0 12 12')
			.attr('refX', 10)
			.attr('refY', 6)
			.attr('markerWidth', 8)
			.attr('markerHeight', 8)
			.attr('orient', 'auto')
			.append('path')
			.attr('d', 'M2,2 L10,6 L2,10 Z')
			.attr('fill', '#C0922B');

		// Glow filter for hover/selected
		const glow = defs.append('filter').attr('id', 'node-glow');
		glow.append('feGaussianBlur').attr('stdDeviation', '2.5').attr('result', 'blur');
		glow.append('feMerge').selectAll('feMergeNode')
			.data(['blur', 'SourceGraphic'])
			.join('feMergeNode')
			.attr('in', (d) => d);

		const g = svgEl.append('g');

		const zoom = d3
			.zoom<SVGSVGElement, unknown>()
			.scaleExtent([0.05, 6])
			.on('zoom', (event) => g.attr('transform', event.transform));
		svgEl.call(zoom);

		// ── Edges (curved paths) ──
		const edgeGroup = g.append('g').attr('class', 'edges');

		const linkPaths = edgeGroup
			.selectAll<SVGPathElement, SimEdge>('path')
			.data(simEdges, (d) => d.id)
			.join('path')
			.attr('fill', 'none')
			.attr('stroke', themeColors.edgeStroke)
			.attr('stroke-width', 2)
			.attr('marker-end', 'url(#neo-arrow)');

		// ── Edge labels (always visible, pill background) ──
		const edgeLabelGroup = g.append('g').attr('class', 'edge-labels');

		const edgeLabelGs = edgeLabelGroup
			.selectAll<SVGGElement, SimEdge>('g')
			.data(simEdges, (d) => d.id)
			.join('g');

		// Pill background rect (sized after text render)
		const edgePills = edgeLabelGs
			.append('rect')
			.attr('rx', 4)
			.attr('ry', 4)
			.attr('fill', themeColors.pillFill)
			.attr('stroke', themeColors.pillStroke)
			.attr('stroke-width', 0.5);

		const edgeTexts = edgeLabelGs
			.append('text')
			.attr('text-anchor', 'middle')
			.attr('dominant-baseline', 'central')
			.attr('fill', themeColors.edgeText)
			.attr('font-size', '9px')
			.attr('font-family', 'system-ui, sans-serif')
			.attr('letter-spacing', '0.3px')
			.text((d) => d.predicate.replace(/_/g, ' '));

		// ── Nodes ──
		const nodeGroup = g.append('g').attr('class', 'nodes');

		const nodeGs = nodeGroup
			.selectAll<SVGGElement, SimNode>('g')
			.data(simNodes, (d) => d.id)
			.join('g')
			.attr('cursor', 'pointer')
			.on('click', (_event, d) => onNodeClick(d.id));

		// Hover ring (hidden by default)
		nodeGs
			.append('circle')
			.attr('class', 'hover-ring')
			.attr('r', NODE_RADIUS + 4)
			.attr('fill', 'none')
			.attr('stroke', 'transparent')
			.attr('stroke-width', 3)
			.attr('filter', 'url(#node-glow)');

		// Main circle
		nodeGs
			.append('circle')
			.attr('class', 'node-circle')
			.attr('r', NODE_RADIUS)
			.attr('fill', (d) => getColors(d.entity_type).fill)
			.attr('stroke', (d) => getColors(d.entity_type).stroke)
			.attr('stroke-width', 2.5);

		// Inside-node text labels (1 or 2 lines)
		nodeGs.each(function (d) {
			const el = d3.select(this);
			const lines = splitLabel(d.name);
			const yOffset = lines.length === 1 ? 0 : -6;
			lines.forEach((line, i) => {
				el.append('text')
					.attr('class', 'node-text')
					.attr('text-anchor', 'middle')
					.attr('dominant-baseline', 'central')
					.attr('y', yOffset + i * 13)
					.attr('fill', themeColors.nodeText)
					.attr('font-size', `${FONT_SIZE}px`)
					.attr('font-weight', '600')
					.attr('font-family', 'system-ui, sans-serif')
					.attr('pointer-events', 'none')
					.text(line);
			});
		});

		// Type badge (small text below the circle)
		nodeGs
			.append('text')
			.attr('class', 'type-badge')
			.attr('y', NODE_RADIUS + 14)
			.attr('text-anchor', 'middle')
			.attr('fill', themeColors.typeBadgeText)
			.attr('font-size', '8px')
			.attr('font-family', 'system-ui, sans-serif')
			.attr('opacity', themeColors.typeBadgeOpacity)
			.attr('pointer-events', 'none')
			.text((d) => d.entity_type.replace(/_/g, ' '));

		// Hover effects
		nodeGs
			.on('mouseenter', function (_, d) {
				d3.select(this).select('.hover-ring')
					.attr('stroke', getColors(d.entity_type).fill)
					.attr('stroke-opacity', 0.6);
				d3.select(this).select('.node-circle').attr('stroke-width', 3.5);
				// Brighten connected edges
				linkPaths.filter((e) => {
					const s = typeof e.source === 'object' ? (e.source as SimNode).id : e.source;
					const t = typeof e.target === 'object' ? (e.target as SimNode).id : e.target;
					return s === d.id || t === d.id;
				}).attr('stroke', '#2980B9').attr('stroke-width', 3);
				edgeTexts.filter((e) => {
					const s = typeof e.source === 'object' ? (e.source as SimNode).id : e.source;
					const t = typeof e.target === 'object' ? (e.target as SimNode).id : e.target;
					return s === d.id || t === d.id;
				}).attr('fill', theme === 'light' ? '#1E293B' : '#E2E8F0').attr('font-weight', '600');
			})
			.on('mouseleave', function () {
				d3.select(this).select('.hover-ring').attr('stroke', 'transparent');
				d3.select(this).select('.node-circle').attr('stroke-width', 2.5);
				// Reset edges (will be re-applied by highlighting)
				linkPaths.attr('stroke', themeColors.edgeStroke).attr('stroke-width', 2);
				edgeTexts.attr('fill', themeColors.edgeText).attr('font-weight', 'normal');
				applyHighlighting();
			});

		// Drag
		const drag = d3
			.drag<SVGGElement, SimNode>()
			.on('start', (event, d) => {
				if (!event.active) simulation!.alphaTarget(0.3).restart();
				d.fx = d.x;
				d.fy = d.y;
			})
			.on('drag', (event, d) => {
				d.fx = event.x;
				d.fy = event.y;
			})
			.on('end', (event, d) => {
				if (!event.active) simulation!.alphaTarget(0);
				d.fx = null;
				d.fy = null;
			});
		nodeGs.call(drag);

		// Simulation
		simulation = d3
			.forceSimulation(simNodes)
			.force(
				'link',
				d3.forceLink<SimNode, SimEdge>(simEdges).id((d) => d.id).distance(140),
			)
			.force('charge', d3.forceManyBody().strength(-400))
			.force('center', d3.forceCenter(width / 2, height / 2))
			.force('collision', d3.forceCollide(NODE_RADIUS + 12))
			.on('tick', () => {
				linkPaths.attr('d', (d) => edgePath(d));

				// Position edge labels at curve midpoint
				edgeLabelGs.each(function (d) {
					const mid = edgeMidpoint(d);
					d3.select(this).attr('transform', `translate(${mid.x},${mid.y}) rotate(${mid.angle})`);
				});

				// Size pills to fit text
				edgeTexts.each(function () {
					const bbox = (this as SVGTextElement).getBBox();
					const pill = d3.select(this.parentNode as Element).select('rect');
					pill
						.attr('x', -bbox.width / 2 - 5)
						.attr('y', -bbox.height / 2 - 2)
						.attr('width', bbox.width + 10)
						.attr('height', bbox.height + 4);
				});

				nodeGs.attr('transform', (d) => `translate(${d.x},${d.y})`);
			});

		(containerEl as any).__d3refs = {
			svgEl, g, zoom, nodeGs, linkPaths, edgeLabelGs, edgePills, edgeTexts,
			simNodes, simEdges, width, height,
		};

		// Apply initial highlight/selection state
		applyHighlighting();
		applySelection();
	}

	function applyHighlighting() {
		const refs = (containerEl as any)?.__d3refs;
		if (!refs) return;
		const { nodeGs, linkPaths, edgePills, edgeTexts } = refs;
		const hasHighlight = highlightedNodeIds || highlightedEdgeIds;

		nodeGs
			.select('.node-circle')
			.attr('opacity', (d: SimNode) => {
				if (!hasHighlight) return 1;
				return highlightedNodeIds?.has(d.id) ? 1 : 0.15;
			});
		nodeGs
			.selectAll('.node-text')
			.attr('opacity', (d: SimNode) => {
				if (!hasHighlight) return 1;
				return highlightedNodeIds?.has(d.id) ? 1 : 0.15;
			});
		nodeGs
			.select('.type-badge')
			.attr('opacity', (d: SimNode) => {
				if (!hasHighlight) return 0.7;
				return highlightedNodeIds?.has(d.id) ? 0.7 : 0.08;
			});

		linkPaths
			.attr('stroke', (d: SimEdge) => {
				if (highlightedEdgeIds?.has(d.id)) return '#C0922B';
				if (hasHighlight) return themeColors.edgeDim;
				return themeColors.edgeStroke;
			})
			.attr('stroke-width', (d: SimEdge) => {
				if (highlightedEdgeIds?.has(d.id)) return 3;
				return 2;
			})
			.attr('marker-end', (d: SimEdge) => {
				if (highlightedEdgeIds?.has(d.id)) return 'url(#neo-arrow-hl)';
				return 'url(#neo-arrow)';
			});

		edgePills
			.attr('opacity', (d: SimEdge) => {
				if (!hasHighlight) return 1;
				return highlightedEdgeIds?.has(d.id) ? 1 : 0.1;
			});
		edgeTexts
			.attr('opacity', (d: SimEdge) => {
				if (!hasHighlight) return 1;
				return highlightedEdgeIds?.has(d.id) ? 1 : 0.1;
			});
	}

	function applySelection() {
		const refs = (containerEl as any)?.__d3refs;
		if (!refs) return;
		const { nodeGs } = refs;

		nodeGs.select('.hover-ring')
			.attr('stroke', (d: SimNode) => d.id === selectedNodeId ? '#2980B9' : 'transparent')
			.attr('stroke-opacity', (d: SimNode) => d.id === selectedNodeId ? 0.8 : 0);
		nodeGs.select('.node-circle')
			.attr('stroke-width', (d: SimNode) => d.id === selectedNodeId ? 4 : 2.5);
	}

	function focusOnNode() {
		if (!focusNodeId) return;
		const refs = (containerEl as any)?.__d3refs;
		if (!refs) return;
		const { svgEl, zoom: zb, simNodes, width, height } = refs;
		const node = simNodes.find((n: SimNode) => n.id === focusNodeId);
		if (!node || node.x == null || node.y == null) return;
		const transform = d3.zoomIdentity
			.translate(width / 2, height / 2)
			.scale(2)
			.translate(-node.x, -node.y);
		svgEl.transition().duration(750).call(zb.transform, transform);
	}

	$effect(() => {
		theme;
		if (nodes && edges) buildGraph();
	});

	$effect(() => {
		highlightedNodeIds;
		highlightedEdgeIds;
		applyHighlighting();
	});

	$effect(() => {
		selectedNodeId;
		applySelection();
	});

	$effect(() => {
		focusNodeId;
		focusOnNode();
	});

	onMount(() => {
		const observer = new ResizeObserver(() => buildGraph());
		observer.observe(containerEl);
		return () => observer.disconnect();
	});

	onDestroy(() => {
		if (simulation) simulation.stop();
	});
</script>

<div bind:this={containerEl} class="w-full h-full min-h-[400px]"></div>
