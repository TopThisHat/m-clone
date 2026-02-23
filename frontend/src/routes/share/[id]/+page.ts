import type { PageLoad } from './$types';
import { getPublicSession } from '$lib/api/sessions';
import { error } from '@sveltejs/kit';

export const load: PageLoad = async ({ params }) => {
	try {
		const session = await getPublicSession(params.id);
		return { session };
	} catch {
		throw error(404, 'This research report is not publicly available');
	}
};
