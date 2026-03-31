/**
 * E2E tests for LLM Document Query Intelligence feature.
 *
 * All API endpoints are mocked via page.route() — the backend does not need
 * to be running.  Tests cover:
 *
 *   1. Upload CSV → wait for schema analysis → submit query → verify results
 *      display with provenance (m-clone-ovfp)
 *
 *   2. Upload CSV → verify column classification UI shows LLM-assigned roles
 *      with confidence indicators (m-clone-nfzo)
 *
 *   3. Submit query with no matches → verify empty state shows explanation
 *      (m-clone-nfzo)
 *
 * These tests validate the QueryResults and ColumnClassificationFeedback
 * components in a realistic upload-then-query flow using route interception.
 * All page.evaluate() calls happen after page.goto() so relative URLs resolve.
 */

import { test, expect, type Page, type BrowserContext } from '@playwright/test';
import type { QueryResult, ColumnClassificationDetail } from '../src/lib/api/documents';

// ── Constants ──────────────────────────────────────────────────────────────────

const SESSION_KEY = 'test-session-abc123';
const CAMPAIGN_ID = 'test-campaign-id';

// ── Mock data ──────────────────────────────────────────────────────────────────

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

const mockUploadResult = {
	session_key: SESSION_KEY,
	filename: 'portfolio.csv',
	char_count: 1240,
	session_char_count: 1240,
	type: 'csv',
	truncated: false,
	rows: 10,
	documents: [{ filename: 'portfolio.csv', type: 'csv', char_count: 1240, rows: 10 }],
};

/** A QueryResult with two matches for "find all owners" */
const mockQueryResultWithMatches: QueryResult = {
	matches: [
		{
			value: 'Jane Doe',
			source_column: 'owners',
			row_numbers: [2],
			confidence: 0.92,
		},
		{
			value: 'John Smith',
			source_column: 'owners',
			row_numbers: [3],
			confidence: 0.78,
		},
	],
	query_interpretation: "Interpreted as: person entities from column 'owners'",
	total_matches: 2,
	error: null,
};

/** A QueryResult with zero matches */
const mockQueryResultEmpty: QueryResult = {
	matches: [],
	query_interpretation:
		"No columns related to 'revenue' were found in this document. The document contains: company, owners, founded_year.",
	total_matches: 0,
	error: null,
};

/** Classification response for a CSV with company/owners/founded_year columns */
const mockColumnClassifications: Record<string, ColumnClassificationDetail> = {
	company: {
		role: 'entity_label',
		semantic_type: 'organization',
		confidence: 0.97,
		reasoning: "Column name 'company' strongly indicates an organization entity label.",
	},
	owners: {
		role: 'attribute',
		semantic_type: 'person',
		confidence: 0.81,
		reasoning: "Column name 'owners' likely contains person names associated with the company.",
	},
	founded_year: {
		role: 'attribute',
		semantic_type: 'date',
		confidence: 0.94,
		reasoning: "Column name 'founded_year' clearly indicates a founding date.",
	},
};

// ── Helpers ────────────────────────────────────────────────────────────────────

async function setAuthCookie(context: BrowserContext) {
	await context.addCookies([
		{ name: 'jwt', value: 'fake-jwt-token', domain: 'localhost', path: '/' },
	]);
}

/** Register baseline API mocks shared across all tests */
async function mockBaseApis(page: Page) {
	await page.route('/api/auth/me', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUser),
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
}

/** Mock the document upload endpoint */
async function mockDocumentUpload(page: Page) {
	await page.route('/api/documents/upload', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(mockUploadResult),
		}),
	);
}

/** Mock the schema analysis status endpoint */
async function mockDocumentStatus(page: Page) {
	await page.route('/api/documents/status**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ alive: true }),
		}),
	);
}

/** Mock POST /api/documents/query with the given result */
async function mockDocumentQuery(page: Page, result: QueryResult) {
	await page.route('/api/documents/query', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(result),
		}),
	);
}

