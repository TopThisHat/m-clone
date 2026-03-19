<script lang="ts">
	import { marked } from 'marked';
	import type { PageData } from './$types';
	import ResearchSwimlane from '$lib/components/ResearchSwimlane.svelte';
	import ChartCard from '$lib/components/ChartCard.svelte';
	import CommentThread from '$lib/components/CommentThread.svelte';
	import PresenceAvatars from '$lib/components/PresenceAvatars.svelte';
	import ReportDiff from '$lib/components/ReportDiff.svelte';
	import type { TraceStep } from '$lib/stores/traceStore';
	import type { ChartPayload } from '$lib/stores/reportStore';
	import type { Comment } from '$lib/api/comments';
	import { getLastSeen, setLastSeen, listComments } from '$lib/api/comments';
	import {
		forkSession,
		subscribe,
		unsubscribe,
		isSubscribed,
		heartbeatPresence,
		getPresence,
		getSessionDiff,
		type PresenceViewer,
		type SessionDiff,
	} from '$lib/api/sessions';
	import { currentUser } from '$lib/stores/authStore';
	import { theme } from '$lib/stores/themeStore';
	import { sessionComments } from '$lib/stores/reportStore';
	import { onMount, onDestroy, untrack } from 'svelte';
	import { tableExport } from '$lib/actions/tableExport';
	import { goto } from '$app/navigation';

	let { data }: { data: PageData } = $props();
	const session = $derived(data.session);
	const isPublic = $derived(session.visibility === 'public' || session.is_public);
	const chartPayloads = $derived(
		((session.trace_steps as TraceStep[]) ?? [])
			.filter((s) => s.chart)
			.map((s) => s.chart as unknown as ChartPayload)
	);

	let showSwimlane = $state(false);
	let showComments = $state(false);
	let copied = $state(false);

	// Live comments (Feature 1 & 3)
	let liveComments = $state<Comment[]>(untrack(() => (data.comments as Comment[]) ?? []));
	let unseenIds = $state(new Set<string>());
	let unseenCount = $derived(unseenIds.size);
	let pollInterval: ReturnType<typeof setInterval> | null = null;

	// Subscribe (Feature 10)
	let subscribed = $state(false);
	let subscribing = $state(false);

	// Presence (Feature 11)
	let viewers = $state<PresenceViewer[]>([]);
	let presenceInterval: ReturnType<typeof setInterval> | null = null;

	// Diff (Feature 12)
	let diff = $state<SessionDiff | null>(null);
	let showDiff = $state(false);
	let diffMode = $state<'unified' | 'side'>('unified');
	let loadingDiff = $state(false);

	// Forking (Feature 7)
	let forking = $state(false);

	// Seed the global comment store so CommentThread can operate
	onMount(async () => {
		sessionComments.set(liveComments);

		// Compute unread (Feature 3)
		const lastSeen = getLastSeen(session.id);
		if (lastSeen) {
			const seen = new Date(lastSeen).getTime();
			const initialUnseen = new Set(
				liveComments
					.filter((c) => new Date(c.created_at).getTime() > seen)
					.map((c) => c.id)
			);
			unseenIds = initialUnseen;
		}

		// Start live comment polling (Feature 1)
		pollInterval = setInterval(async () => {
			const fresh = await listComments(session.id).catch(() => null);
			if (!fresh) return;
			const existingIds = new Set(liveComments.map((c) => c.id));
			const newOnes = fresh.filter((c) => !existingIds.has(c.id));
			if (newOnes.length > 0) {
				if (!showComments) {
					unseenIds = new Set([...unseenIds, ...newOnes.map((c) => c.id)]);
				}
				liveComments = fresh;
				sessionComments.set(fresh);
			} else {
				// Update reactions etc even if no new comments
				liveComments = fresh;
				sessionComments.set(fresh);
			}
		}, 15_000);

		// Subscribe status (Feature 10)
		if ($currentUser && session.visibility === 'team') {
			subscribed = await isSubscribed(session.id).catch(() => false);
		}

		// Presence (Feature 11)
		if ($currentUser) {
			await heartbeatPresence(session.id).catch(() => {});
			viewers = await getPresence(session.id).catch(() => []);
			presenceInterval = setInterval(async () => {
				await heartbeatPresence(session.id).catch(() => {});
				viewers = await getPresence(session.id).catch(() => []);
			}, 20_000);
		}
	});

	onDestroy(() => {
		if (pollInterval) clearInterval(pollInterval);
		if (presenceInterval) clearInterval(presenceInterval);
	});

	function onCommentsOpen() {
		// Clear unseen when user opens comments
		unseenIds = new Set();
		setLastSeen(session.id);
	}

	async function handleFork() {
		if (forking || !$currentUser) return;
		forking = true;
		try {
			const forked = await forkSession(session.id);
			goto(`/?session=${forked.id}`);
		} catch {
			// ignore
		} finally {
			forking = false;
		}
	}

	async function handleSubscribe() {
		if (subscribing || !$currentUser) return;
		subscribing = true;
		try {
			if (subscribed) {
				await unsubscribe(session.id);
				subscribed = false;
			} else {
				await subscribe(session.id);
				subscribed = true;
			}
		} catch {
			// ignore
		} finally {
			subscribing = false;
		}
	}

	async function handleShowDiff() {
		if (diff) {
			showDiff = !showDiff;
			return;
		}
		loadingDiff = true;
		try {
			diff = await getSessionDiff(session.id);
			if (diff) showDiff = true;
		} catch {
			// ignore
		} finally {
			loadingDiff = false;
		}
	}

	// ── Table of contents ─────────────────────────────────────────────────────
	interface TocEntry { id: string; text: string; level: number; }

	const toc = $derived.by((): TocEntry[] => {
		if (!session.report_markdown) return [];
		const entries: TocEntry[] = [];
		const lines = session.report_markdown.split('\n');
		const usedIds = new Map<string, number>();
		for (const line of lines) {
			const m = line.match(/^(#{2,4})\s+(.+)/);
			if (!m) continue;
			const level = m[1].length;
			const text = m[2].trim();
			const baseId = text.toLowerCase().replace(/[^\w]+/g, '-').replace(/(^-|-$)/g, '');
			const count = usedIds.get(baseId) ?? 0;
			const id = count === 0 ? baseId : `${baseId}-${count}`;
			usedIds.set(baseId, count + 1);
			entries.push({ id, text, level });
		}
		return entries;
	});

	// ── Markdown → HTML with heading IDs ──────────────────────────────────────
	const reportHtml = $derived.by(() => {
		if (!session.report_markdown) return '';
		const usedIds = new Map<string, number>();
		const renderer = new marked.Renderer();
		renderer.heading = ({ text, depth }: { text: string; depth: number }) => {
			if (depth < 2 || depth > 4) return `<h${depth}>${text}</h${depth}>`;
			const baseId = text.toLowerCase().replace(/[^\w]+/g, '-').replace(/(^-|-$)/g, '');
			const count = usedIds.get(baseId) ?? 0;
			const id = count === 0 ? baseId : `${baseId}-${count}`;
			usedIds.set(baseId, count + 1);
			return `<h${depth} id="${id}">${text}</h${depth}>`;
		};
		return marked.parse(session.report_markdown, { renderer }) as string;
	});

	function scrollToHeading(id: string) {
		document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	// ── Reading time ──────────────────────────────────────────────────────────
	const readingTime = $derived(
		Math.max(1, Math.ceil((session.report_markdown?.split(/\s+/).length ?? 0) / 200))
	);

	// ── Download ──────────────────────────────────────────────────────────────
	function downloadMarkdown() {
		const blob = new Blob([session.report_markdown], { type: 'text/markdown' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${session.title.slice(0, 60).replace(/[^a-z0-9]/gi, '-')}.md`;
		a.click();
		URL.revokeObjectURL(url);
	}

	let pdfGenerating = $state(false);
	let pdfError = $state('');

	async function downloadPdf() {
		const el = document.getElementById('share-report-content');
		if (!el || pdfGenerating) return;
		pdfGenerating = true;
		pdfError = '';
		try {
			// Add PDF-safe class to neutralize CSS functions html2canvas can't handle
			el.classList.add('pdf-rendering');
			const html2pdf = (await import('html2pdf.js')).default;
			await html2pdf()
				.set({
					margin: 12,
					filename: `${session.title.slice(0, 60).replace(/[^a-z0-9]/gi, '-')}.pdf`,
					image: { type: 'jpeg', quality: 0.92 },
					html2canvas: { scale: 1.5, useCORS: true, logging: false },
					jsPDF: { unit: 'mm', format: 'a4' },
					pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
				})
				.from(el)
				.save();
		} catch (e) {
			pdfError = 'PDF generation failed. Try downloading as Markdown or DOCX instead.';
		} finally {
			el?.classList.remove('pdf-rendering');
			pdfGenerating = false;
		}
	}

	async function copyLink() {
		await navigator.clipboard.writeText(window.location.href).catch(() => {});
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	// Short excerpt for OG description
	const ogDescription = $derived(
		session.report_markdown?.replace(/[#*`_[\]]/g, '').slice(0, 200).trim() ?? ''
	);
</script>

<svelte:head>
	<title>{session.title} — Playbook Research</title>
	<meta name="description" content={ogDescription} />
	<meta property="og:type" content="article" />
	<meta property="og:title" content="{session.title} — Playbook Research" />
	<meta property="og:description" content={ogDescription} />
	<meta property="og:site_name" content="Playbook Research" />
	<meta name="twitter:card" content="summary" />
	<meta name="twitter:title" content={session.title} />
	<meta name="twitter:description" content={ogDescription} />
	{#if !isPublic}
		<meta name="robots" content="noindex" />
	{/if}
</svelte:head>

<div class="min-h-screen bg-navy-950" class:light={$theme === 'light'}>
	<!-- Sticky top bar -->
	<div class="sticky top-0 z-20 bg-navy-950/95 backdrop-blur border-b border-navy-700">
		<div class="max-w-6xl mx-auto px-4 sm:px-6 flex items-center gap-3 h-12">
			<a href="/" class="flex items-center gap-2 flex-shrink-0">
				<div class="w-6 h-6 bg-gold rounded-sm flex items-center justify-center">
					<span class="text-navy font-serif font-bold text-xs">P</span>
				</div>
			</a>
			<span class="text-xs text-slate-500 truncate flex-1">{session.title}</span>

			<!-- Presence avatars (Feature 11) -->
			{#if $currentUser && viewers.length > 0}
				<PresenceAvatars {viewers} currentSid={$currentUser.sid} />
			{/if}

			<div class="flex items-center gap-2 flex-shrink-0">
				<!-- Subscribe bell (Feature 10) -->
				{#if $currentUser && session.visibility === 'team'}
					<button
						onclick={handleSubscribe}
						disabled={subscribing}
						title={subscribed ? 'Unsubscribe from new comments' : 'Subscribe to new comments'}
						class="p-1.5 rounded text-xs border transition-all
							{subscribed ? 'border-gold/40 text-gold bg-gold/5' : 'border-navy-700 text-slate-500 hover:text-gold hover:border-gold/30'}"
					>
						{subscribed ? '🔔' : '🔕'}
					</button>
				{/if}

				<!-- Fork (Feature 7) -->
				{#if $currentUser}
					<button
						onclick={handleFork}
						disabled={forking}
						class="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs border border-navy-700 text-slate-500 hover:text-gold hover:border-gold/30 transition-all disabled:opacity-40"
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
						</svg>
						{forking ? 'Forking…' : 'Fork'}
					</button>
				{/if}

				{#if session.visibility === 'team' && $currentUser}
					<button
						onclick={() => { showComments = !showComments; if (showComments) onCommentsOpen(); }}
						class="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs border transition-all
							{showComments ? 'border-gold/40 text-gold bg-gold/5' : 'border-navy-700 text-slate-500 hover:text-gold hover:border-gold/30'}"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
						</svg>
						Comments
						{#if unseenCount > 0 && !showComments}
							<span class="bg-gold text-navy text-[9px] font-bold rounded-full px-1.5 leading-none py-0.5">{unseenCount}</span>
						{:else if liveComments.length > 0}
							<span class="bg-gold/20 text-gold rounded-full px-1.5 text-[10px]">{liveComments.length}</span>
						{/if}
					</button>
				{/if}
				<button
					onclick={copyLink}
					class="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs border border-navy-700 text-slate-500 hover:text-gold hover:border-gold/30 transition-all"
				>
					{copied ? 'Copied!' : 'Copy link'}
				</button>
			</div>
		</div>
	</div>

	<div class="max-w-6xl mx-auto px-4 sm:px-6 py-8 flex gap-6">

		<!-- TOC sidebar (desktop only, if ≥3 headings) -->
		{#if toc.length >= 3}
			<aside class="hidden lg:block w-52 flex-shrink-0">
				<div class="sticky top-20">
					<p class="text-[10px] text-slate-600 uppercase tracking-widest mb-3">Contents</p>
					<nav class="space-y-0.5">
						{#each toc as entry (entry.id)}
							<button
								onclick={() => scrollToHeading(entry.id)}
								class="block w-full text-left text-xs text-slate-500 hover:text-gold transition-colors leading-snug py-0.5"
								style="padding-left: {(entry.level - 2) * 12}px"
							>
								{entry.text}
							</button>
						{/each}
					</nav>
				</div>
			</aside>
		{/if}

		<!-- Main report column -->
		<div class="flex-1 min-w-0">
			<!-- Report metadata row -->
			<div class="mb-5">
				<div class="flex items-center gap-2 flex-wrap mb-2">
					<span class="text-xs text-slate-600">
						{new Date(session.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
					</span>
					<span class="text-slate-700">·</span>
					<span class="text-xs text-slate-600">{readingTime} min read</span>
					{#if isPublic}
						<span class="ml-auto flex items-center gap-1 text-[10px] text-slate-600 border border-navy-700 rounded-full px-2 py-0.5">
							<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							Public
						</span>
					{:else}
						<span class="ml-auto flex items-center gap-1 text-[10px] text-slate-600 border border-navy-700 rounded-full px-2 py-0.5">
							<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
							</svg>
							Team only
						</span>
					{/if}
				</div>
				<h1 class="font-serif text-xl sm:text-2xl text-slate-100 leading-snug">{session.title}</h1>
				<p class="text-sm text-slate-500 mt-1">{session.query}</p>
			</div>

			<!-- Action buttons -->
			{#if session.report_markdown}
				<div class="flex gap-2 mb-5 flex-wrap">
					<button
						onclick={downloadPdf}
						disabled={pdfGenerating}
						class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 transition-colors disabled:opacity-50"
					>
						{#if pdfGenerating}
							<span class="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
							Generating PDF…
						{:else}
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h4a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
							</svg>
							Download PDF
						{/if}
					</button>
					{#if pdfError}
						<span class="text-xs text-red-400">{pdfError}</span>
					{/if}
					<button
						onclick={downloadMarkdown}
						class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 transition-colors"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
						</svg>
						Download .md
					</button>
					<a
						href="/api/sessions/{session.id}/export?format=docx"
						download
						class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 transition-colors"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h4a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
						</svg>
						Download DOCX
					</a>

					<!-- Compare with previous (Feature 12) -->
					{#if session.parent_session_id || diff}
						<button
							onclick={handleShowDiff}
							disabled={loadingDiff}
							class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs border transition-colors disabled:opacity-40
								{showDiff ? 'border-gold/40 text-gold bg-gold/5' : 'text-slate-400 hover:text-gold border-navy-700 hover:border-gold/30 bg-navy-900'}"
						>
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
							</svg>
							{loadingDiff ? 'Loading…' : showDiff ? 'Hide diff' : 'Compare with previous'}
						</button>
					{/if}

					<!-- Mobile TOC -->
					{#if toc.length >= 3}
						<details class="lg:hidden relative">
							<summary class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-gold border border-navy-700 hover:border-gold/30 bg-navy-900 cursor-pointer list-none">
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7" />
								</svg>
								Contents
							</summary>
							<div class="absolute top-full left-0 mt-1 bg-navy-900 border border-navy-700 rounded-lg p-3 shadow-xl z-10 min-w-48">
								{#each toc as entry (entry.id)}
									<button
										onclick={() => scrollToHeading(entry.id)}
										class="block w-full text-left text-xs text-slate-500 hover:text-gold py-1 transition-colors"
										style="padding-left: {(entry.level - 2) * 10 + 4}px"
									>
										{entry.text}
									</button>
								{/each}
							</div>
						</details>
					{/if}
				</div>
			{/if}

			<!-- Diff view (Feature 12) -->
			{#if showDiff && diff}
				<div class="mb-6">
					<div class="flex items-center gap-2 mb-2">
						<span class="text-xs text-slate-500">
							Comparing with version from {diff.previous_date ? new Date(diff.previous_date).toLocaleDateString() : 'previous run'}
						</span>
						<div class="ml-auto flex gap-1">
							<button
								onclick={() => (diffMode = 'unified')}
								class="text-[10px] px-2 py-0.5 rounded border transition-colors {diffMode === 'unified' ? 'border-gold/40 text-gold' : 'border-navy-700 text-slate-500'}"
							>Unified</button>
							<button
								onclick={() => (diffMode = 'side')}
								class="text-[10px] px-2 py-0.5 rounded border transition-colors {diffMode === 'side' ? 'border-gold/40 text-gold' : 'border-navy-700 text-slate-500'}"
							>Side by side</button>
						</div>
					</div>
					<ReportDiff
						currentMarkdown={diff.current_markdown}
						previousMarkdown={diff.previous_markdown}
						mode={diffMode}
					/>
				</div>
			{/if}

			<!-- Report body -->
			{#if session.report_markdown}
				<div class="border border-navy-600 rounded-lg bg-navy-800/30 overflow-hidden mb-6">
					<div id="share-report-content" class="px-6 py-5">
						<article use:tableExport class="prose prose-sm max-w-none">
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html reportHtml}
						</article>
					</div>
				</div>
			{:else}
				<div class="text-slate-500 text-sm italic mb-6">No report content available.</div>
			{/if}

			<!-- Charts -->
			{#if chartPayloads.length > 0}
				<div class="mb-6 space-y-4">
					{#each chartPayloads as chart, i (i)}
						<ChartCard {chart} />
					{/each}
				</div>
			{/if}

			<!-- Research trace -->
			{#if session.trace_steps?.length}
				<div class="mb-6">
					<button
						onclick={() => (showSwimlane = !showSwimlane)}
						class="flex items-center gap-2 text-xs text-slate-500 hover:text-gold transition-colors"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
						</svg>
						{showSwimlane ? 'Hide' : 'Show'} research trace ({session.trace_steps.length} steps)
					</button>
					{#if showSwimlane}
						<div class="mt-3">
							<ResearchSwimlane steps={session.trace_steps as TraceStep[]} />
						</div>
					{/if}
				</div>
			{/if}

			<!-- Footer -->
			<div class="border-t border-navy-800 pt-6 mt-2 flex items-center justify-between flex-wrap gap-2">
				<div class="flex items-center gap-2">
					<div class="w-5 h-5 bg-gold rounded-sm flex items-center justify-center">
						<span class="text-navy font-serif font-bold text-[10px]">P</span>
					</div>
					<span class="text-xs text-slate-600">Generated by Playbook Research AI</span>
				</div>
				<p class="text-xs text-slate-700">For informational purposes only. Not investment advice.</p>
			</div>
		</div>

		<!-- Comments sidebar (team-shared, authenticated users) -->
		{#if showComments && session.visibility === 'team' && $currentUser}
			<aside class="w-80 flex-shrink-0">
				<div class="sticky top-20 max-h-[calc(100vh-5rem)] overflow-y-auto">
					<CommentThread
						sessionId={session.id}
						unseenIds={unseenIds}
						onCommentsChange={(comments) => {
							liveComments = comments;
						}}
					/>
				</div>
			</aside>
		{/if}
	</div>
</div>
