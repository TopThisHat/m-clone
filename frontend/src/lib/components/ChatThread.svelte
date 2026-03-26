<script lang="ts">
	import { tick } from 'svelte';
	import { marked } from 'marked';
	import { sanitizeHtml } from '$lib/utils/sanitize';
	import { tableExport } from '$lib/actions/tableExport';
	import {
		chatMessages,
		isStreaming,
		errorMessage,
		messageHistory,
		researchPhase,
		chartData,
		conflictWarnings,
		docContextExpired
	} from '$lib/stores/reportStore';
	import { startResearch, retryResearch } from '$lib/api/research';
	import ChartCard from './ChartCard.svelte';
	import ClarificationCard from './ClarificationCard.svelte';
	import { sourcePreview } from './SourcePreview.svelte';
	import { traceStore } from '$lib/stores/traceStore';
	import { pendingClarification } from '$lib/stores/reportStore';

	let threadEl = $state<HTMLDivElement | undefined>();
	let isAtBottom = true;
	let showScrollBtn = $state(false);

	// Build URL → snippet map from trace store
	const urlMap = $derived.by(() => {
		const map = new Map<string, string>();
		for (const step of $traceStore) {
			if (!step.preview) continue;
			// Extract URLs from preview text
			const urlMatches = [...step.preview.matchAll(/URL:\s*(https?:\/\/\S+)/g)];
			for (const m of urlMatches) {
				const url = m[1].trim();
				const snippet = step.preview.slice(0, 300);
				if (!map.has(url)) map.set(url, snippet);
			}
		}
		return map;
	});

	// ── Scroll management ────────────────────────────────────────────────────
	function onScroll() {
		if (!threadEl) return;
		const dist = threadEl.scrollHeight - threadEl.scrollTop - threadEl.clientHeight;
		isAtBottom = dist < 120;
		showScrollBtn = dist > 200;
	}

	function scrollToBottom() {
		if (!threadEl) return;
		threadEl.scrollTo({ top: threadEl.scrollHeight, behavior: 'smooth' });
		isAtBottom = true;
		showScrollBtn = false;
	}

	$effect(() => {
		const msgs = $chatMessages;
		const lastMsg = msgs[msgs.length - 1];
		if (lastMsg?.role === 'user') isAtBottom = true;

		if (isAtBottom) {
			tick().then(() => {
				if (threadEl) {
					threadEl.scrollTop = threadEl.scrollHeight;
					const dist = threadEl.scrollHeight - threadEl.scrollTop - threadEl.clientHeight;
					showScrollBtn = dist > 50;
				}
			});
		}
	});

	// ── Markdown rendering ───────────────────────────────────────────────────
	function renderMd(md: string): string {
		return md ? sanitizeHtml(marked.parse(md) as string) : '';
	}

	// ── Copy ─────────────────────────────────────────────────────────────────
	async function copyText(text: string, btn: HTMLButtonElement) {
		await navigator.clipboard.writeText(text);
		const orig = btn.textContent;
		btn.textContent = 'Copied';
		setTimeout(() => (btn.textContent = orig), 2000);
	}

	// ── Download Markdown ─────────────────────────────────────────────────────
	function downloadMarkdown(content: string, index: number) {
		const blob = new Blob([content], { type: 'text/markdown' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `research-${index + 1}.md`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// ── Download PDF ─────────────────────────────────────────────────────────
	async function downloadPdf(msgId: string, index: number) {
		const el = document.getElementById(`report-content-${msgId}`);
		if (!el) return;
		try {
			const html2pdf = (await import('html2pdf.js')).default;
			html2pdf()
				.set({
					margin: 12,
					filename: `research-report-${index + 1}.pdf`,
					image: { type: 'jpeg', quality: 0.98 },
					html2canvas: { scale: 2 },
					jsPDF: { unit: 'mm', format: 'a4' }
				})
				.from(el)
				.save();
		} catch {
			// html2pdf not available — silently fail
		}
	}

	// ── Share session ─────────────────────────────────────────────────────────
	import { activeSessionId, sessionList } from '$lib/stores/sessionStore';
	import { currentUser } from '$lib/stores/authStore';
	import { sessionComments } from '$lib/stores/reportStore';
	import HighlightableReport from './HighlightableReport.svelte';
	import ShareModal from './ShareModal.svelte';

	let showShareModal = $state(false);
	const activeSession = $derived($sessionList.find((s) => s.id === $activeSessionId));
	const currentVisibility = $derived(activeSession?.visibility ?? 'private');

	// ── Suggested follow-ups ─────────────────────────────────────────────────
	async function submitSuggestion(q: string) {
		if ($isStreaming) return;
		try {
			await startResearch(q, $messageHistory);
		} catch {
			// ignore
		}
	}

	// ── Phase label ──────────────────────────────────────────────────────────
	const phaseLabel: Record<string, string> = {
		planning: 'Planning...',
		searching: 'Searching...',
		evaluating: 'Evaluating...',
		writing: 'Writing...'
	};

	// ── Suggestions ────────────────────────────────────────────────────────
	const suggestions = [
		"Analyse Nvidia's competitive position in the AI chip market",
		'Compare Apple and Microsoft valuations for 2025',
		"Warren Buffett's investment philosophy and track record",
		'Emerging market debt risks in the current rate environment'
	];

	async function runSuggestion(q: string) {
		if ($isStreaming) return;
		try {
			await startResearch(q);
		} catch {
			// ignore
		}
	}

	// ── Chart matching ─────────────────────────────────────────────────────
	function chartsForMessage(content: string) {
		if (!content) return [];
		return $chartData.filter((c) =>
			content.includes(c.ticker) || content.toUpperCase().includes(c.ticker)
		);
	}
</script>

<div class="relative flex-1 overflow-hidden">
	<!-- Scrollable thread -->
	<div
		bind:this={threadEl}
		onscroll={onScroll}
		class="h-full overflow-y-auto px-6 py-6 space-y-6"
	>
		{#if $chatMessages.length === 0}
			<!-- Empty / welcome state -->
			<div class="flex flex-col items-center justify-center h-full gap-8 py-12">
				<div class="text-center">
					<div
						class="w-12 h-12 bg-gold rounded-sm flex items-center justify-center shadow-lg shadow-gold/10 mx-auto mb-4"
					>
						<span class="text-navy font-serif font-bold text-lg select-none">P</span>
					</div>
					<h2 class="font-serif text-2xl text-gold tracking-wide">Playbook Research</h2>
					<p class="text-slate-500 text-sm mt-2 font-light">Ask a research question to begin</p>
				</div>

				<div class="w-full max-w-md space-y-2">
					<p class="text-xs text-slate-600 uppercase tracking-widest text-center mb-3">
						Suggested queries
					</p>
					{#each suggestions as suggestion}
						<button
							onclick={() => runSuggestion(suggestion)}
							class="block w-full text-left text-sm text-slate-400 hover:text-slate-200 px-4 py-3
								border border-navy-700 hover:border-gold/30 rounded-lg hover:bg-navy-800
								transition-all truncate"
						>
							{suggestion}
						</button>
					{/each}
				</div>
			</div>
		{:else}
			{#if $docContextExpired}
				<div class="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-2 flex items-start gap-2">
					<svg class="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
					</svg>
					<div>
						<p class="text-xs text-amber-500 font-medium">Document context expired</p>
						<p class="text-xs text-amber-400/80">The uploaded documents for this session are no longer available. Follow-up questions will not include document context. Re-upload to restore.</p>
					</div>
				</div>
			{/if}
			{#each $chatMessages as msg, i (msg.id)}
				{@const isLast = i === $chatMessages.length - 1}

				{#if msg.role === 'user'}
					<!-- User bubble -->
					<div class="flex justify-end">
						<div
							class="max-w-[90%] md:max-w-[75%] bg-navy-700 border border-navy-600 rounded-2xl rounded-tr-sm px-5 py-3"
						>
							<p class="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
								{msg.content}
							</p>
							{#if msg.attachments?.length}
								<div class="flex flex-wrap gap-1.5 mt-2">
									{#each msg.attachments as att (att.filename)}
										<span class="inline-flex items-center gap-1 bg-navy-600 text-xs text-slate-300 rounded-full px-2 py-0.5">
											<svg class="w-3 h-3 text-slate-400 flex-shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
											</svg>
											<span class="truncate max-w-[120px]">{att.filename}</span>
											<span class="text-slate-500">{att.type}</span>
										</span>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				{:else}
					<!-- Assistant message -->
					<div class="flex flex-col gap-2">
						<!-- Author row -->
						<div class="flex items-center gap-2">
							<div
								class="w-6 h-6 bg-gold rounded-sm flex items-center justify-center flex-shrink-0"
							>
								<span class="text-navy font-serif font-bold text-xs select-none">P</span>
							</div>
							<span class="text-xs text-gold font-medium tracking-wide">Playbook Research</span>

							{#if msg.isStreaming}
								{#if $pendingClarification && msg.clarification && !msg.clarification.answered}
									<span class="text-xs text-gold/70 animate-pulse">Waiting for your input…</span>
								{:else if $researchPhase}
									<span class="text-xs text-slate-500 font-light">
										{phaseLabel[$researchPhase] ?? ''}
									</span>
								{/if}
								<span class="flex gap-1 ml-1">
									{#each [0, 1, 2] as j}
										<span
											class="w-1 h-1 bg-gold/50 rounded-full animate-bounce"
											style="animation-delay: {j * 0.15}s"
										></span>
									{/each}
								</span>
							{/if}
						</div>

						<!-- Clarification card (renders when agent needs user input) -->
						{#if msg.clarification}
							<ClarificationCard clarification={msg.clarification} />
						{/if}

						<!-- Conflict warning banner -->
						{#if msg.conflictWarnings?.length}
							<div class="bg-yellow-900/20 border border-yellow-700/40 rounded-lg px-4 py-2 flex items-start gap-2">
								<svg class="w-4 h-4 text-yellow-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
								</svg>
								<div>
									<p class="text-xs text-yellow-500 font-medium mb-0.5">Source conflict detected</p>
									{#each msg.conflictWarnings as warning}
										<p class="text-xs text-yellow-400/80">{warning}</p>
									{/each}
								</div>
							</div>
						{/if}

						<!-- Content card -->
						<div class="border border-navy-600 rounded-lg bg-navy-800/30 overflow-hidden">
							{#if msg.content}
								<!-- Action buttons -->
								<div class="flex justify-end gap-3 px-4 pt-3 pb-0">
									{#if isLast && !msg.isStreaming && $activeSessionId && $currentUser}
										<button
											onclick={() => (showShareModal = true)}
											class="text-xs text-slate-600 hover:text-gold transition-colors flex items-center gap-1"
											title="Share report"
										>
											<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
											</svg>
											Share
										</button>
									{/if}
									<button
										onclick={() => downloadPdf(msg.id, i)}
										class="text-xs text-slate-600 hover:text-gold transition-colors"
										title="Download as PDF"
									>
										Download PDF
									</button>
									<button
										onclick={() => downloadMarkdown(msg.content, i)}
										class="text-xs text-slate-600 hover:text-gold transition-colors"
										title="Download as Markdown"
									>
										Download .md
									</button>
									<button
										onclick={(e) => copyText(msg.content, e.currentTarget)}
										class="text-xs text-slate-600 hover:text-gold transition-colors"
									>
										Copy
									</button>
								</div>
								<div class="px-5 pb-5 pt-2">
									<div
										id="report-content-{msg.id}"
										use:sourcePreview={{ urlMap }}
									>
										{#if isLast && $activeSessionId && !msg.isStreaming}
											<HighlightableReport
												html={renderMd(msg.content)}
												comments={$sessionComments}
												canComment={!!$currentUser}
											/>
										{:else}
											<article use:tableExport class="prose prose-sm max-w-none">
												<!-- eslint-disable-next-line svelte/no-at-html-tags -->
												{@html renderMd(msg.content)}
											</article>
										{/if}
									</div>

									<!-- Sources footnote section -->
									{#if msg.sources?.length}
										<div class="mt-4 pt-4 border-t border-navy-700">
											<p class="text-xs text-slate-500 uppercase tracking-widest mb-2">Sources</p>
											<ol class="space-y-1">
												{#each msg.sources as src, i}
													<li class="text-xs text-slate-400">
														<span class="text-gold mr-1.5">[{i + 1}]</span>
														<a
															href={src.url}
															target="_blank"
															rel="noopener noreferrer"
															class="hover:text-gold underline underline-offset-2 transition-colors"
														>
															{src.title}
														</a>
														<span class="text-slate-600 ml-1">— {src.domain}</span>
													</li>
												{/each}
											</ol>
										</div>
									{/if}

									<!-- Inline charts for tickers mentioned in this report -->
									{#each chartsForMessage(msg.content) as chart}
										<ChartCard {chart} />
									{/each}
								</div>
							{:else if msg.isStreaming}
								<div class="px-5 py-5 flex items-center gap-3 text-slate-500 text-sm">
									<span class="flex gap-1">
										{#each [0, 1, 2] as j}
											<span
												class="w-1.5 h-1.5 bg-gold/40 rounded-full animate-bounce"
												style="animation-delay: {j * 0.15}s"
											></span>
										{/each}
									</span>
									<span class="font-light">Conducting research...</span>
								</div>
							{/if}
						</div>

						<!-- Suggested follow-ups (last completed message only) -->
						{#if isLast && !msg.isStreaming && !$isStreaming && msg.suggestions?.length}
							<div class="flex flex-wrap gap-2 pt-1">
								{#each msg.suggestions as suggestion}
									<button
										onclick={() => submitSuggestion(suggestion)}
										class="text-xs px-3 py-1.5 border border-navy-700 rounded-full text-slate-500
											hover:text-gold hover:border-gold/30 hover:bg-navy-800/50 transition-all"
									>
										{suggestion}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			{/each}

			<!-- Error with retry -->
			{#if $errorMessage}
				<div
					class="bg-red-900/20 border border-red-800/40 rounded-lg px-4 py-3 flex items-start justify-between gap-4"
				>
					<p class="text-red-400 text-sm leading-relaxed">{$errorMessage}</p>
					<button
						onclick={retryResearch}
						class="text-xs text-red-400 hover:text-red-300 border border-red-800/40 hover:border-red-600/40 rounded px-2.5 py-1 flex-shrink-0 transition-colors"
					>
						Retry
					</button>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Scroll-to-bottom button -->
	{#if showScrollBtn}
		<button
			onclick={scrollToBottom}
			class="absolute bottom-4 right-4 bg-navy-800 border border-navy-600 hover:border-gold/40 rounded-full w-8 h-8 flex items-center justify-center text-slate-400 hover:text-gold shadow-lg transition-all"
			title="Jump to latest"
			aria-label="Scroll to bottom"
		>
			↓
		</button>
	{/if}
</div>

{#if showShareModal && $activeSessionId}
	<ShareModal
		sessionId={$activeSessionId}
		{currentVisibility}
		onClose={() => (showShareModal = false)}
		onVisibilityChange={(v) => {
			sessionList.update((list) =>
				list.map((s) => (s.id === $activeSessionId ? { ...s, visibility: v } : s))
			);
		}}
	/>
{/if}
