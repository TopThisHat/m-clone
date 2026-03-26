import { apiFetch } from './apiFetch';

export interface MatrixCell {
	entity_id: string;
	attribute_id: string;
	value_boolean: boolean | null;
	value_numeric: number | null;
	value_text: string | null;
	value_select: string | null;
	updated_at: string | null;
	updated_by: string | null;
}

/** The typed value stored in a cell (null = clear the cell) */
export type CellValue = boolean | number | string | null;

export type AttributeType = 'boolean' | 'numeric' | 'text' | 'select';

export interface MatrixCellUpsert {
	entity_id: string;
	attribute_id: string;
	value: CellValue;
	attribute_type?: AttributeType;
}

/** Extract the typed value from a MatrixCell based on attribute_type. */
export function getCellValue(cell: MatrixCell, attrType: AttributeType): CellValue {
	switch (attrType) {
		case 'boolean':
			return cell.value_boolean;
		case 'numeric':
			return cell.value_numeric;
		case 'select':
			return cell.value_select;
		default:
			return cell.value_text;
	}
}

export const matrixApi = {
	upsertCell: (campaignId: string, data: MatrixCellUpsert): Promise<MatrixCell> =>
		apiFetch(`/api/campaigns/${campaignId}/matrix/cells`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),

	deleteCell: (
		campaignId: string,
		data: { entity_id: string; attribute_id: string }
	): Promise<{ deleted: boolean }> =>
		apiFetch(`/api/campaigns/${campaignId}/matrix/cells`, {
			method: 'DELETE',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		}),
};
