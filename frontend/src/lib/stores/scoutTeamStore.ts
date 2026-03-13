import { browser } from '$app/environment';
import { writable } from 'svelte/store';

const STORAGE_KEY = 'scout_team_id';

function createScoutTeamStore() {
	const initial = browser ? (localStorage.getItem(STORAGE_KEY) ?? null) : null;
	const { subscribe, set } = writable<string | null>(initial);

	return {
		subscribe,
		select(teamId: string | null) {
			if (browser) {
				if (teamId) localStorage.setItem(STORAGE_KEY, teamId);
				else localStorage.removeItem(STORAGE_KEY);
			}
			set(teamId);
		},
	};
}

export const scoutTeam = createScoutTeamStore();
