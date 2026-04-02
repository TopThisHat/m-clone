## ADDED Requirements

### Requirement: Command palette overlay triggered by Cmd+K
The system SHALL display a command palette overlay when the user presses Cmd+K (or Ctrl+K on non-Mac) or clicks the search pill in the top bar. The palette SHALL support fuzzy entity search with grouped results.

#### Scenario: Cmd+K opens palette
- **WHEN** user presses Cmd+K while on the KG explore page
- **THEN** a centered modal overlay SHALL appear with a focused search input and placeholder "Search Knowledge Graph..."

#### Scenario: Alternative trigger with slash key
- **WHEN** user presses "/" while no input is focused on the KG explore page
- **THEN** the command palette SHALL open (same as Cmd+K)

#### Scenario: Escape closes palette
- **WHEN** the command palette is open and user presses Escape
- **THEN** the palette SHALL close immediately

### Requirement: Fuzzy trigram search via /api/kg/suggest endpoint
The system SHALL provide a `GET /api/kg/suggest` endpoint that returns entity suggestions using PostgreSQL trigram similarity matching, responding in under 50ms.

#### Scenario: Type-ahead returns fuzzy matches
- **WHEN** user types "Tger" in the palette
- **THEN** the endpoint SHALL return entities like "Tiger Capital", "Tiger Global", "Tiger Woods" ranked by trigram similarity score

#### Scenario: Response time under 50ms
- **WHEN** the suggest endpoint is called with a 3+ character query
- **THEN** the response SHALL return within 50ms for teams with up to 5000 entities

#### Scenario: Results include metadata
- **WHEN** the suggest endpoint returns results
- **THEN** each result SHALL include: entity name, entity_type, entity ID, and relationship count

### Requirement: Grouped search results display
The command palette SHALL display results grouped into sections: Entities, Relationships, and Filters.

#### Scenario: Entity results show type and relationship count
- **WHEN** search results include entities
- **THEN** each entity result SHALL display: entity name, entity type badge, and relationship count (e.g., "Tiger Capital [Company] 12 rels")

#### Scenario: Filter suggestions appear
- **WHEN** user types a term matching an entity type or predicate family
- **THEN** the palette SHALL show filter suggestions (e.g., "Show only Companies", "Show only Transaction relationships")

### Requirement: Debounced search with 150ms delay
The system SHALL debounce search input by 150ms to avoid excessive API calls during typing.

#### Scenario: Rapid typing does not trigger per-keystroke requests
- **WHEN** user types "Tiger" rapidly (5 keystrokes in 200ms)
- **THEN** only one API call SHALL be made (after 150ms of no typing)

### Requirement: Result selection focuses graph
The system SHALL focus the graph on the selected entity when the user selects a result from the command palette.

#### Scenario: Selecting an entity focuses and opens detail
- **WHEN** user selects an entity from the palette results (click or Enter)
- **THEN** the graph camera SHALL animate to center on that entity, the entity SHALL be highlighted, and the entity detail panel SHALL open

#### Scenario: Selecting a filter applies it
- **WHEN** user selects a filter suggestion from the palette
- **THEN** the corresponding type or family filter SHALL be applied to the graph and the palette SHALL close

### Requirement: Keyboard navigation in results
The system SHALL support arrow key navigation through search results and Enter to select.

#### Scenario: Arrow keys navigate results
- **WHEN** the palette shows results and user presses Down arrow
- **THEN** the next result SHALL be highlighted; Up arrow SHALL highlight the previous result

#### Scenario: Enter selects highlighted result
- **WHEN** a result is highlighted via keyboard and user presses Enter
- **THEN** the highlighted result SHALL be selected (same behavior as clicking it)
