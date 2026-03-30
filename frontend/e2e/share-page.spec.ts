/**
 * E2E tests for the share page (/share/[id])
 *
 * These tests mock all API routes so the backend does not need to be running.
 * The share page load function calls:
 *   - /api/share/:id          (GET session data)
 *   - /api/sessions/:id/comments (GET initial comments)
 *   - /api/auth/me             (GET user, via layout.server.ts)
 *
 * All tests use the "chromium" project unless overridden per test.
 */

import { test, expect, type Page } from '@playwright/test';

// ── Shared fixtures ────────────────────────────────────────────────────────────

const SESSION_ID = 'test-share-session';

const mockSession = {
	id: SESSION_ID,
	title: 'Q1 2025 Market Analysis',
	query: 'What is the outlook for tech stocks in Q1 2025?',
	visibility: 'team',
	is_public: false,
	report_markdown: [
		'## Executive Summary',
		'',
		'This is an executive summary of the market analysis.',
		'',
		'## Key Findings',
		'',
		'Several key findings were identified during research.',
		'',
		'## Conclusion',
		'',
		'The analysis concludes with actionable recommendations.',
	].join('\n'),
	created_at: '2025-01-15T10:00:00Z',
	trace_steps: [],
	parent_session_id: null,
};

const mockSessionPublic = {
	...mockSession,
	id: 'test-share-public',
	visibility: 'public',
	is_public: true,
};

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

/**
 * Register all API mocks needed for a standard authenticated share page load.
 */
async function mockAuthenticatedSharePage(page: Page, session = mockSession) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUser),
		}),
	);

	await page.route(`/api/share/${session.id}`, (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(session),
		}),
	);

	await page.route(`/api/sessions/${session.id}/comments`, (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify([]),
		}),
	);

	// Presence and subscription endpoints — best-effort, return empty
	await page.route(`/api/sessions/${session.id}/presence`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route(`/api/sessions/${session.id}/subscribe`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
	);
	await page.route(`/api/sessions/${session.id}/subscribed`, (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: 'false' }),
	);
}

/**
 * Register mocks for an unauthenticated share page (no /api/auth/me user).
 */
async function mockUnauthenticatedSharePage(page: Page, session = mockSession) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({ status: 401, body: '' }),
	);

	await page.route(`/api/share/${session.id}`, (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ ...session, visibility: 'public', is_public: true }),
		}),
	);

	await page.route(`/api/sessions/${session.id}/comments`, (route) =>
		route.fulfill({ status: 403, body: '' }),
	);
}

// ── Theme tests ────────────────────────────────────────────────────────────────

