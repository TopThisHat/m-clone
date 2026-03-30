import { apiFetch } from './apiFetch';
import type { BulkDeleteResult, PaginatedResponse } from './entities';

export type { BulkDeleteResult, PaginatedResponse };

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
	list: (
		teamId?: string | null,
		opts?: { limit?: number; offset?: number; search?: string; sort_by?: string; sort_dir?: 'asc' | 'desc' }
	): Promise<PaginatedResponse<LibraryEntity>> => {
		const params = new URLSearchParams();
		if (teamId) params.set('team_id', teamId);
		if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
		if (opts?.offset !== undefined) params.set('offset', String(opts.offset));
		if (opts?.search) params.set('search', opts.search);
		if (opts?.sort_by) params.set('sort_by', opts.sort_by);
		if (opts?.sort_dir) params.set('sort_dir', opts.sort_dir);
		const qs = params.toString();
		return apiFetch(`/api/library/entities${qs ? `?${qs}` : ''}`);
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

	bulkDelete: (ids: string[]): Promise<BulkDeleteResult> =>
		apiFetch('/api/library/entities/bulk', {
			method: 'DELETE',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),
};

export const libraryAttributesApi = {
	list: (
		teamId?: string | null,
		opts?: { limit?: number; offset?: number; search?: string; sort_by?: string; sort_dir?: 'asc' | 'desc' }
	): Promise<PaginatedResponse<LibraryAttribute>> => {
		const params = new URLSearchParams();
		if (teamId) params.set('team_id', teamId);
		if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
		if (opts?.offset !== undefined) params.set('offset', String(opts.offset));
		if (opts?.search) params.set('search', opts.search);
		if (opts?.sort_by) params.set('sort_by', opts.sort_by);
		if (opts?.sort_dir) params.set('sort_dir', opts.sort_dir);
		const qs = params.toString();
		return apiFetch(`/api/library/attributes${qs ? `?${qs}` : ''}`);
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

	bulkDelete: (ids: string[]): Promise<BulkDeleteResult> =>
		apiFetch('/api/library/attributes/bulk', {
			method: 'DELETE',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ids }),
		}),
};
