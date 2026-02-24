<script lang="ts">
	import { onMount } from 'svelte';
	import { startResearch, cancelResearch } from '$lib/api/research';
	import { uploadPdf } from '$lib/api/documents';
	import { isStreaming, errorMessage, messageHistory, chatMessages } from '$lib/stores/reportStore';

	let query = $state('');
	let pdfSessionKey = $state<string | undefined>(undefined);
	let uploading = $state(false);
	let uploadInfo = $state<{ filename: string; pages: number } | null>(null);
	let uploadError = $state<string | null>(null);
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

	const showPdfAttach = $derived(!$isStreaming);

	async function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		uploading = true;
		uploadError = null;
		uploadInfo = null;
		try {
			const result = await uploadPdf(file);
			pdfSessionKey = result.session_key;
			uploadInfo = { filename: result.filename, pages: result.pages };
		} catch (err) {
			uploadError = err instanceof Error ? err.message : 'Upload failed';
			pdfSessionKey = undefined;
		} finally {
			uploading = false;
		}
	}

	function removeDocument() {
		pdfSessionKey = undefined;
		uploadInfo = null;
		uploadError = null;
		if (fileInput) fileInput.value = '';
	}

	async function handleSubmit() {
		const q = query.trim();
		if (!q || $isStreaming || uploading) return;

		const history = $messageHistory;
		const pdfKey = pdfSessionKey;

		query = '';
		resetTextarea();
		errorMessage.set(null);

		// Clear PDF after first send
		if (pdfKey) {
			pdfSessionKey = undefined;
			uploadInfo = null;
			if (fileInput) fileInput.value = '';
		}

		try {
			await startResearch(q, pdfKey, history, depth, selectedModel);
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

	const placeholder = $derived(
		$chatMessages.length > 0 ? 'Ask a follow-up question...' : 'Ask a research question...'
	);
</script>

<div class="flex flex-col gap-2">
	{#if uploadError}
		<p class="text-red-400 text-xs px-1">{uploadError}</p>
	{/if}

	<!-- Attached PDF indicator -->
	{#if uploadInfo}
		<div
			class="flex items-center justify-between bg-navy-700 border border-navy-600 rounded-lg px-4 py-2"
		>
			<div class="flex items-center gap-2 min-w-0">
				<svg
					class="w-3.5 h-3.5 text-gold flex-shrink-0"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1.5"
						d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
					/>
				</svg>
				<span class="text-xs text-slate-300 truncate">{uploadInfo.filename}</span>
				<span class="text-xs text-slate-500 flex-shrink-0">{uploadInfo.pages}p</span>
			</div>
			<button
				onclick={removeDocument}
				class="text-slate-500 hover:text-red-400 text-xs ml-2 flex-shrink-0 transition-colors"
				aria-label="Remove document"
			>
				✕
			</button>
		</div>
	{/if}

	<!-- Input row -->
	<div class="flex items-end gap-2">
		<!-- PDF attach icon (only on fresh conversation) -->
		{#if showPdfAttach}
			<label
				class="flex-shrink-0 cursor-pointer text-slate-500 hover:text-gold transition-colors pb-3"
				title="Attach PDF document"
			>
				{#if uploading}
					<span class="flex gap-0.5 pb-0.5">
						{#each [0, 1, 2] as i}
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
					accept=".pdf"
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
				{#each ['fast', 'balanced', 'deep'] as d}
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
					{#each models as m}
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
