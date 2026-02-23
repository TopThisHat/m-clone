import { get } from 'svelte/store';
import { traceStore } from '$lib/stores/traceStore';
import {
	chatMessages,
	reportMarkdown,
	isStreaming,
	errorMessage,
	messageHistory,
	researchPhase,
	chartData,
	conflictWarnings,
	memoryContext
} from '$lib/stores/reportStore';
import type { ChartPayload } from '$lib/stores/reportStore';
import { activeSessionId, sessionList } from '$lib/stores/sessionStore';
import { createSession, updateSession, listSessions } from '$lib/api/sessions';
import type { ToolIconType } from '$lib/stores/traceStore';

let controller: AbortController | null = null;

// ── Suggestion generation ────────────────────────────────────────────────────

function generateSuggestions(markdown: string): string[] {
	const headers = [...markdown.matchAll(/^## (.+)$/gm)]
		.map((m) => m[1].trim())
		.filter((h) => !/^(sources|summary|takeaway|introduction|overview|conclusion)/i.test(h))
		.slice(0, 2)
		.map((h) => `Tell me more about ${h}`);

	const isFinancial =
		/\$[\d,]+|\bP\/E\b|\bmarket cap\b|\bstock\b|\brevenue\b|\bEBITDA\b/i.test(markdown);

	const generic = isFinancial
		? ['What are the key investment risks?', 'How does this compare to its peers?']
		: ['What are the main risks or challenges?', "What's the latest development in this area?"];

	return [...new Set([...headers, ...generic])].slice(0, 4);
}

// ── Core research runner ─────────────────────────────────────────────────────

export async function startResearch(
	query: string,
	pdfSessionKey?: string,
	msgHistory?: unknown[] | null
): Promise<void> {
	const isFollowUp = !!msgHistory;
	const originalQuery = query;

	if (controller) controller.abort();
	controller = new AbortController();

	const userMsgId = crypto.randomUUID();
	const asstMsgId = crypto.randomUUID();

	traceStore.reset();
	errorMessage.set(null);
	researchPhase.set(null);
	memoryContext.set('');
	conflictWarnings.set([]);

	if (!isFollowUp) {
		chatMessages.set([]);
		reportMarkdown.set('');
		messageHistory.set(null);
		activeSessionId.set(null);
		chartData.set([]);
	}

	chatMessages.update((msgs) => [...msgs, { id: userMsgId, role: 'user', content: originalQuery }]);
	chatMessages.update((msgs) => [
		...msgs,
		{ id: asstMsgId, role: 'assistant', content: '', isStreaming: true }
	]);

	isStreaming.set(true);

	const body: Record<string, unknown> = { query, pdf_session_key: pdfSessionKey ?? null };
	if (isFollowUp) body.message_history = msgHistory;

	let response: Response;
	try {
		response = await fetch('/api/research', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
			signal: controller.signal
		});
	} catch (err) {
		isStreaming.set(false);
		researchPhase.set(null);
		chatMessages.update((msgs) => msgs.filter((m) => m.id !== asstMsgId));
		if (err instanceof Error && err.name === 'AbortError') return;
		throw err;
	}

	if (!response.ok || !response.body) {
		isStreaming.set(false);
		researchPhase.set(null);
		chatMessages.update((msgs) => msgs.filter((m) => m.id !== asstMsgId));
		throw new Error(`Research request failed: ${response.status} ${response.statusText}`);
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	let accumulatedText = '';
	let finalReportData: Record<string, unknown> | null = null;

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });
			const messages = buffer.split('\n\n');
			buffer = messages.pop() ?? '';

			for (const msg of messages) {
				if (!msg.trim()) continue;
				const lines = msg.split('\n');
				let eventType = '';
				let dataStr = '';
				for (const line of lines) {
					if (line.startsWith('event: ')) eventType = line.slice(7).trim();
					if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
				}
				if (!eventType || !dataStr) continue;
				let data: Record<string, unknown>;
				try {
					data = JSON.parse(dataStr);
				} catch {
					continue;
				}
				const result = handleSSEEvent(eventType, data, accumulatedText, isFollowUp, query, asstMsgId);
				accumulatedText = result.accumulatedText;
				if (result.finalReportData) finalReportData = result.finalReportData;
			}
		}

		if (finalReportData) {
			const currentId = get(activeSessionId);
			const report = get(reportMarkdown);
			const steps = get(traceStore);
			try {
				if (currentId) {
					await updateSession(currentId, {
						report_markdown: report,
						message_history: finalReportData.messages as unknown[],
						trace_steps: steps
					});
				} else {
					const s = await createSession({
						title: originalQuery.slice(0, 80),
						query: originalQuery,
						report_markdown: report,
						message_history: finalReportData.messages as unknown[],
						trace_steps: steps
					});
					activeSessionId.set(s.id);
				}
				sessionList.set(await listSessions());
			} catch {
				// non-fatal
			}
		}
	} catch (err) {
		if (err instanceof Error && err.name === 'AbortError') return;
		errorMessage.set(err instanceof Error ? err.message : 'An unknown error occurred');
		chatMessages.update((msgs) =>
			msgs.map((m) => (m.id === asstMsgId ? { ...m, isStreaming: false } : m))
		);
	} finally {
		isStreaming.set(false);
		researchPhase.set(null);
	}
}