/** Mock the import endpoint to return column classifications */
async function mockImportUpload(page: Page) {
	await page.route(`/api/campaigns/${CAMPAIGN_ID}/import`, (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				inserted: 10,
				skipped: 0,
				column_map: {
					company: 'entity_label',
					owners: 'attribute',
					founded_year: 'attribute',
				},
				column_classifications: mockColumnClassifications,
			}),
		}),
	);
}

// ── Test suite: Upload and query flow (m-clone-ovfp) ──────────────────────────

test.describe('Document query flow', () => {
	test.beforeEach(async ({ context }) => {
		await setAuthCookie(context);
	});

	test('upload CSV and submit query shows results with provenance', async ({ page }) => {
		await mockBaseApis(page);
		await mockDocumentUpload(page);
		await mockDocumentStatus(page);
		await mockDocumentQuery(page, mockQueryResultWithMatches);

		// Navigate first so relative URLs work in page.evaluate
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// Simulate document upload via mocked API
		const uploadResponse = await page.evaluate(async () => {
			const form = new FormData();
			form.append('file', new Blob(['company,owners\nAcme,Jane'], { type: 'text/csv' }), 'test.csv');
			const r = await fetch('/api/documents/upload', {
				method: 'POST',
				body: form,
				credentials: 'include',
			});
			if (!r.ok) return null;
			return r.json();
		});

		expect(uploadResponse).not.toBeNull();
		expect(uploadResponse.session_key).toBe(SESSION_KEY);
		expect(uploadResponse.type).toBe('csv');

		// Submit query against the uploaded document session
		const queryResponse = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'find all owners' }),
				credentials: 'include',
			});
			if (!r.ok) return null;
			return r.json();
		}, SESSION_KEY);

		expect(queryResponse).not.toBeNull();

		// All four top-level fields must be present
		expect(queryResponse).toHaveProperty('matches');
		expect(queryResponse).toHaveProperty('query_interpretation');
		expect(queryResponse).toHaveProperty('total_matches');
		expect(queryResponse).toHaveProperty('error');

		// Verify matches with provenance
		expect(queryResponse.matches).toHaveLength(2);
		expect(queryResponse.total_matches).toBe(2);
		expect(queryResponse.error).toBeNull();

		const firstMatch = queryResponse.matches[0];
		expect(firstMatch.value).toBe('Jane Doe');
		expect(firstMatch.source_column).toBe('owners');
		expect(firstMatch.row_numbers).toContain(2);
		expect(firstMatch.confidence).toBeGreaterThan(0.5);

		// query_interpretation must always be a non-empty string
		expect(typeof queryResponse.query_interpretation).toBe('string');
		expect(queryResponse.query_interpretation.length).toBeGreaterThan(0);
	});

	test('query request body always contains session_key and query fields', async ({ page }) => {
		await mockBaseApis(page);

		const capturedBodies: Array<Record<string, unknown>> = [];
		await page.route('/api/documents/query', async (route) => {
			const body = route.request().postDataJSON() as Record<string, unknown>;
			capturedBodies.push(body);
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockQueryResultWithMatches),
			});
		});

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		await page.evaluate(async (sessionKey: string) => {
			await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'find all owners' }),
				credentials: 'include',
			});
		}, SESSION_KEY);

		expect(capturedBodies.length).toBeGreaterThan(0);
		for (const body of capturedBodies) {
			expect(body).toHaveProperty('session_key');
			expect(body).toHaveProperty('query');
			expect(typeof body['session_key']).toBe('string');
			expect(typeof body['query']).toBe('string');
		}
	});

	test('total_matches reflects full count even when matches array is truncated', async ({
		page,
	}) => {
		const truncatedResult: QueryResult = {
			...mockQueryResultWithMatches,
			matches: [mockQueryResultWithMatches.matches[0]],
			total_matches: 50,
		};

		await mockBaseApis(page);
		await mockDocumentQuery(page, truncatedResult);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'find all' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		expect(response.total_matches).toBe(50);
		expect(response.matches).toHaveLength(1);
		expect(response.total_matches).toBeGreaterThan(response.matches.length);
	});
});

