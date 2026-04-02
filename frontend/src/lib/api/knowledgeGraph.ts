import { apiFetch } from './apiFetch';

export interface KGEntity {
	id: string;
	name: string;
	entity_type: string;
	aliases: string[];
	metadata: Record<string, unknown>;
	description: string;
	disambiguation_context: string;
	relationship_count: number;
	team_id: string | null;
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
	graph_source?: string;
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

export interface KGGraphNode {
	id: string;
	name: string;
	entity_type: string;
	aliases: string[];
	description?: string;
	metadata?: Record<string, unknown>;
}

export interface KGGraphEdge {
	id: string;
	source: string;
	target: string;
	predicate: string;
	predicate_family: string;
	confidence: number;
	graph_source?: string;
}

export interface KGGraph {
	nodes: KGGraphNode[];
	edges: KGGraphEdge[];
}

export interface DealPartnerPerson {
	id: string;
	name: string;
}

export interface SharedDeal {
	entity_id: string;
	entity_name: string;
	person1_predicate: string;
	person2_predicate: string;
}

export interface DealPartnerGroup {
	person1: DealPartnerPerson;
	person2: DealPartnerPerson;
	shared_deals: SharedDeal[];
}

export interface KGQueryResult {
	entities: (KGEntity & { graph_source: string })[];
	relationships: (KGRelationship & { graph_source: string })[];
	sources_used: string[];
}

export interface EntityPatch {
	name?: string;
	entity_type?: string;
	aliases?: string[];
	metadata?: Record<string, unknown>;
	description?: string;
	disambiguation_context?: string;
}

export interface RelationshipPatch {
	predicate?: string;
	predicate_family?: string;
	confidence?: number;
	evidence?: string;
}

export interface KGSuggestResult {
	id: string;
	name: string;
	entity_type: string;
	relationship_count: number;
}

export const kgApi = {
	listEntities: (params: {
		search?: string;
		entity_type?: string;
		team_id?: string;
		limit?: number;
		offset?: number;
	} = {}): Promise<KGEntityPage> => {
		const q = new URLSearchParams();
		if (params.search) q.set('search', params.search);
		if (params.entity_type) q.set('entity_type', params.entity_type);
		if (params.team_id) q.set('team_id', params.team_id);
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		if (params.offset !== undefined) q.set('offset', String(params.offset));
		return apiFetch(`/api/kg/entities?${q}`);
	},

	getEntity: (id: string): Promise<KGEntity> =>
		apiFetch(`/api/kg/entities/${id}`),

	getRelationships: (id: string, direction = 'both'): Promise<KGRelationship[]> =>
		apiFetch(`/api/kg/entities/${id}/relationships?direction=${direction}`),

	search: (q: string, teamId?: string): Promise<KGEntity[]> => {
		const params = new URLSearchParams({ q });
		if (teamId) params.set('team_id', teamId);
		return apiFetch(`/api/kg/search?${params}`);
	},

	getStats: (teamId?: string): Promise<KGStats> => {
		const params = new URLSearchParams();
		if (teamId) params.set('team_id', teamId);
		return apiFetch(`/api/kg/stats?${params}`);
	},

	getConflicts: (limit = 50, offset = 0): Promise<KGConflict[]> =>
		apiFetch(`/api/kg/conflicts?limit=${limit}&offset=${offset}`),

	getGraph: (params: {
		entity_types?: string[];
		predicate_families?: string[];
		team_id?: string;
		search?: string;
		metadata_key?: string;
		metadata_value?: string;
		limit?: number;
	} = {}): Promise<KGGraph> => {
		const q = new URLSearchParams();
		if (params.entity_types?.length) q.set('entity_types', params.entity_types.join(','));
		if (params.predicate_families?.length) q.set('predicate_families', params.predicate_families.join(','));
		if (params.team_id) q.set('team_id', params.team_id);
		if (params.search) q.set('search', params.search);
		if (params.metadata_key) q.set('metadata_key', params.metadata_key);
		if (params.metadata_value) q.set('metadata_value', params.metadata_value);
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		return apiFetch(`/api/kg/graph?${q}`);
	},

	getDealPartners: (): Promise<DealPartnerGroup[]> =>
		apiFetch('/api/kg/deal-partners'),

	// Edit endpoints (admin/owner only)
	updateEntity: (id: string, patch: EntityPatch): Promise<KGEntity> =>
		apiFetch(`/api/kg/entities/${id}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(patch),
		}),

	deleteEntity: (id: string): Promise<{ deleted: boolean }> =>
		apiFetch(`/api/kg/entities/${id}`, { method: 'DELETE' }),

	updateRelationship: (id: string, patch: RelationshipPatch): Promise<KGRelationship> =>
		apiFetch(`/api/kg/relationships/${id}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(patch),
		}),

	deleteRelationship: (id: string): Promise<{ deleted: boolean }> =>
		apiFetch(`/api/kg/relationships/${id}`, { method: 'DELETE' }),

	// Query endpoint
	queryGraph: (q: string, teamId?: string): Promise<KGQueryResult> => {
		const params = new URLSearchParams({ q });
		if (teamId) params.set('team_id', teamId);
		return apiFetch(`/api/kg/query?${params}`);
	},

	getNeighbors: (
		entityId: string,
		params: { depth?: number; limit?: number; exclude_ids?: string[]; team_id?: string } = {}
	): Promise<KGGraph> => {
		const q = new URLSearchParams();
		if (params.depth !== undefined) q.set('depth', String(params.depth));
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		if (params.exclude_ids?.length) q.set('exclude_ids', params.exclude_ids.join(','));
		if (params.team_id) q.set('team_id', params.team_id);
		return apiFetch(`/api/kg/entities/${entityId}/neighbors?${q}`);
	},

	// Autocomplete suggest
	suggest: (q: string, teamId: string, limit = 10): Promise<KGSuggestResult[]> => {
		const params = new URLSearchParams({ q, team_id: teamId, limit: String(limit) });
		return apiFetch(`/api/kg/suggest?${params}`);
	},

	// Super admin: view any team's graph
	adminGetTeamGraph: (teamId: string, params: {
		entity_types?: string[];
		predicate_families?: string[];
		search?: string;
		limit?: number;
	} = {}): Promise<KGGraph> => {
		const q = new URLSearchParams();
		if (params.entity_types?.length) q.set('entity_types', params.entity_types.join(','));
		if (params.predicate_families?.length) q.set('predicate_families', params.predicate_families.join(','));
		if (params.search) q.set('search', params.search);
		if (params.limit !== undefined) q.set('limit', String(params.limit));
		return apiFetch(`/api/kg/admin/graph/${teamId}?${q}`);
	},
};
