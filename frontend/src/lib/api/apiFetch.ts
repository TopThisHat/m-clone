export async function apiFetch(path: string, init: RequestInit = {}) {
	const res = await fetch(path, { credentials: 'include', ...init });
	if (!res.ok) {
		if (res.status === 401 && typeof window !== 'undefined') {
			window.location.href = '/login';
			throw new Error('Session expired');
		}
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? `HTTP ${res.status}`);
	}
	if (res.status === 204) return null;
	return res.json();
}
