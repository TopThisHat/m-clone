import { apiFetch } from './apiFetch';

export interface Notification {
	id: string;
	recipient_sid: string;
	type: string;
	payload: Record<string, unknown>;
	read: boolean;
	created_at: string;
}

export async function fetchNotifications(): Promise<Notification[]> {
	try {
		return await apiFetch('/api/notifications');
	} catch {
		return []; // silently degrade on fetch error (e.g. not authenticated yet)
	}
}

export async function markRead(notificationId: string): Promise<void> {
	await apiFetch(`/api/notifications/${notificationId}/read`, {
		method: 'PATCH',
	});
}

export async function markAllRead(): Promise<void> {
	await apiFetch('/api/notifications/read-all', {
		method: 'POST',
	});
}
