## ADDED Requirements

### Requirement: Minimal top bar with 4 items
The top bar SHALL contain only: Back link, Team Badge, Search pill (Cmd+K trigger), and action icon buttons (Chat, Upload). All filter controls SHALL be removed from the top bar.

#### Scenario: Top bar renders 4 items
- **WHEN** the KG explore page loads
- **THEN** the top bar SHALL contain exactly: Back link, Team Badge, Search pill, and 2 icon buttons (Chat, Upload)

#### Scenario: No filter chips in header
- **WHEN** the KG explore page loads
- **THEN** entity type chips, predicate family chips, Deal Partners button, and Advanced Filters button SHALL NOT appear in the top bar

### Requirement: Collapsible bottom filter strip
All filter controls SHALL move to a bottom strip that is collapsed by default, showing only a node/edge count summary, and expands upward to reveal full filter controls.

#### Scenario: Collapsed state shows count
- **WHEN** the filter strip is collapsed (default)
- **THEN** it SHALL display: node count, edge count, and a toggle button to expand (e.g., "47 nodes · 83 edges [Filters v]")

#### Scenario: Expanded state shows all filters
- **WHEN** user clicks the filter toggle
- **THEN** the strip SHALL expand upward to show: entity type filter chips, predicate family filter chips, Deal Partners toggle, Metadata filter, and Clear All button

#### Scenario: Color-coded node count
- **WHEN** the graph has nodes loaded
- **THEN** the node count pill SHALL be: green (0-100 nodes), amber (101-300 nodes), red (301+ nodes)

### Requirement: Left-edge zoom rail
Zoom controls (Zoom In, Zoom Out, Fit to View, Reset Layout) SHALL be displayed as a vertical icon button rail on the left edge of the graph area.

#### Scenario: Zoom rail displays 4 buttons
- **WHEN** the KG explore page loads
- **THEN** the left edge SHALL show vertically stacked icon buttons: +, -, Fit, Reset

#### Scenario: Zoom in button zooms graph
- **WHEN** user clicks the + button
- **THEN** the graph camera SHALL zoom in by one step

#### Scenario: Fit button shows all nodes
- **WHEN** user clicks the Fit button
- **THEN** the graph camera SHALL animate to show all nodes in the viewport

### Requirement: Full-viewport graph canvas
The graph canvas SHALL occupy the full remaining viewport height between the top bar and bottom filter strip, with no competing side panels that push the graph.

#### Scenario: Graph fills available space
- **WHEN** the KG explore page loads with no panels open
- **THEN** the graph canvas SHALL fill 100% of the width and height between top bar and bottom strip

#### Scenario: Panels overlay without resizing graph
- **WHEN** the chat panel or entity detail panel opens
- **THEN** the graph canvas SHALL NOT resize; panels SHALL overlay on top of the graph

### Requirement: Entity detail panel as right overlay
The entity detail panel SHALL open as an overlay on the right edge of the graph when a node is selected, without pushing or resizing the graph canvas.

#### Scenario: Node click opens detail overlay
- **WHEN** user clicks a node on the graph
- **THEN** the entity detail panel SHALL slide in from the right edge as an overlay

#### Scenario: Detail panel coexists with chat
- **WHEN** the chat panel is open on the left and user clicks a node
- **THEN** the entity detail panel SHALL open on the right WITHOUT closing the chat panel

#### Scenario: Clicking graph background closes detail panel
- **WHEN** user clicks on the graph background (not a node)
- **THEN** the entity detail panel SHALL close

### Requirement: Keyboard shortcuts
The system SHALL support keyboard shortcuts for common actions on the KG explore page.

#### Scenario: Escape closes active panel
- **WHEN** user presses Escape
- **THEN** the topmost open panel (detail, chat, or palette) SHALL close

#### Scenario: Question mark shows shortcut cheat sheet
- **WHEN** user presses "?" while no input is focused
- **THEN** a modal SHALL display all available keyboard shortcuts

#### Scenario: Cmd+K opens search
- **WHEN** user presses Cmd+K
- **THEN** the command palette SHALL open

### Requirement: Remove broken minimap
The current grid-based SVG minimap (150x100, bottom-right) SHALL be removed from the explore page.

#### Scenario: No grid minimap rendered
- **WHEN** the KG explore page loads
- **THEN** no 150x100 SVG minimap with grid-positioned dots SHALL be rendered

### Requirement: Slide-out panels removed
The current slide-out right panels for Query and Upload SHALL be removed entirely. Query is replaced by the chat panel (left sidebar). Upload is replaced by the wizard modal.

#### Scenario: No slide-out query panel
- **WHEN** user navigates to the KG explore page
- **THEN** there SHALL be no slide-out query panel; the chat panel replaces it

#### Scenario: No slide-out upload panel
- **WHEN** user navigates to the KG explore page
- **THEN** there SHALL be no slide-out upload panel; the wizard modal replaces it
