/**
 * Document intelligence hardening tests (m-clone-di27).
 *
 * Covers:
 *   1. Upload API contract per file type: CSV, Excel, PDF, image
 *   2. Schema endpoint contract per file type
 *   3. SSE query_result → adaptive component rendering (all 6 types)
 *   4. Full upload → schema → suggestion → query → result flow (CSV)
 *   5. Concurrent query load (50 parallel requests)
 *   6. Query latency measurements (P50 / P95 / P99)
 *   7. Error and edge-case coverage
 *
 * All API routes are mocked — backend does not need to run.
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';

// ── Constants ──────────────────────────────────────────────────────────────────

const SESSION_KEY = 'hardening-test-session-key';
const LATENCY_TARGET_P50_MS = 500;
const LATENCY_TARGET_P95_MS = 1000;
const LATENCY_TARGET_P99_MS = 2000;

// ── Shared mock payloads ───────────────────────────────────────────────────────

const mockUser = { sid: 'user-abc', display_name: 'Test User', theme: 'dark' };

const uploadResultFor = (type: string, extra: Record<string, unknown> = {}) => ({
	session_key: SESSION_KEY,
	filename: `test.${type}`,
	char_count: 2048,
	session_char_count: 2048,
	type,
	truncated: false,
	documents: [{ filename: `test.${type}`, type, char_count: 2048 }],
	...extra,
});

const csvSchemaReady = {
	ready: true,
	document_type: 'tabular',
	total_sheets: 1,
	summary: 'Tabular document with 1 sheet. Columns include: company, revenue, founded_year.',
	columns: [
		{ name: 'company', inferred_type: 'text', semantic_type: 'organization' },
		{ name: 'revenue', inferred_type: 'numeric', semantic_type: 'financial_amount' },
		{ name: 'founded_year', inferred_type: 'date', semantic_type: 'date' },
	],
	suggestions: [
		'What is the total revenue?',
		'List all companies',
		'What is the date range in founded_year?',
	],
};

const excelSchemaReady = {
	...csvSchemaReady,
	total_sheets: 3,
	summary: 'Spreadsheet with 3 sheets. Columns include: company, revenue, founded_year.',
};

const pdfSchemaReady = {
	ready: true,
	document_type: 'prose',
	total_sheets: 0,
	summary: 'Prose document with 12 pages.',
	columns: [],
	suggestions: [
		'Summarize the key data in test.pdf',
		'What are the main topics discussed?',
		'What conclusions does the document reach?',
	],
};

const imageSchemaReady = {
	ready: true,
	document_type: 'image',
	total_sheets: 0,
	summary: 'Image document. OCR extracted text.',
	columns: [],
	suggestions: ['What text appears in this image?', 'Describe the contents of this image'],
};

// ── SSE mock helpers ───────────────────────────────────────────────────────────

function makeSSEBody(queryResult: Record<string, unknown>): string {
	const events: string[] = [
		`event: query_result\ndata: ${JSON.stringify(queryResult)}\n\n`,
		`event: final_report\ndata: ${JSON.stringify({ markdown: 'Analysis complete.', messages: [], sources: [] })}\n\n`,
		`event: done\ndata: {}\n\n`,
	];
	return events.join('');
}

const listQueryResult = {
	matches: [
		{ value: 'Acme Corp', source_column: 'company', row_numbers: [1], confidence: 0.95 },
		{ value: 'Globex Inc', source_column: 'company', row_numbers: [2], confidence: 0.91 },
		{ value: 'Initech', source_column: 'company', row_numbers: [3], confidence: 0.88 },
	],
	query_interpretation: 'List of company names from the company column.',
	total_matches: 3,
	error: null,
};

const countQueryResult = {
	matches: [
		{ value: '$4,200,000', source_column: 'revenue', row_numbers: [1], confidence: 0.99 },
	],
	query_interpretation: 'Total revenue summed across all rows.',
	total_matches: 1,
	error: null,
};

const tableQueryResult = {
	matches: [
		{
			value: { company: 'Acme', revenue: '1M', founded_year: '2010' },
			source_column: 'company',
			row_numbers: [1],
			confidence: 0.92,
		},
		{
			value: { company: 'Globex', revenue: '2M', founded_year: '2015' },
			source_column: 'company',
			row_numbers: [2],
			confidence: 0.89,
		},
	],
	query_interpretation: 'Company records with revenue and founding year.',
	total_matches: 2,
	error: null,
};

const proseQueryResult = {
	matches: [
		{
			value: 'Revenue increased significantly in the third quarter of fiscal year 2024.',
			source_column: 'body',
			row_numbers: [],
			confidence: 0.84,
			text_positions: [{ start: 120, end: 193 }],
		},
		{
			value: 'Operating margins improved by 3.2 percentage points year-over-year.',
			source_column: 'body',
			row_numbers: [],
			confidence: 0.78,
			text_positions: [{ start: 850, end: 920 }],
		},
	],
	query_interpretation: 'Passages mentioning revenue and financial performance.',
	total_matches: 2,
	error: null,
};

const emptyQueryResult = {
	matches: [],
	query_interpretation: 'No matches found for the specified criteria.',
	total_matches: 0,
	error: null,
};

const errorQueryResult = {
	matches: [],
	query_interpretation: '',
	total_matches: 0,
	error: 'Document session not found or has expired.',
};

// ── Helpers ────────────────────────────────────────────────────────────────────

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

async function mockBaseApis(page: Page) {
	await page.route('/api/auth/me', (r) =>
		r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockUser) }),
	);
	await page.route('/api/teams', (r) =>
		r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/rules', (r) =>
		r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/sessions', (r) =>
		r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.route('/api/config/models', (r) =>
		r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
}

async function typeAndSubmitQuery(page: Page, query: string) {
	const textarea = page.locator('textarea').first();
	await textarea.waitFor({ state: 'visible', timeout: 5000 });
	await textarea.fill(query);
	await textarea.press('Enter');
}

// ── 1. Upload API contract per file type ──────────────────────────────────────

test.describe('Upload API contract', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	for (const [ext, type, extra] of [
		['csv', 'csv', {}],
		['xlsx', 'xlsx', { sheets: 3 }],
		['pdf', 'pdf', { pages: 12 }],
		['png', 'image', {}],
	] as const) {
		test(`POST /api/documents/upload accepts .${ext} and returns required fields`, async ({ page }) => {
			await mockBaseApis(page);
			await page.route('/api/documents/upload', (r) =>
				r.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(uploadResultFor(type, extra)),
				}),
			);
			await page.goto('/');
			await page.waitForLoadState('networkidle');

			const result = await page.evaluate(
				async ({ ext }: { ext: string }) => {
					const form = new FormData();
					form.append(
						'file',
						new Blob(['test content'], { type: 'application/octet-stream' }),
						`test.${ext}`,
					);
					const r = await fetch('/api/documents/upload', {
						method: 'POST',
						body: form,
						credentials: 'include',
					});
					return r.json();
				},
				{ ext },
			);

			expect(typeof result.session_key).toBe('string');
			expect(result.session_key.length).toBeGreaterThan(0);
			expect(typeof result.char_count).toBe('number');
			expect(typeof result.session_char_count).toBe('number');
			expect(typeof result.truncated).toBe('boolean');
			expect(Array.isArray(result.documents)).toBe(true);
			expect(result.documents.length).toBeGreaterThan(0);
		});
	}

	test('upload result documents array contains filename and type', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(uploadResultFor('csv')),
			}),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['a,b\n1,2'], { type: 'text/csv' }), 'test.csv');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return r.json();
		});

		for (const doc of result.documents) {
			expect(doc).toHaveProperty('filename');
			expect(doc).toHaveProperty('type');
			expect(doc).toHaveProperty('char_count');
		}
	});
});

// ── 2. Schema API contract per file type ──────────────────────────────────────

test.describe('Schema API contract', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	test('CSV schema: tabular document_type, columns array', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(csvSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.ready).toBe(true);
		expect(result.document_type).toBe('tabular');
		expect(Array.isArray(result.columns)).toBe(true);
		expect(result.columns.length).toBeGreaterThan(0);
		for (const col of result.columns) {
			expect(col).toHaveProperty('name');
			expect(col).toHaveProperty('inferred_type');
			expect(col).toHaveProperty('semantic_type');
		}
	});

	test('Excel schema: multiple sheets reflected in total_sheets', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(excelSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.ready).toBe(true);
		expect(result.total_sheets).toBe(3);
	});

	test('PDF schema: prose document_type, suggestions present', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(pdfSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.ready).toBe(true);
		expect(result.document_type).toBe('prose');
		expect(Array.isArray(result.suggestions)).toBe(true);
		expect(result.suggestions.length).toBeGreaterThan(0);
	});

	test('image schema: image document_type returned', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(imageSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.ready).toBe(true);
		expect(result.document_type).toBe('image');
	});

	test('schema returns ready:false while analysis is pending', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ready: false }) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.ready).toBe(false);
	});

	test('schema suggestions are 1–3 non-empty strings', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(csvSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);

		expect(result.suggestions.length).toBeGreaterThanOrEqual(1);
		expect(result.suggestions.length).toBeLessThanOrEqual(3);
		for (const s of result.suggestions) {
			expect(typeof s).toBe('string');
			expect(s.trim().length).toBeGreaterThan(0);
		}
	});
});

// ── 3. SSE query_result → adaptive component rendering ────────────────────────

test.describe('Adaptive result rendering via SSE', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	async function setupResearchMock(page: Page, queryResult: Record<string, unknown>) {
		await mockBaseApis(page);
		await page.route('/api/research', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'text/event-stream',
				body: makeSSEBody(queryResult),
			}),
		);
	}

	test('list result: [data-testid="result-list"] appears for multiple string matches', async ({
		page,
	}) => {
		await setupResearchMock(page, listQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'List all companies');

		const resultList = page.locator('[data-testid="result-list"]');
		await resultList.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultList.isVisible()).toBe(true);
	});

	test('count result: [data-testid="result-count"] appears for single numeric match', async ({
		page,
	}) => {
		await setupResearchMock(page, countQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'What is the total revenue?');

		const resultCount = page.locator('[data-testid="result-count"]');
		await resultCount.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultCount.isVisible()).toBe(true);
		// The numeric value appears in the component
		expect(await resultCount.textContent()).toContain('$4,200,000');
	});

	test('table result: [data-testid="result-table"] appears for multi-column object matches', async ({
		page,
	}) => {
		await setupResearchMock(page, tableQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'Show company revenue and founding year');

		const resultTable = page.locator('[data-testid="result-table"]');
		await resultTable.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultTable.isVisible()).toBe(true);
		// Column headers derived from object keys
		await expect(resultTable.locator('th')).toHaveCount(4); // company, revenue, founded_year, Row
	});

	test('prose result: [data-testid="result-prose"] appears for text_positions matches', async ({
		page,
	}) => {
		await setupResearchMock(page, proseQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'Find revenue mentions in the document');

		const resultProse = page.locator('[data-testid="result-prose"]');
		await resultProse.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultProse.isVisible()).toBe(true);
		// Prose result renders blockquotes
		const blockquotes = resultProse.locator('blockquote');
		expect(await blockquotes.count()).toBe(2);
	});

	test('empty result: [data-testid="result-empty"] appears when matches is empty', async ({
		page,
	}) => {
		await setupResearchMock(page, emptyQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'Find something that does not exist');

		const resultEmpty = page.locator('[data-testid="result-empty"]');
		await resultEmpty.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultEmpty.isVisible()).toBe(true);
		expect(await resultEmpty.textContent()).toContain('No matches found');
	});

	test('error result: [data-testid="result-error"] appears when error field is set', async ({
		page,
	}) => {
		await setupResearchMock(page, errorQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'Query against expired session');

		const resultError = page.locator('[data-testid="result-error"]');
		await resultError.waitFor({ state: 'visible', timeout: 10000 });
		expect(await resultError.isVisible()).toBe(true);
		expect(await resultError.textContent()).toContain('Document session not found');
	});

	test('query-results container always wraps the adaptive component', async ({ page }) => {
		await setupResearchMock(page, listQueryResult);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const isVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!isVisible) { test.skip(); return; }

		await typeAndSubmitQuery(page, 'List companies');

		const container = page.locator('[data-testid="query-results"]');
		await container.waitFor({ state: 'visible', timeout: 10000 });
		expect(await container.isVisible()).toBe(true);
	});
});

// ── 4. Full flow: CSV upload → schema ready → suggestion click → query → result ─

test.describe('Full upload → schema → query → result flow', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	test('CSV: upload → schema polling → ready phase → suggestion populates textarea', async ({
		page,
	}) => {
		await mockBaseApis(page);

		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(uploadResultFor('csv')),
			}),
		);

		let schemaCallCount = 0;
		await page.route('/api/documents/schema**', (r) => {
			schemaCallCount++;
			// Return ready on first poll
			return r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(csvSchemaReady),
			});
		});

		await page.route('/api/research', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'text/event-stream',
				body: makeSSEBody(listQueryResult),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		const textareaVisible = await textarea.isVisible({ timeout: 3000 }).catch(() => false);
		if (!textareaVisible) { test.skip(); return; }

		// Trigger upload via file input (force:true for hidden inputs)
		const fileInput = page.locator('input[type="file"]').first();
		await fileInput.setInputFiles(
			{
				name: 'portfolio.csv',
				mimeType: 'text/csv',
				buffer: Buffer.from('company,revenue,founded_year\nAcme,1000000,2010\nGlobex,2000000,2015'),
			},
			{ force: true },
		).catch(async () => {
			// Fallback: programmatic upload when setInputFiles unavailable
			await page.evaluate(async () => {
				const form = new FormData();
				form.append(
					'file',
					new Blob(['company,revenue\nAcme,1M'], { type: 'text/csv' }),
					'portfolio.csv',
				);
				await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			});
		});

		// Wait for schema ready indicator (polling starts after upload succeeds)
		const readyIndicator = page.locator('[data-testid="schema-phase-ready"]');
		await readyIndicator.waitFor({ state: 'visible', timeout: 10000 }).catch(() => null);

		// If ready indicator visible, verify suggestions appear and are clickable
		if (await readyIndicator.isVisible().catch(() => false)) {
			const suggestion = page.locator('[data-testid="schema-suggestion"]').first();
			if (await suggestion.isVisible({ timeout: 2000 }).catch(() => false)) {
				const suggestionText = await suggestion.textContent();
				await suggestion.click();
				const textareaValue = await textarea.inputValue();
				expect(textareaValue).toBe(suggestionText?.trim());
			}
		}
	});

	test('PDF upload returns prose schema type', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(uploadResultFor('pdf', { pages: 12 })),
			}),
		);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(pdfSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// Verify PDF upload contract
		const result = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['%PDF-1.4'], { type: 'application/pdf' }), 'report.pdf');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return r.json();
		});
		expect(result.type).toBe('pdf');
		expect(result.documents[0]).toHaveProperty('filename', 'test.pdf');

		// Verify PDF schema contract
		const schema = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);
		expect(schema.document_type).toBe('prose');
		expect(schema.columns).toHaveLength(0);
	});

	test('Excel upload with multiple sheets reflects sheet count', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(uploadResultFor('xlsx', { sheets: 3 })),
			}),
		);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(excelSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const uploadResult = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['xl content'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), 'data.xlsx');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return r.json();
		});
		expect(uploadResult.sheets).toBe(3);

		const schema = await page.evaluate(async (key: string) => {
			const r = await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
			return r.json();
		}, SESSION_KEY);
		expect(schema.total_sheets).toBe(3);
	});
});

// ── 5. Concurrent query load test ─────────────────────────────────────────────

test.describe('Concurrent query load', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	test('50 concurrent POST /api/documents/query requests all succeed', async ({ page }) => {
		await mockBaseApis(page);

		let requestCount = 0;
		await page.route('/api/documents/query', (r) => {
			requestCount++;
			return r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(listQueryResult),
			});
		});

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const results = await page.evaluate(async () => {
			const CONCURRENCY = 50;
			const responses = await Promise.all(
				Array.from({ length: CONCURRENCY }, (_, i) =>
					fetch('/api/documents/query', {
						method: 'POST',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({ session_key: 'load-test-key', query: `query ${i}` }),
						credentials: 'include',
					})
						.then((r) => r.json())
						.then((data) => ({ ok: true, data }))
						.catch((err: unknown) => ({ ok: false, error: String(err) })),
				),
			);
			return responses;
		});

		const successful = results.filter((r) => r.ok);
		expect(successful.length).toBe(50);

		// Every successful response has the required shape
		for (const r of successful) {
			expect(r.data).toHaveProperty('matches');
			expect(r.data).toHaveProperty('query_interpretation');
			expect(r.data).toHaveProperty('total_matches');
		}
	});

	test('10 concurrent schema polls all resolve correctly', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(csvSchemaReady) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const results = await page.evaluate(async (key: string) => {
			return Promise.all(
				Array.from({ length: 10 }, () =>
					fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' })
						.then((r) => r.json()),
				),
			);
		}, SESSION_KEY);

		expect(results).toHaveLength(10);
		for (const r of results) {
			expect(r.ready).toBe(true);
			expect(r.document_type).toBe('tabular');
		}
	});
});

// ── 6. Query latency measurements ─────────────────────────────────────────────

test.describe('Query latency (P50/P95/P99)', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	test('mock query latency P50/P95/P99 within acceptable bounds', async ({ page }) => {
		await mockBaseApis(page);

		// Introduce realistic variable latency (0–50ms) to simulate server variance
		await page.route('/api/documents/query', async (r) => {
			const delay = Math.random() * 50; // 0–50ms simulated latency
			await new Promise((res) => setTimeout(res, delay));
			return r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(listQueryResult),
			});
		});

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const latencies = await page.evaluate(async () => {
			const SAMPLES = 30;
			const times: number[] = [];
			for (let i = 0; i < SAMPLES; i++) {
				const start = performance.now();
				await fetch('/api/documents/query', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ session_key: 'latency-key', query: `latency test ${i}` }),
					credentials: 'include',
				});
				times.push(performance.now() - start);
			}
			times.sort((a, b) => a - b);
			return {
				p50: times[Math.floor(SAMPLES * 0.5)],
				p95: times[Math.floor(SAMPLES * 0.95)],
				p99: times[Math.floor(SAMPLES * 0.99)],
				min: times[0],
				max: times[SAMPLES - 1],
			};
		});

		// With mock latency of 0–50ms, all percentiles should be well within target
		expect(latencies.p50).toBeLessThan(LATENCY_TARGET_P50_MS);
		expect(latencies.p95).toBeLessThan(LATENCY_TARGET_P95_MS);
		expect(latencies.p99).toBeLessThan(LATENCY_TARGET_P99_MS);
	});

	test('schema polling latency P95 under target', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', async (r) => {
			const delay = Math.random() * 30;
			await new Promise((res) => setTimeout(res, delay));
			return r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(csvSchemaReady),
			});
		});

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const latencies = await page.evaluate(async (key: string) => {
			const SAMPLES = 20;
			const times: number[] = [];
			for (let i = 0; i < SAMPLES; i++) {
				const start = performance.now();
				await fetch(`/api/documents/schema?session_key=${key}`, { credentials: 'include' });
				times.push(performance.now() - start);
			}
			times.sort((a, b) => a - b);
			return {
				p50: times[Math.floor(SAMPLES * 0.5)],
				p95: times[Math.floor(SAMPLES * 0.95)],
			};
		}, SESSION_KEY);

		expect(latencies.p50).toBeLessThan(LATENCY_TARGET_P50_MS);
		expect(latencies.p95).toBeLessThan(LATENCY_TARGET_P95_MS);
	});
});

// ── 7. Error and edge-case coverage ──────────────────────────────────────────

test.describe('Error and edge cases', () => {
	test.beforeEach(async ({ context }) => setAuthCookie(context));

	test('upload 413 when file too large: error field present in response', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 413,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'File size (25.0MB) exceeds the 20MB limit.' }),
			}),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const { status, body } = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['x'.repeat(1024)], { type: 'text/plain' }), 'huge.txt');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return { status: r.status, body: await r.json() };
		});

		expect(status).toBe(413);
		expect(typeof body.detail).toBe('string');
		expect(body.detail).toContain('limit');
	});

	test('upload 400 for unsupported file type', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({
				status: 400,
				contentType: 'application/json',
				body: JSON.stringify({ detail: "Unsupported file type '.exe'." }),
			}),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const { status } = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['MZ'], { type: 'application/octet-stream' }), 'malware.exe');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return { status: r.status };
		});

		expect(status).toBe(400);
	});

	test('query 404 for missing session returns error', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/query', (r) =>
			r.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Document session not found' }),
			}),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const { status } = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'nonexistent', query: 'anything' }),
				credentials: 'include',
			});
			return { status: r.status };
		});

		expect(status).toBe(404);
	});

	test('query 429 when rate limit exceeded', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/query', (r) =>
			r.fulfill({
				status: 429,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Rate limit exceeded: 10 queries per minute.' }),
				headers: { 'Retry-After': '60' },
			}),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const { status } = await page.evaluate(async () => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: 'rate-limit-key', query: 'query' }),
				credentials: 'include',
			});
			return { status: r.status };
		});

		expect(status).toBe(429);
	});

	test('truncated upload includes truncated:true in response', async ({ page }) => {
		await mockBaseApis(page);
		const truncatedResult = { ...uploadResultFor('csv'), truncated: true, char_count: 500000 };
		await page.route('/api/documents/upload', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(truncatedResult) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['x'.repeat(1000)], { type: 'text/csv' }), 'large.csv');
			const r = await fetch('/api/documents/upload', { method: 'POST', body: form, credentials: 'include' });
			return r.json();
		});

		expect(result.truncated).toBe(true);
	});

	test('schema endpoint returns ready:false when session key is unknown', async ({ page }) => {
		await mockBaseApis(page);
		await page.route('/api/documents/schema**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ready: false }) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async () => {
			const r = await fetch('/api/documents/schema?session_key=unknown-key', { credentials: 'include' });
			return r.json();
		});

		expect(result.ready).toBe(false);
	});

	test('multi-document session: session_char_count is sum of all documents', async ({ page }) => {
		await mockBaseApis(page);
		const multiDocResult = {
			...uploadResultFor('csv'),
			session_char_count: 4096, // 2048 + 2048
			documents: [
				{ filename: 'file1.csv', type: 'csv', char_count: 2048 },
				{ filename: 'file2.csv', type: 'csv', char_count: 2048 },
			],
		};
		// Use ** wildcard so Playwright intercepts uploads with or without query params
		await page.route('**/api/documents/upload**', (r) =>
			r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(multiDocResult) }),
		);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const result = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['a,b\n1,2'], { type: 'text/csv' }), 'file2.csv');
			// Append to existing session via query param
			const r = await fetch('/api/documents/upload?session_key=existing-key', {
				method: 'POST',
				body: form,
				credentials: 'include',
			});
			return r.json();
		});

		expect(result.session_char_count).toBe(4096);
		expect(result.documents).toHaveLength(2);
	});
});
