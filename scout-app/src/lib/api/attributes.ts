export interface Attribute {
	id: string;
	campaign_id: string;
	label: string;
	description: string | null;
	weight: number;
	created_at: string;
}

export interface AttributeCreate {
	label: string;
	description?: string;
	weight?: number;
}

export interface AttributeUpdate {
	label?: string;
	description?: string;
	weight?: number;
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

export const attributesApi = {
	list: (campaignId: string): Promise<Attribute[]> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes`),

	create: (campaignId: string, data: AttributeCreate): Promise<Attribute> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	update: (campaignId: string, attributeId: string, data: AttributeUpdate): Promise<Attribute> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/${attributeId}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (campaignId: string, attributeId: string): Promise<null> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/${attributeId}`, { method: 'DELETE' }),

	importFrom: (campaignId: string, sourceCampaignId: string): Promise<Attribute[]> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/import`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source_campaign_id: sourceCampaignId }),
		}),
};
