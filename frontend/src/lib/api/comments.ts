import { assertOk } from './errors';

export interface Comment {
	id: string;
	session_id: string;
	author_sid: string;
	author_name: string;
	author_avatar: string | null;
	body: string;
	mentions: string[];
	parent_id: string | null;
	created_at: string;
	updated_at: string;
}

export async function listComments(sessionId: string): Promise<Comment[]> {
	const res = await fetch(`/api/sessions/${sessionId}/comments`, { credentials: 'include' });
	if (!res.ok) return []; // silently degrade — no DB or not authed
	return res.json();
}

export async function createComment(sessionId: string, body: string, parentId?: string): Promise<Comment> {
	const res = await fetch(`/api/sessions/${sessionId}/comments`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ body, parent_id: parentId ?? null }),
	});
	await assertOk(res, 'Failed to post comment.');
	return res.json();
}

export async function deleteComment(commentId: string): Promise<void> {
	const res = await fetch(`/api/comments/${commentId}`, {
		method: 'DELETE',
		credentials: 'include',
	});
	await assertOk(res, 'Failed to delete comment.');
}
