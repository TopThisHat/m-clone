import type { SessionSummary } from '$lib/stores/sessionStore';

export interface SessionFull extends SessionSummary {
	report_markdown: string;
	message_history: unknown[];
	trace_steps: unknown[];
	parent_session_id?: string | null;
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

export interface PresenceViewer {
	user_sid: string;
	display_name: string;
	avatar_url: string | null;
}

export interface SessionDiff {
	current_markdown: string;
	previous_markdown: string;
	previous_id: string;
	previous_date: string | null;
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

export async function forkSession(id: string): Promise<{ id: string; title: string }> {
	const res = await fetch(`/api/sessions/${id}/fork`, {
		method: 'POST',
		credentials: 'include'
	});
	return handleResponse<{ id: string; title: string }>(res);
}

export async function subscribe(id: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}/subscribe`, {
		method: 'POST',
		credentials: 'include'
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function unsubscribe(id: string): Promise<void> {
	const res = await fetch(`/api/sessions/${id}/subscribe`, {
		method: 'DELETE',
		credentials: 'include'
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function isSubscribed(id: string): Promise<boolean> {
	const res = await fetch(`/api/sessions/${id}/subscribe`, { credentials: 'include' });
	if (!res.ok) return false;
	const data = await res.json();
	return data.subscribed ?? false;
}

export async function heartbeatPresence(id: string): Promise<void> {
	await fetch(`/api/sessions/${id}/presence`, {
		method: 'POST',
		credentials: 'include'
	});
}

export async function getPresence(id: string): Promise<PresenceViewer[]> {
	const res = await fetch(`/api/sessions/${id}/presence`, { credentials: 'include' });
	if (!res.ok) return [];
	return res.json();
}

export async function getSessionDiff(id: string): Promise<SessionDiff | null> {
	const res = await fetch(`/api/sessions/${id}/diff`, { credentials: 'include' });
	if (!res.ok) return null;
	return res.json();
}
