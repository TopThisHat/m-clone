export interface UploadResult {
	session_key: string;
	filename: string;
	pages: number;
	char_count: number;
}

export interface KGUploadResult {
	session_id: string;
	filename: string;
	char_count: number;
	status: string;
	message: string;
}

export const SUPPORTED_EXTENSIONS = [
	'.pdf',
	'.docx',
	'.xlsx',
	'.xls',
	'.csv',
	'.tsv',
	'.png',
	'.jpg',
	'.jpeg',
	'.gif',
	'.webp'
];

export function isSupportedFile(filename: string): boolean {
	const ext = filename.lastIndexOf('.') >= 0 ? filename.slice(filename.lastIndexOf('.')).toLowerCase() : '';
	return SUPPORTED_EXTENSIONS.includes(ext);
}

export async function uploadPdf(file: File): Promise<UploadResult> {
	const form = new FormData();
	form.append('file', file);

	const res = await fetch('/api/documents/upload', {
		method: 'POST',
		body: form,
		credentials: 'include'
	});

	if (!res.ok) {
		let detail = 'Upload failed';
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore parse error
		}
		throw new Error(detail);
	}

	return res.json();
}

export async function uploadToKG(file: File, teamId?: string): Promise<KGUploadResult> {
	const form = new FormData();
	form.append('file', file);

	let url = '/api/documents/upload-to-kg';
	if (teamId) {
		url += `?team_id=${encodeURIComponent(teamId)}`;
	}

	const res = await fetch(url, {
		method: 'POST',
		body: form,
		credentials: 'include'
	});

	if (!res.ok) {
		let detail = 'Upload failed';
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore parse error
		}
		throw new Error(detail);
	}

	return res.json();
}
