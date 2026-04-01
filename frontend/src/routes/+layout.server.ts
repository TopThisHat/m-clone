import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';
import type { Team } from '$lib/api/teams';

const PUBLIC_PATHS = ['/login', '/share', '/auth'];

export const load: LayoutServerLoad = async ({ cookies, fetch, url }) => {
	const isPublic = PUBLIC_PATHS.some((p) => url.pathname.startsWith(p));
	const jwt = cookies.get('jwt');

	if (!jwt) {
		if (!isPublic) throw redirect(303, '/login');
		return { user: null, teams: [] };
	}

	const res = await fetch('/api/auth/me').catch(() => null);
	if (!res || !res.ok) {
		if (!isPublic) throw redirect(303, '/login');
		return { user: null, teams: [] };
	}

	const user = await res.json().catch(() => null);

	const teamsRes = await fetch('/api/teams', { credentials: 'include' }).catch(() => null);
	const teamsRaw = teamsRes?.ok ? await teamsRes.json().catch(() => null) : null;
	const teams: Team[] = Array.isArray(teamsRaw) ? teamsRaw : [];

	return { user, teams };
};
