<script lang="ts">
	import { tick } from 'svelte';
	import { marked } from 'marked';
	import {
		chatMessages,
		isStreaming,
		errorMessage,
		messageHistory,
		researchPhase,
		chartData,
		conflictWarnings
	} from '$lib/stores/reportStore';
	import { startResearch, retryResearch } from '$lib/api/research';
	import ChartCard from './ChartCard.svelte';
	import { sourcePreview } from './SourcePreview.svelte';
	import { traceStore } from '$lib/stores/traceStore';

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
		return md ? (marked.parse(md) as string) : '';
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
	import { activeSessionId } from '$lib/stores/sessionStore';
	import { shareSession } from '$lib/api/sessions';

	async function copyShareLink(btn: HTMLButtonElement) {
		const id = $activeSessionId;
		if (!id) return;
		try {
			await shareSession(id);
			const shareUrl = `${window.location.origin}/share/${id}`;
			await navigator.clipboard.writeText(shareUrl);
			const orig = btn.textContent;
			btn.textContent = 'Link copied!';
			setTimeout(() => (btn.textContent = orig), 2000);
		} catch {
			// ignore
		}
	}

	// ── Suggested follow-ups ─────────────────────────────────────────────────
	async function submitSuggestion(q: string) {
		if ($isStreaming) return;
		try {
			await startResearch(q, undefined, $messageHistory);
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
								{#if $researchPhase}
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
									{#if isLast && !msg.isStreaming && $activeSessionId}
										<button
											onclick={(e) => copyShareLink(e.currentTarget)}
											class="text-xs text-slate-600 hover:text-gold transition-colors"
											title="Share report"
										>
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
										<article class="prose prose-sm max-w-none">
											<!-- eslint-disable-next-line svelte/no-at-html-tags -->
											{@html renderMd(msg.content)}
										</article>
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
