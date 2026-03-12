import { apiFetch } from './apiFetch';

export interface Entity {
	id: string;
	campaign_id: string;
	label: string;
	description: string | null;
	gwm_id: string | null;
	metadata: Record<string, unknown>;
	created_at: string;
}

export interface EntityCreate {
	label: string;
	description?: string;
	gwm_id?: string;
	metadata?: Record<string, unknown>;
}

export const entitiesApi = {
	list: (campaignId: string): Promise<Entity[]> =>
		apiFetch(`/api/campaigns/${campaignId}/entities`),

	create: (campaignId: string, data: EntityCreate): Promise<Entity> =>
		apiFetch(`/api/campaigns/${campaignId}/entities`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	bulkCreate: (campaignId: string, entities: EntityCreate[]): Promise<Entity[]> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/bulk`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(entities),
		}),

	update: (campaignId: string, entityId: string, data: Partial<EntityCreate>): Promise<Entity> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/${entityId}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (campaignId: string, entityId: string): Promise<null> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/${entityId}`, { method: 'DELETE' }),

	importFrom: (campaignId: string, sourceCampaignId: string): Promise<Entity[]> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/import`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source_campaign_id: sourceCampaignId }),
		}),
};
