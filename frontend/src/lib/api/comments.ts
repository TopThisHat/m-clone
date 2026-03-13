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
): Promise<Comment> {
	const res = await fetch(`/api/sessions/${sessionId}/comments`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({
			body,
			parent_id: parentId ?? null,
			highlight_anchor: anchor ?? null,
		}),
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
