import type { SessionSummary } from '$lib/stores/sessionStore';

export interface SessionFull extends SessionSummary {
	report_markdown: string;
	message_history: unknown[];
	trace_steps: unknown[];
}

export interface SessionCreate {
	title: string;
	query: string;
	report_markdown?: string;
	message_history?: unknown[];
	trace_steps?: unknown[];
}

export interface SessionUpdate {
	title?: string;
	report_markdown?: string;
	message_history?: unknown[];
	trace_steps?: unknown[];
	is_public?: boolean;
	usage_tokens?: number;
}

async function handleResponse<T>(res: Response): Promise<T> {
	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore parse error
		}
		throw new Error(detail);
	}
	return res.json() as Promise<T>;
}

export async function listSessions(search?: string): Promise<SessionSummary[]> {
	const url = search ? `/api/sessions?q=${encodeURIComponent(search)}` : '/api/sessions';
	const res = await fetch(url);
	return handleResponse<SessionSummary[]>(res);
}

export async function getSession(id: string): Promise<SessionFull> {
	const res = await fetch(`/api/sessions/${id}`);
	return handleResponse<SessionFull>(res);
}

export async function createSession(data: SessionCreate): Promise<SessionFull> {
	const res = await fetch('/api/sessions', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
	return handleResponse<SessionFull>(res);
}

export async function updateSession(id: string, patch: SessionUpdate): Promise<SessionFull> {
	const res = await fetch(`/api/sessions/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(patch)
	});
	return handleResponse<SessionFull>(res);
}

export async function deleteSession(id: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore
		}
		throw new Error(detail);
	}
}

export async function shareSession(id: string): Promise<{ share_url: string }> {
	const res = await fetch(`/api/sessions/${id}/share`, { method: 'POST' });
	return handleResponse<{ share_url: string }>(res);
}

export async function unshareSession(id: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}/share`, { method: 'DELETE' });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function getPublicSession(id: string): Promise<SessionFull> {
	const res = await fetch(`/api/share/${id}`, { credentials: 'include' });
	return handleResponse<SessionFull>(res);
}

export async function getSessionTeams(id: string): Promise<string[]> {
	const res = await fetch(`/api/sessions/${id}/teams`, { credentials: 'include' });
	if (!res.ok) return [];
	return res.json();
}

export async function shareSessionToTeam(id: string, teamId: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}/teams`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ team_id: teamId })
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function unshareSessionFromTeam(id: string, teamId: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}/teams/${teamId}`, {
		method: 'DELETE',
		credentials: 'include'
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}
