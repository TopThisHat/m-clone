## ADDED Requirements

### Requirement: WebGL2 graph rendering via Sigma.js v3
The system SHALL render the knowledge graph using Sigma.js v3 with WebGL2, replacing the current D3.js SVG renderer. All nodes and edges SHALL be rendered as WebGL sprites with zero DOM mutations per frame.

#### Scenario: Graph renders at 60fps with 2000 nodes
- **WHEN** the graph contains 2000 nodes and 5000 edges
- **THEN** the renderer SHALL maintain 60fps during pan, zoom, and idle states

#### Scenario: Graph renders at 60fps during layout animation
- **WHEN** ForceAtlas2 layout is actively computing positions
- **THEN** the graph SHALL animate smoothly at 60fps because layout runs in a Web Worker

### Requirement: ForceAtlas2 layout in Web Worker
The system SHALL run the ForceAtlas2 force-directed layout algorithm in a Web Worker thread, never blocking the main thread during layout computation.

#### Scenario: Layout computation does not block UI
- **WHEN** a graph with 1000+ nodes is loaded and layout begins
- **THEN** the main thread SHALL remain responsive (no jank, click/hover events fire immediately)

#### Scenario: Layout converges and stops
- **WHEN** the ForceAtlas2 simulation reaches convergence
- **THEN** the layout worker SHALL stop automatically and the graph SHALL remain static until user interaction

### Requirement: Graphology data layer
The system SHALL use graphology as the graph data structure, supporting incremental node/edge additions and removals without full graph rebuilds.

#### Scenario: Incremental node addition via mergeNodes
- **WHEN** new nodes are added via the `mergeNodes()` API (e.g., double-click expansion)
- **THEN** only the new nodes and edges SHALL be added to the graphology instance; existing node positions SHALL be preserved

#### Scenario: Node/edge removal
- **WHEN** filters are applied that exclude certain entity types
- **THEN** the corresponding nodes and edges SHALL be removed from the graphology instance and disappear from the rendered graph without a full rebuild

### Requirement: Node interaction events
The system SHALL support click, double-click, right-click, hover enter, and hover leave events on nodes, equivalent to the current D3 implementation.

#### Scenario: Node click selects entity
- **WHEN** user clicks a node
- **THEN** the `onNodeClick` callback SHALL fire with the node's entity ID

#### Scenario: Node double-click expands neighbors
- **WHEN** user double-clicks a node
- **THEN** the `onNodeDblClick` callback SHALL fire, triggering neighbor expansion via the existing API

#### Scenario: Node right-click opens context menu
- **WHEN** user right-clicks a node
- **THEN** the `onNodeContextMenu` callback SHALL fire with the node ID and mouse coordinates for HTML overlay positioning

#### Scenario: Node hover highlights connections
- **WHEN** user hovers over a node
- **THEN** the node and its connected edges SHALL be visually highlighted, and non-connected elements SHALL be dimmed

### Requirement: Edge interaction events
The system SHALL support click and hover events on edges for tooltips and selection.

#### Scenario: Edge hover shows tooltip
- **WHEN** user hovers over an edge
- **THEN** the edge predicate, confidence, and connected entity names SHALL be displayed in an HTML tooltip overlay

#### Scenario: Edge click selects relationship
- **WHEN** user clicks an edge
- **THEN** the `onEdgeClick` callback SHALL fire with the relationship ID

### Requirement: Camera controls
The system SHALL support programmatic camera operations: fit-to-view, focus-on-node, zoom-in, zoom-out, and reset.

#### Scenario: Fit to view shows all nodes
- **WHEN** `fitToView()` is called
- **THEN** the camera SHALL animate to show all nodes within the viewport with appropriate padding

#### Scenario: Focus on node centers and zooms
- **WHEN** `focusOnNode(entityId)` is called
- **THEN** the camera SHALL animate to center on the specified node at a zoom level where the node and its immediate neighbors are visible

### Requirement: Label level-of-detail rendering
The system SHALL implement automatic label culling based on zoom level to maintain performance at low zoom levels.

#### Scenario: Labels hidden at low zoom
- **WHEN** the camera zoom ratio is below 0.3
- **THEN** node labels SHALL NOT be rendered; only node circles SHALL be visible

#### Scenario: High-degree labels prioritized at medium zoom
- **WHEN** the camera zoom ratio is between 0.3 and 0.7
- **THEN** only the top 50 nodes by degree SHALL display labels; edge labels SHALL be hidden

#### Scenario: Full labels at high zoom
- **WHEN** the camera zoom ratio is above 0.7
- **THEN** all visible node labels and edge predicate labels SHALL be rendered

### Requirement: Node budget removal
The system SHALL remove the current 500-node hard cap and 150-node initial load limit. The system SHALL support rendering up to 5000 nodes with WebGL.

#### Scenario: Large graph loads without blocking
- **WHEN** a team's KG contains 3000 entities
- **THEN** the graph SHALL load and render all entities without a blocking warning or artificial cap

### Requirement: True minimap with viewport indicator
The system SHALL optionally display a minimap that reflects actual node positions using a secondary Sigma renderer sharing the same graphology instance.

#### Scenario: Minimap shows actual graph layout
- **WHEN** the minimap is visible and the graph has been laid out
- **THEN** the minimap SHALL display node positions matching the main graph layout (not a grid approximation)

#### Scenario: Minimap shows viewport rectangle
- **WHEN** the user pans or zooms the main graph
- **THEN** the minimap SHALL display a rectangle indicating the currently visible viewport area

#### Scenario: Minimap is optional
- **WHEN** the node count is below 50
- **THEN** the minimap SHALL NOT be displayed by default (toggleable via icon button)

### Requirement: Node visual styling
The system SHALL render nodes with entity-type-specific colors, supporting both light and dark themes, matching the current color scheme.

#### Scenario: Entity type colors applied
- **WHEN** nodes are rendered
- **THEN** each node SHALL be colored according to its entity type (person=blue, company=teal, sports_team=amber, location=green, pe_fund=purple, other=gray)

#### Scenario: Theme switching updates colors
- **WHEN** the user switches between light and dark theme
- **THEN** node and edge colors SHALL update to the corresponding theme variant without a full graph rebuild

### Requirement: Drag interaction
The system SHALL support dragging individual nodes to reposition them, with the layout respecting the new fixed position.

#### Scenario: Node drag repositions
- **WHEN** user drags a node to a new position
- **THEN** the node SHALL move to the dragged position and remain fixed there; the layout algorithm SHALL treat it as a fixed node
