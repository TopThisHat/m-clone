export interface Monitor {
	id: string;
	owner_sid: string;
	label: string;
	query: string;
	frequency: 'daily' | 'weekly';
	last_run_at: string | null;
	next_run_at: string;
	created_at: string;
}

export interface MonitorCreate {
	label: string;
	query: string;
	frequency: 'daily' | 'weekly';
}

async function handleResponse<T>(res: Response): Promise<T> {
	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore
		}
		throw new Error(detail);
	}
	return res.json() as Promise<T>;
}

export async function listMonitors(): Promise<Monitor[]> {
	const res = await fetch('/api/monitors', { credentials: 'include' });
	return handleResponse<Monitor[]>(res);
}

export async function createMonitor(data: MonitorCreate): Promise<Monitor> {
	const res = await fetch('/api/monitors', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(data)
	});
	return handleResponse<Monitor>(res);
}

export async function deleteMonitor(id: string): Promise<void> {
	const res = await fetch(`/api/monitors/${id}`, {
		method: 'DELETE',
		credentials: 'include'
	});
	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			const err = await res.json();
			detail = err.detail ?? detail;
		} catch {
			// ignore
		}
		throw new Error(detail);
	}
}