test.describe('Share page - theme', () => {
	test('page renders with dark theme class by default', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		// The layout root uses class:light based on the theme store.
		// The default user theme is "dark" so .light should NOT be present.
		const root = page.locator('div.h-screen');
		await expect(root).not.toHaveClass(/light/);
	});

	test('light theme applies .light class on layout root', async ({ page }) => {
		// Override user with light theme preference
		await page.route('/api/auth/me', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ ...mockUser, theme: 'light' }),
			}),
		);
		await page.route(`/api/share/${SESSION_ID}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockSession),
			}),
		);
		await page.route(`/api/sessions/${SESSION_ID}/comments`, (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
		);

		await page.goto(`/share/${SESSION_ID}`);
		const root = page.locator('div.h-screen');
		await expect(root).toHaveClass(/light/);
	});

	test('sticky header is visible after scrolling', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const header = page.locator('.sticky.top-0').first();
		await expect(header).toBeVisible();

		// Scroll down and verify the sticky header remains visible
		await page.evaluate(() => window.scrollBy(0, 400));
		await expect(header).toBeVisible();
	});
});

// ── Skip-to-content link ───────────────────────────────────────────────────────

test.describe('Share page - accessibility', () => {
	test('skip-to-content link is visible on focus', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		// The skip link sits in the layout; it is sr-only until focused
		const skipLink = page.locator('a[href="#main-content"]');
		await expect(skipLink).toBeAttached();

		// Tab to focus it — it should become visible
		await page.keyboard.press('Tab');
		await expect(skipLink).toBeVisible();
	});

	test('page title reflects session title', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		await expect(page).toHaveTitle(/Q1 2025 Market Analysis/);
	});

	test('report heading is rendered as h1', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const h1 = page.locator('h1');
		await expect(h1).toContainText('Q1 2025 Market Analysis');
	});

	test('table of contents nav has accessible label', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		// The session has 3 headings, so TOC should be rendered
		const nav = page.locator('nav[aria-label="Table of contents"]');
		await expect(nav).toBeVisible();
	});
});

// ── Copy link ──────────────────────────────────────────────────────────────────

test.describe('Share page - copy link', () => {
	test('copy link button shows "Copied!" after success', async ({ page, context }) => {
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const copyBtn = page.locator('button', { hasText: 'Copy link' });
		await expect(copyBtn).toBeVisible();
		await copyBtn.click();

		await expect(copyBtn).toContainText('Copied!');
		// Text reverts after ~2s
		await expect(copyBtn).toContainText('Copy link', { timeout: 4000 });
	});

	test('copy link button shows "Failed to copy" when clipboard is denied', async ({ page }) => {
		// Deny clipboard permissions so navigator.clipboard.writeText throws
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		// Override clipboard.writeText to reject
		await page.evaluate(() => {
			Object.defineProperty(navigator, 'clipboard', {
				value: {
					writeText: () => Promise.reject(new Error('Clipboard denied')),
				},
				configurable: true,
			});
		});

		const copyBtn = page.locator('button', { hasText: 'Copy link' });
		await copyBtn.click();

		await expect(copyBtn).toContainText('Failed to copy');
		await expect(copyBtn).toContainText('Copy link', { timeout: 4000 });
	});
});

// ── Comments drawer ────────────────────────────────────────────────────────────

test.describe('Share page - comments drawer (desktop)', () => {
	test('comments button is visible for authenticated team-shared session', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await expect(commentsBtn).toBeVisible();
	});

	test('comments sidebar opens on desktop when comments button is clicked', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		// Initially no sidebar
		const sidebar = page.locator('aside.hidden.md\\:block').first();
		await expect(sidebar).not.toBeVisible();

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await commentsBtn.click();

		// Sidebar should now be visible
		await expect(sidebar).toBeVisible();
	});

	test('comments button is hidden for unauthenticated users', async ({ page }) => {
		await mockUnauthenticatedSharePage(page, { ...mockSession, visibility: 'public', is_public: true });
		await page.goto(`/share/${SESSION_ID}`);

		// The comments button requires both $currentUser and visibility === 'team'
		const commentsBtn = page.locator('button[aria-label*="comments"]');
		await expect(commentsBtn).toHaveCount(0);
	});
});

test.describe('Share page - comments drawer (mobile)', () => {
	test.use({ viewport: { width: 390, height: 844 } });

	test('comments drawer opens as slide-over on mobile', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await commentsBtn.click();

		// Mobile drawer should be present (role=dialog)
		const drawer = page.locator('[role="dialog"][aria-label="Comments"]');
		await expect(drawer).toBeVisible();
	});

	test('mobile comments drawer closes on Escape key', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await commentsBtn.click();

		const drawer = page.locator('[role="dialog"][aria-label="Comments"]');
		await expect(drawer).toBeVisible();

		await page.keyboard.press('Escape');
		await expect(drawer).not.toBeVisible();
	});

	test('mobile comments drawer closes when backdrop is clicked', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await commentsBtn.click();

		const drawer = page.locator('[role="dialog"][aria-label="Comments"]');
		await expect(drawer).toBeVisible();

		// Click the backdrop (aria-hidden overlay)
		const backdrop = drawer.locator('[aria-hidden="true"]').first();
		await backdrop.click();

		await expect(drawer).not.toBeVisible();
	});

	test('mobile comments drawer has close button', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const commentsBtn = page.locator('button[aria-label*="comments"]').first();
		await commentsBtn.click();

		const drawer = page.locator('[role="dialog"][aria-label="Comments"]');
		const closeBtn = drawer.locator('button[aria-label="Close comments"]');
		await expect(closeBtn).toBeVisible();

		await closeBtn.click();
		await expect(drawer).not.toBeVisible();
	});
});

// ── Diff mode ──────────────────────────────────────────────────────────────────

test.describe('Share page - diff mode', () => {
	const sessionWithParent = {
		...mockSession,
		parent_session_id: 'parent-session-abc',
	};

	test('side-by-side diff button is hidden on mobile viewport', async ({ page }) => {
		test.use({ viewport: { width: 390, height: 844 } });

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
				body: JSON.stringify(sessionWithParent),
			}),
		);
		await page.route(`/api/sessions/${SESSION_ID}/comments`, (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
		);
		await page.route(`/api/sessions/${SESSION_ID}/diff`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					current_markdown: '## New\n\nNew content.',
					previous_markdown: '## Old\n\nOld content.',
					previous_date: '2024-12-01T00:00:00Z',
				}),
			}),
		);

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/share/${SESSION_ID}`);

		// Trigger diff load
		const compareBtn = page.locator('button', { hasText: /Compare with previous/i });
		await expect(compareBtn).toBeVisible();
		await compareBtn.click();

		// "Side by side" button should not be present on mobile
		const sideBtn = page.locator('button', { hasText: 'Side by side' });
		await expect(sideBtn).toHaveCount(0);
	});

	test('unified diff mode button is active by default when diff loads', async ({ page }) => {
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
				body: JSON.stringify(sessionWithParent),
			}),
		);
		await page.route(`/api/sessions/${SESSION_ID}/comments`, (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
		);
		await page.route(`/api/sessions/${SESSION_ID}/diff`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					current_markdown: '## New\n\nNew content.',
					previous_markdown: '## Old\n\nOld content.',
					previous_date: '2024-12-01T00:00:00Z',
				}),
			}),
		);

		await page.goto(`/share/${SESSION_ID}`);

		const compareBtn = page.locator('button', { hasText: /Compare with previous/i });
		await compareBtn.click();

		// Unified button should be styled as active
		const unifiedBtn = page.locator('button', { hasText: 'Unified' });
		await expect(unifiedBtn).toBeVisible();
		await expect(unifiedBtn).toHaveClass(/border-gold/);
	});
});

