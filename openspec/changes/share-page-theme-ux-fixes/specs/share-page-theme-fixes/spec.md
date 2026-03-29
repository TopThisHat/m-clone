## ADDED Requirements

### Requirement: Sticky header respects light mode
The sticky header bar on the share page SHALL render with a light background color when the theme is set to light mode. The `bg-navy-950/95` opacity variant MUST be overridden in the `.light` scope to use `rgba(241, 245, 249, 0.95)` (slate-50 at 95% opacity).

#### Scenario: Light mode sticky header
- **WHEN** the user toggles to light mode on the share page
- **THEN** the sticky header bar renders with a light translucent background instead of dark navy

#### Scenario: Backdrop blur preserved in light mode
- **WHEN** the user scrolls the share page in light mode
- **THEN** the sticky header maintains its backdrop-blur effect with the light background at 95% opacity

### Requirement: ReportDiff highlights adapt to light mode
The diff view SHALL display additions and deletions with theme-appropriate background colors. In light mode, `bg-red-900/30` and `bg-green-900/30` MUST be overridden to use lighter variants that are visible against the white background.

#### Scenario: Diff additions in light mode
- **WHEN** viewing a report diff in light mode
- **THEN** added text uses a light green background (e.g., `rgba(34, 197, 94, 0.15)`) that is visible against the white page background

#### Scenario: Diff deletions in light mode
- **WHEN** viewing a report diff in light mode
- **THEN** deleted text uses a light red background (e.g., `rgba(239, 68, 68, 0.15)`) that is visible against the white page background

### Requirement: ChartCard renders theme-aware colors
The ChartCard component SHALL read the current theme and compute chart.js configuration colors dynamically. Grid lines, tick labels, and axis colors MUST adapt to the active theme.

#### Scenario: Chart grid in dark mode
- **WHEN** viewing a chart in dark mode
- **THEN** grid lines use `#1a3660` (navy-600) and tick labels use `#64748b` (slate-500)

#### Scenario: Chart grid in light mode
- **WHEN** viewing a chart in light mode
- **THEN** grid lines use `#e2e8f0` (slate-200) and tick labels use `#475569` (slate-600)

#### Scenario: Theme toggle updates chart
- **WHEN** the user toggles the theme while a chart is visible
- **THEN** the chart updates its colors without requiring a page reload

### Requirement: No redundant light class on share page
The share page root div SHALL NOT apply its own `class:light` directive. It MUST rely on the root layout's `.light` class for theme cascading.

#### Scenario: Single light class in DOM
- **WHEN** the share page is rendered in light mode
- **THEN** only the root layout div has the `light` class; the share page root div does not duplicate it
