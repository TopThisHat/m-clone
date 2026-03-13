import { writable } from 'svelte/store';

export interface Anchor {
	quote: string;
	context_before: string;
	context_after: string;
}

// ID of the comment whose highlight is currently focused
// Report listens to scroll/pulse its mark; CommentThread listens to scroll to the comment
export const activeCommentId = writable<string | null>(null);

// Anchor being composed for a new comment (set when user selects text in the report)
export const pendingAnchor = writable<Anchor | null>(null);