// ── Report content ─────────────────────────────────────────────────────────────

test.describe('Share page - report content', () => {
	test('report markdown is rendered inside article element', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const article = page.locator('article.prose');
		await expect(article).toBeVisible();
		await expect(article).toContainText('Executive Summary');
	});

	test('public badge is shown for public sessions', async ({ page }) => {
		await page.route('/api/auth/me', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ ...mockUser, theme: 'dark' }),
			}),
		);
		await page.route(`/api/share/${mockSessionPublic.id}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockSessionPublic),
			}),
		);
		await page.route(`/api/sessions/${mockSessionPublic.id}/comments`, (route) =>
			route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
		);

		await page.goto(`/share/${mockSessionPublic.id}`);

		// Public badge text
		const badge = page.locator('text=Public');
		await expect(badge).toBeVisible();
	});

	test('team-only badge is shown for private sessions', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const badge = page.locator('text=Team only');
		await expect(badge).toBeVisible();
	});

	test('reading time is displayed', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const readTime = page.locator('text=/\\d+ min read/');
		await expect(readTime).toBeVisible();
	});

	test('download buttons are visible when report has content', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		await expect(page.locator('button', { hasText: 'Download PDF' })).toBeVisible();
		await expect(page.locator('button', { hasText: 'Download .md' })).toBeVisible();
		await expect(page.locator('a', { hasText: 'Download DOCX' })).toBeVisible();
	});
});

// ── Subscribe / Fork controls ─────────────────────────────────────────────────

test.describe('Share page - subscribe and fork', () => {
	test('subscribe bell is visible for authenticated team sessions', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const bellBtn = page.locator('button[aria-label*="Subscribe"]');
		await expect(bellBtn).toBeVisible();
	});

	test('fork button is visible when user is authenticated', async ({ page }) => {
		await mockAuthenticatedSharePage(page);
		await page.goto(`/share/${SESSION_ID}`);

		const forkBtn = page.locator('button', { hasText: /Fork/i });
		await expect(forkBtn).toBeVisible();
	});
});
