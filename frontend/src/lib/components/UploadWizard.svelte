<script lang="ts">
	import { uploadToKG, type KGUploadResult } from '$lib/api/documents';

	// ── File type definitions ──────────────────────────────────────────────────

	type FileType = 'document' | 'dataset' | 'image';

	interface FileTypeCard {
		id: FileType;
		title: string;
		description: string;
		formats: string;
		extensions: string[];
		accept: string;
	}

	const FILE_TYPES: FileTypeCard[] = [
		{
			id: 'document',
			title: 'Document',
			description:
				'AI reads your file, identifies people, companies, locations, and relationships, then adds them to your team\'s graph',
			formats: 'PDF, DOCX',
			extensions: ['.pdf', '.docx'],
			accept: '.pdf,.docx',
		},
		{
			id: 'dataset',
			title: 'Dataset',
			description: 'Maps columns to entities and relationships',
			formats: 'CSV, Excel',
			extensions: ['.csv', '.xlsx', '.xls'],
			accept: '.csv,.xlsx,.xls',
		},
		{
			id: 'image',
			title: 'Image',
			description: 'OCR extracts text, then identifies entities',
			formats: 'PNG, JPEG, GIF, WebP',
			extensions: ['.png', '.jpg', '.jpeg', '.gif', '.webp'],
			accept: '.png,.jpg,.jpeg,.gif,.webp',
		},
	];

	// ── Step labels ────────────────────────────────────────────────────────────

	const STEP_LABELS = ['Choose type', 'Select file', 'Processing'];

	// ── Processing stages for Step 3 ──────────────────────────────────────────

	type StageStatus = 'pending' | 'active' | 'done';

	interface ProcessingStage {
		label: string;
		status: StageStatus;
	}

	// ── Props ──────────────────────────────────────────────────────────────────

	interface Props {
		/** Whether the wizard is visible */
		open: boolean;
		/** Called when user closes or cancels */
		onClose: () => void;
		/** Team ID to scope the upload */
		teamId?: string | null;
		/** Called when upload completes and user clicks "View in graph" */
		onComplete: () => void;
	}

	let { open, onClose, teamId = null, onComplete }: Props = $props();

	// ── Wizard state ───────────────────────────────────────────────────────────

	let currentStep = $state<1 | 2 | 3>(1);
	let selectedFileType = $state<FileTypeCard | null>(null);
	let selectedFile = $state<File | null>(null);
	let processingStages = $state<ProcessingStage[]>([]);
	let uploadError = $state('');
	let dropError = $state('');
	let isDragging = $state(false);
	let uploadResult = $state<KGUploadResult | null>(null);
	let isDone = $state(false);

	// ── Derived ───────────────────────────────────────────────────────────────

	let selectedCard = $derived(
		selectedFileType ? FILE_TYPES.find((f) => f.id === selectedFileType!.id) ?? null : null
	);

	// ── Dialog element ────────────────────────────────────────────────────────

	let dialogEl = $state<HTMLDialogElement | undefined>();
	let triggerEl: HTMLElement | null = null;

	$effect(() => {
		if (!dialogEl) return;
		if (open) {
			triggerEl = document.activeElement as HTMLElement | null;
			dialogEl.showModal();
		} else {
			if (dialogEl.open) dialogEl.close();
		}
	});

	function handleClose() {
		queueMicrotask(() => triggerEl?.focus());
		reset();
		onClose();
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === dialogEl) handleClose();
	}

	// ── Step navigation ────────────────────────────────────────────────────────

	function selectFileType(card: FileTypeCard) {
		selectedFileType = card;
		selectedFile = null;
		dropError = '';
		currentStep = 2;
	}

	function goBack() {
		if (currentStep === 2) {
			currentStep = 1;
			selectedFile = null;
			dropError = '';
		}
	}

	// ── Step 2: file drop / selection ─────────────────────────────────────────

	function validateFile(file: File): string | null {
		if (!selectedFileType) return 'No file type selected';
		const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
		if (!selectedFileType.extensions.includes(ext)) {
			return `Invalid file type "${ext}". Accepted: ${selectedFileType.formats}`;
		}
		const maxMb = 20;
		if (file.size > maxMb * 1024 * 1024) {
			return `File exceeds ${maxMb} MB limit`;
		}
		return null;
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		isDragging = true;
	}

	function handleDragLeave() {
		isDragging = false;
	}

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
		const file = e.dataTransfer?.files[0];
		if (!file) return;
		const err = validateFile(file);
		if (err) {
			dropError = err;
			selectedFile = null;
		} else {
			dropError = '';
			selectedFile = file;
		}
	}

	function handleFileInput(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;
		const err = validateFile(file);
		if (err) {
			dropError = err;
			selectedFile = null;
		} else {
			dropError = '';
			selectedFile = file;
		}
	}

	function clearFile() {
		selectedFile = null;
		dropError = '';
	}

	// ── Step 3: upload + staged progress ─────────────────────────────────────

	function initStages(file: File): ProcessingStage[] {
		return [
			{ label: `File received (${formatBytes(file.size)})`, status: 'pending' },
			{ label: 'Extracting text...', status: 'pending' },
			{ label: 'Identifying entities...', status: 'pending' },
		];
	}

	async function startUpload() {
		if (!selectedFile || !selectedFileType) return;

		const file = selectedFile;
		uploadError = '';
		uploadResult = null;
		isDone = false;
		processingStages = initStages(file);
		currentStep = 3;

		// Stage 1: file received — mark active immediately
		processingStages = processingStages.map((s, i) =>
			i === 0 ? { ...s, status: 'active' } : s
		);

		try {
			const result = await uploadToKG(file, teamId ?? undefined);
			uploadResult = result;

			// Stage 1 done → Stage 2 active
			processingStages = processingStages.map((s, i) => {
				if (i === 0) return { ...s, status: 'done' };
				if (i === 1) return { ...s, status: 'active' };
				return s;
			});

			// Stage 2 → 3 after 1.5s (extraction is async server-side)
			await delay(1500);
			processingStages = processingStages.map((s, i) => {
				if (i === 1) return { ...s, status: 'done' };
				if (i === 2) return { ...s, status: 'active' };
				return s;
			});

			// Stage 3 done after 2s
			await delay(2000);
			processingStages = processingStages.map((s) => ({ ...s, status: 'done' }));
			isDone = true;
		} catch (err: unknown) {
			uploadError = err instanceof Error ? err.message : 'Upload failed';
			// Reset to step 2 so user can retry
			currentStep = 2;
			processingStages = [];
		}
	}

	function delay(ms: number): Promise<void> {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	function handleViewInGraph() {
		handleClose();
		onComplete();
	}

	// ── Reset ─────────────────────────────────────────────────────────────────

	function reset() {
		currentStep = 1;
		selectedFileType = null;
		selectedFile = null;
		processingStages = [];
		uploadError = '';
		dropError = '';
		isDragging = false;
		uploadResult = null;
		isDone = false;
	}

	// ── Formatting helpers ────────────────────────────────────────────────────

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	}
</script>

