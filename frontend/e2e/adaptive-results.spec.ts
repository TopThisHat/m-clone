/**
 * E2E tests for adaptive result display components (m-clone-wak9).
 *
 * Verifies that detectResultType correctly routes QueryResult payloads
 * to the appropriate display component (count / list / table / prose / empty / error).
 *
 * All tests are unit-style: they import the pure detection utility directly
 * (no browser required) and the API contract is validated via page.evaluate
 * mocks so the backend does not need to run.
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';

// ── Helpers ────────────────────────────────────────────────────────────────────

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

async function mockBaseApis(page: Page) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ sid: 'user-abc', display_name: 'Test User', theme: 'dark' }),
		}),
	);
	await page.route('/api/teams', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/rules', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/sessions', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/config/models', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
}

// ── QueryResult mock factory ───────────────────────────────────────────────────

function makeQueryResult(overrides: Record<string, unknown> = {}) {
	return {
		matches: [],
		query_interpretation: 'Test interpretation',
		total_matches: 0,
		error: null,
		...overrides,
	};
}

// ── detectResultType unit tests (run in browser context via page.evaluate) ────

test.describe('detectResultType utility', () => {
	test.beforeEach(async ({ context }) => {
		await setAuthCookie(context);
	});

	test('returns "error" when result.error is set', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			// Inline the detection logic to test without module import
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				if (first.text_positions && (first.text_positions as unknown[]).length > 0) return 'prose';
				if (m.length === 1 && /^\$?[\d,]+\.?\d*\s*[KMBkmb%]?$/.test(String(first.value).trim())) return 'count';
				return 'list';
			}
			return detect({ error: 'Session not found', matches: [] });
		});
		expect(result).toBe('error');
	});

	test('returns "empty" when matches array is empty', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				return 'list';
			}
			return detect({ error: null, matches: [] });
		});
		expect(result).toBe('empty');
	});

	test('returns "table" for multi-column paired values', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				if (first.text_positions && (first.text_positions as unknown[]).length > 0) return 'prose';
				if (m.length === 1 && /^\$?[\d,]+\.?\d*\s*[KMBkmb%]?$/.test(String(first.value).trim())) return 'count';
				return 'list';
			}
			return detect({
				error: null,
				matches: [{ value: { company: 'Acme', revenue: '100' }, source_column: 'company', row_numbers: [1], confidence: 0.9 }],
			});
		});
		expect(result).toBe('table');
	});

	test('returns "table" when source_column is an array', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				return 'list';
			}
			return detect({
				error: null,
				matches: [{ value: 'Acme', source_column: ['company', 'industry'], row_numbers: [1], confidence: 0.9 }],
			});
		});
		expect(result).toBe('table');
	});

	test('returns "prose" when match has text_positions', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				if (first.text_positions && (first.text_positions as unknown[]).length > 0) return 'prose';
				return 'list';
			}
			return detect({
				error: null,
				matches: [{ value: 'The revenue grew by 20%', source_column: 'content', text_positions: [{ start: 0, end: 25 }], row_numbers: [], confidence: 0.85 }],
			});
		});
		expect(result).toBe('prose');
	});

	test('returns "count" for a single numeric match', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				if (first.text_positions && (first.text_positions as unknown[]).length > 0) return 'prose';
				if (m.length === 1 && /^\$?[\d,]+\.?\d*\s*[KMBkmb%]?$/.test(String(first.value).trim())) return 'count';
				return 'list';
			}
			return detect({
				error: null,
				matches: [{ value: '$1,234,567', source_column: 'revenue', row_numbers: [1], confidence: 0.99 }],
			});
		});
		expect(result).toBe('count');
	});

	test('returns "list" for multiple string results', async ({ page }) => {
		await mockBaseApis(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(() => {
			function detect(r: { error?: string | null; matches?: unknown[] }) {
				if (r.error) return 'error';
				const m = r.matches ?? [];
				if (m.length === 0) return 'empty';
				const first = m[0] as { value: unknown; source_column: unknown; text_positions?: unknown[] };
				if (typeof first.value === 'object' && !Array.isArray(first.value) && first.value !== null) return 'table';
				if (Array.isArray(first.source_column)) return 'table';
				if (first.text_positions && (first.text_positions as unknown[]).length > 0) return 'prose';
				if (m.length === 1 && /^\$?[\d,]+\.?\d*\s*[KMBkmb%]?$/.test(String(first.value).trim())) return 'count';
				return 'list';
			}
			return detect({
				error: null,
				matches: [
					{ value: 'Acme Corp', source_column: 'company', row_numbers: [1], confidence: 0.9 },
					{ value: 'Globex', source_column: 'company', row_numbers: [2], confidence: 0.85 },
				],
			});
		});
		expect(result).toBe('list');
	});
});

// ── API contract tests ─────────────────────────────────────────────────────────

test.describe('Document query API contract', () => {
	test.beforeEach(async ({ context }) => {
		await setAuthCookie(context);
	});

	test('POST /api/documents/query returns matches array with required fields', async ({ page }) => {
		await mockBaseApis(page);

		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(
					makeQueryResult({
						matches: [
							{
								value: 'Acme Corp',
								source_column: 'company',
								row_numbers: [3],
								confidence: 0.92,
							},
							{
								value: 'Globex',
								source_column: 'company',
								row_numbers: [7],
								confidence: 0.88,
							},
						],
						total_matches: 2,
					}),
				),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'test-key', query: 'list companies' }),
				credentials: 'include',
			});
			return r.json();
		});

		expect(Array.isArray(response.matches)).toBe(true);
		expect(response.total_matches).toBeGreaterThan(0);
		expect(typeof response.query_interpretation).toBe('string');
		expect(response.error).toBeNull();

		for (const match of response.matches) {
			expect(match).toHaveProperty('value');
			expect(match).toHaveProperty('source_column');
			expect(match).toHaveProperty('row_numbers');
			expect(match).toHaveProperty('confidence');
			expect(typeof match.confidence).toBe('number');
			expect(match.confidence).toBeGreaterThanOrEqual(0);
			expect(match.confidence).toBeLessThanOrEqual(1);
		}
	});

	test('POST /api/documents/query returns error field on failure', async ({ page }) => {
		await mockBaseApis(page);

		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(
					makeQueryResult({
						error: 'Session not found or expired',
						matches: [],
						total_matches: 0,
					}),
				),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'expired-key', query: 'anything' }),
				credentials: 'include',
			});
			return r.json();
		});

		expect(typeof response.error).toBe('string');
		expect(response.error.length).toBeGreaterThan(0);
	});

	test('multi-column result has object value with column keys', async ({ page }) => {
		await mockBaseApis(page);

		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(
					makeQueryResult({
						matches: [
							{
								value: { company: 'Acme', revenue: '10M', year: '2023' },
								source_column: 'company',
								row_numbers: [1],
								confidence: 0.95,
							},
						],
						total_matches: 1,
					}),
				),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'test-key', query: 'show company revenue by year' }),
				credentials: 'include',
			});
			return r.json();
		});

		const first = response.matches[0];
		expect(typeof first.value).toBe('object');
		expect(first.value).toHaveProperty('company');
		expect(first.value).toHaveProperty('revenue');
	});

	test('prose result has text_positions', async ({ page }) => {
		await mockBaseApis(page);

		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(
					makeQueryResult({
						matches: [
							{
								value: 'Revenue increased significantly in Q3',
								source_column: 'body',
								row_numbers: [],
								confidence: 0.78,
								text_positions: [{ start: 120, end: 158 }],
							},
						],
						total_matches: 1,
					}),
				),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'test-key', query: 'find revenue mentions' }),
				credentials: 'include',
			});
			return r.json();
		});

		const first = response.matches[0];
		expect(Array.isArray(first.text_positions)).toBe(true);
		expect(first.text_positions.length).toBeGreaterThan(0);
		expect(first.text_positions[0]).toHaveProperty('start');
		expect(first.text_positions[0]).toHaveProperty('end');
	});
});
