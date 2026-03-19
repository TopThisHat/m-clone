import type { PageLoad } from './$types';
import { error, redirect } from '@sveltejs/kit';

export const load: PageLoad = async ({ params, fetch, parent }) => {
	const res = await fetch(`/api/share/${params.id}`, { credentials: 'include' }).catch(() => null);
	if (!res || !res.ok) {
		const status = res?.status ?? 0;
		if (status === 401) {
			// User is not authenticated — redirect to login then back
			throw redirect(303, `/login?redirect=/share/${params.id}`);
		}
		// Check if the user is logged in to give a better message
		const { user } = await parent();
		if (!user) {
			throw error(403, 'This report is shared with a team. Please log in to view it.');
		}
		throw error(404, 'This report is not available. It may be private or you may not have access.');
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
