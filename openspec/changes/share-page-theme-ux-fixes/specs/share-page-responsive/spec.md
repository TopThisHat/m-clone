## ADDED Requirements

### Requirement: Comments sidebar is usable on mobile
The comments sidebar SHALL render as a slide-over drawer on screens below the `md` breakpoint instead of an inline column.

#### Scenario: Mobile comments drawer
- **WHEN** the user taps the comments toggle on a mobile device
- **THEN** a slide-over drawer appears from the right containing the comments thread

#### Scenario: Close drawer on outside click
- **WHEN** the comments drawer is open and the user clicks/taps outside of it
- **THEN** the drawer closes

#### Scenario: Close drawer on Escape
- **WHEN** the comments drawer is open and the user presses Escape
- **THEN** the drawer closes

#### Scenario: Desktop retains inline layout
- **WHEN** the screen width is at or above the `md` breakpoint
- **THEN** the comments sidebar renders inline as `w-80` alongside the report (existing behavior)

### Requirement: Diff view auto-selects unified mode on mobile
The diff comparison view SHALL default to unified mode on mobile screens and hide the side-by-side option.

#### Scenario: Mobile diff defaults to unified
- **WHEN** the user opens a diff comparison on a screen below the `md` breakpoint
- **THEN** the diff renders in unified mode by default

#### Scenario: Side-by-side option hidden on mobile
- **WHEN** viewing the diff mode toggle on a screen below the `md` breakpoint
- **THEN** the "Side by side" option is hidden

#### Scenario: Desktop retains both options
- **WHEN** viewing the diff mode toggle on a screen at or above the `md` breakpoint
- **THEN** both "Unified" and "Side by side" options are available

### Requirement: Top bar handles overflow on small screens
The top bar action buttons SHALL gracefully handle overflow on small screens without breaking layout.

#### Scenario: Small screen button overflow
- **WHEN** the share page top bar renders on a screen narrower than 640px
- **THEN** buttons remain accessible without horizontal overflow causing layout breakage (via priority hiding, wrapping, or overflow scroll)