{#if open}
	<dialog
		bind:this={dialogEl}
		class="bg-transparent p-0 m-auto backdrop:bg-black/70 backdrop:backdrop-blur-sm w-full max-w-lg"
		aria-labelledby="upload-wizard-title"
		onclose={handleClose}
		onclick={handleBackdropClick}
	>
		<div class="bg-navy-900 border border-navy-700 rounded-xl shadow-2xl w-full mx-4 overflow-hidden">
			<!-- Header -->
			<div class="flex items-center justify-between px-5 py-4 border-b border-navy-700">
				<h2 id="upload-wizard-title" class="text-sm font-semibold text-slate-200">
					Upload to Knowledge Graph
				</h2>
				<button
					onclick={handleClose}
					class="text-slate-500 hover:text-slate-300 transition-colors"
					aria-label="Close wizard"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<!-- Step indicator -->
			<div class="flex items-center px-5 py-3 border-b border-navy-800 gap-0">
				{#each STEP_LABELS as label, i (i)}
					{@const step = i + 1}
					{@const isActive = currentStep === step}
					{@const isDoneStep = currentStep > step}
					<div class="flex items-center {i < STEP_LABELS.length - 1 ? 'flex-1' : ''}">
						<div class="flex flex-col items-center gap-1">
							<div
								class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-colors
									{isDoneStep
										? 'bg-gold text-navy-900'
										: isActive
										? 'bg-gold/20 border border-gold text-gold'
										: 'bg-navy-800 border border-navy-600 text-slate-500'}"
							>
								{#if isDoneStep}
									<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
									</svg>
								{:else}
									{step}
								{/if}
							</div>
							<span
								class="text-[10px] whitespace-nowrap transition-colors
									{isActive ? 'text-gold' : isDoneStep ? 'text-slate-400' : 'text-slate-600'}"
							>
								{label}
							</span>
						</div>
						{#if i < STEP_LABELS.length - 1}
							<div class="flex-1 h-px mx-2 mb-3 {isDoneStep ? 'bg-gold/40' : 'bg-navy-700'}"></div>
						{/if}
					</div>
				{/each}
			</div>

			<!-- Step content -->
			<div class="px-5 py-5">
				<!-- ── Step 1: File type cards ── -->
				{#if currentStep === 1}
					<p class="text-xs text-slate-400 mb-4">
						Choose the type of file you want to add to the knowledge graph.
					</p>
					<div class="space-y-3">
						{#each FILE_TYPES as card (card.id)}
							<button
								onclick={() => selectFileType(card)}
								class="w-full text-left rounded-lg border px-4 py-3.5 transition-all
									border-navy-600 hover:border-gold hover:bg-gold/5 group"
							>
								<div class="flex items-start gap-3">
									<!-- Icon -->
									<div class="w-8 h-8 rounded-md bg-navy-800 border border-navy-600 group-hover:border-gold/40 flex items-center justify-center shrink-0 mt-0.5 transition-colors">
										{#if card.id === 'document'}
											<svg class="w-4 h-4 text-slate-400 group-hover:text-gold transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
											</svg>
										{:else if card.id === 'dataset'}
											<svg class="w-4 h-4 text-slate-400 group-hover:text-gold transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M3 14h18M10 3v18M14 3v18M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
											</svg>
										{:else}
											<svg class="w-4 h-4 text-slate-400 group-hover:text-gold transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
											</svg>
										{/if}
									</div>
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 mb-0.5">
											<span class="text-sm font-medium text-slate-200 group-hover:text-gold transition-colors">
												{card.title}
											</span>
											<span class="text-[10px] text-slate-500 font-mono">{card.formats}</span>
										</div>
										<p class="text-xs text-slate-500 leading-relaxed">{card.description}</p>
									</div>
									<svg class="w-4 h-4 text-slate-600 group-hover:text-gold transition-colors shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
									</svg>
								</div>
							</button>
						{/each}
					</div>
				{/if}

				<!-- ── Step 2: Drop zone ── -->
				{#if currentStep === 2 && selectedCard}
					<div class="space-y-4">
						<!-- Drop zone -->
						<div
							role="region"
							aria-label="File drop zone"
							class="border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer
								{isDragging ? 'border-gold bg-gold/5' : 'border-navy-600 hover:border-navy-500'}"
							ondragover={handleDragOver}
							ondragleave={handleDragLeave}
							ondrop={handleDrop}
						>
							<!-- Upload cloud icon -->
							<div class="flex justify-center mb-3">
								<svg class="w-8 h-8 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
								</svg>
							</div>
							<p class="text-sm text-slate-300 font-medium mb-1">
								Drop your {selectedCard.title.toLowerCase()} here
							</p>
							<p class="text-xs text-slate-500 mb-4">
								Accepted: {selectedCard.formats}
							</p>
							<label class="cursor-pointer">
								<span class="text-xs px-3 py-1.5 rounded border border-navy-600 text-slate-300 hover:text-slate-200 hover:border-navy-500 transition-colors">
									Browse files
								</span>
								<input
									type="file"
									accept={selectedCard.accept}
									class="hidden"
									onchange={handleFileInput}
									aria-label="Choose {selectedCard.title} file"
								/>
							</label>
						</div>

						<!-- Selected file preview -->
						{#if selectedFile}
							<div class="flex items-center gap-3 bg-navy-800 rounded-lg px-3 py-2.5 border border-navy-700">
								<div class="w-7 h-7 rounded bg-navy-700 flex items-center justify-center shrink-0">
									{#if selectedCard.id === 'document'}
										<svg class="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
										</svg>
									{:else if selectedCard.id === 'dataset'}
										<svg class="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M3 14h18M10 3v18M14 3v18M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
										</svg>
									{:else}
										<svg class="w-4 h-4 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
										</svg>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<p class="text-xs text-slate-200 truncate">{selectedFile.name}</p>
									<p class="text-[10px] text-slate-500">{formatBytes(selectedFile.size)}</p>
								</div>
								<button
									onclick={clearFile}
									class="text-slate-500 hover:text-slate-300 transition-colors"
									aria-label="Remove file"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
									</svg>
								</button>
							</div>
						{/if}

						<!-- Drop error -->
						{#if dropError}
							<p class="text-xs text-red-400" role="alert">{dropError}</p>
						{/if}

						<!-- Upload error (from a failed attempt) -->
						{#if uploadError}
							<p class="text-xs text-red-400" role="alert">{uploadError}</p>
						{/if}

						<!-- Actions -->
						<div class="flex gap-2 pt-1">
							<button
								onclick={startUpload}
								disabled={!selectedFile}
								class="flex-1 text-sm px-4 py-2 rounded-lg border transition-colors font-medium
									{selectedFile
										? 'border-gold/50 bg-gold/10 text-gold hover:bg-gold/20'
										: 'border-navy-700 bg-navy-800 text-slate-600 cursor-not-allowed'}"
							>
								Extract &amp; Add to KG
							</button>
							<button
								onclick={goBack}
								class="text-sm px-4 py-2 rounded-lg border border-navy-600 text-slate-400 hover:text-slate-200 hover:border-navy-500 transition-colors"
							>
								Back
							</button>
						</div>
					</div>
				{/if}

				<!-- ── Step 3: Processing status ── -->
				{#if currentStep === 3}
					<div class="space-y-5">
						<p class="text-xs text-slate-400">
							Processing <span class="text-slate-300 font-medium">{uploadResult?.filename ?? selectedFile?.name ?? 'file'}</span>
						</p>

						<!-- Stage list -->
						<div class="space-y-3">
							{#each processingStages as stage, i (i)}
								<div class="flex items-center gap-3">
									<!-- Status icon -->
									<div class="w-5 h-5 shrink-0 flex items-center justify-center">
										{#if stage.status === 'done'}
											<svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
											</svg>
										{:else if stage.status === 'active'}
											<svg class="w-4 h-4 text-gold animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
											</svg>
										{:else}
											<div class="w-4 h-4 rounded-full border border-navy-600"></div>
										{/if}
									</div>
									<span
										class="text-sm transition-colors
											{stage.status === 'done'
												? 'text-slate-300'
												: stage.status === 'active'
												? 'text-slate-200'
												: 'text-slate-600'}"
									>
										{stage.label}
									</span>
								</div>
							{/each}
						</div>

						<!-- Done state -->
						{#if isDone}
							<div class="rounded-lg bg-navy-800 border border-navy-700 px-4 py-3 space-y-1">
								<p class="text-xs text-green-400 font-medium">Queued for processing</p>
								<p class="text-[10px] text-slate-400">
									{uploadResult?.message ?? 'Entities and relationships will appear in the graph shortly.'}
								</p>
							</div>
							<button
								onclick={handleViewInGraph}
								class="w-full text-sm px-4 py-2 rounded-lg border border-gold/50 bg-gold/10 text-gold hover:bg-gold/20 transition-colors font-medium"
							>
								View in graph
							</button>
						{/if}

						<!-- Upload error in step 3 (shouldn't normally show — we redirect back to step 2) -->
						{#if uploadError}
							<p class="text-xs text-red-400" role="alert">{uploadError}</p>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</dialog>
{/if}
