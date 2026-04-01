import { writable } from 'svelte/store';
import type { Comment } from '$lib/api/comments';
import type { QueryResult } from '$lib/api/documents';

export interface ChatSource {
	url: string;
	title: string;
	domain: string;
}

export interface ClarificationData {
	clarification_id: string;
	question: string;
	context: string | null;
	options: string[];
	answer?: string;
	answered: boolean;
}

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	isStreaming?: boolean;
	suggestions?: string[];
	conflictWarnings?: string[];
	sources?: ChatSource[];
	clarification?: ClarificationData;
	attachments?: { filename: string; type: string }[];
	queryResult?: QueryResult;
}

export interface ChartPayload {
	ticker: string;
	period: string;
	type: string;
	labels: string[];
	values: number[];
	pct_change: number;
}

export type ResearchPhase = 'planning' | 'searching' | 'evaluating' | 'writing' | null;
export const researchPhase = writable<ResearchPhase>(null);

export const chatMessages = writable<ChatMessage[]>([]);
export const reportMarkdown = writable<string>('');
export const isStreaming = writable<boolean>(false);
export const errorMessage = writable<string | null>(null);
export const messageHistory = writable<unknown[] | null>(null);

// New stores for enhanced features
export const chartData = writable<ChartPayload[]>([]);
export const conflictWarnings = writable<string[]>([]);
export const memoryContext = writable<string>('');
export const pendingClarification = writable<ClarificationData | null>(null);

// Shared comment state so HighlightableReport can read what CommentThread loaded
export const sessionComments = writable<Comment[]>([]);

// Document upload session key — shared across ChatInput, research.ts, etc.
export const docSessionKey = writable<string | undefined>(undefined);

// True when a restored session had a doc key but the Redis content has expired.
export const docContextExpired = writable<boolean>(false);
