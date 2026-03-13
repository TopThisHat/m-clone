import { apiFetch } from './apiFetch';

export interface Campaign {
	id: string;
	owner_sid: string;
	team_id: string | null;
	name: string;
	description: string | null;
	schedule: string | null;
	is_active: boolean;
	last_run_at: string | null;
	next_run_at: string | null;
	last_completed_at: string | null;
	entity_count: number;
	attribute_count: number;
	result_count: number;
	created_at: string;
	updated_at: string;
}

export interface CampaignStats {
	campaigns: number;
	entities: number;
	results: number;
	jobs_last_7_days: number;
	knowledge_entries: number;
}

export interface CampaignCreate {
	name: string;
	description?: string;
	schedule?: string;
	team_id?: string;
}

export interface CampaignUpdate {
	name?: string;
	description?: string;
	schedule?: string;
	is_active?: boolean;
}

export const campaignsApi = {
	list: (teamId?: string | null): Promise<Campaign[]> => {
		const qs = teamId ? `?team_id=${encodeURIComponent(teamId)}` : '';
		return apiFetch(`/api/campaigns${qs}`);
	},

	create: (data: CampaignCreate): Promise<Campaign> =>
		apiFetch('/api/campaigns', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	get: (id: string): Promise<Campaign> => apiFetch(`/api/campaigns/${id}`),

	update: (id: string, data: CampaignUpdate): Promise<Campaign> =>
		apiFetch(`/api/campaigns/${id}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (id: string): Promise<null> =>
		apiFetch(`/api/campaigns/${id}`, { method: 'DELETE' }),

	clone: (id: string): Promise<Campaign> =>
		apiFetch(`/api/campaigns/${id}/clone`, { method: 'POST' }),

	getStats: (teamId?: string | null): Promise<CampaignStats> => {
		const qs = teamId ? `?team_id=${encodeURIComponent(teamId)}` : '';
		return apiFetch(`/api/campaigns/stats${qs}`);
	},
};
