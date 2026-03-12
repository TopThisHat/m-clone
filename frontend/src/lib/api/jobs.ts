import { apiFetch } from './apiFetch';

export interface Job {
	id: string;
	campaign_id: string;
	triggered_by: string | null;
	triggered_sid: string | null;
	status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
	entity_filter: string[] | null;
	attribute_filter: string[] | null;
	total_pairs: number;
	completed_pairs: number;
	error: string | null;
	created_at: string;
	started_at: string | null;
	completed_at: string | null;
}

export interface JobCreate {
	entity_ids?: string[];
	attribute_ids?: string[];
}

export interface Result {
	id: string;
	job_id: string;
	entity_id: string;
	attribute_id: string;
	present: boolean;
	confidence: number | null;
	evidence: string | null;
	report_md: string | null;
	entity_label: string | null;
	attribute_label: string | null;
	created_at: string;
}

export interface Score {
	entity_id: string;
	campaign_id: string;
	entity_label: string | null;
	gwm_id: string | null;
	total_score: number;
	attributes_present: number;
	attributes_checked: number;
	last_updated: string | null;
}

export interface Knowledge {
	gwm_id: string;
	attribute_label: string;
	present: boolean;
	confidence: number | null;
	evidence: string | null;
	source_job_id: string | null;
	source_campaign_id: string | null;
	source_campaign_name: string | null;
	entity_label: string | null;
	last_updated: string | null;
}

export const jobsApi = {
	create: (campaignId: string, data: JobCreate = {}): Promise<Job> =>
		apiFetch(`/api/campaigns/${campaignId}/jobs`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	list: (campaignId: string): Promise<Job[]> =>
		apiFetch(`/api/campaigns/${campaignId}/jobs`),

	get: (jobId: string): Promise<Job> =>
		apiFetch(`/api/jobs/${jobId}`),

	getResults: (
		jobId: string,
		params: { entity_id?: string; attribute_id?: string; present?: boolean; limit?: number; offset?: number } = {}
	): Promise<Result[]> => {
		const q = new URLSearchParams();
		if (params.entity_id) q.set('entity_id', params.entity_id);
		if (params.attribute_id) q.set('attribute_id', params.attribute_id);
		if (params.present !== undefined) q.set('present', String(params.present));
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		if (params.offset !== undefined) q.set('offset', String(params.offset));
		return apiFetch(`/api/jobs/${jobId}/results?${q}`);
	},

	getScores: (campaignId: string): Promise<Score[]> =>
		apiFetch(`/api/campaigns/${campaignId}/scores`),

	getKnowledge: (campaignId: string): Promise<Knowledge[]> =>
		apiFetch(`/api/campaigns/${campaignId}/knowledge`),

	cancel: (jobId: string): Promise<{ cancelled: boolean }> =>
		apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' }),
};
