/**
 * E2E tests for comment team attribution pills.
 *
 * These tests mock all API routes so the backend does not need to be running.
 * They verify that:
 *   - Comments with team context show a team pill next to the author name
 *   - Comments without team context (team_name = null) show no pill
 *   - Multiple teams receive distinct visual color classes
 *
 * Tests run against the share page (/share/:id) because it renders
 * CommentThread without requiring authentication for the report itself.
 */

import { test, expect, type BrowserContext } from '@playwright/test';

// ── Shared fixtures ────────────────────────────────────────────────────────────

const SESSION_ID = 'test-team-pills-session';

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

const mockSession = {
	id: SESSION_ID,
	title: 'Team Pills Test Session',
	query: 'Test query',
	visibility: 'team',
	is_public: true,
	report_markdown: '## Test Report\n\nSome content for testing.',
	created_at: '2026-01-01T10:00:00Z',
	trace_steps: [],
	owner_sid: 'user-1',
	owner_name: 'Test User',
};

const mockUser = {
	sid: 'user-1',
	display_name: 'Test User',
	email: 'test@example.com',
	avatar_url: null,
};

const mockComments = [
	{
		id: 'comment-with-team',
		session_id: SESSION_ID,
		author_sid: 'user-2',
		author_name: 'Alice Smith',
		author_avatar: null,
		body: 'This comment is from the Engineering team.',
		mentions: [],
		parent_id: null,
		highlight_anchor: null,
		created_at: '2026-01-01T11:00:00Z',
		updated_at: '2026-01-01T11:00:00Z',
		comment_type: 'comment',
		proposed_text: null,
		suggestion_status: null,
		reactions: {},
		team_id: 'team-eng',
		team_name: 'Engineering',
	},
	{
		id: 'comment-no-team',
		session_id: SESSION_ID,
		author_sid: 'user-3',
		author_name: 'Bob Jones',
		author_avatar: null,
		body: 'This is a personal comment with no team context.',
		mentions: [],
		parent_id: null,
		highlight_anchor: null,
		created_at: '2026-01-01T12:00:00Z',
		updated_at: '2026-01-01T12:00:00Z',
		comment_type: 'comment',
		proposed_text: null,
		suggestion_status: null,
		reactions: {},
		team_id: null,
		team_name: null,
	},
	{
		id: 'comment-different-team',
		session_id: SESSION_ID,
		author_sid: 'user-4',
		author_name: 'Carol White',
		author_avatar: null,
		body: 'This comment is from the Design team.',
		mentions: [],
		parent_id: null,
		highlight_anchor: null,
		created_at: '2026-01-01T13:00:00Z',
		updated_at: '2026-01-01T13:00:00Z',
		comment_type: 'comment',
		proposed_text: null,
		suggestion_status: null,
		reactions: {},
		team_id: 'team-design',
		team_name: 'Design',
	},
];

// ── Mock API setup ─────────────────────────────────────────────────────────────

async function setupMocks(context: BrowserContext) {
	await context.route(`**/api/auth/me`, (route) => {
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockUser) });
	});

	await context.route(`**/api/share/${SESSION_ID}`, (route) => {
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSession) });
	});

	await context.route(`**/api/sessions/${SESSION_ID}/comments`, (route) => {
		if (route.request().method() === 'GET') {
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockComments),
			});
		} else {
			// POST - echo back a new comment
			route.fulfill({
				status: 201,
				contentType: 'application/json',
				body: JSON.stringify({
					...mockComments[0],
					id: 'new-comment',
					body: 'New comment',
				}),
			});
		}
	});
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('Comment team pills', () => {
	test('shows team pill on comments with team context', async ({ page, context }) => {
		await setAuthCookie(context);
		await setupMocks(context);

		await page.goto(`/share/${SESSION_ID}`);

		// Open the comments panel
		const commentsButton = page.getByRole('button', { name: /comments/i });
		await commentsButton.click();

		// The Engineering team pill should appear next to Alice's comment
		const engineeringPill = page.getByRole('generic').filter({ hasText: 'Engineering' }).first();
		await expect(engineeringPill).toBeVisible();
	});

	test('no pill on comments without team context', async ({ page, context }) => {
		await setAuthCookie(context);
		await setupMocks(context);

		await page.goto(`/share/${SESSION_ID}`);

		const commentsButton = page.getByRole('button', { name: /comments/i });
		await commentsButton.click();

		// Bob's comment should be visible but have no pill (team_name is null)
		const bobComment = page.locator('[data-comment-id="comment-no-team"]');
		await expect(bobComment).toBeVisible();

		// No span with aria-label matching "Posted from ... team" inside Bob's comment
		const pillInsideBobComment = bobComment.locator('[aria-label*="Posted from"]');
		await expect(pillInsideBobComment).toHaveCount(0);
	});

	test('pill has correct aria-label for accessibility', async ({ page, context }) => {
		await setAuthCookie(context);
		await setupMocks(context);

		await page.goto(`/share/${SESSION_ID}`);

		const commentsButton = page.getByRole('button', { name: /comments/i });
		await commentsButton.click();

		// Engineering pill should have aria-label="Posted from Engineering team"
		const pill = page.locator('[aria-label="Posted from Engineering team"]');
		await expect(pill).toBeVisible();
	});

	test('different teams receive visually distinct pills', async ({ page, context }) => {
		await setAuthCookie(context);
		await setupMocks(context);

		await page.goto(`/share/${SESSION_ID}`);

		const commentsButton = page.getByRole('button', { name: /comments/i });
		await commentsButton.click();

		const engineeringPill = page.locator('[aria-label="Posted from Engineering team"]');
		const designPill = page.locator('[aria-label="Posted from Design team"]');

		await expect(engineeringPill).toBeVisible();
		await expect(designPill).toBeVisible();

		// The two pills should have different class sets (color coding)
		const engClass = await engineeringPill.getAttribute('class');
		const designClass = await designPill.getAttribute('class');

		expect(engClass).not.toBe(designClass);
	});
});
