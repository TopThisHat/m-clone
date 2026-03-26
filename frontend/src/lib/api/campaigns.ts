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

// ── Comparison types ─────────────────────────────────────────────────────────

export interface ComparisonEntityInfo {
	id: string;
	label: string;
	gwm_id: string | null;
	total_score: number | null;
	attributes_present: number | null;
	attributes_checked: number | null;
}

export interface ComparisonEntityValue {
	present: boolean;
	confidence: number | null;
	evidence: string | null;
}

export interface ComparisonAttributeRow {
	attribute_id: string;
	label: string;
	description: string | null;
	weight: number;
	attribute_type: string;
	category: string | null;
	entity_values: Record<string, ComparisonEntityValue | null>;
	best_entity_ids: string[];
	worst_entity_ids: string[];
}

export interface ComparisonSummary {
	entity_count: number;
	attribute_count: number;
}

export interface ComparisonHighlights {
	best_score_entity_ids: string[];
	worst_score_entity_ids: string[];
}

export interface ComparisonOut {
	campaign_id: string;
	entities: ComparisonEntityInfo[];
	attributes: ComparisonAttributeRow[];
	summary: ComparisonSummary;
	highlights: ComparisonHighlights;
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

	compare: (campaignId: string, entityIds: string[]): Promise<ComparisonOut> =>
		apiFetch(`/api/campaigns/${campaignId}/compare`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ entity_ids: entityIds }),
		}),
};
