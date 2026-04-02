## ADDED Requirements

### Requirement: 3-step upload wizard modal
The system SHALL replace the current slide-out upload panel with a 3-step modal wizard: (1) Choose file type with explanation, (2) File selection/drop, (3) Processing status with results.

#### Scenario: Upload button opens wizard modal
- **WHEN** user clicks the Upload icon button in the top bar
- **THEN** a centered modal SHALL open showing Step 1: file type selection

#### Scenario: Modal closes on cancel or backdrop click
- **WHEN** user clicks Cancel or clicks the backdrop
- **THEN** the wizard SHALL close and no upload SHALL occur

### Requirement: Step 1 explains AI processing before upload
Step 1 SHALL display file type cards (Document, Dataset, Image) with clear descriptions of what the AI will do with each type, so users understand the outcome before committing.

#### Scenario: Document card explains entity extraction
- **WHEN** Step 1 is displayed
- **THEN** the Document card SHALL show: accepted formats (PDF, DOCX), and description "AI reads your file, identifies people, companies, locations, and relationships, then adds them to your team's graph"

#### Scenario: Dataset card explains column mapping
- **WHEN** Step 1 is displayed
- **THEN** the Dataset card SHALL show: accepted formats (CSV, Excel), and description "Maps columns to entities and relationships"

#### Scenario: Image card explains OCR
- **WHEN** Step 1 is displayed
- **THEN** the Image card SHALL show: accepted formats (PNG, JPEG, GIF, WebP), and description "OCR extracts text, then identifies entities"

#### Scenario: Selecting a card advances to Step 2
- **WHEN** user clicks a file type card
- **THEN** the wizard SHALL advance to Step 2 with the drop zone filtered to the selected file types

### Requirement: Step 2 file selection with drag-and-drop
Step 2 SHALL provide a drag-and-drop zone and file browser button for selecting the file to upload.

#### Scenario: File drop zone accepts valid files
- **WHEN** user drops a file matching the selected type (e.g., PDF for Document)
- **THEN** the file SHALL be accepted and displayed with filename and size

#### Scenario: Invalid file type rejected
- **WHEN** user drops a file that doesn't match the selected type
- **THEN** the drop zone SHALL display an error message indicating the accepted formats

#### Scenario: Next button advances to Step 3 and starts upload
- **WHEN** a valid file is selected and user clicks "Extract & Add to KG"
- **THEN** the file SHALL be uploaded to `POST /api/documents/upload?mode=kg` and the wizard SHALL advance to Step 3

### Requirement: Step 3 shows live processing status
Step 3 SHALL display real-time processing status as the backend extracts entities from the uploaded document.

#### Scenario: Upload progress shown
- **WHEN** the file is being uploaded
- **THEN** Step 3 SHALL show: checkmark "File received (X MB)"

#### Scenario: Processing status updates
- **WHEN** the backend is processing the document
- **THEN** Step 3 SHALL show: spinner "Extracting text...", then "Identifying entities..."

#### Scenario: Completion shows entity count
- **WHEN** processing completes
- **THEN** Step 3 SHALL show: "Done: X entities, Y relationships added" with a "View in graph" button

#### Scenario: View in graph refreshes and focuses new entities
- **WHEN** user clicks "View in graph"
- **THEN** the wizard SHALL close, the graph SHALL refresh with updated data, and the camera SHALL focus on the newly added entities

### Requirement: Upload wizard replaces slide-out panel
The current slide-out right panel for upload SHALL be removed entirely. The upload button in the header SHALL trigger the wizard modal instead.

#### Scenario: No slide-out panel exists
- **WHEN** user navigates to the KG explore page
- **THEN** there SHALL be no slide-out upload panel; only the modal wizard is available via the upload button
