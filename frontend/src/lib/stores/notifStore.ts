import { writable, derived } from 'svelte/store';
import { fetchNotifications, type Notification } from '$lib/api/notifications';

function createNotifStore() {
	const { subscribe, set, update } = writable<Notification[]>([]);

	let intervalId: ReturnType<typeof setInterval> | null = null;

	async function refresh() {
		try {
			const data = await fetchNotifications();
			set(data);
		} catch {
			// silently ignore if not authenticated
		}
	}

	function startPolling() {
		refresh();
		intervalId = setInterval(refresh, 30_000);
	}

	function stopPolling() {
		if (intervalId !== null) {
			clearInterval(intervalId);
			intervalId = null;
		}
	}

	function markOneRead(id: string) {
		update((list) => list.map((n) => (n.id === id ? { ...n, read: true } : n)));
	}

	function markAllRead() {
		update((list) => list.map((n) => ({ ...n, read: true })));
	}

	return { subscribe, refresh, startPolling, stopPolling, markOneRead, markAllRead };
}

export const notifications = createNotifStore();
export const unreadCount = derived(notifications, ($n) => $n.filter((n) => !n.read).length);
