export interface Campaign {
	id: string;
	owner_sid: string;
	name: string;
	description: string | null;
	schedule: string | null;
	is_active: boolean;
	last_run_at: string | null;
	next_run_at: string | null;
	created_at: string;
	updated_at: string;
}

export interface CampaignCreate {
	name: string;
	description?: string;
	schedule?: string;
}

export interface CampaignUpdate {
	name?: string;
	description?: string;
	schedule?: string;
	is_active?: boolean;
}

async function apiFetch(path: string, init?: RequestInit) {
	const res = await fetch(path, { credentials: 'include', ...init });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? 'Request failed');
	}
	if (res.status === 204) return null;
	return res.json();
}

export const campaignsApi = {
	list: (): Promise<Campaign[]> => apiFetch('/api/campaigns'),

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
};
