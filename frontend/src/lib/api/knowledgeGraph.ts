import { apiFetch } from './apiFetch';

export interface KGEntity {
	id: string;
	name: string;
	entity_type: string;
	aliases: string[];
	metadata: Record<string, unknown>;
	relationship_count: number;
	created_at: string;
	updated_at: string;
}

export interface KGRelationship {
	id: string;
	subject_id: string;
	predicate: string;
	predicate_family: string;
	object_id: string;
	confidence: number;
	evidence: string | null;
	source_session_id: string | null;
	is_active: boolean;
	subject_name: string;
	subject_type: string;
	object_name: string;
	object_type: string;
	created_at: string;
}

export interface KGConflict {
	id: string;
	old_relationship_id: string;
	new_relationship_id: string;
	old_predicate: string;
	new_predicate: string;
	subject_name: string;
	object_name: string;
	detected_at: string;
}

export interface KGStats {
	total_entities: number;
	total_relationships: number;
	total_conflicts: number;
	entity_types: number;
}

export interface KGEntityPage {
	items: KGEntity[];
	total: number;
}

export const kgApi = {
	listEntities: (params: {
		search?: string;
		entity_type?: string;
		limit?: number;
		offset?: number;
	} = {}): Promise<KGEntityPage> => {
		const q = new URLSearchParams();
		if (params.search) q.set('search', params.search);
		if (params.entity_type) q.set('entity_type', params.entity_type);
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		if (params.offset !== undefined) q.set('offset', String(params.offset));
		return apiFetch(`/api/kg/entities?${q}`);
	},

	getEntity: (id: string): Promise<KGEntity> =>
		apiFetch(`/api/kg/entities/${id}`),

	getRelationships: (id: string, direction = 'both'): Promise<KGRelationship[]> =>
		apiFetch(`/api/kg/entities/${id}/relationships?direction=${direction}`),

	search: (q: string): Promise<KGEntity[]> =>
		apiFetch(`/api/kg/search?q=${encodeURIComponent(q)}`),

	getStats: (): Promise<KGStats> =>
		apiFetch('/api/kg/stats'),

	getConflicts: (limit = 50, offset = 0): Promise<KGConflict[]> =>
		apiFetch(`/api/kg/conflicts?limit=${limit}&offset=${offset}`),
};
