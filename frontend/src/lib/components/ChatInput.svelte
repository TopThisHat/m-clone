<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { fly } from 'svelte/transition';
	import { startResearch, cancelResearch } from '$lib/api/research';
	import {
		uploadDocument,
		uploadDocumentToSession,
		validateDroppedFile,
		ACCEPT_STRING,
		type UploadFileStatus
	} from '$lib/api/documents';
	import { get } from 'svelte/store';
	import { isStreaming, errorMessage, messageHistory, chatMessages, docSessionKey } from '$lib/stores/reportStore';
	import { activeSessionId } from '$lib/stores/sessionStore';

	let query = $state('');
	let documents = $state<UploadFileStatus[]>([]);
	let fileInput = $state<HTMLInputElement | undefined>();
	let textareaEl = $state<HTMLTextAreaElement | undefined>();

	// ── Research depth ──────────────────────────────────────────────────────
	let depth = $state<'fast' | 'balanced' | 'deep'>('balanced');

	// ── Model selection ─────────────────────────────────────────────────────
	let models = $state<{ id: string; label: string; description: string }[]>([]);
	let selectedModel = $state('openai:gpt-4o');

	onMount(async () => {
		try {
			const res = await fetch('/api/config/models');
			if (res.ok) {
				models = await res.json();
				if (models.length) selectedModel = models[0].id;
			}
		} catch {
			// silently ignore — model selector will be hidden
		}
	});

	// Reset local display state on any session transition (null, A→B, new research)
	// Intentional imperative reset — not derivable, these states have independent lifecycles
	// docSessionKey is NOT cleared here — that's handled by newResearch() and startResearch()
	$effect(() => {
		$activeSessionId; // track any change
		revokePreviewUrls(documents);
		documents = [];
		if (fileInput) fileInput.value = '';
	});

	let srAnnouncement = $state('');
	let streamingAnnouncement = $state('');
	let _streamingAnnouncementTimer: ReturnType<typeof setTimeout> | null = null;

	// Batch progress — non-null only during a processFiles call with 3+ valid files
	let uploadProgress = $state<{ completed: number; total: number } | null>(null);

	const uploading = $derived(documents.some((d) => d.status === 'uploading' || d.status === 'pending'));
	const showAttach = $derived(!$isStreaming);

	// Respect prefers-reduced-motion for chip entry animations
	const prefersReducedMotion =
		typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

	const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp']);
	function isImageFile(filename: string): boolean {
		const ext = filename.lastIndexOf('.') >= 0 ? filename.slice(filename.lastIndexOf('.')).toLowerCase() : '';
		return IMAGE_EXTENSIONS.has(ext);
	}

	function revokePreviewUrls(docs: typeof documents) {
		for (const d of docs) {
			if (d.previewUrl) URL.revokeObjectURL(d.previewUrl);
		}
	}

	onDestroy(() => revokePreviewUrls(documents));

	function getTypeLabel(filename: string): string {
		const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
		if (ext === '.pdf') return 'PDF';
		if (ext === '.xlsx' || ext === '.xls') return 'Excel';
		if (ext === '.csv') return 'CSV';
		if (ext === '.tsv') return 'TSV';
		if (ext === '.docx') return 'Word';
		if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) return 'Image';
		return 'File';
	}

	function getTypeBadgeClass(filename: string): string {
		const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
		if (ext === '.pdf') return 'bg-red-900/50 text-red-300';
		if (ext === '.docx') return 'bg-blue-900/50 text-blue-300';
		if (ext === '.xlsx' || ext === '.xls') return 'bg-green-900/50 text-green-300';
		if (ext === '.csv' || ext === '.tsv') return 'bg-teal-900/50 text-teal-300';
		if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) return 'bg-purple-900/50 text-purple-300';
		return 'bg-navy-600 text-gold';
	}

	function getMetaLabel(doc: UploadFileStatus): string | null {
		if (doc.status !== 'success' || !doc.result) return null;
		const r = doc.result;
		if (r.pages) return `${r.pages} pg`;
		if (r.sheets) return `${r.sheets} sheets`;
		if (r.rows) return `${r.rows} rows`;
		return null;
	}

	/** Shared upload pipeline used by file input, drop zone, and paste handler. */
	export async function processFiles(files: File[]) {
		if ($isStreaming) {
			if (_streamingAnnouncementTimer) clearTimeout(_streamingAnnouncementTimer);
			streamingAnnouncement = 'Wait for the current response to finish before attaching files.';
			_streamingAnnouncementTimer = setTimeout(() => { streamingAnnouncement = ''; }, 4000);
			return;
		}

		// Announce summary for mixed/multi-file drops
		const rejectedCount = files.filter(f => validateDroppedFile(f) !== null).length;
		const validCount = files.length - rejectedCount;
		if (files.length > 1) {
			srAnnouncement = rejectedCount > 0
				? `${validCount} file${validCount !== 1 ? 's' : ''} uploading. ${rejectedCount} file${rejectedCount !== 1 ? 's' : ''} rejected.`
				: `Uploading ${validCount} file${validCount !== 1 ? 's' : ''}.`;
		} else if (files.length === 1) {
			srAnnouncement = rejectedCount ? `${files[0].name} rejected.` : `Uploading ${files[0].name}.`;
		}

		// Show consolidated progress bar when uploading 3+ files in one batch
		if (validCount >= 3) {
			uploadProgress = { completed: 0, total: validCount };
		}

		for (const file of files) {
			const validationError = validateDroppedFile(file);
			if (validationError) {
				documents = [...documents, { filename: file.name, status: 'error', error: validationError }];
				continue;
			}

			const previewUrl = isImageFile(file.name) ? URL.createObjectURL(file) : undefined;
			const entry: UploadFileStatus = { filename: file.name, status: 'uploading', previewUrl };
			documents = [...documents, entry];
			const idx = documents.length - 1;

			try {
				const result = $docSessionKey
					? await uploadDocumentToSession(file, $docSessionKey)
					: await uploadDocument(file);
				docSessionKey.set(result.session_key);
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'success' as const, result } : d
				);
				srAnnouncement = `${file.name} uploaded successfully.`;
			} catch (err) {
				const errorMsg = err instanceof Error ? err.message : 'Upload failed';
				// store file ref on upload errors only — enables retry
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'error' as const, error: errorMsg, file } : d
				);
			}

			// Increment batch counter after each valid file completes (success or error)
			if (uploadProgress) {
				uploadProgress = { ...uploadProgress, completed: uploadProgress.completed + 1 };
			}
		}

		uploadProgress = null;
		textareaEl?.focus();
	}

	async function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const files = input.files;
		if (!files || files.length === 0) return;
		await processFiles(Array.from(files));
		if (fileInput) fileInput.value = '';
	}

	function handlePaste(e: ClipboardEvent) {
		const items = e.clipboardData?.items;
		if (!items) return;
		const files: File[] = [];
		for (const item of Array.from(items)) {
			if (item.kind === 'file') {
				const file = item.getAsFile();
				if (file) files.push(file);
			}
		}
		if (files.length > 0) {
			e.preventDefault();
			processFiles(files);
		}
	}

	function removeDocument(index: number) {
		const removed = documents[index];
		if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
		documents = documents.filter((_, i) => i !== index);
		if (documents.length === 0) {
			if (fileInput) fileInput.value = '';
			// Only clear the doc session store if no messages have been sent yet.
			// Once messages exist, session docs persist in Redis — chip removal is visual-only.
			if (get(chatMessages).length === 0) {
				docSessionKey.set(undefined);
			}
		}
	}

	async function retryDocument(index: number) {
		const doc = documents[index];
		if (!doc?.file) return;
		const file = doc.file;
		// Remove the error chip first, then re-process
		removeDocument(index);
		await processFiles([file]);
	}

	// 9.2: Capture docSessionKey, clear UI, then pass captured key
	async function handleSubmit() {
		const q = query.trim();
		if (!q || $isStreaming || uploading) return;

		const history = $messageHistory;

		// Capture attachment metadata from successfully-uploaded documents before clearing UI
		const attachments = documents
			.filter((d) => d.status === 'success')
			.map((d) => ({ filename: d.filename, type: getTypeLabel(d.filename) }));

		query = '';
		resetTextarea();
		errorMessage.set(null);

		if ($docSessionKey) {
			revokePreviewUrls(documents);
			documents = [];
			if (fileInput) fileInput.value = '';
			// docSessionKey is NOT cleared here — startResearch reads it from the store
			// and clears it after capturing the value
		}

		try {
			await startResearch(q, history, depth, selectedModel, attachments.length ? attachments : undefined);
		} catch (err) {
			if (err instanceof Error && err.name === 'AbortError') return;
			errorMessage.set(err instanceof Error ? err.message : 'An error occurred');
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}

	function resetTextarea() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
	}

	function autoResize() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = Math.min(textareaEl.scrollHeight, 160) + 'px';
	}

	const isTruncated = $derived(documents.some((d) => d.result?.truncated));

	const placeholder = $derived(
		$chatMessages.length > 0 ? 'Ask a follow-up question...' : 'Ask a research question...'
	);
