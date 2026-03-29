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

export interface BulkEntityResult {
	inserted: Entity[];
	skipped: number;
}

export interface BulkDeleteResult {
	deleted: number;
}

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
	limit: number;
	offset: number;
}

export const entitiesApi = {
	list: (
		campaignId: string,
		opts?: { limit?: number; offset?: number; search?: string; sort_by?: string; order?: string }
	): Promise<PaginatedResponse<Entity>> => {
		const params = new URLSearchParams();
		if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
		if (opts?.offset !== undefined) params.set('offset', String(opts.offset));
		if (opts?.search) params.set('search', opts.search);
		if (opts?.sort_by) params.set('sort_by', opts.sort_by);
		if (opts?.order) params.set('order', opts.order);
		const qs = params.toString();
		return apiFetch(`/api/campaigns/${campaignId}/entities${qs ? `?${qs}` : ''}`);
	},

	create: (campaignId: string, data: EntityCreate): Promise<Entity> =>
		apiFetch(`/api/campaigns/${campaignId}/entities`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	bulkCreate: (campaignId: string, entities: EntityCreate[]): Promise<BulkEntityResult> =>
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

	bulkDelete: (campaignId: string, ids: string[]): Promise<BulkDeleteResult> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/bulk`, {
			method: 'DELETE',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),

	importFrom: (campaignId: string, sourceCampaignId: string): Promise<BulkEntityResult> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/import`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source_campaign_id: sourceCampaignId }),
		}),

	importFromLibrary: (campaignId: string, ids: string[]): Promise<BulkEntityResult> =>
		apiFetch(`/api/campaigns/${campaignId}/entities/import-library`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),
};
