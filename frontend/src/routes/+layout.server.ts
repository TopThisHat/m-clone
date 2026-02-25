import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

const PUBLIC_PATHS = ['/login', '/share', '/auth'];

export const load: LayoutServerLoad = async ({ cookies, fetch, url }) => {
	const isPublic = PUBLIC_PATHS.some((p) => url.pathname.startsWith(p));
	const jwt = cookies.get('jwt');

	if (!jwt) {
		if (!isPublic) throw redirect(303, '/login');
		return { user: null };
	}

	const res = await fetch('/api/auth/me').catch(() => null);
	if (!res || !res.ok) {
		if (!isPublic) throw redirect(303, '/login');
		return { user: null };
	}

	const user = await res.json().catch(() => null);
	return { user };
};
