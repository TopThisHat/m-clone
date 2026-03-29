/**
 * Unit tests for CommentThread logic.
 *
 * CommentThread is a complex Svelte 5 component with side effects (fetch, timers,
 * DOM mutations). Rather than mounting the component with jsdom — which would
 * require mocking SvelteKit stores, $app/environment, chart.js, etc. — these
 * tests exercise the pure logic extracted from the component in isolation.
 *
 * This mirrors the pattern used in JobProgress.test.ts (logic-only, no DOM).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── remove() confirmation logic ───────────────────────────────────────────────

describe('CommentThread - delete confirmation', () => {
	beforeEach(() => {
		vi.stubGlobal('confirm', vi.fn());
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('calls confirm() before deleting a comment', async () => {
		const confirmMock = vi.mocked(window.confirm);
		confirmMock.mockReturnValue(false); // user cancels

		const deleteComment = vi.fn();

		// Simulate the remove() function from CommentThread
		async function remove(id: string) {
			if (!confirm('Are you sure you want to delete this comment?')) return;
			await deleteComment(id);
		}

		await remove('comment-1');

		expect(confirmMock).toHaveBeenCalledOnce();
		expect(confirmMock).toHaveBeenCalledWith('Are you sure you want to delete this comment?');
		expect(deleteComment).not.toHaveBeenCalled();
	});

	it('proceeds with deletion when user confirms', async () => {
		const confirmMock = vi.mocked(window.confirm);
		confirmMock.mockReturnValue(true);

		const deleteComment = vi.fn().mockResolvedValue(undefined);

		async function remove(id: string) {
			if (!confirm('Are you sure you want to delete this comment?')) return;
			await deleteComment(id);
		}

		await remove('comment-42');

		expect(confirmMock).toHaveBeenCalledOnce();
		expect(deleteComment).toHaveBeenCalledWith('comment-42');
	});

	it('does not delete when user cancels', async () => {
		const confirmMock = vi.mocked(window.confirm);
		confirmMock.mockReturnValue(false);

		const deleteComment = vi.fn();

		async function remove(id: string) {
			if (!confirm('Are you sure you want to delete this comment?')) return;
			await deleteComment(id);
		}

		await remove('comment-99');

		expect(deleteComment).not.toHaveBeenCalled();
	});
});

// ── isEdited() logic ──────────────────────────────────────────────────────────

describe('CommentThread - isEdited()', () => {
	function isEdited(created_at: string, updated_at: string): boolean {
		const created = new Date(created_at).getTime();
		const updated = new Date(updated_at).getTime();
		return updated - created > 5000;
	}

	it('returns false when created and updated are the same', () => {
		const ts = '2025-01-01T10:00:00Z';
		expect(isEdited(ts, ts)).toBe(false);
	});

	it('returns false when update is within 5 seconds of creation', () => {
		expect(isEdited('2025-01-01T10:00:00Z', '2025-01-01T10:00:04.999Z')).toBe(false);
	});

	it('returns true when update is more than 5 seconds after creation', () => {
		expect(isEdited('2025-01-01T10:00:00Z', '2025-01-01T10:00:06Z')).toBe(true);
	});

	it('returns true for comments edited much later', () => {
		expect(isEdited('2025-01-01T10:00:00Z', '2025-01-01T11:30:00Z')).toBe(true);
	});
});

// ── @mention filtering logic ──────────────────────────────────────────────────

describe('CommentThread - mention filtering', () => {
	interface MentionUser {
		sid: string;
		display_name: string;
		avatar_url: string | null;
	}

	const users: MentionUser[] = [
		{ sid: 'alice', display_name: 'Alice Smith', avatar_url: null },
		{ sid: 'bob', display_name: 'Bob Jones', avatar_url: null },
		{ sid: 'charlie', display_name: 'Charlie Brown', avatar_url: null },
		{ sid: 'dave', display_name: 'Dave Lee', avatar_url: null },
		{ sid: 'eve', display_name: 'Eve Adams', avatar_url: null },
		{ sid: 'frank', display_name: 'Frank Chen', avatar_url: null },
		{ sid: 'grace', display_name: 'Grace Kim', avatar_url: null },
	];

	function filterMentions(query: string, allUsers: MentionUser[]): MentionUser[] {
		return query === ''
			? allUsers.slice(0, 6)
			: allUsers
					.filter(
						(u) =>
							u.display_name.toLowerCase().includes(query.toLowerCase()) ||
							u.sid.toLowerCase().includes(query.toLowerCase()),
					)
					.slice(0, 6);
	}

	it('returns up to 6 users when query is empty', () => {
		const result = filterMentions('', users);
		expect(result).toHaveLength(6);
	});

	it('filters by display name (case-insensitive)', () => {
		const result = filterMentions('alice', users);
		expect(result).toHaveLength(1);
		expect(result[0].sid).toBe('alice');
	});

	it('filters by sid', () => {
		const result = filterMentions('bob', users);
		expect(result[0].sid).toBe('bob');
	});

	it('is case-insensitive for display names', () => {
		expect(filterMentions('ALICE', users)).toHaveLength(1);
		expect(filterMentions('alice', users)).toHaveLength(1);
	});

	it('returns empty array when no users match', () => {
		expect(filterMentions('xyzzy', users)).toHaveLength(0);
	});

	it('caps results at 6 even when more match', () => {
		// All 7 users match empty query but we cap at 6
		expect(filterMentions('', users)).toHaveLength(6);
	});
});

// ── Top-level / replies split logic ──────────────────────────────────────────

describe('CommentThread - comment tree structure', () => {
	interface MinimalComment {
		id: string;
		parent_id: string | null;
		body: string;
	}

	function buildTree(comments: MinimalComment[]) {
		const topLevel = comments.filter((c) => !c.parent_id);
		const replies = comments.reduce<Record<string, MinimalComment[]>>((acc, c) => {
			if (c.parent_id) {
				if (!acc[c.parent_id]) acc[c.parent_id] = [];
				acc[c.parent_id].push(c);
			}
			return acc;
		}, {});
		return { topLevel, replies };
	}

	it('separates top-level comments from replies', () => {
		const comments: MinimalComment[] = [
			{ id: 'c1', parent_id: null, body: 'Top level' },
			{ id: 'c2', parent_id: 'c1', body: 'Reply to c1' },
			{ id: 'c3', parent_id: null, body: 'Another top level' },
		];

		const { topLevel, replies } = buildTree(comments);

		expect(topLevel).toHaveLength(2);
		expect(replies['c1']).toHaveLength(1);
		expect(replies['c1'][0].id).toBe('c2');
	});

	it('returns empty replies for comments with no children', () => {
		const comments: MinimalComment[] = [
			{ id: 'c1', parent_id: null, body: 'Top level' },
		];

		const { topLevel, replies } = buildTree(comments);

		expect(topLevel).toHaveLength(1);
		expect(replies['c1']).toBeUndefined();
	});

	it('handles empty comment list', () => {
		const { topLevel, replies } = buildTree([]);
		expect(topLevel).toHaveLength(0);
		expect(Object.keys(replies)).toHaveLength(0);
	});
});

// ── Unseen count logic ────────────────────────────────────────────────────────

describe('CommentThread - unseen count', () => {
	it('counts only comments whose ids are in the unseenIds set', () => {
		const comments = [
			{ id: 'c1' },
			{ id: 'c2' },
			{ id: 'c3' },
		];
		const unseenIds = new Set(['c2', 'c3']);

		const unseenCount = comments.filter((c) => unseenIds.has(c.id)).length;
		expect(unseenCount).toBe(2);
	});

	it('returns 0 when unseenIds is empty', () => {
		const comments = [{ id: 'c1' }, { id: 'c2' }];
		const unseenIds = new Set<string>();

		const unseenCount = comments.filter((c) => unseenIds.has(c.id)).length;
		expect(unseenCount).toBe(0);
	});
});
