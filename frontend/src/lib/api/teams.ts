import { assertOk } from './errors';

export interface Team {
	id: string;
	slug: string;
	display_name: string;
	description: string;
	created_by: string;
	created_at: string;
	role?: string;
}

export interface TeamMember {
	sid: string;
	display_name: string;
	email: string;
	avatar_url: string | null;
	role: string;
	joined_at: string;
}

export interface TeamDetail extends Team {
	members: TeamMember[];
	your_role: string;
}

const BASE = '/api/teams';

export async function listTeams(): Promise<Team[]> {
	const res = await fetch(BASE, { credentials: 'include' });
	if (!res.ok) return []; // no DB, not authed, etc. → empty list
	return res.json();
}

export async function createTeam(data: { slug: string; display_name: string; description?: string }): Promise<Team> {
	const res = await fetch(BASE, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(data),
	});
	await assertOk(res, 'Failed to create team.');
	return res.json();
}

export async function getTeam(slug: string): Promise<TeamDetail> {
	const res = await fetch(`${BASE}/${slug}`, { credentials: 'include' });
	await assertOk(res, 'Could not load team.');
	return res.json();
}

export async function updateTeam(slug: string, patch: { display_name?: string; description?: string }): Promise<Team> {
	const res = await fetch(`${BASE}/${slug}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(patch),
	});
	await assertOk(res, 'Failed to save changes.');
	return res.json();
}

export async function deleteTeam(slug: string): Promise<void> {
	const res = await fetch(`${BASE}/${slug}`, { method: 'DELETE', credentials: 'include' });
	await assertOk(res, 'Failed to delete team.');
}

export async function inviteMember(slug: string, sid: string, role = 'member'): Promise<void> {
	const res = await fetch(`${BASE}/${slug}/members`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ sid, role }),
	});
	await assertOk(res, 'Failed to invite member.');
}

export async function updateMemberRole(slug: string, sid: string, role: string): Promise<void> {
	const res = await fetch(`${BASE}/${slug}/members/${sid}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify({ role }),
	});
	await assertOk(res, 'Failed to update role.');
}

export async function removeMember(slug: string, sid: string): Promise<void> {
	const res = await fetch(`${BASE}/${slug}/members/${sid}`, {
		method: 'DELETE',
		credentials: 'include',
	});
	await assertOk(res, 'Failed to remove member.');
}

export async function getTeamSessions(slug: string): Promise<Record<string, unknown>[]> {
	const res = await fetch(`${BASE}/${slug}/sessions`, { credentials: 'include' });
	if (!res.ok) return [];
	return res.json();
}

export async function getTeamActivity(slug: string): Promise<Record<string, unknown>[]> {
	const res = await fetch(`${BASE}/${slug}/activity`, { credentials: 'include' });
	if (!res.ok) return [];
	return res.json();
}
