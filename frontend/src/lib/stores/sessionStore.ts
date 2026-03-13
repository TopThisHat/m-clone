import { writable } from 'svelte/store';
import { chatMessages, reportMarkdown, errorMessage, messageHistory, sessionComments } from '$lib/stores/reportStore';
import { traceStore } from '$lib/stores/traceStore';

export interface SessionSummary {
	id: string;
	title: string;
	query: string;
	created_at: string;
	updated_at: string;
	is_public?: boolean;
	usage_tokens?: number;
	owner_sid?: string | null;
	visibility?: string;
}

export const activeSessionId = writable<string | null>(null);
export const sessionList = writable<SessionSummary[]>([]);

export function newResearch() {
	chatMessages.set([]);
	reportMarkdown.set('');
	messageHistory.set(null);
	traceStore.reset();
	errorMessage.set(null);
	activeSessionId.set(null);
	sessionComments.set([]);
}
