## ADDED Requirements

### Requirement: Share page content SHALL be scrollable
The share page (`/share/[id]`) SHALL allow vertical scrolling of its full content when the report, charts, comments, or research trace exceed the viewport height.

#### Scenario: Long report scrolls on share page
- **WHEN** a shared report's content exceeds the viewport height
- **THEN** the user SHALL be able to scroll vertically through the entire page content including report body, charts, research trace, and footer

#### Scenario: Share page fills available layout space
- **WHEN** the share page renders inside the root layout
- **THEN** the share page root container SHALL use `h-full overflow-y-auto` instead of `min-h-screen` to properly fill and scroll within the root layout's `flex-1 overflow-hidden` main area

### Requirement: CommentThread sidebar SHALL use a single scroll context
The CommentThread sidebar on the share page SHALL NOT create double-nested scroll containers. The sidebar outer wrapper SHALL provide the viewport constraint and the CommentThread component SHALL flex to fill available space.

#### Scenario: Comments scroll without double nesting
- **WHEN** the comment sidebar is open on the share page with more comments than fit in the viewport
- **THEN** comments SHALL be scrollable in a single scroll container (not two nested scrollable divs)

#### Scenario: CommentThread adapts to parent height
- **WHEN** the CommentThread component is rendered inside the share page sidebar
- **THEN** the comment list area SHALL use `flex-1 overflow-y-auto min-h-0` to fill available space instead of a hardcoded `max-h-[60vh]`

#### Scenario: CommentThread sidebar uses flex layout
- **WHEN** the comment sidebar is rendered on the share page
- **THEN** the sidebar wrapper SHALL remove its own `overflow-y-auto` and instead use `flex flex-col` so CommentThread manages its own scroll

### Requirement: ReportPanel SHALL use responsive max-heights
The ReportPanel component SHALL use responsive Tailwind max-height breakpoints instead of a single hardcoded `max-h-[55vh]`.

#### Scenario: ReportPanel scales across viewports
- **WHEN** the ReportPanel renders on different screen sizes
- **THEN** the content area SHALL use responsive max-heights (`max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]`) with `overflow-y-auto`

### Requirement: ReportDiff SHALL use responsive max-heights
The ReportDiff component SHALL use responsive Tailwind max-height breakpoints instead of a single hardcoded `max-h-[60vh]` in both unified and side-by-side modes.

#### Scenario: Unified diff view scales across viewports
- **WHEN** the ReportDiff renders in unified mode on different screen sizes
- **THEN** the diff container SHALL use responsive max-heights (`max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]`) with `overflow-y-auto`

#### Scenario: Side-by-side diff view scales across viewports
- **WHEN** the ReportDiff renders in side-by-side mode on different screen sizes
- **THEN** the grid container SHALL use responsive max-heights (`max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]`) with `overflow-y-auto`
