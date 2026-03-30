## ADDED Requirements

### Requirement: Share page buttons use design system utilities
All buttons on the share page SHALL use the app's design system utility classes (`btn-gold`, `btn-secondary`) instead of hand-rolled Tailwind classes.

#### Scenario: Primary action buttons
- **WHEN** rendering action buttons that perform primary actions (e.g., submit comment)
- **THEN** the button uses the `btn-gold` utility class

#### Scenario: Secondary action buttons
- **WHEN** rendering action buttons that perform secondary actions (e.g., copy link, download PDF, download MD, download DOCX, fork)
- **THEN** the button uses the `btn-secondary` utility class

### Requirement: CommentThread uses design system utilities
All inputs, textareas, and buttons in the CommentThread component SHALL use the app's design system utility classes.

#### Scenario: Comment textareas
- **WHEN** rendering a comment compose or edit textarea
- **THEN** the textarea uses the `input-field` utility class

#### Scenario: Comment submit button
- **WHEN** rendering the comment submit button
- **THEN** the button uses the `btn-gold` utility class

#### Scenario: Comment secondary buttons
- **WHEN** rendering comment action buttons (edit save, cancel, etc.)
- **THEN** the buttons use the appropriate design system utility class

### Requirement: Report container uses card utility
The main report content container SHALL use the `card` utility class for consistent card styling.

#### Scenario: Report card styling
- **WHEN** rendering the report content container
- **THEN** the container uses the `card` utility class with consistent border-radius and border styling

### Requirement: Share page heading uses brand style
The share page h1 title SHALL use `text-gold` to match the app-wide heading convention.

#### Scenario: Report title in dark mode
- **WHEN** viewing the share page title in dark mode
- **THEN** the h1 renders in gold color (`text-gold`) matching other headings in the application

#### Scenario: Report title in light mode
- **WHEN** viewing the share page title in light mode
- **THEN** the h1 renders in the light mode gold variant, maintaining the heading convention
