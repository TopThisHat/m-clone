<script lang="ts">
	import { apiFetch } from '$lib/api/apiFetch';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';

	interface Props {
		onHighlight?: (entityIds: string[]) => void;
		onPath?: (paths: unknown[], sourceId: string, targetId: string) => void;
		/** Called when user wants to focus/center camera on a single entity node */
		onFocusNode?: (entityId: string) => void;
		/** Returns a display name for an entity ID, or null if not in current graph */
		lookupEntityName?: (entityId: string) => string | null;
		teamId?: string | null;
	}

	let { onHighlight, onPath, onFocusNode, lookupEntityName, teamId = null }: Props = $props();

	// ── State ─────────────────────────────────────────────────────────────────
	let messages = $state<ChatMessage[]>([]);
	let inputValue = $state('');
	let streaming = $state(false);
	let sessionId = $state<string | null>(null);
	let scrollEl = $state<HTMLDivElement | null>(null);
	let inputEl = $state<HTMLTextAreaElement | null>(null);
	let activeToolCalls = $state<Record<string, { name: string; status: string }>>({});

	interface ChatMessage {
		id: string;
		role: 'user' | 'assistant';
		content: string;
		entityHighlights?: string[];
		paths?: unknown[];
		pending?: boolean;
	}

	const STARTER_PROMPTS = [
		'Who works at Blackstone?',
		'Show me all ownership chains',
		'What connects Acme to GlobalCorp?',
	];

	// ── Scroll to bottom on new messages ─────────────────────────────────────
	$effect(() => {
		// Depend on messages length
		const _ = messages.length;
		if (scrollEl) {
			scrollEl.scrollTop = scrollEl.scrollHeight;
		}
	});

	// ── Send message ──────────────────────────────────────────────────────────
	async function sendMessage(text?: string) {
		const msg = (text ?? inputValue).trim();
		if (!msg || streaming) return;

		inputValue = '';
		streaming = true;
		activeToolCalls = {};

		const userMsgId = crypto.randomUUID();
		messages = [
			...messages,
			{ id: userMsgId, role: 'user', content: msg },
		];

		const assistantMsgId = crypto.randomUUID();
		messages = [
			...messages,
			{ id: assistantMsgId, role: 'assistant', content: '', pending: true },
		];

		const resolvedTeamId = teamId ?? $scoutTeam ?? undefined;

		try {
			const res = await fetch('/api/kg/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({
					message: msg,
					session_id: sessionId,
					team_id: resolvedTeamId,
				}),
			});

			if (!res.ok) {
				const err = await res.json().catch(() => ({ detail: 'Request failed' }));
				updateAssistantMsg(assistantMsgId, `Error: ${err.detail ?? 'Request failed'}`);
				return;
			}

			const reader = res.body?.getReader();
			if (!reader) return;

			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });

				// SSE blocks are separated by double newlines
				const blocks = buffer.split('\n\n');
				// Keep the last (possibly incomplete) block in the buffer
				buffer = blocks.pop() ?? '';

				for (const block of blocks) {
					if (!block.trim()) continue;
					const eventLine = block.split('\n').find((l) => l.startsWith('event: '));
					const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
					if (!eventLine || !dataLine) continue;

					const eventType = eventLine.slice(7).trim();
					try {
						const data = JSON.parse(dataLine.slice(6));
						handleSSEEvent(eventType, data, assistantMsgId);
					} catch {
						// ignore parse errors
					}
				}
			}
		} catch (err) {
			updateAssistantMsg(assistantMsgId, `Connection error: ${String(err)}`);
		} finally {
			streaming = false;
			activeToolCalls = {};
			// Remove pending flag
			messages = messages.map((m) =>
				m.id === assistantMsgId ? { ...m, pending: false } : m
			);
		}
	}

	function handleSSEEvent(type: string, data: Record<string, unknown>, assistantId: string) {
		switch (type) {
			case 'start':
				if (data.session_id && !sessionId) {
					sessionId = data.session_id as string;
				}
				break;

			case 'text_delta':
				appendAssistantToken(assistantId, data.token as string);
				break;

			case 'tool_call_start':
				activeToolCalls = {
					...activeToolCalls,
					[data.call_id as string]: {
						name: data.tool_name as string,
						status: 'executing',
					},
				};
				break;

			case 'tool_result':
				activeToolCalls = {
					...activeToolCalls,
					[data.call_id as string]: {
						name: (activeToolCalls[data.call_id as string]?.name ?? data.tool_name) as string,
						status: 'done',
					},
				};
				break;

			case 'kg_highlight':
				if (Array.isArray(data.entity_ids) && data.entity_ids.length > 0) {
					onHighlight?.(data.entity_ids as string[]);
					// Store on message for action buttons
					messages = messages.map((m) =>
						m.id === assistantId
							? { ...m, entityHighlights: data.entity_ids as string[] }
							: m
					);
				}
				break;

			case 'kg_path':
				if (Array.isArray(data.paths)) {
					onPath?.(data.paths, data.source_id as string, data.target_id as string);
					messages = messages.map((m) =>
						m.id === assistantId ? { ...m, paths: data.paths as unknown[] } : m
					);
				}
				break;

			case 'done':
				if (data.session_id && !sessionId) {
					sessionId = data.session_id as string;
				}
				break;

			case 'error':
				appendAssistantToken(assistantId, `\n\n[Error: ${data.message}]`);
				break;
		}
	}

	function appendAssistantToken(id: string, token: string) {
		messages = messages.map((m) =>
			m.id === id ? { ...m, content: m.content + token } : m
		);
	}

	function updateAssistantMsg(id: string, content: string) {
		messages = messages.map((m) =>
			m.id === id ? { ...m, content, pending: false } : m
		);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	function clearChat() {
		messages = [];
		sessionId = null;
		activeToolCalls = {};
	}

	function focusEntity(entityId: string) {
		onFocusNode?.(entityId);
	}

	function showAllOnGraph(entityIds: string[]) {
		onHighlight?.(entityIds);
	}

	function toolLabel(name: string): string {
		const labels: Record<string, string> = {
			search_kg_entities: 'Entity Search',
			get_entity_relationships: 'Relationships',
			find_connections: 'Path Finding',
			aggregate_kg: 'Analytics',
			get_entity_details: 'Entity Details',
			explore_neighborhood: 'Neighborhood',
		};
		return labels[name] ?? name;
	}
</script>

<div class="flex flex-col h-full bg-navy-950 border-r border-navy-700 overflow-hidden">
	<!-- Header -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-navy-700 bg-navy-900 shrink-0">
		<div class="flex items-center gap-2">
			<svg class="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
			</svg>
			<span class="text-xs font-medium text-slate-200">KG Chat</span>
		</div>
		{#if messages.length > 0}
			<button
				onclick={clearChat}
				class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
				title="Clear conversation"
			>
				Clear
			</button>
		{/if}
	</div>

	<!-- Active tool calls indicator -->
	{#if Object.keys(activeToolCalls).length > 0}
		<div class="px-3 py-1.5 bg-navy-900/60 border-b border-navy-700 shrink-0">
			<div class="flex flex-wrap gap-1">
				{#each Object.entries(activeToolCalls) as [callId, tc] (callId)}
					<span class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-navy-800 border border-navy-600 text-slate-400">
						{#if tc.status === 'executing'}
							<span class="w-1.5 h-1.5 rounded-full bg-gold animate-pulse"></span>
						{:else}
							<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
						{/if}
						{toolLabel(tc.name)}
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Messages -->
	<div
		bind:this={scrollEl}
		class="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0"
	>
		{#if messages.length === 0}
			<!-- Empty state with starter prompts -->
			<div class="flex flex-col gap-3 pt-4">
				<p class="text-xs text-slate-500 text-center">Ask anything about your knowledge graph</p>
				<div class="flex flex-col gap-1.5">
					{#each STARTER_PROMPTS as prompt (prompt)}
						<button
							onclick={() => sendMessage(prompt)}
							disabled={streaming}
							class="text-left text-xs px-3 py-2 rounded border border-navy-700 text-slate-400 hover:text-slate-200 hover:border-navy-500 hover:bg-navy-800/60 transition-colors disabled:opacity-40"
						>
							{prompt}
						</button>
					{/each}
				</div>
			</div>
		{:else}
			{#each messages as message (message.id)}
				<div class="flex flex-col gap-1 {message.role === 'user' ? 'items-end' : 'items-start'}">
					{#if message.role === 'user'}
						<div class="max-w-[85%] bg-navy-800 rounded-lg px-3 py-2 text-xs text-slate-200">
							{message.content}
						</div>
					{:else}
						<div class="w-full">
							<div class="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
								{#if message.pending && !message.content}
									<span class="inline-flex items-center gap-1 text-slate-500">
										<span class="w-1 h-1 rounded-full bg-slate-500 animate-bounce" style="animation-delay: 0ms"></span>
										<span class="w-1 h-1 rounded-full bg-slate-500 animate-bounce" style="animation-delay: 150ms"></span>
										<span class="w-1 h-1 rounded-full bg-slate-500 animate-bounce" style="animation-delay: 300ms"></span>
									</span>
								{:else}
									{message.content}
								{/if}
							</div>

							<!-- Action buttons when there are entity highlights -->
							{#if message.entityHighlights && message.entityHighlights.length > 0 && !message.pending}
								<div class="flex flex-wrap gap-1 mt-2">
									{#each message.entityHighlights as entityId (entityId)}
										{@const name = lookupEntityName?.(entityId) ?? null}
										<button
											onclick={() => focusEntity(entityId)}
											class="text-[10px] px-2 py-0.5 rounded border border-navy-600 text-slate-400 hover:text-gold hover:border-gold/40 transition-colors"
										>
											Focus {name ?? entityId.slice(0, 8) + '…'} in graph
										</button>
									{/each}
									{#if message.entityHighlights.length > 1}
										<button
											onclick={() => showAllOnGraph(message.entityHighlights!)}
											class="text-[10px] px-2 py-0.5 rounded border border-gold/40 text-gold hover:bg-gold/10 transition-colors"
										>
											Show all on graph
										</button>
									{/if}
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>

	<!-- Input -->
	<div class="shrink-0 border-t border-navy-700 p-2">
		<div class="flex items-end gap-2 bg-navy-800 border border-navy-600 rounded-lg px-2 py-1.5 focus-within:border-gold transition-colors">
			<textarea
				bind:this={inputEl}
				bind:value={inputValue}
				onkeydown={handleKeydown}
				placeholder="Ask about the knowledge graph..."
				disabled={streaming}
				rows={1}
				class="flex-1 bg-transparent text-xs text-slate-200 placeholder-slate-500 resize-none focus:outline-none min-h-[20px] max-h-[120px] disabled:opacity-50"
				style="field-sizing: content;"
			></textarea>
			<button
				onclick={() => sendMessage()}
				disabled={!inputValue.trim() || streaming}
				class="btn-gold text-xs px-2 py-1 rounded shrink-0 disabled:opacity-40"
				title="Send (Enter)"
			>
				{#if streaming}
					<svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
					</svg>
				{:else}
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
					</svg>
				{/if}
			</button>
		</div>
		<p class="text-[10px] text-slate-600 mt-1 text-center">Enter to send · Shift+Enter for newline</p>
	</div>
</div>
