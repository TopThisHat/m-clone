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

// ── Multi-mode types ─────────────────────────────────────────────────────────

export interface ClassificationData {
	mode: string;
	reasoning: string;
	estimated_steps: number;
	batch_size: number | null;
	warning: boolean;
}

export interface ExecutionPlanStep {
	step_number: number;
	description: string;
	status: string;
}

export interface ExecutionPlan {
	task_summary: string;
	steps: ExecutionPlanStep[];
}

export interface ProgressData {
	message: string;
	phase: string;
	current?: number;
	total?: number;
	percent?: number;
	step_label?: string;
}

export interface BatchJob {
	job_id: string;
	item_count: number;
}

export interface ConfirmationPending {
	message: string;
	options?: string[];
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

// ── Multi-mode agent state ────────────────────────────────────────────────────

export const currentMode = writable<string | null>(null);
export const classificationData = writable<ClassificationData | null>(null);
export const executionPlan = writable<ExecutionPlan | null>(null);
export const progressData = writable<ProgressData | null>(null);
export const batchJob = writable<BatchJob | null>(null);
export const confirmationPending = writable<ConfirmationPending | null>(null);

export const reportStore = {
	setClassification(data: ClassificationData) {
		classificationData.set(data);
		currentMode.set(data.mode);
	},
	setProgress(data: ProgressData) {
		progressData.set(data);
	},
	setExecutionPlan(data: ExecutionPlan) {
		executionPlan.set(data);
	},
	updatePlanStep(data: { step_number: number; status: string }) {
		executionPlan.update((plan) => {
			if (!plan) return plan;
			return {
				...plan,
				steps: plan.steps.map((s) =>
					s.step_number === data.step_number ? { ...s, status: data.status } : s
				)
			};
		});
	},
	setBatchJob(data: BatchJob) {
		batchJob.set(data);
	},
	setConfirmation(data: ConfirmationPending) {
		confirmationPending.set(data);
	},
	reset() {
		currentMode.set(null);
		classificationData.set(null);
		executionPlan.set(null);
		progressData.set(null);
		batchJob.set(null);
		confirmationPending.set(null);
	}
};
