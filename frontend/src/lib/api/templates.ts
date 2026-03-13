import { apiFetch } from './apiFetch';

export interface AttributeTemplate {
	id: string;
	owner_sid: string;
	team_id: string | null;
	name: string;
	attributes: Array<{ label: string; description?: string; weight?: number }>;
	created_at: string;
}

export const templatesApi = {
	list: (): Promise<AttributeTemplate[]> => apiFetch('/api/attribute-templates'),

	create: (data: { name: string; team_id?: string | null; attributes: AttributeTemplate['attributes'] }): Promise<AttributeTemplate> =>
		apiFetch('/api/attribute-templates', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	delete: (id: string): Promise<null> =>
		apiFetch(`/api/attribute-templates/${id}`, { method: 'DELETE' }),
};
