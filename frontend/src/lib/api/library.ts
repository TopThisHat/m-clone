import { apiFetch } from './apiFetch';

export interface LibraryEntity {
	id: string;
	owner_sid: string;
	team_id: string | null;
	label: string;
	description: string | null;
	gwm_id: string | null;
	metadata: Record<string, unknown>;
	created_at: string;
}

export interface LibraryAttribute {
	id: string;
	owner_sid: string;
	team_id: string | null;
	label: string;
	description: string | null;
	weight: number;
	created_at: string;
}

export interface LibraryEntityCreate {
	label: string;
	description?: string;
	gwm_id?: string;
	metadata?: Record<string, unknown>;
	team_id?: string;
}

export interface LibraryAttributeCreate {
	label: string;
	description?: string;
	weight?: number;
	team_id?: string;
}

export interface BulkLibraryResult<T> {
	inserted: T[];
	skipped: number;
}

export const libraryEntitiesApi = {
	list: (teamId?: string | null): Promise<LibraryEntity[]> => {
		const params = teamId ? `?team_id=${teamId}` : '';
		return apiFetch(`/api/library/entities${params}`);
	},

	create: (data: LibraryEntityCreate): Promise<LibraryEntity> =>
		apiFetch('/api/library/entities', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	bulkCreate: (
		items: LibraryEntityCreate[],
		teamId?: string | null
	): Promise<BulkLibraryResult<LibraryEntity>> =>
		apiFetch('/api/library/entities/bulk', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ items, team_id: teamId ?? null }),
		}),

	update: (id: string, data: Partial<LibraryEntityCreate>): Promise<LibraryEntity> =>
		apiFetch(`/api/library/entities/${id}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (id: string): Promise<null> =>
		apiFetch(`/api/library/entities/${id}`, { method: 'DELETE' }),
};

export const libraryAttributesApi = {
	list: (teamId?: string | null): Promise<LibraryAttribute[]> => {
		const params = teamId ? `?team_id=${teamId}` : '';
		return apiFetch(`/api/library/attributes${params}`);
	},

	create: (data: LibraryAttributeCreate): Promise<LibraryAttribute> =>
		apiFetch('/api/library/attributes', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	bulkCreate: (
		items: LibraryAttributeCreate[],
		teamId?: string | null
	): Promise<BulkLibraryResult<LibraryAttribute>> =>
		apiFetch('/api/library/attributes/bulk', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ items, team_id: teamId ?? null }),
		}),

	update: (id: string, data: Partial<LibraryAttributeCreate>): Promise<LibraryAttribute> =>
		apiFetch(`/api/library/attributes/${id}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (id: string): Promise<null> =>
		apiFetch(`/api/library/attributes/${id}`, { method: 'DELETE' }),
};
