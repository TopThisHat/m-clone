import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const stored = browser ? (localStorage.getItem('theme') as 'dark' | 'light' | null) : null;

export const theme = writable<'dark' | 'light'>(stored ?? 'dark');

theme.subscribe((v) => {
	if (browser) {
		localStorage.setItem('theme', v);
		// Keep the <html> class in sync so the inline script and CSS agree
		document.documentElement.classList.toggle('theme-light', v === 'light');
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
 * Called once in +layout.svelte when the user is known.
 * Only updates if the server value differs from localStorage, preventing
 * an unnecessary flash caused by re-fetching on every page.
 */
export function initTheme(userTheme: string | null | undefined): void {
	if (userTheme === 'dark' || userTheme === 'light') {
		// Only update if there's no local preference yet
		if (!stored) {
			theme.set(userTheme);
		}
	}
}
