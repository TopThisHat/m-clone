export interface User {
	sid: string;
	display_name: string;
	email: string;
	is_super_admin?: boolean;
}

export async function devLogin(sid: string, display_name: string, email = ''): Promise<boolean> {
	try {
		const res = await fetch('/api/auth/dev-login', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ sid, display_name, email }),
		});
		return res.ok;
	} catch {
		return false;
	}
}
