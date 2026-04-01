/**
 * E2E tests for GlobalTeamSelector in the root header.
 *
 * All tests mock backend API routes so no running server is required.
 * Auth is simulated via a fake JWT cookie.
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

const mockTeams = [
	{ id: 'team-1', slug: 'team-1', display_name: 'Alpha Team', description: '', created_by: 'user-abc', created_at: '2025-01-01T00:00:00Z', role: 'admin' },
	{ id: 'team-2', slug: 'team-2', display_name: 'Beta Squad', description: '', created_by: 'user-abc', created_at: '2025-01-01T00:00:00Z', role: 'member' },
	{ id: 'team-3', slug: 'team-3', display_name: 'Gamma Group', description: '', created_by: 'user-abc', created_at: '2025-01-01T00:00:00Z', role: 'member' },
];

const mockTeamsMany = Array.from({ length: 8 }, (_, i) => ({
	id: `team-${i}`,
	slug: `team-${i}`,
	display_name: `Team ${String.fromCharCode(65 + i)}`, // Team A, Team B, ...
	description: '',
	created_by: 'user-abc',
	created_at: '2025-01-01T00:00:00Z',
	role: 'member',
}));

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

async function mockBaseRoutes(page: Page, teams = mockTeams) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUser),
		})
	);
	await page.route('/api/teams', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(teams),
		})
	);
	// Notification polling — return empty to avoid noise
	await page.route('/api/notifications*', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
	);
}

// ── Visibility ────────────────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — visibility', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('team selector is visible in header when logged in', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const selector = page.locator('.global-team-selector');
		await expect(selector).toBeVisible();
	});

	test('shows Personal label when no team is active', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		// The trigger button should contain "Personal" on desktop
		const btn = page.locator('.global-team-selector button').first();
		await expect(btn).toContainText('Personal');
	});
});

// ── Dropdown open/close ───────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — dropdown', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('dropdown opens when trigger is clicked', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		const dropdown = page.locator('[role="listbox"]');
		await expect(dropdown).toBeVisible();
	});

	test('dropdown closes when trigger is clicked again', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();
		await expect(page.locator('[role="listbox"]')).toBeVisible();

		await btn.click();
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();
	});

	test('dropdown closes when clicking outside', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();
		await expect(page.locator('[role="listbox"]')).toBeVisible();

		// Click somewhere outside the selector
		await page.mouse.click(10, 10);
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();
	});

	test('dropdown lists Personal and all teams', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		const listbox = page.locator('[role="listbox"]');
		await expect(listbox).toContainText('Personal');
		await expect(listbox).toContainText('Alpha Team');
		await expect(listbox).toContainText('Beta Squad');
		await expect(listbox).toContainText('Gamma Group');
	});
});

// ── Team switching ────────────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — team switching', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('selecting a team closes the dropdown and shows team name in trigger', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// Click Alpha Team option
		await page.locator('[role="option"]').filter({ hasText: 'Alpha Team' }).click();

		// Dropdown should close
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();

		// Trigger should now show Alpha Team
		await expect(btn).toContainText('Alpha Team');
	});

	test('selecting Personal shows Personal in trigger', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// First click Alpha Team, then switch back to Personal
		await page.locator('[role="option"]').filter({ hasText: 'Alpha Team' }).click();
		await btn.click();
		await page.locator('[role="option"]').filter({ hasText: 'Personal' }).click();

		await expect(btn).toContainText('Personal');
	});

	test('active team has checkmark indicator', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// Select Beta Squad
		await page.locator('[role="option"]').filter({ hasText: 'Beta Squad' }).click();

		// Re-open
		await btn.click();

		// Beta Squad option should have aria-selected=true
		const activeOption = page.locator('[role="option"][aria-selected="true"]');
		await expect(activeOption).toContainText('Beta Squad');
	});
});

// ── Search filter ─────────────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — search filter', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('search input appears when 6+ teams', async ({ page }) => {
		await mockBaseRoutes(page, mockTeamsMany);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		const searchInput = page.locator('[aria-label="Filter teams"]');
		await expect(searchInput).toBeVisible();
	});

	test('search input is hidden when fewer than 6 teams', async ({ page }) => {
		await mockBaseRoutes(page, mockTeams); // only 3 teams
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		const searchInput = page.locator('[aria-label="Filter teams"]');
		await expect(searchInput).not.toBeVisible();
	});

	test('typing in search filters the team list', async ({ page }) => {
		await mockBaseRoutes(page, mockTeamsMany);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		const searchInput = page.locator('[aria-label="Filter teams"]');
		await searchInput.fill('Team A');

		const listbox = page.locator('[role="listbox"]');
		await expect(listbox).toContainText('Team A');
		// Team B should not be visible after filtering
		await expect(listbox).not.toContainText('Team B');
	});
});

// ── Keyboard navigation ───────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — keyboard navigation', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('Escape closes the dropdown and returns focus to trigger', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();
		await expect(page.locator('[role="listbox"]')).toBeVisible();

		await page.keyboard.press('Escape');
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();
	});

	test('ArrowDown moves highlight down through options', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// Arrow down to move past Personal to first team
		await page.keyboard.press('ArrowDown');

		// The second option (index 1 = first team) should be highlighted
		const highlighted = page.locator('[data-highlighted="true"]');
		await expect(highlighted).toContainText('Alpha Team');
	});

	test('ArrowUp moves highlight up', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// Go down twice
		await page.keyboard.press('ArrowDown');
		await page.keyboard.press('ArrowDown');

		// Then back up
		await page.keyboard.press('ArrowUp');

		const highlighted = page.locator('[data-highlighted="true"]');
		await expect(highlighted).toContainText('Alpha Team');
	});

	test('Enter selects the highlighted option', async ({ page }) => {
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// Navigate to Alpha Team (index 1)
		await page.keyboard.press('ArrowDown');
		await page.keyboard.press('Enter');

		// Dropdown closes and trigger shows Alpha Team
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();
		await expect(btn).toContainText('Alpha Team');
	});
});

// ── No teams state ────────────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — no teams', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('shows no-teams muted text in trigger when teams array is empty', async ({ page }) => {
		await mockBaseRoutes(page, []);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await expect(btn).toContainText('No teams');
	});

	test('clicking no-teams trigger navigates to /teams', async ({ page }) => {
		await mockBaseRoutes(page, []);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		await expect(page).toHaveURL(/\/teams/);
	});
});

// ── Single team mode ──────────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — single team', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('single-team trigger has no chevron and no dropdown opens', async ({ page }) => {
		await mockBaseRoutes(page, [mockTeams[0]]);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		// No dropdown for single team
		await expect(page.locator('[role="listbox"]')).not.toBeVisible();
	});

	test('single-team trigger navigates to /teams/[slug] on click', async ({ page }) => {
		await mockBaseRoutes(page, [mockTeams[0]]);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		await btn.click();

		await expect(page).toHaveURL(/\/teams\/team-1/);
	});
});

// ── Responsive behavior ───────────────────────────────────────────────────────

test.describe('GlobalTeamSelector — responsive', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('on mobile: initial circle shown, team name text hidden', async ({ page }) => {
		await page.setViewportSize({ width: 375, height: 812 });
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		// The text label span has hidden md:block — it should not be visible on mobile
		const label = btn.locator('span.hidden.md\\:block');
		await expect(label).not.toBeVisible();
	});

	test('on desktop: team name is visible in trigger', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 800 });
		await mockBaseRoutes(page);
		await page.goto('/');

		const btn = page.locator('.global-team-selector button').first();
		const label = btn.locator('span.hidden.md\\:block').first();
		await expect(label).toBeVisible();
	});
});

// ── Scout layout: TeamSwitcher removed ───────────────────────────────────────

test.describe('Scout layout — TeamSwitcher removed', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('Scout layout top bar does not contain old pill-button TeamSwitcher', async ({ page }) => {
		await mockBaseRoutes(page);
		// Mock campaigns endpoint
		await page.route('/api/campaigns*', (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		await page.goto('/campaigns');

		// The old TeamSwitcher used aria-labelledby="team-switcher-label"
		// It should no longer exist in the Scout layout
		const oldSwitcherLabel = page.locator('#team-switcher-label');
		await expect(oldSwitcherLabel).toHaveCount(0);
	});
});
