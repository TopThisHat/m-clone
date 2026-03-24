<script lang="ts">
	import { onMount } from 'svelte';
	import { startResearch, cancelResearch } from '$lib/api/research';
	import {
		uploadDocument,
		uploadDocumentToSession,
		ACCEPT_STRING,
		type UploadFileStatus
	} from '$lib/api/documents';
	import { isStreaming, errorMessage, messageHistory, chatMessages } from '$lib/stores/reportStore';
	import { activeSessionId } from '$lib/stores/sessionStore';

	let query = $state('');
	let documents = $state<UploadFileStatus[]>([]);
	let docSessionKey = $state<string | undefined>(undefined);
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

	// 9.4: Reset when activeSessionId becomes null (new research)
	// Intentional imperative reset — not derivable, these states have independent lifecycles
	$effect(() => {
		if ($activeSessionId === null) {
			documents = [];
			docSessionKey = undefined;
		}
	});

	const uploading = $derived(documents.some((d) => d.status === 'uploading' || d.status === 'pending'));
	const showAttach = $derived(!$isStreaming);

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

	function getMetaLabel(doc: UploadFileStatus): string | null {
		if (doc.status !== 'success' || !doc.result) return null;
		const r = doc.result;
		if (r.pages) return `${r.pages} pg`;
		if (r.sheets) return `${r.sheets} sheets`;
		if (r.rows) return `${r.rows} rows`;
		return null;
	}

	async function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const files = input.files;
		if (!files || files.length === 0) return;

		const fileList = Array.from(files);

		for (const file of fileList) {
			const entry: UploadFileStatus = { filename: file.name, status: 'uploading' };
			documents = [...documents, entry];
			const idx = documents.length - 1;

			try {
				const result = docSessionKey
					? await uploadDocumentToSession(file, docSessionKey)
					: await uploadDocument(file);

				docSessionKey = result.session_key;
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'success' as const, result } : d
				);
			} catch (err) {
				const errorMsg = err instanceof Error ? err.message : 'Upload failed';
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'error' as const, error: errorMsg } : d
				);
			}
		}

		if (fileInput) fileInput.value = '';
	}

	function removeDocument(index: number) {
		documents = documents.filter((_, i) => i !== index);
		if (documents.length === 0) {
			docSessionKey = undefined;
		}
	}

	// 9.2: Capture docSessionKey, clear UI, then pass captured key
	async function handleSubmit() {
		const q = query.trim();
		if (!q || $isStreaming || uploading) return;

		const history = $messageHistory;
		const capturedDocKey = docSessionKey;

		query = '';
		resetTextarea();
		errorMessage.set(null);

		if (capturedDocKey) {
			docSessionKey = undefined;
			documents = [];
			if (fileInput) fileInput.value = '';
		}

		try {
			await startResearch(q, capturedDocKey, history, depth, selectedModel);
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
	<!-- Document chips + errors -->
	{#if documents.length > 0}
		<div class="flex flex-wrap gap-1.5">
			{#each documents as doc, i (i)}
				<div
					class="flex items-center gap-1.5 bg-navy-700 border rounded px-2.5 py-1
					       {doc.status === 'error' ? 'border-red-800/50' : 'border-navy-600'}"
				>
					{#if doc.status === 'uploading'}
						<span class="flex gap-0.5">
							{#each [0, 1, 2] as j (j)}
								<span
									class="w-1 h-1 bg-gold rounded-full animate-bounce"
									style="animation-delay: {j * 0.12}s"
								></span>
							{/each}
						</span>
					{:else}
						<span
							class="text-[10px] font-medium px-1 py-0.5 rounded
							       {doc.status === 'error' ? 'bg-red-900/40 text-red-400' : 'bg-navy-600 text-gold'}"
						>
							{getTypeLabel(doc.filename)}
						</span>
					{/if}
					<span class="text-xs text-slate-300 truncate max-w-[120px]">{doc.filename}</span>
					{#if doc.status === 'success'}
						{@const meta = getMetaLabel(doc)}
						{#if meta}
							<span class="text-[10px] text-slate-500">{meta}</span>
						{/if}
					{/if}
					{#if doc.status === 'error'}
						<span class="text-[10px] text-red-400 truncate max-w-[100px]">{doc.error}</span>
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
			<p class="text-amber-400 text-xs px-1">
				Some documents were truncated to fit within the session size limit.
			</p>
		{/if}
	{/if}

	<!-- Input row -->
	<div class="flex items-end gap-2">
		<!-- Attach icon -->
		{#if showAttach}
			<label
				class="flex-shrink-0 cursor-pointer text-slate-500 hover:text-gold transition-colors pb-3
				       {uploading ? 'pointer-events-none opacity-60' : ''}"
				title="Attach documents"
			>
				{#if uploading}
					<span class="flex gap-0.5 pb-0.5">
						{#each [0, 1, 2] as i (i)}
							<span
								class="w-1 h-1 bg-gold rounded-full animate-bounce"
								style="animation-delay: {i * 0.12}s"
							></span>
						{/each}
					</span>
				{:else}
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="1.5"
							d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
						/>
					</svg>
				{/if}
				<input
					bind:this={fileInput}
					type="file"
					accept={ACCEPT_STRING}
					multiple
					onchange={handleFileSelect}
					class="hidden"
					disabled={uploading}
				/>
			</label>
		{/if}

		<!-- Textarea -->
		<textarea
			bind:this={textareaEl}
			bind:value={query}
			onkeydown={handleKeydown}
			oninput={autoResize}
			{placeholder}
			rows="1"
			disabled={$isStreaming}
			class="input-base flex-1 px-4 py-3 text-sm resize-none font-light leading-relaxed"
			style="min-height:48px; overflow:hidden;"
		></textarea>

		<!-- Send / Stop -->
		{#if $isStreaming}
			<button
				onclick={cancelResearch}
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
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
			<div class="flex rounded-lg border border-navy-600 overflow-hidden text-xs">
				{#each ['fast', 'balanced', 'deep'] as d (d)}
					<button
						onclick={() => (depth = d as 'fast' | 'balanced' | 'deep')}
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
