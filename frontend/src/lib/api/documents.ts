export interface UploadResult {
	session_key: string;
	filename: string;
	pages: number;
	char_count: number;
}

export async function uploadPdf(file: File): Promise<UploadResult> {
	const form = new FormData();
	form.append('file', file);

	const res = await fetch('/api/documents/upload', {
		method: 'POST',
		body: form
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
