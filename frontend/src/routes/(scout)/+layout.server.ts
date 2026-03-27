import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies, fetch }) => {
	const jwt = cookies.get('jwt');
	if (!jwt) throw redirect(302, '/login');

	const res = await fetch('/api/auth/me').catch(() => null);
	if (!res || !res.ok) throw redirect(302, '/login');

	const user = await res.json();

	const teamsRes = await fetch('/api/teams').catch(() => null);
	const teamsRaw = teamsRes?.ok ? await teamsRes.json().catch(() => null) : null;
	const teams: import('$lib/api/teams').Team[] = Array.isArray(teamsRaw) ? teamsRaw : [];

	return { user, teams };
};