export async function retryResearch(): Promise<void> {
	const msgs = get(chatMessages);
	let lastUserIdx = -1;
	for (let i = msgs.length - 1; i >= 0; i--) {
		if (msgs[i].role === 'user') {
			lastUserIdx = i;
			break;
		}
	}
	if (lastUserIdx === -1) return;

	const lastQuery = msgs[lastUserIdx].content;
	const history = get(messageHistory);

	chatMessages.update((m) => m.slice(0, lastUserIdx));
	errorMessage.set(null);

	await startResearch(lastQuery, undefined, history);
}

// ── SSE event handler ────────────────────────────────────────────────────────

function handleSSEEvent(
	eventType: string,
	data: Record<string, unknown>,
	accumulatedText: string,
	isFollowUp: boolean,
	query: string,
	asstMsgId: string
): { accumulatedText: string; finalReportData: Record<string, unknown> | null } {
	let finalReportData: Record<string, unknown> | null = null;

	switch (eventType) {
		case 'memory_context': {
			const ctx = data.context as string;
			if (ctx) memoryContext.set(ctx);
			break;
		}

		case 'tool_call_start': {
			const toolName = data.tool_name as string;
			if (toolName === 'create_research_plan') {
				researchPhase.set('planning');
			} else if (toolName === 'evaluate_research_completeness') {
				researchPhase.set('evaluating');
			} else {
				researchPhase.set('searching');
			}
			traceStore.addStep({
				id: data.call_id as string,
				toolName,
				toolLabel: data.tool_label as string,
				icon: (data.icon as ToolIconType) ?? 'tool',
				status: 'pending'
			});
			break;
		}

		case 'tool_executing':
			traceStore.updateStep(data.call_id as string, {
				status: 'running',
				args: data.args as Record<string, unknown>
			});
			break;

		case 'tool_result':
			traceStore.updateStep(data.call_id as string, {
				status: 'done',
				preview: data.preview as string
			});
			break;

		case 'chart_data': {
			const chart = data.chart as ChartPayload;
			if (chart) chartData.update((d) => [...d, chart]);
			break;
		}

		case 'conflict_warning': {
			const warnings = data.warnings as string[];
			if (warnings?.length) conflictWarnings.set(warnings);
			break;
		}

		case 'text_delta': {
			const token = (data.token as string) ?? '';
			accumulatedText += token;
			researchPhase.set('writing');
			chatMessages.update((msgs) =>
				msgs.map((m) => (m.id === asstMsgId ? { ...m, content: accumulatedText } : m))
			);
			break;
		}

		case 'final_report': {
			const md = data.markdown as string;
			const suggestions = generateSuggestions(md);
			const warnings = (data.conflict_warnings as string[]) || get(conflictWarnings);

			chatMessages.update((msgs) =>
				msgs.map((m) =>
					m.id === asstMsgId
						? { ...m, content: md, isStreaming: false, suggestions, conflictWarnings: warnings }
						: m
				)
			);
			if (isFollowUp) {
				reportMarkdown.update(
					(prev) => prev + '\n\n---\n\n**Follow-up: ' + query + '**\n\n' + md
				);
			} else {
				reportMarkdown.set(md);
			}
			if (data.messages) {
				messageHistory.set(data.messages as unknown[]);
			}
			finalReportData = data;
			break;
		}

		case 'error':
			errorMessage.set(data.message as string);
			chatMessages.update((msgs) =>
				msgs.map((m) => (m.id === asstMsgId ? { ...m, isStreaming: false } : m))
			);
			break;

		case 'done':
			isStreaming.set(false);
			break;
	}

	return { accumulatedText, finalReportData };
}

export function cancelResearch(): void {
	controller?.abort();
	isStreaming.set(false);
}
