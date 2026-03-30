/**
 * E2E tests for the four entity/attribute pages:
 *   1. Entity Library          (/entities)
 *   2. Attribute Library       (/attributes)
 *   3. Campaign Entities       (/campaigns/test-campaign-id/entities)
 *   4. Campaign Attributes     (/campaigns/test-campaign-id/attributes)
 *
 * All tests mock every API call via page.route() so the backend does not
 * need to be running.  Auth is simulated by returning a valid user from
 * GET /api/auth/me and a JWT cookie is NOT required because the scout
 * layout.server.ts checks the cookie, but in test mode the dev server
 * handles SSR differently — we simulate it by intercepting the fetch.
 *
 * Cookie note: The scout layout redirects to /login when jwt cookie is
 * absent.  We set a fake cookie before each navigation so the server-side
 * load function proceeds past the redirect guard.
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';

// ── Shared constants ───────────────────────────────────────────────────────────

const CAMPAIGN_ID = 'test-campaign-id';

// ── Mock data ──────────────────────────────────────────────────────────────────

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

const mockTeams = [{ id: 'team-1', name: 'Test Team', slug: 'test-team' }];

const mockEntities = Array.from({ length: 5 }, (_, i) => ({
	id: `entity-${i + 1}`,
	campaign_id: CAMPAIGN_ID,
	label: `Entity ${i + 1}`,
	description: `Description for entity ${i + 1}`,
	gwm_id: i % 2 === 0 ? `GWM-${1000 + i}` : null,
	metadata: {},
	created_at: new Date(2025, 0, i + 1).toISOString(),
}));

const mockAttributes = Array.from({ length: 5 }, (_, i) => ({
	id: `attr-${i + 1}`,
	campaign_id: CAMPAIGN_ID,
	label: `Attribute ${i + 1}`,
	description: `Description for attribute ${i + 1}`,
	weight: (i + 1) * 2,
	created_at: new Date(2025, 0, i + 1).toISOString(),
}));

const mockLibraryEntities = Array.from({ length: 5 }, (_, i) => ({
	id: `lib-entity-${i + 1}`,
	owner_sid: 'user-abc',
	team_id: 'team-1',
	label: `Library Entity ${i + 1}`,
	description: `Description ${i + 1}`,
	gwm_id: i % 2 === 0 ? `GWM-${2000 + i}` : null,
	metadata: {},
	created_at: new Date(2025, 0, i + 1).toISOString(),
}));

const mockLibraryAttributes = Array.from({ length: 5 }, (_, i) => ({
	id: `lib-attr-${i + 1}`,
	owner_sid: 'user-abc',
	team_id: 'team-1',
	label: `Library Attr ${i + 1}`,
	description: `Description ${i + 1}`,
	weight: (i + 1) * 2,
	created_at: new Date(2025, 0, i + 1).toISOString(),
}));

const mockCampaign = {
	id: CAMPAIGN_ID,
	name: 'Test Campaign',
	description: 'A test campaign',
	created_at: '2025-01-01T00:00:00Z',
};

// ── Helper: set fake JWT cookie so server-side layout guard passes ──────────────

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{
			name: 'jwt',
			value: 'fake-jwt-token',
			domain: 'localhost',
			path: '/',
		},
	]);
}

// ── Helper: register auth API mocks shared across all scout pages ──────────────

async function mockAuthRoutes(page: Page) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUser),
		}),
	);

	await page.route('/api/teams', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockTeams),
		}),
	);
}

// ── Helper: register library entity API mocks ──────────────────────────────────

async function mockLibraryEntityRoutes(page: Page) {
	await page.route('/api/library/entities**', (route) => {
		const method = route.request().method();
		if (method === 'DELETE') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ deleted: 1 }),
			});
		}
		if (method === 'POST') {
			return route.fulfill({
				status: 201,
				contentType: 'application/json',
				body: JSON.stringify(mockLibraryEntities[0]),
			});
		}
		// GET — paginated list
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				items: mockLibraryEntities,
				total: mockLibraryEntities.length,
				limit: 50,
				offset: 0,
			}),
		});
	});
}

// ── Helper: register library attribute API mocks ───────────────────────────────

async function mockLibraryAttributeRoutes(page: Page) {
	await page.route('/api/library/attributes**', (route) => {
		const method = route.request().method();
		if (method === 'DELETE') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ deleted: 1 }),
			});
		}
		if (method === 'POST') {
			return route.fulfill({
				status: 201,
				contentType: 'application/json',
				body: JSON.stringify(mockLibraryAttributes[0]),
			});
		}
		// GET — paginated list
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				items: mockLibraryAttributes,
				total: mockLibraryAttributes.length,
				limit: 50,
				offset: 0,
			}),
		});
	});
}

// ── Helper: register campaign entity API mocks ─────────────────────────────────

async function mockCampaignEntityRoutes(page: Page) {
	await page.route(`/api/campaigns/${CAMPAIGN_ID}/entities**`, (route) => {
		const method = route.request().method();
		if (method === 'DELETE') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ deleted: 1 }),
			});
		}
		if (method === 'POST') {
			const url = route.request().url();
			if (url.includes('/import-library')) {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ inserted: [mockEntities[0]], skipped: 0 }),
				});
			}
			if (url.includes('/import')) {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ inserted: [mockEntities[0]], skipped: 0 }),
				});
			}
			return route.fulfill({
				status: 201,
				contentType: 'application/json',
				body: JSON.stringify(mockEntities[0]),
			});
		}
		if (method === 'PATCH') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockEntities[0]),
			});
		}
		// GET — paginated list
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				items: mockEntities,
				total: mockEntities.length,
				limit: 50,
				offset: 0,
			}),
		});
	});

	// Also mock the campaigns list (used by import-from-campaign dropdown)
	await page.route('/api/campaigns**', (route) => {
		const url = route.request().url();
		if (url.includes(`/${CAMPAIGN_ID}`)) {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockCampaign),
			});
		}
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify([mockCampaign]),
		});
	});

	// Mock library entities for the "Import from Library" panel
	await mockLibraryEntityRoutes(page);
}

// ── Helper: register campaign attribute API mocks ──────────────────────────────

async function mockCampaignAttributeRoutes(page: Page) {
	await page.route(`/api/campaigns/${CAMPAIGN_ID}/attributes**`, (route) => {
		const method = route.request().method();
		if (method === 'DELETE') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ deleted: 1 }),
			});
		}
		if (method === 'POST') {
			const url = route.request().url();
			if (url.includes('/import-library')) {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ inserted: [mockAttributes[0]], skipped: 0 }),
				});
			}
			if (url.includes('/import')) {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ inserted: [mockAttributes[0]], skipped: 0 }),
				});
			}
			return route.fulfill({
				status: 201,
				contentType: 'application/json',
				body: JSON.stringify(mockAttributes[0]),
			});
		}
		if (method === 'PATCH') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockAttributes[0]),
			});
		}
		// GET — paginated list
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				items: mockAttributes,
				total: mockAttributes.length,
				limit: 50,
				offset: 0,
			}),
		});
	});

	// Also mock the campaigns list (used by import-from-campaign dropdown)
	await page.route('/api/campaigns**', (route) => {
		const url = route.request().url();
		if (url.includes(`/${CAMPAIGN_ID}`)) {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockCampaign),
			});
		}
		return route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify([mockCampaign]),
		});
	});

	// Mock library attributes for the "Import from Library" panel
	await mockLibraryAttributeRoutes(page);
}

// ══════════════════════════════════════════════════════════════════════════════
// 1. Entity Library Page (/entities)
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Entity Library Page (/entities)', () => {
	test.beforeEach(async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryEntityRoutes(page);
	});

	test('page loads and shows entity library heading', async ({ page }) => {
		await page.goto('/entities');
		await expect(page.locator('h1')).toContainText('Entity Library');
	});

	test('entity table is visible with row data', async ({ page }) => {
		await page.goto('/entities');
		const table = page.locator('table[aria-label="Entity library"]');
		await expect(table).toBeVisible();
		await expect(page.locator('td', { hasText: 'Library Entity 1' }).first()).toBeVisible();
	});

	test('search input is present with correct aria-label', async ({ page }) => {
		await page.goto('/entities');
		const search = page.locator('input[aria-label="Search entities"]');
		await expect(search).toBeVisible();
	});

	test('select-all checkbox selects all items', async ({ page }) => {
		await page.goto('/entities');
		const selectAll = page.locator('input[aria-label="Select all entities on this page"]');
		await expect(selectAll).toBeVisible();
		await selectAll.check();
		// After checking, at least one row checkbox should be checked
		const rowCheckboxes = page.locator('input[aria-label^="Select Library Entity"]');
		const count = await rowCheckboxes.count();
		for (let i = 0; i < count; i++) {
			await expect(rowCheckboxes.nth(i)).toBeChecked();
		}
	});

	test('select-all checkbox deselects all items when all are selected', async ({ page }) => {
		await page.goto('/entities');
		const selectAll = page.locator('input[aria-label="Select all entities on this page"]');
		// Check all then uncheck all
		await selectAll.check();
		await selectAll.uncheck();
		const rowCheckboxes = page.locator('input[aria-label^="Select Library Entity"]');
		const count = await rowCheckboxes.count();
		for (let i = 0; i < count; i++) {
			await expect(rowCheckboxes.nth(i)).not.toBeChecked();
		}
	});

	test('individual row checkbox can be selected', async ({ page }) => {
		await page.goto('/entities');
		const firstCheckbox = page.locator('input[aria-label="Select Library Entity 1"]');
		await expect(firstCheckbox).toBeVisible();
		await firstCheckbox.check();
		await expect(firstCheckbox).toBeChecked();
	});

	test('bulk delete button appears when items are selected', async ({ page }) => {
		await page.goto('/entities');
		// No items selected — Delete button should not exist
		await expect(page.locator('button', { hasText: 'Delete' }).first()).not.toBeVisible();

		const firstCheckbox = page.locator('input[aria-label="Select Library Entity 1"]');
		await firstCheckbox.check();
		// Now the delete button should appear
		await expect(page.locator('button', { hasText: 'Delete' }).first()).toBeVisible();
	});

	test('selected count shown in stats line with gold color', async ({ page }) => {
		await page.goto('/entities');
		const firstCheckbox = page.locator('input[aria-label="Select Library Entity 1"]');
		await firstCheckbox.check();
		// Stats line should show "1 selected" styled with text-gold
		const selectedSpan = page.locator('span.text-gold.font-semibold');
		await expect(selectedSpan.first()).toBeVisible();
		await expect(selectedSpan.first()).toContainText('1');
	});

	test('+ Add button toggles the add entity form panel', async ({ page }) => {
		await page.goto('/entities');
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add' });
		await expect(addBtn).toHaveAttribute('aria-expanded', 'false');

		await addBtn.click();
		await expect(addBtn).toHaveAttribute('aria-expanded', 'true');

		// Add form should be visible
		const form = page.locator('h3', { hasText: 'Add Entity to Library' });
		await expect(form).toBeVisible();
	});

	test('Upload button toggles the CSV upload panel', async ({ page }) => {
		await page.goto('/entities');
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload' });
		await expect(uploadBtn).toHaveAttribute('aria-expanded', 'false');

		await uploadBtn.click();
		await expect(uploadBtn).toHaveAttribute('aria-expanded', 'true');

		const panel = page.locator('h3', { hasText: 'Upload CSV / Excel to Library' });
		await expect(panel).toBeVisible();
	});

	test('opening add panel closes upload panel (mutual exclusion)', async ({ page }) => {
		await page.goto('/entities');
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload' });
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add' });

		// Open upload panel
		await uploadBtn.click();
		await expect(page.locator('h3', { hasText: 'Upload CSV / Excel to Library' })).toBeVisible();

		// Open add panel — upload should close
		await addBtn.click();
		await expect(page.locator('h3', { hasText: 'Add Entity to Library' })).toBeVisible();
		await expect(page.locator('h3', { hasText: 'Upload CSV / Excel to Library' })).not.toBeVisible();
	});

	test('opening upload panel closes add panel (mutual exclusion)', async ({ page }) => {
		await page.goto('/entities');
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload' });
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add' });

		// Open add panel first
		await addBtn.click();
		await expect(page.locator('h3', { hasText: 'Add Entity to Library' })).toBeVisible();

		// Open upload panel — add should close
		await uploadBtn.click();
		await expect(page.locator('h3', { hasText: 'Upload CSV / Excel to Library' })).toBeVisible();
		await expect(page.locator('h3', { hasText: 'Add Entity to Library' })).not.toBeVisible();
	});

	test('sort pill buttons are visible (Label, GWM ID, Date)', async ({ page }) => {
		await page.goto('/entities');
		await expect(page.locator('button', { hasText: 'Label' }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: 'GWM ID' }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: 'Date' }).first()).toBeVisible();
	});

	test('clicking a sort pill changes its active state', async ({ page }) => {
		await page.goto('/entities');
		const labelBtn = page.locator('button', { hasText: /^Label/ }).first();
		await labelBtn.click();
		// Active sort pill gets bg-gold/10 class and text-gold
		await expect(labelBtn).toHaveClass(/text-gold/);
	});

	test('GWM ID filter chips are visible (All, Has GWM ID, Missing GWM ID)', async ({ page }) => {
		await page.goto('/entities');
		await expect(page.locator('button', { hasText: 'All' }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: 'Has GWM ID' })).toBeVisible();
		await expect(page.locator('button', { hasText: 'Missing GWM ID' })).toBeVisible();
	});

	test('GWM ID filter "Has GWM ID" chip becomes active on click', async ({ page }) => {
		await page.goto('/entities');
		const hasChip = page.locator('button', { hasText: 'Has GWM ID' });
		await hasChip.click();
		await expect(hasChip).toHaveClass(/text-gold/);
	});

	test('CSV export button is visible', async ({ page }) => {
		await page.goto('/entities');
		await expect(page.locator('button', { hasText: 'CSV' })).toBeVisible();
	});

	test('table has sticky header', async ({ page }) => {
		await page.goto('/entities');
		const thead = page.locator('table[aria-label="Entity library"] thead');
		await expect(thead).toHaveClass(/sticky/);
	});

	test('error messages use role="alert"', async ({ page }) => {
		// Override library API to return an error
		await page.route('/api/library/entities**', (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' }),
		);
		await page.goto('/entities');
		// Error should render with role=alert
		const alert = page.locator('[role="alert"]');
		await expect(alert).toBeVisible({ timeout: 5000 });
	});
});

// ══════════════════════════════════════════════════════════════════════════════
// 2. Attribute Library Page (/attributes)
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Attribute Library Page (/attributes)', () => {
	test.beforeEach(async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryAttributeRoutes(page);
	});

	test('page loads and shows attribute library heading', async ({ page }) => {
		await page.goto('/attributes');
		await expect(page.locator('h1')).toContainText('Attribute Library');
	});

	test('attribute table is visible with row data', async ({ page }) => {
		await page.goto('/attributes');
		const table = page.locator('table[aria-label="Attribute library"]');
		await expect(table).toBeVisible();
		await expect(page.locator('td', { hasText: 'Library Attr 1' }).first()).toBeVisible();
	});

	test('search input is present with correct aria-label', async ({ page }) => {
		await page.goto('/attributes');
		const search = page.locator('input[aria-label="Search attributes"]');
		await expect(search).toBeVisible();
	});

	test('select-all checkbox is visible', async ({ page }) => {
		await page.goto('/attributes');
		const selectAll = page.locator('input[aria-label="Select all attributes on this page"]');
		await expect(selectAll).toBeVisible();
	});

	test('individual row checkbox can be selected', async ({ page }) => {
		await page.goto('/attributes');
		const firstCheckbox = page.locator('input[aria-label="Select Library Attr 1"]');
		await expect(firstCheckbox).toBeVisible();
		await firstCheckbox.check();
		await expect(firstCheckbox).toBeChecked();
	});

	test('bulk delete button appears when items are selected', async ({ page }) => {
		await page.goto('/attributes');
		// Delete button should not be visible with no selection
		const deleteBtn = page.locator('button', { hasText: /^Delete/ });
		await expect(deleteBtn).not.toBeVisible();

		const firstCheckbox = page.locator('input[aria-label="Select Library Attr 1"]');
		await firstCheckbox.check();
		await expect(deleteBtn).toBeVisible();
	});

	test('selected count shown in gold color in stats', async ({ page }) => {
		await page.goto('/attributes');
		const firstCheckbox = page.locator('input[aria-label="Select Library Attr 1"]');
		await firstCheckbox.check();
		const selectedSpan = page.locator('span.text-gold.font-semibold');
		await expect(selectedSpan.first()).toBeVisible();
	});

	test('+ Add Attribute button toggles the add panel', async ({ page }) => {
		await page.goto('/attributes');
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add Attribute' });
		await expect(addBtn).toHaveAttribute('aria-expanded', 'false');

		await addBtn.click();
		await expect(addBtn).toHaveAttribute('aria-expanded', 'true');

		const panel = page.locator('[aria-label="Add attribute to library"]');
		await expect(panel).toBeVisible();
	});

	test('Upload button toggles the CSV upload panel', async ({ page }) => {
		await page.goto('/attributes');
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload' });
		await expect(uploadBtn).toHaveAttribute('aria-expanded', 'false');

		await uploadBtn.click();
		await expect(uploadBtn).toHaveAttribute('aria-expanded', 'true');

		const panel = page.locator('[aria-label="Upload CSV to library"]');
		await expect(panel).toBeVisible();
	});

	test('opening add panel closes upload panel', async ({ page }) => {
		await page.goto('/attributes');
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload' });
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add Attribute' });

		await uploadBtn.click();
		await expect(page.locator('[aria-label="Upload CSV to library"]')).toBeVisible();

		await addBtn.click();
		await expect(page.locator('[aria-label="Add attribute to library"]')).toBeVisible();
		await expect(page.locator('[aria-label="Upload CSV to library"]')).not.toBeVisible();
	});

	test('sort pills visible (Label, Weight, Date)', async ({ page }) => {
		await page.goto('/attributes');
		await expect(page.locator('button', { hasText: /^Label/ }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: /^Weight/ }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: /^Date/ }).first()).toBeVisible();
	});

	test('clicking weight sort pill activates it', async ({ page }) => {
		await page.goto('/attributes');
		const weightBtn = page.locator('button', { hasText: /^Weight/ }).first();
		await weightBtn.click();
		await expect(weightBtn).toHaveClass(/text-gold/);
	});

	test('weight range sliders are present', async ({ page }) => {
		await page.goto('/attributes');
		const sliders = page.locator('input[type="range"]');
		// Two sliders — min and max weight
		await expect(sliders).toHaveCount(2);
	});

	test('weight bars are rendered in table rows', async ({ page }) => {
		await page.goto('/attributes');
		// Weight bars are the visual progress-bar divs inside each row
		const weightBar = page.locator('div.bg-navy-700.rounded-full').first();
		await expect(weightBar).toBeVisible();
	});

	test('Export CSV button is visible', async ({ page }) => {
		await page.goto('/attributes');
		await expect(page.locator('button', { hasText: 'Export CSV' })).toBeVisible();
	});

	test('table has sticky header', async ({ page }) => {
		await page.goto('/attributes');
		const thead = page.locator('table[aria-label="Attribute library"] thead');
		await expect(thead).toHaveClass(/sticky/);
	});

	test('error messages use role="alert"', async ({ page }) => {
		await page.route('/api/library/attributes**', (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' }),
		);
		await page.goto('/attributes');
		const alert = page.locator('[role="alert"]');
		await expect(alert).toBeVisible({ timeout: 5000 });
	});
});

// ══════════════════════════════════════════════════════════════════════════════
// 3. Campaign Entities Page (/campaigns/test-campaign-id/entities)
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Campaign Entities Page (/campaigns/:id/entities)', () => {
	test.beforeEach(async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockCampaignEntityRoutes(page);
	});

	test('page loads and shows entities table', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const table = page.locator('table[aria-label="Entities"]');
		await expect(table).toBeVisible();
		await expect(page.locator('td', { hasText: 'Entity 1' }).first()).toBeVisible();
	});

	test('entities heading shows total count', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const heading = page.locator('h2');
		await expect(heading).toContainText('Entities');
		await expect(heading).toContainText('5');
	});

	test('search input is present with correct aria-label', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const search = page.locator('input[aria-label="Search entities"]');
		await expect(search).toBeVisible();
	});

	test('sort pills are visible (Label, GWM ID, Date)', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		await expect(page.locator('button[aria-label^="Sort by Label"]')).toBeVisible();
		await expect(page.locator('button[aria-label^="Sort by GWM ID"]')).toBeVisible();
		await expect(page.locator('button[aria-label^="Sort by Date"]')).toBeVisible();
	});

	test('sort pills have aria-pressed attribute', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const labelPill = page.locator('button[aria-label^="Sort by Label"]');
		await expect(labelPill).toHaveAttribute('aria-pressed');
	});

	test('GWM ID filter chips are visible (All, Has GWM ID, Missing GWM ID)', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		await expect(page.locator('button', { hasText: 'All' }).first()).toBeVisible();
		await expect(page.locator('button', { hasText: 'Has GWM ID' })).toBeVisible();
		await expect(page.locator('button', { hasText: 'Missing GWM ID' })).toBeVisible();
	});

	test('clicking "Has GWM ID" filter shows only entities with gwm_id', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		await page.locator('button', { hasText: 'Has GWM ID' }).click();
		// mockEntities has gwm_id on indices 0, 2, 4 → labels Entity 1, 3, 5
		await expect(page.locator('td', { hasText: 'Entity 1' }).first()).toBeVisible();
		// Entity 2 has no gwm_id — should not appear
		await expect(page.locator('td', { hasText: 'Entity 2' })).not.toBeVisible();
	});

	test('clicking "Missing GWM ID" filter shows only entities without gwm_id', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		await page.locator('button', { hasText: 'Missing GWM ID' }).click();
		// Entity 2 and 4 have null gwm_id
		await expect(page.locator('td', { hasText: 'Entity 2' }).first()).toBeVisible();
		// Entity 1 has GWM-1000 — should not appear
		await expect(page.locator('td', { hasText: 'Entity 1' })).not.toBeVisible();
	});

	test('Export CSV button is visible', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		await expect(page.locator('button', { hasText: 'Export CSV' })).toBeVisible();
	});

	test('select-all checkbox selects all rows', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const selectAll = page.locator('input[aria-label="Select all entities on this page"]');
		await selectAll.check();
		const firstRow = page.locator('input[aria-label="Select Entity 1"]');
		await expect(firstRow).toBeChecked();
	});

	test('bulk delete button appears when rows are selected', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		// No selection → delete not visible
		await expect(page.locator('button', { hasText: /Delete selected/ })).not.toBeVisible();

		const firstRow = page.locator('input[aria-label="Select Entity 1"]');
		await firstRow.check();
		await expect(page.locator('button', { hasText: /Delete selected/ })).toBeVisible();
	});

	test('selected count appears in stats line', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const firstRow = page.locator('input[aria-label="Select Entity 1"]');
		await firstRow.check();
		const goldSpan = page.locator('span.text-gold.font-semibold');
		await expect(goldSpan.first()).toBeVisible();
	});

	test('Edit button activates inline edit mode for a row', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const editBtn = page.locator('button[aria-label="Edit Entity 1"]');
		await editBtn.click();
		// Label input should appear
		const labelInput = page.locator('label[for^="edit-label-entity-1"]');
		await expect(page.locator('input[id^="edit-label-entity-1"]')).toBeVisible();
	});

	test('Cancel button exits inline edit mode', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const editBtn = page.locator('button[aria-label="Edit Entity 1"]');
		await editBtn.click();
		const cancelBtn = page.locator('button[aria-label="Cancel editing Entity 1"]');
		await cancelBtn.click();
		// Edit form should be gone
		await expect(page.locator('input[id^="edit-label-entity-1"]')).not.toBeVisible();
	});

	test('Escape key cancels inline edit', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const editBtn = page.locator('button[aria-label="Edit Entity 1"]');
		await editBtn.click();
		const labelInput = page.locator('input[id^="edit-label-entity-1"]');
		await expect(labelInput).toBeVisible();
		await labelInput.press('Escape');
		await expect(labelInput).not.toBeVisible();
	});

	test('Enter key in inline edit triggers save', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const editBtn = page.locator('button[aria-label="Edit Entity 1"]');
		await editBtn.click();
		const labelInput = page.locator('input[id^="edit-label-entity-1"]');
		await expect(labelInput).toBeVisible();
		await labelInput.fill('Updated Entity 1');
		await labelInput.press('Enter');
		// After save the edit form should be gone (save succeeded with mocked PATCH)
		await expect(labelInput).not.toBeVisible();
	});

	test('table wrapper is scrollable', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const wrapper = page.locator('div.overflow-auto').first();
		await expect(wrapper).toBeVisible();
	});

	test('table has sticky header', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const thead = page.locator('table[aria-label="Entities"] thead');
		await expect(thead).toHaveClass(/sticky/);
	});

	test('back link to campaign is present', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const backLink = page.locator(`a[href="/campaigns/${CAMPAIGN_ID}"]`);
		await expect(backLink).toBeVisible();
	});

	test('+ Add Entity button expands the add form panel', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add Entity' });
		await expect(addBtn).toHaveAttribute('aria-expanded', 'false');
		await addBtn.click();
		await expect(addBtn).toHaveAttribute('aria-expanded', 'true');
		const form = page.locator('[aria-label="Add entity"]');
		await expect(form).toBeVisible();
	});

	test('Upload CSV button expands the CSV upload panel', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const uploadBtn = page.locator('button[aria-expanded]', { hasText: 'Upload CSV' });
		await uploadBtn.click();
		await expect(uploadBtn).toHaveAttribute('aria-expanded', 'true');
		const panel = page.locator('[aria-label="Upload entities via CSV"]');
		await expect(panel).toBeVisible();
	});

	test('Import from Library button expands the library import panel', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const importBtn = page.locator('button', { hasText: 'Import from Library' });
		await importBtn.click();
		const panel = page.locator('[aria-label="Import entities from library"]');
		await expect(panel).toBeVisible();
	});

	test('error messages use role="alert"', async ({ page }) => {
		await page.route(`/api/campaigns/${CAMPAIGN_ID}/entities**`, (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' }),
		);
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const alert = page.locator('[role="alert"]');
		await expect(alert).toBeVisible({ timeout: 5000 });
	});
});

// ══════════════════════════════════════════════════════════════════════════════
// 4. Campaign Attributes Page (/campaigns/test-campaign-id/attributes)
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Campaign Attributes Page (/campaigns/:id/attributes)', () => {
	test.beforeEach(async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockCampaignAttributeRoutes(page);
	});

	test('page loads and shows attributes table', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		// Wait for loading to finish — LoadingSpinner goes away
		await expect(page.locator('[data-testid="loading-spinner"]').or(page.locator('.animate-spin'))).not.toBeVisible({ timeout: 5000 });
		const heading = page.locator('h2');
		await expect(heading).toContainText('Attributes');
	});

	test('attributes heading shows total count', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const heading = page.locator('h2');
		await expect(heading).toContainText('Attributes');
		await expect(heading).toContainText('5');
	});

	test('search input is present with correct aria-label', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const search = page.locator('input[aria-label="Search attributes"]');
		await expect(search).toBeVisible();
	});

	test('sort pills are visible (Label, Weight, Date)', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		await expect(page.locator('button[aria-label^="Sort by Label"]')).toBeVisible();
		await expect(page.locator('button[aria-label^="Sort by Weight"]')).toBeVisible();
		await expect(page.locator('button[aria-label^="Sort by Date"]')).toBeVisible();
	});

	test('sort pills have aria-pressed attribute', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const labelPill = page.locator('button[aria-label^="Sort by Label"]');
		await expect(labelPill).toHaveAttribute('aria-pressed');
	});

	test('weight range sliders are present', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const sliders = page.locator('input[type="range"]');
		await expect(sliders).toHaveCount(2);
	});

	test('weight range slider filter hides rows outside range', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		// Attribute 1 has weight 2, Attribute 5 has weight 10
		// Set minWeight slider to 9 so only Attribute 5 is visible
		const minSlider = page.locator('input[type="range"]').nth(0);
		await minSlider.fill('9');
		// Attribute 1 (weight 2) should be hidden
		await expect(page.locator('td', { hasText: 'Attribute 1' })).not.toBeVisible();
	});

	test('Export CSV button is visible', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		await expect(page.locator('button', { hasText: 'Export CSV' })).toBeVisible();
	});

	test('select-all checkbox is visible', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const selectAll = page.locator('input[aria-label^="Select all"]');
		await expect(selectAll.first()).toBeVisible();
	});

	test('bulk delete button appears when items are selected', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		await expect(page.locator('button', { hasText: /Delete selected/ })).not.toBeVisible();

		const firstRow = page.locator('input[aria-label="Select Attribute 1"]');
		await firstRow.check();
		await expect(page.locator('button', { hasText: /Delete selected/ })).toBeVisible();
	});

	test('Delete button text (not "Del") visible on delete action', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const firstRow = page.locator('input[aria-label="Select Attribute 1"]');
		await firstRow.check();
		const deleteBtn = page.locator('button', { hasText: /Delete selected/ });
		await expect(deleteBtn).toBeVisible();
		// Verify the text says "Delete" not abbreviated "Del"
		const text = await deleteBtn.textContent();
		expect(text).toMatch(/Delete/);
		expect(text).not.toMatch(/^Del$/);
	});

	test('weight bars are rendered in table rows', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		// Each attribute row contains a weight progress bar wrapper
		const weightBar = page.locator('div.bg-navy-700.rounded-full').first();
		await expect(weightBar).toBeVisible();
	});

	test('Edit button activates inline edit mode', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const editBtn = page.locator('button[aria-label="Edit Attribute 1"]');
		await editBtn.click();
		const labelInput = page.locator('input[id^="edit-attr-label-attr-1"]');
		await expect(labelInput).toBeVisible();
	});

	test('Escape key cancels inline edit', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const editBtn = page.locator('button[aria-label="Edit Attribute 1"]');
		await editBtn.click();
		const labelInput = page.locator('input[id^="edit-attr-label-attr-1"]');
		await expect(labelInput).toBeVisible();
		await labelInput.press('Escape');
		await expect(labelInput).not.toBeVisible();
	});

	test('Enter key in inline edit triggers save', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const editBtn = page.locator('button[aria-label="Edit Attribute 1"]');
		await editBtn.click();
		const labelInput = page.locator('input[id^="edit-attr-label-attr-1"]');
		await expect(labelInput).toBeVisible();
		await labelInput.fill('Updated Attribute 1');
		await labelInput.press('Enter');
		await expect(labelInput).not.toBeVisible();
	});

	test('table has sticky header', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const table = page.locator('table').first();
		await expect(table).toBeVisible();
		const thead = table.locator('thead');
		await expect(thead).toHaveClass(/sticky/);
	});

	test('back link to campaign is present', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const backLink = page.locator(`a[href="/campaigns/${CAMPAIGN_ID}"]`);
		await expect(backLink).toBeVisible();
	});

	test('+ Add Attribute button expands the add form panel', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const addBtn = page.locator('button[aria-expanded]', { hasText: '+ Add Attribute' });
		await expect(addBtn).toHaveAttribute('aria-expanded', 'false');
		await addBtn.click();
		await expect(addBtn).toHaveAttribute('aria-expanded', 'true');
	});

	test('Import from Library button expands the library import panel', async ({ page }) => {
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const importBtn = page.locator('button', { hasText: 'Import from Library' });
		await importBtn.click();
		const panel = page.locator('[aria-label="Import attributes from library"]');
		await expect(panel).toBeVisible();
	});

	test('error messages use role="alert"', async ({ page }) => {
		await page.route(`/api/campaigns/${CAMPAIGN_ID}/attributes**`, (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' }),
		);
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const alert = page.locator('[role="alert"]');
		await expect(alert).toBeVisible({ timeout: 5000 });
	});
});

// ══════════════════════════════════════════════════════════════════════════════
// 5. Cross-page consistency
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Cross-page consistency', () => {
	const pages = [
		{
			name: 'Entity Library',
			url: '/entities',
			setupMocks: async (page: Page) => {
				await mockLibraryEntityRoutes(page);
			},
			tableLabel: 'Entity library',
		},
		{
			name: 'Attribute Library',
			url: '/attributes',
			setupMocks: async (page: Page) => {
				await mockLibraryAttributeRoutes(page);
			},
			tableLabel: 'Attribute library',
		},
		{
			name: 'Campaign Entities',
			url: `/campaigns/${CAMPAIGN_ID}/entities`,
			setupMocks: async (page: Page) => {
				await mockCampaignEntityRoutes(page);
			},
			tableLabel: 'Entities',
		},
		{
			name: 'Campaign Attributes',
			url: `/campaigns/${CAMPAIGN_ID}/attributes`,
			setupMocks: async (page: Page) => {
				await mockCampaignAttributeRoutes(page);
			},
			tableLabel: null, // Campaign attributes table has no aria-label
		},
	];

	for (const pg of pages) {
		test(`${pg.name}: uses gold color scheme`, async ({ page, context }) => {
			await setAuthCookie(context);
			await mockAuthRoutes(page);
			await pg.setupMocks(page);
			await page.goto(pg.url);
			// Gold color appears in the heading or toolbar
			const goldElements = page.locator('.text-gold');
			await expect(goldElements.first()).toBeVisible();
		});

		test(`${pg.name}: has search input`, async ({ page, context }) => {
			await setAuthCookie(context);
			await mockAuthRoutes(page);
			await pg.setupMocks(page);
			await page.goto(pg.url);
			const search = page.locator('input[aria-label="Search entities"], input[aria-label="Search attributes"]');
			await expect(search.first()).toBeVisible();
		});

		test(`${pg.name}: table has sticky header`, async ({ page, context }) => {
			await setAuthCookie(context);
			await mockAuthRoutes(page);
			await pg.setupMocks(page);
			await page.goto(pg.url);
			// Find the thead in any table on the page
			const thead = page.locator('table thead').first();
			await expect(thead).toBeVisible();
			await expect(thead).toHaveClass(/sticky/);
		});

		test(`${pg.name}: table is inside a scrollable wrapper`, async ({ page, context }) => {
			await setAuthCookie(context);
			await mockAuthRoutes(page);
			await pg.setupMocks(page);
			await page.goto(pg.url);
			const scrollWrapper = page.locator('div.overflow-auto').first();
			await expect(scrollWrapper).toBeVisible();
		});
	}

	test('scout nav bar is visible on all scout pages', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryEntityRoutes(page);
		await page.goto('/entities');
		const nav = page.locator('nav[aria-label="Scout"]');
		await expect(nav).toBeVisible();
		// All three nav links should be present
		await expect(nav.locator('a', { hasText: 'Campaigns' })).toBeVisible();
		await expect(nav.locator('a', { hasText: 'Entities' })).toBeVisible();
		await expect(nav.locator('a', { hasText: 'Attributes' })).toBeVisible();
	});

	test('active nav link has aria-current="page"', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryEntityRoutes(page);
		await page.goto('/entities');
		const entitiesLink = page.locator('nav[aria-label="Scout"] a[aria-current="page"]');
		await expect(entitiesLink).toHaveText('Entities');
	});
});

// ══════════════════════════════════════════════════════════════════════════════
// 6. Mobile viewport tests
// ══════════════════════════════════════════════════════════════════════════════

test.describe('Mobile viewport', () => {
	test.use({ viewport: { width: 390, height: 844 } });

	test('Entity Library page loads on mobile', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryEntityRoutes(page);
		await page.goto('/entities');
		await expect(page.locator('h1')).toContainText('Entity Library');
	});

	test('Attribute Library page loads on mobile', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockLibraryAttributeRoutes(page);
		await page.goto('/attributes');
		await expect(page.locator('h1')).toContainText('Attribute Library');
	});

	test('Campaign Entities page loads on mobile', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockCampaignEntityRoutes(page);
		await page.goto(`/campaigns/${CAMPAIGN_ID}/entities`);
		const heading = page.locator('h2');
		await expect(heading).toContainText('Entities');
	});

	test('Campaign Attributes page loads on mobile', async ({ page, context }) => {
		await setAuthCookie(context);
		await mockAuthRoutes(page);
		await mockCampaignAttributeRoutes(page);
		await page.goto(`/campaigns/${CAMPAIGN_ID}/attributes`);
		const heading = page.locator('h2');
		await expect(heading).toContainText('Attributes');
	});
});
