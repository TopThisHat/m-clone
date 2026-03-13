import { assertOk } from './errors';

export interface Anchor {
	quote: string;
	context_before: string;
	context_after: string;
}

export interface Comment {
	id: string;
	session_id: string;
	author_sid: string;
	author_name: string;
	author_avatar: string | null;
	body: string;
	mentions: string[];
	parent_id: string | null;
	highlight_anchor: Anchor | null;
	created_at: string;
	updated_at: string;
	comment_type: string;
	proposed_text: string | null;
	suggestion_status: string | null;
	reactions: Record<string, string[]>;
}

export async function listComments(sessionId: string): Promise<Comment[]> {
	const res = await fetch(`/api/sessions/${sessionId}/comments`, { credentials: 'include' });
	if (!res.ok) return [];
	return res.json();
}

export async function createComment(
	sessionId: string,
	body: string,
	parentId?: string,
	anchor?: Anchor,
	commentType?: string,
	proposedText?: string,
): Promise<Comment> {
	const res = await fetch(`/api/sessions/${sessionId}/comments`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({
			body,
			parent_id: parentId ?? null,
			highlight_anchor: anchor ?? null,
			comment_type: commentType ?? 'comment',
			proposed_text: proposedText ?? null,
		}),
	});
	await assertOk(res, 'Failed to post comment.');
	return res.json();
}

export async function updateComment(commentId: string, body: string): Promise<Comment> {
	const res = await fetch(`/api/comments/${commentId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ body }),
	});
	await assertOk(res, 'Failed to update comment.');
	return res.json();
}

export async function deleteComment(commentId: string): Promise<void> {
	const res = await fetch(`/api/comments/${commentId}`, {
		method: 'DELETE',
		credentials: 'include',
	});
	await assertOk(res, 'Failed to delete comment.');
}

export async function toggleReaction(
	commentId: string,
	emoji: string,
): Promise<Record<string, string[]>> {
	const res = await fetch(`/api/comments/${commentId}/reactions`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ emoji }),
	});
	await assertOk(res, 'Failed to toggle reaction.');
	return res.json();
}

export async function resolveSuggestion(
	commentId: string,
	status: 'accepted' | 'rejected',
): Promise<Comment> {
	const res = await fetch(`/api/comments/${commentId}/suggestion`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ status }),
	});
	await assertOk(res, 'Failed to resolve suggestion.');
	return res.json();
}

// ── Unread comment tracking (localStorage) ────────────────────────────────────

const LAST_SEEN_KEY = 'comment_last_seen';

function getStoredMap(): Record<string, string> {
	try {
		return JSON.parse(localStorage.getItem(LAST_SEEN_KEY) ?? '{}');
	} catch {
		return {};
	}
}

export function getLastSeen(sessionId: string): string | null {
	return getStoredMap()[sessionId] ?? null;
}

export function setLastSeen(sessionId: string): void {
	const map = getStoredMap();
	map[sessionId] = new Date().toISOString();
	localStorage.setItem(LAST_SEEN_KEY, JSON.stringify(map));
}
