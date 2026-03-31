import { apiFetch } from './apiFetch';

// ── Query types ────────────────────────────────────────────────────────────────

export interface MatchEntry {
	/** Extracted value — scalar for single-column, keyed dict for multi-column paired queries */
	value: string | Record<string, string>;
	/** Column name (string) or array of column names for paired queries */
	source_column: string | string[];
	/** 1-based row numbers where this match was found */
	row_numbers: number[];
	/** Extraction confidence in range [0, 1] */
	confidence: number;
	/** Character-level positions within source text (prose documents only) */
	text_positions?: { start: number; end: number }[];
}

export interface QueryResult {
	matches: MatchEntry[];
	/** Human-readable summary of how the query was interpreted — always a non-empty string */
	query_interpretation: string;
	/** Full match count, even when matches array is truncated by limit */
	total_matches: number;
	/** Null on success; human-readable message on any failure condition */
	error: string | null;
}

export interface ColumnClassificationDetail {
	/** Import role assigned by the LLM classifier */
	role: 'entity_label' | 'entity_gwm_id' | 'entity_description' | 'attribute';
	/** Semantic category of the column's values */
	semantic_type: 'person' | 'organization' | 'location' | 'date' | 'financial_amount' | 'generic';
	/** Classifier confidence in range [0, 1] */
	confidence: number;
	/** LLM reasoning for the classification */
	reasoning: string;
}

// ── API functions ───────────────────────────────────────────────────────────────

export async function queryDocument(
	sessionKey: string,
	query: string,
	limit?: number
): Promise<QueryResult> {
	const url = limit != null
		? `/api/documents/query?limit=${limit}`
		: '/api/documents/query';

	return apiFetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ session_key: sessionKey, query }),
	});
}

// ── Document types ──────────────────────────────────────────────────────────────

export interface DocumentInfo {
	filename: string;
	type: string;
	char_count?: number;
	pages?: number;
	sheets?: number;
	rows?: number;
}

export interface UploadResult {
	session_key: string;
	filename: string;
	char_count: number;
	session_char_count: number;
	type: string;
	truncated: boolean;
	pages?: number;
	sheets?: number;
	rows?: number;
	documents: DocumentInfo[];
}

export interface UploadFileStatus {
	filename: string;
	status: 'pending' | 'uploading' | 'success' | 'error';
	error?: string;
	result?: UploadResult;
	previewUrl?: string;
	file?: File;
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

export const ACCEPT_STRING = SUPPORTED_EXTENSIONS.join(',');

export const MAX_CLIENT_FILE_SIZE_MB = 20;
export const MAX_CLIENT_FILE_SIZE = MAX_CLIENT_FILE_SIZE_MB * 1024 * 1024;

export function isSupportedFile(filename: string): boolean {
	const ext = filename.lastIndexOf('.') >= 0 ? filename.slice(filename.lastIndexOf('.')).toLowerCase() : '';
	return SUPPORTED_EXTENSIONS.includes(ext);
}

/** Returns null for valid files, or an error message string for invalid ones. */
export function validateDroppedFile(file: File): string | null {
	if (!isSupportedFile(file.name)) {
		const ext = file.name.lastIndexOf('.') >= 0 ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : '(no extension)';
		return `Unsupported file type: ${ext}`;
	}
	if (file.size > MAX_CLIENT_FILE_SIZE) {
		return `File exceeds ${MAX_CLIENT_FILE_SIZE_MB} MB limit`;
	}
	return null;
}

export async function uploadDocument(file: File): Promise<UploadResult> {
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

export async function uploadDocumentToSession(file: File, sessionKey: string): Promise<UploadResult> {
	const form = new FormData();
	form.append('file', file);

	const res = await fetch(`/api/documents/upload?session_key=${encodeURIComponent(sessionKey)}`, {
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

export async function checkDocSessionAlive(sessionKey: string): Promise<boolean> {
	const res = await fetch(
		`/api/documents/status?session_key=${encodeURIComponent(sessionKey)}`,
		{ credentials: 'include' }
	);
	if (!res.ok) return false;
	const data = await res.json();
	return data.alive ?? false;
}

export async function uploadToKG(file: File, teamId?: string): Promise<KGUploadResult> {
	const form = new FormData();
	form.append('file', file);

	const params = new URLSearchParams({ mode: 'kg' });
	if (teamId) params.set('team_id', teamId);
	const url = `/api/documents/upload?${params.toString()}`;

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
