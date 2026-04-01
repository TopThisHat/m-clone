/**
 * E2E tests for TeamShareTags on the share page (/share/[id]).
 *
 * All tests mock the API so no backend is required.
 * The share page calls:
 *   - /api/share/:id            (session data — now includes shared_team_names)
 *   - /api/sessions/:id/comments
 *   - /api/auth/me
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';

const SESSION_ID = 'test-team-tags-session';

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

const baseSession = {
	id: SESSION_ID,
	title: 'Team Tags Test Report',
	query: 'Testing team attribution tags',
	visibility: 'team',
	is_public: false,
	report_markdown: '## Summary\n\nTest content.',
	created_at: '2025-01-15T10:00:00Z',
	trace_steps: [],
	parent_session_id: null,
};

async function mockSharePage(page: Page, sessionOverride: Record<string, unknown> = {}) {
	const session = { ...baseSession, ...sessionOverride };

	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUser),
		}),
	);

	await page.route(`/api/share/${SESSION_ID}`, (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(session),
		}),
	);

	await page.route(`/api/sessions/${SESSION_ID}/comments`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);

	await page.route(`/api/sessions/${SESSION_ID}/presence`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);

	await page.route(`/api/sessions/${SESSION_ID}/subscribed`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: 'false' }),
	);
}

// ── Single team name ──────────────────────────────────────────────────────────

test.describe('TeamShareTags - single team', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('shows team name tag instead of "Team only" when one team is present', async ({ page }) => {
		await mockSharePage(page, { shared_team_names: ['Alpha Team'] });
		await page.goto(`/share/${SESSION_ID}`);

		// The old static "Team only" text should not appear
		await expect(page.locator('text=Team only')).toHaveCount(0);

		// The team name tag should be visible
		await expect(page.locator('text=Alpha Team')).toBeVisible();
	});
});

// ── Multiple teams within maxVisible ─────────────────────────────────────────

test.describe('TeamShareTags - multiple teams', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('shows both team tags when count equals default maxVisible (2)', async ({ page }) => {
		await mockSharePage(page, { shared_team_names: ['Alpha Team', 'Beta Team'] });
		await page.goto(`/share/${SESSION_ID}`);

		await expect(page.locator('text=Alpha Team')).toBeVisible();
		await expect(page.locator('text=Beta Team')).toBeVisible();

		// No overflow button when at maxVisible
		await expect(page.locator('button', { hasText: /more/ })).toHaveCount(0);
	});
});

// ── Overflow expand ───────────────────────────────────────────────────────────

test.describe('TeamShareTags - overflow expand', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('shows overflow button when teams exceed maxVisible', async ({ page }) => {
		await mockSharePage(page, {
			shared_team_names: ['Alpha Team', 'Beta Team', 'Gamma Team'],
		});
		await page.goto(`/share/${SESSION_ID}`);

		// First two visible, one hidden
		await expect(page.locator('text=Alpha Team')).toBeVisible();
		await expect(page.locator('text=Beta Team')).toBeVisible();
		await expect(page.locator('text=Gamma Team')).toHaveCount(0);

		// Overflow button shows "+1 more"
		const overflowBtn = page.locator('button', { hasText: '+1 more' });
		await expect(overflowBtn).toBeVisible();
	});

	test('clicking overflow button expands all team tags', async ({ page }) => {
		await mockSharePage(page, {
			shared_team_names: ['Alpha Team', 'Beta Team', 'Gamma Team'],
		});
		await page.goto(`/share/${SESSION_ID}`);

		const overflowBtn = page.locator('button', { hasText: '+1 more' });
		await overflowBtn.click();

		// All three tags now visible
		await expect(page.locator('text=Alpha Team')).toBeVisible();
		await expect(page.locator('text=Beta Team')).toBeVisible();
		await expect(page.locator('text=Gamma Team')).toBeVisible();

		// Overflow button is gone
		await expect(page.locator('button', { hasText: /more/ })).toHaveCount(0);
	});

	test('shows correct overflow count for many teams', async ({ page }) => {
		await mockSharePage(page, {
			shared_team_names: ['A', 'B', 'C', 'D', 'E'],
		});
		await page.goto(`/share/${SESSION_ID}`);

		// Default maxVisible=2, so 3 hidden → "+3 more"
		const overflowBtn = page.locator('button', { hasText: '+3 more' });
		await expect(overflowBtn).toBeVisible();
	});
});

// ── No teams ─────────────────────────────────────────────────────────────────

test.describe('TeamShareTags - no teams', () => {
	test.beforeEach(async ({ context }) => { await setAuthCookie(context); });

	test('renders nothing when shared_team_names is empty', async ({ page }) => {
		await mockSharePage(page, { shared_team_names: [] });
		await page.goto(`/share/${SESSION_ID}`);

		// No people-icon tags at all in the metadata row
		const metadataRow = page.locator('.flex.items-center.gap-2.flex-wrap.mb-2');
		await expect(metadataRow).toBeVisible();

		// No overflow button
		await expect(page.locator('button', { hasText: /more/ })).toHaveCount(0);
	});

	test('renders nothing when shared_team_names is absent', async ({ page }) => {
		// No shared_team_names key at all — component uses ?? []
		await mockSharePage(page, {});
		await page.goto(`/share/${SESSION_ID}`);

		await expect(page.locator('button', { hasText: /more/ })).toHaveCount(0);
	});
});
