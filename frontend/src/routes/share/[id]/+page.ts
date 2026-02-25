import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';

export const load: PageLoad = async ({ params, fetch }) => {
	const res = await fetch(`/api/share/${params.id}`).catch(() => null);
	if (!res || !res.ok) {
		throw error(404, 'This research report is not publicly available');
	}
	const session = await res.json();
	return { session };
};