</script>

<div class="flex flex-col gap-2">
	<!-- Screen reader announcements (visually hidden) -->
	<div class="sr-only" aria-live="polite" aria-atomic="true">{srAnnouncement}</div>
	<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{streamingAnnouncement}</div>

	<!-- Consolidated progress bar: shown for batches of 3+ files -->
	{#if uploadProgress !== null}
		<div
			class="px-2.5 py-2 bg-navy-700 border border-navy-600 rounded"
			role="progressbar"
			aria-valuenow={uploadProgress.completed}
			aria-valuemin={0}
			aria-valuemax={uploadProgress.total}
			aria-label="Uploading files: {uploadProgress.completed} of {uploadProgress.total} complete"
		>
			<div class="flex justify-between text-xs mb-1.5">
				<span class="text-slate-400">Uploading {uploadProgress.total} files…</span>
				<span class="text-gold tabular-nums">{uploadProgress.completed} / {uploadProgress.total}</span>
			</div>
			<div class="w-full bg-navy-800 rounded-full h-1 overflow-hidden">
				<div
					class="bg-gold h-1 rounded-full transition-[width] duration-300 ease-out"
					style="width: {uploadProgress.total > 0 ? Math.round((uploadProgress.completed / uploadProgress.total) * 100) : 0}%"
				></div>
			</div>
		</div>
	{/if}

	<!-- Document chips + errors -->
	{#if documents.length > 0}
		<div class="flex flex-wrap gap-1.5" role="list" aria-label="Attached files">
			{#each documents as doc, i (i)}
				<div
					role="listitem"
					in:fly={{ y: prefersReducedMotion ? 0 : -4, duration: prefersReducedMotion ? 0 : 150, delay: prefersReducedMotion ? 0 : i * 30 }}
					class="flex items-center gap-1.5 bg-navy-700 border rounded px-2.5 py-1
					       {doc.status === 'error' ? 'border-red-800/50' : 'border-navy-600'}"
				>
					{#if doc.status === 'uploading'}
						<span class="flex gap-0.5">
							{#each [0, 1, 2] as j (j)}
								<span
									class="w-1 h-1 bg-gold rounded-full motion-safe:animate-bounce"
									style="animation-delay: {j * 0.12}s"
								></span>
							{/each}
						</span>
					{:else if doc.previewUrl}
						<img
							src={doc.previewUrl}
							alt=""
							class="w-6 h-6 rounded object-cover flex-shrink-0"
							aria-hidden="true"
						/>
					{:else}
						<span
							class="text-xs font-medium px-1 py-0.5 rounded
							       {doc.status === 'error' ? 'bg-red-900/40 text-red-400' : getTypeBadgeClass(doc.filename)}"
						>
							{getTypeLabel(doc.filename)}
						</span>
					{/if}
					<span class="text-xs text-slate-300 truncate max-w-[120px]">{doc.filename}</span>
					{#if doc.status === 'success'}
						{@const meta = getMetaLabel(doc)}
						{#if meta}
							<span class="text-xs text-slate-500">{meta}</span>
						{/if}
					{/if}
					{#if doc.status === 'error'}
						<span class="text-xs text-red-400 truncate max-w-[100px]" role="alert">{doc.error}</span>
						{#if doc.file}
							<button
								onclick={() => retryDocument(i)}
								class="text-xs text-slate-500 hover:text-gold transition-colors flex-shrink-0"
								aria-label="Retry upload for {doc.filename}"
							>
								↺
							</button>
						{/if}
					{/if}
					{#if doc.status !== 'uploading'}
						<button
							onclick={() => removeDocument(i)}
							class="text-slate-500 hover:text-red-400 transition-colors text-xs ml-0.5 flex-shrink-0"
							aria-label="Remove {doc.filename}"
						>
							&#10005;
						</button>
					{/if}
				</div>
			{/each}
		</div>

		{#if isTruncated}
			<div class="flex items-center gap-2 px-2.5 py-1.5 bg-amber-900/20 border border-amber-700/40 rounded text-xs text-amber-400" role="status">
				<svg class="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
						d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
				</svg>
				Some documents were truncated to fit within the session size limit.
			</div>
		{/if}
	{/if}

	<!-- Input row -->
	<div class="flex items-end gap-2">
		<!-- Attach icon -->
		{#if showAttach}
			<button
				type="button"
				onclick={() => fileInput?.click()}
				disabled={uploading}
				class="flex-shrink-0 cursor-pointer text-slate-500 hover:text-gold transition-colors pb-3
				       disabled:pointer-events-none disabled:opacity-60"
				title="Attach documents"
				aria-label="Attach documents"
			>
				{#if uploading}
					<span class="flex gap-0.5 pb-0.5">
						{#each [0, 1, 2] as i (i)}
							<span
								class="w-1 h-1 bg-gold rounded-full motion-safe:animate-bounce"
								style="animation-delay: {i * 0.12}s"
							></span>
						{/each}
					</span>
				{:else}
					<svg class="w-5 h-5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="1.5"
							d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
						/>
					</svg>
				{/if}
			</button>
			<input
				bind:this={fileInput}
				type="file"
				accept={ACCEPT_STRING}
				multiple
				onchange={handleFileSelect}
				class="hidden"
				disabled={uploading}
			/>
		{/if}

		<!-- Textarea -->
		<textarea
			bind:this={textareaEl}
			bind:value={query}
			onkeydown={handleKeydown}
			oninput={autoResize}
			onpaste={handlePaste}
			{placeholder}
			rows="1"
			disabled={$isStreaming}
			aria-label="Research query"
			class="input-base flex-1 px-4 py-3 text-sm resize-none font-light leading-relaxed"
			style="min-height:48px; overflow:hidden;"
		></textarea>

		<!-- Send / Stop -->
		{#if $isStreaming}
			<button
				onclick={cancelResearch}
				aria-label="Stop research"
				class="flex-shrink-0 px-4 py-3 border border-navy-600 hover:border-red-700/50 text-slate-400
					   hover:text-red-400 rounded-lg transition-all text-sm"
			>
				Stop
			</button>
		{:else}
			<button
				onclick={handleSubmit}
				disabled={!query.trim() || uploading}
				class="flex-shrink-0 btn-gold px-4 py-3"
				title="Send (Enter)"
				aria-label="Send research query"
			>
				<svg class="w-4 h-4" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M14 5l7 7m0 0l-7 7m7-7H3"
					/>
				</svg>
			</button>
		{/if}
	</div>

	<!-- Depth + model controls -->
	{#if !$isStreaming}
		<div class="flex items-center gap-3 flex-wrap">
			<!-- Depth selector -->
			<div class="flex rounded-lg border border-navy-600 overflow-hidden text-xs" role="group" aria-label="Research depth">
				{#each ['fast', 'balanced', 'deep'] as d (d)}
					<button
						onclick={() => (depth = d as 'fast' | 'balanced' | 'deep')}
						aria-pressed={depth === d}
						class="flex-1 px-3 py-1.5 transition-colors
							{depth === d ? 'bg-navy-700 text-gold' : 'text-slate-500 hover:text-slate-300'}"
					>
						{d.charAt(0).toUpperCase() + d.slice(1)}
					</button>
				{/each}
			</div>

			<!-- Model picker (only when multiple models available) -->
			{#if models.length > 1}
				<select
					bind:value={selectedModel}
					aria-label="AI model"
					class="input-base text-xs py-1.5 px-3 w-auto"
				>
					{#each models as m (m.id)}
						<option value={m.id}>{m.label} — {m.description}</option>
					{/each}
				</select>
			{/if}

			<p class="text-xs text-slate-700 ml-auto">
				Enter to send · Shift+Enter for new line
			</p>
		</div>
	{/if}
</div>
