import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';

export const load: PageLoad = async ({ params, fetch }) => {
	const res = await fetch(`/api/share/${params.id}`, { credentials: 'include' }).catch(() => null);
	if (!res || !res.ok) {
		throw error(404, 'This research report is not publicly available');
	}
	const session = await res.json();

	// Fetch comments (best-effort — only available for authenticated team-shared sessions)
	let comments: unknown[] = [];
	const commentsRes = await fetch(`/api/sessions/${params.id}/comments`, {
		credentials: 'include'
	}).catch(() => null);
	if (commentsRes?.ok) {
		comments = await commentsRes.json();
	}

	return { session, comments };
};
