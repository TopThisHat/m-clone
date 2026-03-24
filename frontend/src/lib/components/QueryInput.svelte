<script lang="ts">
	import { startResearch, cancelResearch } from '$lib/api/research';
	import {
		uploadDocument,
		uploadDocumentToSession,
		ACCEPT_STRING,
		type UploadFileStatus
	} from '$lib/api/documents';
	import { isStreaming, errorMessage } from '$lib/stores/reportStore';
	import { activeSessionId } from '$lib/stores/sessionStore';

	let query = $state('');
	let documents = $state<UploadFileStatus[]>([]);
	let docSessionKey = $state<string | undefined>(undefined);
	let uploading = $state(false);
	let fileInput = $state<HTMLInputElement>();

	// 8.9: Reset when activeSessionId becomes null (new research)
	// Intentional imperative reset — not derivable, these states have independent lifecycles
	$effect(() => {
		if ($activeSessionId === null) {
			documents = [];
			docSessionKey = undefined;
		}
	});

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

	// 8.3: Sequential multi-file upload
	async function handleFileSelect(e: Event) {
		const input = e.target as HTMLInputElement;
		const files = input.files;
		if (!files || files.length === 0) return;

		uploading = true;
		const fileList = Array.from(files);

		for (const file of fileList) {
			const entry: UploadFileStatus = { filename: file.name, status: 'uploading' };
			documents = [...documents, entry];
			const idx = documents.length - 1;

			try {
				const result = docSessionKey
					? await uploadDocumentToSession(file, docSessionKey)
					: await uploadDocument(file);

				// Always update session key from response (handles stale key rotation)
				docSessionKey = result.session_key;
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'success' as const, result } : d
				);
			} catch (err) {
				// 8.4: Per-file error — continue remaining files
				const errorMsg = err instanceof Error ? err.message : 'Upload failed';
				documents = documents.map((d, j) =>
					j === idx ? { ...d, status: 'error' as const, error: errorMsg } : d
				);
			}
		}

		uploading = false;
		if (fileInput) fileInput.value = '';
	}

	// 8.6: Frontend-only chip removal
	function removeDocument(index: number) {
		documents = documents.filter((_, i) => i !== index);
		if (documents.length === 0) {
			docSessionKey = undefined;
		}
	}

	async function handleSubmit() {
		if (!query.trim() || $isStreaming) return;
		errorMessage.set(null);
		try {
			// 8.8: Pass docSessionKey to startResearch
			await startResearch(query.trim(), docSessionKey);
		} catch (err) {
			if (err instanceof Error && err.name === 'AbortError') return;
			errorMessage.set(err instanceof Error ? err.message : 'An error occurred');
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
	}

	const isTruncated = $derived(documents.some((d) => d.result?.truncated));

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
			{#each exampleQueries as example (example)}
				<button
					onclick={() => (query = example)}
					class="block w-full text-left text-xs text-slate-500 hover:text-gold py-1 px-2 rounded hover:bg-navy-700 transition-colors truncate"
				>
					{example}
				</button>
			{/each}
		</div>
	{/if}

	<!-- Document Upload -->
	<div class="space-y-2">
		<!-- Document chips -->
		{#if documents.length > 0}
			<div class="flex flex-wrap gap-2">
				{#each documents as doc, i (i)}
					<div
						class="flex items-center gap-2 bg-navy-700 border rounded-lg px-3 py-1.5
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
								class="text-[10px] font-medium px-1.5 py-0.5 rounded
								       {doc.status === 'error' ? 'bg-red-900/40 text-red-400' : 'bg-navy-600 text-gold'}"
							>
								{getTypeLabel(doc.filename)}
							</span>
						{/if}
						<span class="text-xs text-slate-300 truncate max-w-[150px]">{doc.filename}</span>
						{#if doc.status === 'success'}
							{@const meta = getMetaLabel(doc)}
							{#if meta}
								<span class="text-[10px] text-slate-500">{meta}</span>
							{/if}
						{/if}
						{#if doc.status === 'error'}
							<span class="text-[10px] text-red-400 truncate max-w-[120px]">{doc.error}</span>
						{/if}
						{#if doc.status !== 'uploading'}
							<button
								onclick={() => removeDocument(i)}
								class="text-slate-500 hover:text-red-400 transition-colors text-xs ml-1 flex-shrink-0"
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

		<!-- Upload label -->
		<label
			class="flex items-center gap-3 px-4 py-3 border border-dashed border-navy-600 rounded-lg
			       cursor-pointer hover:border-gold/40 hover:bg-navy-800/50 transition-all group
			       {uploading ? 'pointer-events-none opacity-60' : ''}"
		>
			{#if uploading}
				<span class="flex gap-1">
					{#each [0, 1, 2] as i (i)}
						<span
							class="w-1.5 h-1.5 bg-gold rounded-full animate-bounce"
							style="animation-delay: {i * 0.12}s"
						></span>
					{/each}
				</span>
				<span class="text-sm text-slate-400">Uploading...</span>
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
					Attach documents <span class="text-slate-600 text-xs">(optional)</span>
				</span>
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
