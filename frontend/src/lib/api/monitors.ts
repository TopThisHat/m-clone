export interface Monitor {
	id: string;
	owner_sid: string;
	label: string;
	query: string;
	frequency: 'daily' | 'weekly';
	is_active: boolean;
	last_run_at: string | null;
	next_run_at: string;
	created_at: string;
}

export interface MonitorCreate {
	label: string;
	query: string;
	frequency: 'daily' | 'weekly';
}

export interface MonitorUpdate {
	label?: string;
	query?: string;
	frequency?: 'daily' | 'weekly';
	is_active?: boolean;
}

export interface MonitorRun {
	id: string;
	title: string | null;
	query: string | null;
	created_at: string;
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

export async function updateMonitor(id: string, data: MonitorUpdate): Promise<Monitor> {
	const res = await fetch(`/api/monitors/${id}`, {
		method: 'PATCH',
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

export async function triggerMonitor(id: string): Promise<{ triggered: boolean }> {
	const res = await fetch(`/api/monitors/${id}/trigger`, {
		method: 'POST',
		credentials: 'include'
	});
	return handleResponse<{ triggered: boolean }>(res);
}

export async function listMonitorRuns(id: string): Promise<MonitorRun[]> {
	const res = await fetch(`/api/monitors/${id}/runs`, { credentials: 'include' });
	return handleResponse<MonitorRun[]>(res);
}
