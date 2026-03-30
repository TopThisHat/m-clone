## ADDED Requirements

### Requirement: Icon-only buttons have accessible names
All icon-only or emoji-only buttons on the share page SHALL have `aria-label` attributes that describe their purpose.

#### Scenario: Subscribe bell button
- **WHEN** a screen reader encounters the subscribe button
- **THEN** it announces "Subscribe to notifications" or "Unsubscribe from notifications" based on state

#### Scenario: Copy link button
- **WHEN** a screen reader encounters the copy link button
- **THEN** it announces "Copy share link"

#### Scenario: Comments toggle button
- **WHEN** a screen reader encounters the comments toggle button
- **THEN** it announces "Show comments" or "Hide comments" based on state, along with the comment count

### Requirement: Skip-to-content link exists
The root layout SHALL include a visually-hidden skip-to-content link as the first focusable element that jumps to the main content area.

#### Scenario: Keyboard user skips navigation
- **WHEN** a keyboard user presses Tab on page load
- **THEN** the first focused element is a "Skip to content" link
- **WHEN** the user activates the skip link
- **THEN** focus moves to the main content area, bypassing all navigation elements

### Requirement: Metadata text meets contrast requirements
All metadata text on the share page SHALL meet WCAG 2.1 AA contrast ratio of at least 4.5:1 for normal text.

#### Scenario: Date and reading time contrast
- **WHEN** viewing the report metadata (date, reading time) in dark mode
- **THEN** the text color provides at least 4.5:1 contrast ratio against the background (use `text-slate-500` minimum instead of `text-slate-600`/`text-slate-700`)

#### Scenario: Footer disclaimer contrast
- **WHEN** viewing the footer disclaimer text
- **THEN** the text color provides at least 4.5:1 contrast ratio against the background

### Requirement: Presence tooltips are keyboard accessible
The presence avatar tooltips SHALL be accessible to keyboard users, not only mouse hover.

#### Scenario: Keyboard focus shows tooltip
- **WHEN** a keyboard user focuses on a presence avatar
- **THEN** the tooltip showing the viewer's name becomes visible

#### Scenario: Mouse hover shows tooltip
- **WHEN** a mouse user hovers over a presence avatar
- **THEN** the tooltip showing the viewer's name becomes visible (existing behavior preserved)

### Requirement: Reaction picker has keyboard support
The emoji reaction picker SHALL support keyboard navigation and dismissal.

#### Scenario: Escape closes picker
- **WHEN** the reaction picker is open and the user presses Escape
- **THEN** the picker closes and focus returns to the trigger button

#### Scenario: Tab cycles within picker
- **WHEN** the reaction picker is open and the user presses Tab
- **THEN** focus cycles through the emoji options within the picker (focus trap)
