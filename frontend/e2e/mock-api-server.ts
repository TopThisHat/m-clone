/**
 * Lightweight mock API server for E2E tests.
 *
 * During SSR, SvelteKit's fetch goes through Vite's proxy to localhost:8000.
 * Playwright's page.route() only intercepts browser-level requests, not SSR
 * fetches. This server fills that gap by responding to API routes the pages
 * need so SSR can render successfully without the real backend.
 *
 * Individual tests still use page.route() to override client-side behavior.
 * Since SvelteKit caches SSR data for hydration, client-side re-fetches only
 * happen on subsequent navigations.
 *
 * Usage: started automatically by Playwright via playwright.config.ts webServer.
 */

import http from 'node:http';

const PORT = 8001;

// ── Mock data ────────────────────────────────────────────────────────────────

const mockUser = {
	sid: 'user-abc',
	display_name: 'Test User',
	theme: 'dark',
};

const mockSession = {
	id: 'test-share-session',
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

const mockSessionWithParent = {
	...mockSession,
	id: 'test-share-diff',
	parent_session_id: 'parent-session-abc',
};

const sessions: Record<string, typeof mockSession> = {
	'test-share-session': mockSession,
	'test-share-public': mockSessionPublic,
	'test-share-diff': mockSessionWithParent,
};

// ── Mock entity/attribute data for entity-attribute-pages tests ──────────────

const mockTeams = [{ id: 'team-1', name: 'Test Team', slug: 'test-team' }];

const CAMPAIGN_ID = 'test-campaign-id';

const mockCampaign = {
	id: CAMPAIGN_ID,
	name: 'Test Campaign',
	status: 'active',
	created_at: '2025-01-01T00:00:00Z',
};

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
	label: `Library Attribute ${i + 1}`,
	description: `Description ${i + 1}`,
	weight: (i + 1) * 2,
	created_at: new Date(2025, 0, i + 1).toISOString(),
}));

// ── Route matching helpers ───────────────────────────────────────────────────

function json(res: http.ServerResponse, data: unknown, status = 200) {
	res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
	res.end(JSON.stringify(data));
}

function text(res: http.ServerResponse, body: string, status = 200) {
	res.writeHead(status, { 'Content-Type': 'text/plain', 'Access-Control-Allow-Origin': '*' });
	res.end(body);
}

// ── Server ───────────────────────────────────────────────────────────────────

const server = http.createServer((req, res) => {
	const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
	const path = url.pathname;
	const method = req.method ?? 'GET';

	// CORS preflight
	if (method === 'OPTIONS') {
		res.writeHead(204, {
			'Access-Control-Allow-Origin': '*',
			'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
			'Access-Control-Allow-Headers': 'Content-Type, Authorization, Cookie',
		});
		res.end();
		return;
	}

	// ── Auth ──────────────────────────────────────────────────────────────
	if (path === '/api/auth/me') {
		const cookie = req.headers.cookie ?? '';
		if (cookie.includes('jwt=')) {
			return json(res, mockUser);
		}
		return text(res, '', 401);
	}

	// ── Share page ────────────────────────────────────────────────────────
	const shareMatch = path.match(/^\/api\/share\/(.+)$/);
	if (shareMatch) {
		const id = shareMatch[1];
		const session = sessions[id];
		if (session) return json(res, session);
		return text(res, 'Not found', 404);
	}

	// ── Session sub-resources ─────────────────────────────────────────────
	const commentsMatch = path.match(/^\/api\/sessions\/(.+)\/comments$/);
	if (commentsMatch) return json(res, []);

	const presenceMatch = path.match(/^\/api\/sessions\/(.+)\/presence$/);
	if (presenceMatch) return json(res, []);

	const subscribedMatch = path.match(/^\/api\/sessions\/(.+)\/subscribed$/);
	if (subscribedMatch) return json(res, false);

	const subscribeMatch = path.match(/^\/api\/sessions\/(.+)\/subscribe$/);
	if (subscribeMatch) return json(res, {});

	const diffMatch = path.match(/^\/api\/sessions\/(.+)\/diff$/);
	if (diffMatch) {
		return json(res, {
			current_markdown: '## New\n\nNew content.',
			previous_markdown: '## Old\n\nOld content.',
			previous_date: '2024-12-01T00:00:00Z',
		});
	}

	// ── Teams ─────────────────────────────────────────────────────────────
	if (path === '/api/teams') return json(res, mockTeams);

	// ── Campaigns ─────────────────────────────────────────────────────────
	if (path === '/api/campaigns' || path.match(/^\/api\/campaigns\/?$/)) {
		return json(res, [mockCampaign]);
	}
	const campaignMatch = path.match(/^\/api\/campaigns\/([^/]+)$/);
	if (campaignMatch) return json(res, mockCampaign);

	// ── Campaign entities ─────────────────────────────────────────────────
	const campEntitiesMatch = path.match(/^\/api\/campaigns\/([^/]+)\/entities/);
	if (campEntitiesMatch) {
		if (method === 'DELETE') return json(res, { deleted: 1 });
		if (method === 'POST') return json(res, mockEntities[0], 201);
		return json(res, { items: mockEntities, total: mockEntities.length, limit: 50, offset: 0 });
	}

	// ── Campaign attributes ───────────────────────────────────────────────
	const campAttrsMatch = path.match(/^\/api\/campaigns\/([^/]+)\/attributes/);
	if (campAttrsMatch) {
		if (method === 'DELETE') return json(res, { deleted: 1 });
		if (method === 'POST') return json(res, mockAttributes[0], 201);
		return json(res, { items: mockAttributes, total: mockAttributes.length, limit: 50, offset: 0 });
	}

	// ── Library entities ──────────────────────────────────────────────────
	if (path.startsWith('/api/library/entities')) {
		if (method === 'DELETE') return json(res, { deleted: 1 });
		if (method === 'POST') return json(res, mockLibraryEntities[0], 201);
		return json(res, { items: mockLibraryEntities, total: mockLibraryEntities.length, limit: 50, offset: 0 });
	}

	// ── Library attributes ────────────────────────────────────────────────
	if (path.startsWith('/api/library/attributes')) {
		if (method === 'DELETE') return json(res, { deleted: 1 });
		if (method === 'POST') return json(res, mockLibraryAttributes[0], 201);
		return json(res, { items: mockLibraryAttributes, total: mockLibraryAttributes.length, limit: 50, offset: 0 });
	}

	// ── Health check (used by Playwright to know the server is ready) ────
	if (path === '/health') return text(res, 'ok');

	// ── Fallback ──────────────────────────────────────────────────────────
	text(res, 'Not found', 404);
});

server.listen(PORT, () => {
	console.log(`Mock API server listening on http://localhost:${PORT}`);
});
