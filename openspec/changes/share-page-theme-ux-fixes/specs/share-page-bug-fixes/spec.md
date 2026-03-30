## ADDED Requirements

### Requirement: Copy link only confirms on success
The copy link function SHALL only display "Copied!" feedback when the clipboard write operation succeeds.

#### Scenario: Successful copy
- **WHEN** the user clicks "Copy link" and the clipboard API succeeds
- **THEN** the button text changes to "Copied!" temporarily

#### Scenario: Failed copy
- **WHEN** the user clicks "Copy link" and the clipboard API fails (e.g., non-secure context)
- **THEN** the button does NOT show "Copied!" and displays an error indication instead

### Requirement: Fork and subscribe show error feedback
The fork and subscribe actions SHALL display user-visible error feedback when the API call fails, instead of silently swallowing errors.

#### Scenario: Fork failure
- **WHEN** the user clicks the fork button and the API returns an error
- **THEN** the user sees an error message (toast or inline) explaining the failure

#### Scenario: Subscribe failure
- **WHEN** the user clicks subscribe/unsubscribe and the API returns an error
- **THEN** the user sees an error message and the subscribe state does not change

### Requirement: Comment deletion requires confirmation
Deleting a comment SHALL require user confirmation before executing.

#### Scenario: Delete with confirmation
- **WHEN** the user clicks the delete button on a comment
- **THEN** a confirmation prompt appears asking the user to confirm deletion
- **WHEN** the user confirms
- **THEN** the comment is deleted

#### Scenario: Delete cancelled
- **WHEN** the user clicks the delete button and then cancels the confirmation
- **THEN** the comment is NOT deleted

### Requirement: Polling pauses when tab is backgrounded
Comment polling and presence heartbeat intervals SHALL pause when the browser tab is not visible and resume when the tab becomes visible again.

#### Scenario: Tab hidden stops polling
- **WHEN** the user switches to another browser tab
- **THEN** comment polling and presence heartbeat requests stop

#### Scenario: Tab visible resumes polling
- **WHEN** the user returns to the share page tab
- **THEN** comment polling and presence heartbeat resume, with an immediate fetch on return

### Requirement: No duplicate footer
The share page SHALL NOT render its own footer if the root layout already provides one with the same content.

#### Scenario: Single footer visible
- **WHEN** the share page is rendered
- **THEN** only one instance of the disclaimer/footer text is visible to the user
