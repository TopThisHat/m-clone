export interface Notification {
	id: string;
	recipient_sid: string;
	type: string;
	payload: Record<string, unknown>;
	read: boolean;
	created_at: string;
}

export async function fetchNotifications(): Promise<Notification[]> {
	const res = await fetch('/api/notifications', { credentials: 'include' });
	if (!res.ok) return []; // silently degrade on any error
	return res.json();
}

export async function markRead(notificationId: string): Promise<void> {
	await fetch(`/api/notifications/${notificationId}/read`, {
		method: 'PATCH',
		credentials: 'include',
	});
}

export async function markAllRead(): Promise<void> {
	await fetch('/api/notifications/read-all', {
		method: 'POST',
		credentials: 'include',
	});
}
