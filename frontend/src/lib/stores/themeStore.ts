import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const stored = browser ? (localStorage.getItem('theme') as 'dark' | 'light' | null) : null;

export const theme = writable<'dark' | 'light'>(stored ?? 'dark');

theme.subscribe((v) => {
	if (browser) {
		localStorage.setItem('theme', v);
	}
});
