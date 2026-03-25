import { writable, derived } from 'svelte/store';
import { marked } from 'marked';
import type { Comment } from '$lib/api/comments';

// Configure marked for safe rendering
marked.setOptions({ gfm: true, breaks: true });

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
export const streamingText = writable<string>('');
export const errorMessage = writable<string | null>(null);
export const messageHistory = writable<unknown[] | null>(null);

// New stores for enhanced features
export const chartData = writable<ChartPayload[]>([]);
export const conflictWarnings = writable<string[]>([]);
export const memoryContext = writable<string>('');
export const pendingClarification = writable<ClarificationData | null>(null);

export const reportHtml = derived(reportMarkdown, ($md) =>
	$md ? (marked.parse($md) as string) : ''
);

// Shared comment state so HighlightableReport can read what CommentThread loaded
export const sessionComments = writable<Comment[]>([]);

// Document upload session key — shared across ChatInput, research.ts, etc.
export const docSessionKey = writable<string | undefined>(undefined);
