import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const stored = browser ? (localStorage.getItem('theme') as 'dark' | 'light' | null) : null;

export const theme = writable<'dark' | 'light'>(stored ?? 'dark');

theme.subscribe((v) => {
	if (browser) {
		localStorage.setItem('theme', v);
		// Sync to server (fire-and-forget; silently fails if not logged in)
		fetch('/api/auth/preferences', {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ theme: v }),
			credentials: 'include'
		}).catch(() => {});
	}
});

/**
 * Initialize theme from server-side user data.
 * Called in +layout.svelte once the user is known.
 * Only overrides if a valid server value is provided.
 */
export function initTheme(userTheme: string | null | undefined): void {
	if (userTheme === 'dark' || userTheme === 'light') {
		theme.set(userTheme);
	}
}
