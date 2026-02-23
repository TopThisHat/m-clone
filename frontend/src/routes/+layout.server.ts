import type { LayoutServerLoad } from './$types';

// Optionally load the current user on every page.
// No redirect — pages here are accessible without auth.
export const load: LayoutServerLoad = async ({ cookies, fetch }) => {
	const jwt = cookies.get('jwt');
	if (!jwt) return { user: null };

	const res = await fetch('/api/auth/me').catch(() => null);
	if (!res || !res.ok) return { user: null };

	const user = await res.json().catch(() => null);
	return { user };
};
