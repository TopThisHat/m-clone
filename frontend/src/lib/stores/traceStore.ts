import { writable } from 'svelte/store';

export type TraceStepStatus = 'pending' | 'running' | 'done' | 'error';
export type ToolIconType = 'search' | 'book' | 'chart' | 'document' | 'plan' | 'evaluate' | 'tool';

export interface TraceStep {
	id: string;
	toolName: string;
	toolLabel: string;
	icon: ToolIconType;
	status: TraceStepStatus;
	args?: Record<string, unknown>;
	preview?: string;
	timestamp: number;
}

function createTraceStore() {
	const { subscribe, update, set } = writable<TraceStep[]>([]);

	return {
		subscribe,
		reset: () => set([]),
		restore: (steps: TraceStep[]) => set(steps),

		addStep: (step: Omit<TraceStep, 'timestamp'>) =>
			update((steps) => [...steps, { ...step, timestamp: Date.now() }]),

		updateStep: (id: string, patch: Partial<TraceStep>) =>
			update((steps) => steps.map((s) => (s.id === id ? { ...s, ...patch } : s)))
	};
}

export const traceStore = createTraceStore();
