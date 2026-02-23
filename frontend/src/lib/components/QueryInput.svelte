<script lang="ts">
	import { startResearch, cancelResearch } from '$lib/api/research';
	import { uploadPdf } from '$lib/api/documents';
	import { isStreaming, errorMessage } from '$lib/stores/reportStore';

	let query = $state('');
	let pdfSessionKey = $state<string | undefined>(undefined);
	let uploading = $state(false);
	let uploadInfo = $state<{ filename: string; pages: number } | null>(null);
	let uploadError = $state<string | null>(null);
	let fileInput = $state<HTMLInputElement>();

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
		if (!query.trim() || $isStreaming) return;
		errorMessage.set(null);
		try {
			await startResearch(query.trim(), pdfSessionKey);
		} catch (err) {
			if (err instanceof Error && err.name === 'AbortError') return;
			errorMessage.set(err instanceof Error ? err.message : 'An error occurred');
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
	}

	const exampleQueries = [
		"Analyse Nvidia's competitive position in the AI chip market",
		'Compare Apple and Microsoft valuations for 2025',
		"Warren Buffett's investment philosophy and track record",
		'Emerging market debt risks in the current rate environment'
	];
</script>

<div class="space-y-4">
	<!-- Textarea -->
	<div class="relative">
		<textarea
			bind:value={query}
			onkeydown={handleKeydown}
			placeholder="What would you like to research? E.g. &ldquo;Analyse Nvidia's position in the AI semiconductor market for 2025&rdquo;"
			rows="6"
			class="input-base w-full px-5 py-4 text-sm resize-none font-light leading-relaxed"
		></textarea>
		<span class="absolute bottom-3 right-4 text-slate-600 text-xs select-none">
			{#if navigator.platform.toLowerCase().includes('mac')}&#8984;{:else}Ctrl{/if}+&crarr; to submit
		</span>
	</div>

	<!-- Example queries -->
	{#if !query}
		<div class="space-y-1">
			<p class="text-xs text-slate-600 uppercase tracking-widest mb-2">Suggested queries</p>
			{#each exampleQueries as example}
				<button
					onclick={() => (query = example)}
					class="block w-full text-left text-xs text-slate-500 hover:text-gold py-1 px-2 rounded hover:bg-navy-700 transition-colors truncate"
				>
					{example}
				</button>
			{/each}
		</div>
	{/if}

	<!-- PDF Upload -->
	<div class="space-y-2">
		{#if uploadInfo}
			<div
				class="flex items-center justify-between bg-navy-700 border border-navy-600 rounded-lg px-4 py-2.5"
			>
				<div class="flex items-center gap-2.5 min-w-0">
					<svg
						class="w-4 h-4 text-gold flex-shrink-0"
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
					<span class="text-xs text-slate-500 flex-shrink-0">{uploadInfo.pages} pages</span>
				</div>
				<button
					onclick={removeDocument}
					class="text-slate-500 hover:text-red-400 transition-colors text-xs ml-2 flex-shrink-0"
					aria-label="Remove document"
				>
					&#10005;
				</button>
			</div>
		{:else}
			<label
				class="flex items-center gap-3 px-4 py-3 border border-dashed border-navy-600 rounded-lg
				       cursor-pointer hover:border-gold/40 hover:bg-navy-800/50 transition-all group"
			>
				{#if uploading}
					<span class="flex gap-1">
						{#each [0, 1, 2] as i}
							<span
								class="w-1.5 h-1.5 bg-gold rounded-full animate-bounce"
								style="animation-delay: {i * 0.12}s"
							></span>
						{/each}
					</span>
					<span class="text-sm text-slate-400">Uploading document...</span>
				{:else}
					<svg
						class="w-4 h-4 text-slate-500 group-hover:text-gold transition-colors flex-shrink-0"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="1.5"
							d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
						/>
					</svg>
					<span class="text-sm text-slate-500 group-hover:text-slate-300 transition-colors">
						Attach a PDF document <span class="text-slate-600 text-xs">(optional)</span>
					</span>
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

		{#if uploadError}
			<p class="text-red-400 text-xs px-1">{uploadError}</p>
		{/if}
	</div>

	{#if $errorMessage}
		<div class="bg-red-900/20 border border-red-800/40 rounded-lg px-4 py-3">
			<p class="text-red-400 text-xs">{$errorMessage}</p>
		</div>
	{/if}

	<!-- Action buttons -->
	<div class="flex gap-3">
		<button
			onclick={handleSubmit}
			disabled={!query.trim() || $isStreaming || uploading}
			class="btn-gold flex-1"
		>
			{$isStreaming ? 'Researching...' : 'Begin Research'}
		</button>

		{#if $isStreaming}
			<button
				onclick={cancelResearch}
				class="px-4 py-3 border border-navy-600 hover:border-red-700/50 text-slate-400 hover:text-red-400
				       rounded-lg transition-all text-sm"
			>
				Cancel
			</button>
		{/if}
	</div>
</div>
