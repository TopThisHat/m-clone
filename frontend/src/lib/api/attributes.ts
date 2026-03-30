import { apiFetch } from './apiFetch';
import type { BulkDeleteResult, PaginatedResponse } from './entities';

export type { BulkDeleteResult, PaginatedResponse };

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

export interface BulkAttributeResult {
	inserted: Attribute[];
	skipped: number;
}

export const attributesApi = {
	list: (
		campaignId: string,
		opts?: { limit?: number; offset?: number; search?: string; sort_by?: string; order?: string }
	): Promise<PaginatedResponse<Attribute>> => {
		const params = new URLSearchParams();
		if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
		if (opts?.offset !== undefined) params.set('offset', String(opts.offset));
		if (opts?.search) params.set('search', opts.search);
		if (opts?.sort_by) params.set('sort_by', opts.sort_by);
		if (opts?.order) params.set('order', opts.order);
		const qs = params.toString();
		return apiFetch(`/api/campaigns/${campaignId}/attributes${qs ? `?${qs}` : ''}`);
	},

	create: (campaignId: string, data: AttributeCreate): Promise<Attribute> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	bulkCreate: (campaignId: string, attributes: AttributeCreate[]): Promise<BulkAttributeResult> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/bulk`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(attributes),
		}),

	update: (campaignId: string, attributeId: string, data: AttributeUpdate): Promise<Attribute> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/${attributeId}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (campaignId: string, attributeId: string): Promise<null> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/${attributeId}`, { method: 'DELETE' }),

	bulkDelete: (campaignId: string, ids: string[]): Promise<BulkDeleteResult> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/bulk`, {
			method: 'DELETE',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),

	importFrom: (campaignId: string, sourceCampaignId: string): Promise<BulkAttributeResult> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/import`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source_campaign_id: sourceCampaignId }),
		}),

	importFromLibrary: (campaignId: string, ids: string[]): Promise<BulkAttributeResult> =>
		apiFetch(`/api/campaigns/${campaignId}/attributes/import-library`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),
};