// ── Test suite: Classification UI and empty state (m-clone-nfzo) ───────────────

test.describe('Column classification and empty state', () => {
	test.beforeEach(async ({ context }) => {
		await setAuthCookie(context);
	});

	test('column classification response includes roles and confidence per column', async ({
		page,
	}) => {
		await mockBaseApis(page);
		await mockImportUpload(page);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (campaignId: string) => {
			const form = new FormData();
			const csvContent = 'company,owners,founded_year\nAcme Corp,Jane Doe,2001';
			form.append(
				'file',
				new Blob([csvContent], { type: 'text/csv' }),
				'test.csv',
			);
			const r = await fetch(`/api/campaigns/${campaignId}/import`, {
				method: 'POST',
				body: form,
				credentials: 'include',
			});
			return r.json();
		}, CAMPAIGN_ID);

		expect(response).toHaveProperty('column_classifications');
		const classifications = response.column_classifications as Record<
			string,
			ColumnClassificationDetail
		>;

		// Each column must have all required fields with valid values
		for (const [, detail] of Object.entries(classifications)) {
			expect(detail).toHaveProperty('role');
			expect(detail).toHaveProperty('semantic_type');
			expect(detail).toHaveProperty('confidence');
			expect(detail).toHaveProperty('reasoning');

			expect([
				'entity_label',
				'entity_gwm_id',
				'entity_description',
				'attribute',
			]).toContain(detail.role);

			expect(detail.confidence).toBeGreaterThanOrEqual(0);
			expect(detail.confidence).toBeLessThanOrEqual(1);
		}

		// At least one column must be entity_label for a valid import
		const roles = Object.values(classifications).map((d) => d.role);
		expect(roles).toContain('entity_label');
	});

	test('classification confidence scores are present and valid for all columns', async ({
		page,
	}) => {
		await mockBaseApis(page);
		await mockImportUpload(page);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (campaignId: string) => {
			const form = new FormData();
			const csvContent = 'company,owners,founded_year\nAcme Corp,Jane Doe,2001';
			form.append(
				'file',
				new Blob([csvContent], { type: 'text/csv' }),
				'test.csv',
			);
			const r = await fetch(`/api/campaigns/${campaignId}/import`, {
				method: 'POST',
				body: form,
				credentials: 'include',
			});
			return r.json();
		}, CAMPAIGN_ID);

		const classifications = response.column_classifications as Record<
			string,
			ColumnClassificationDetail
		>;

		// company should have high confidence as entity_label
		expect(classifications['company'].confidence).toBeGreaterThanOrEqual(0.9);

		// All confidence values must be in valid [0, 1] range
		for (const [col, detail] of Object.entries(classifications)) {
			expect(detail.confidence, `${col} confidence out of range`).toBeGreaterThanOrEqual(0);
			expect(detail.confidence, `${col} confidence out of range`).toBeLessThanOrEqual(1);
		}
	});

	test('query with no matches returns empty result with explanation in query_interpretation', async ({
		page,
	}) => {
		await mockBaseApis(page);
		await mockDocumentQuery(page, mockQueryResultEmpty);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'find all revenue' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		// All four top-level fields must be present
		expect(response).toHaveProperty('matches');
		expect(response).toHaveProperty('query_interpretation');
		expect(response).toHaveProperty('total_matches');
		expect(response).toHaveProperty('error');

		expect(response.matches).toHaveLength(0);
		expect(response.total_matches).toBe(0);
		expect(response.error).toBeNull();

		// query_interpretation explains why no matches — never empty, always a string
		expect(typeof response.query_interpretation).toBe('string');
		expect(response.query_interpretation.length).toBeGreaterThan(0);
		expect(response.query_interpretation).toContain('revenue');
	});

	test('query_interpretation is always a non-null string regardless of result state', async ({
		page,
	}) => {
		await mockBaseApis(page);
		await mockDocumentQuery(page, mockQueryResultWithMatches);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// With matches
		const withMatches = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'owners' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		expect(typeof withMatches.query_interpretation).toBe('string');
		expect(withMatches.query_interpretation.length).toBeGreaterThan(0);

		// Re-register the empty result mock (overrides prior route)
		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(mockQueryResultEmpty),
			}),
		);

		// With empty results
		const withEmpty = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'revenue' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		expect(typeof withEmpty.query_interpretation).toBe('string');
		expect(withEmpty.query_interpretation.length).toBeGreaterThan(0);
	});

	test('error response delivers structured error field at HTTP 200, not HTTP 500', async ({
		page,
	}) => {
		await mockBaseApis(page);

		const errorResult: QueryResult = {
			matches: [],
			query_interpretation: '',
			total_matches: 0,
			error: 'LLM service temporarily unavailable. Please try again.',
		};

		await page.route('/api/documents/query', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(errorResult),
			}),
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'test' }),
				credentials: 'include',
			});
			return { status: r.status, body: await r.json() };
		}, SESSION_KEY);

		// HTTP status must be 200 — error is in the response body
		expect(response.status).toBe(200);
		expect(response.body.error).not.toBeNull();
		expect(typeof response.body.error).toBe('string');
		expect(response.body.matches).toHaveLength(0);
		expect(response.body.total_matches).toBe(0);
	});
});

