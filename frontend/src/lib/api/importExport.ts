import { apiFetch } from './apiFetch';

export interface ImportErrorDetail {
	row: number;
	field?: string;
	message: string;
}

export interface ImportPreview {
	row_count: number;
	column_map: Record<string, string>; // header → role (entity_label|entity_gwm_id|entity_description|attribute)
	entities: Array<{ label: string; gwm_id?: string; description?: string }>;
	attributes: Array<{ label: string }>;
	cells: Array<{ entity_label: string; attribute_label: string; value: string }>;
	errors: ImportErrorDetail[];
}

export interface ImportCommitResult {
	entities_inserted: number;
	entities_skipped: number;
	attributes_inserted: number;
	attributes_skipped: number;
	cells_upserted: number;
}

export const importExportApi = {
	upload(campaignId: string, file: File): Promise<ImportPreview> {
		const form = new FormData();
		form.append('file', file);
		return apiFetch(`/api/campaigns/${campaignId}/import/upload`, {
			method: 'POST',
			body: form,
		});
	},

	commit(
		campaignId: string,
		data: { entities: ImportPreview['entities']; attributes: ImportPreview['attributes']; cells: ImportPreview['cells'] }
	): Promise<ImportCommitResult> {
		return apiFetch(`/api/campaigns/${campaignId}/import/commit`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
	},

	downloadErrorReport(
		campaignId: string,
		rows: Record<string, string>[],
		errors: ImportErrorDetail[]
	): Promise<Blob> {
		return apiFetch(`/api/campaigns/${campaignId}/import/error-report`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ rows, errors }),
		}).then(async (res) => {
			// apiFetch returns parsed json by default; for blob we need raw fetch
			return res as unknown as Blob;
		});
	},

	async downloadErrorReportBlob(
		campaignId: string,
		rows: Record<string, string>[],
		errors: ImportErrorDetail[]
	): Promise<void> {
		const res = await fetch(`/api/campaigns/${campaignId}/import/error-report`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ rows, errors }),
		});
		if (!res.ok) {
			const err = await res.json().catch(() => ({ detail: res.statusText }));
			throw new Error(err.detail ?? `HTTP ${res.status}`);
		}
		const blob = await res.blob();
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'import-errors.csv';
		a.click();
		URL.revokeObjectURL(url);
	},
};
