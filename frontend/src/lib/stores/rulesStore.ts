import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export interface Rule {
	id: string;
	text: string;
	createdAt: string;
}

const stored: Rule[] = browser
	? JSON.parse(localStorage.getItem('research_rules') ?? '[]')
	: [];

export const rules = writable<Rule[]>(stored);

rules.subscribe((v) => {
	if (browser) localStorage.setItem('research_rules', JSON.stringify(v));
});

export function addRule(text: string): void {
	const trimmed = text.trim();
	if (!trimmed) return;
	rules.update((rs) => [
		...rs,
		{ id: crypto.randomUUID(), text: trimmed, createdAt: new Date().toISOString() }
	]);
}

export function deleteRule(id: string): void {
	rules.update((rs) => rs.filter((r) => r.id !== id));
}