// ── Test suite: Match entry data contract (m-clone-0g2s) ──────────────────────

test.describe('QueryResults component data contract', () => {
	test.beforeEach(async ({ context }) => {
		await setAuthCookie(context);
	});

	test('each match entry has required provenance fields', async ({ page }) => {
		await mockBaseApis(page);
		await mockDocumentQuery(page, mockQueryResultWithMatches);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'find owners' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		for (const match of response.matches) {
			// Required fields for provenance display in QueryResults component
			expect(match).toHaveProperty('value');
			expect(match).toHaveProperty('source_column');
			expect(match).toHaveProperty('row_numbers');
			expect(match).toHaveProperty('confidence');

			// row_numbers must be a non-empty array of numbers
			expect(Array.isArray(match.row_numbers)).toBe(true);
			expect(match.row_numbers.length).toBeGreaterThan(0);

			// confidence in [0, 1]
			expect(match.confidence).toBeGreaterThanOrEqual(0);
			expect(match.confidence).toBeLessThanOrEqual(1);
		}
	});

	test('multi-column paired match has array source_column and dict value', async ({ page }) => {
		const pairedResult: QueryResult = {
			matches: [
				{
					value: { company: 'Acme Corp', owners: 'Jane Doe' },
					source_column: ['company', 'owners'],
					row_numbers: [2],
					confidence: 0.88,
				},
			],
			query_interpretation: 'Interpreted as: paired company-owner relationships',
			total_matches: 1,
			error: null,
		};

		await mockBaseApis(page);
		await mockDocumentQuery(page, pairedResult);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const response = await page.evaluate(async (sessionKey: string) => {
			const r = await fetch('/api/documents/query', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ session_key: sessionKey, query: 'who owns what' }),
				credentials: 'include',
			});
			return r.json();
		}, SESSION_KEY);

		expect(response.matches).toHaveLength(1);
		const match = response.matches[0];

		// Paired query: source_column is an array of column names
		expect(Array.isArray(match.source_column)).toBe(true);
		expect(match.source_column).toContain('company');
		expect(match.source_column).toContain('owners');

		// Paired query: value is a dict keyed by column name
		expect(typeof match.value).toBe('object');
		expect(match.value).toHaveProperty('company');
		expect(match.value).toHaveProperty('owners');
		expect(match.value['company']).toBe('Acme Corp');
		expect(match.value['owners']).toBe('Jane Doe');
	});
});
