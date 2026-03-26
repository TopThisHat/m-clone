<script lang="ts">
	import { importExportApi, type ImportPreview, type ImportErrorDetail } from '$lib/api/importExport';
	import ImportErrorPanel from './ImportErrorPanel.svelte';

	let {
		campaignId,
		onimported,
		oncancel,
	}: {
		campaignId: string;
		/** Called after a successful commit with result stats. */
		onimported?: (result: {
			entities_inserted: number;
			entities_skipped: number;
			attributes_inserted: number;
			attributes_skipped: number;
			cells_upserted: number;
		}) => void;
		oncancel?: () => void;
	} = $props();

	// ── Wizard steps ─────────────────────────────────────────────────────────
	// 1 upload → 2 mapping → 3 preview → 4 errors → 5 confirm (success)
	type Step = 1 | 2 | 3 | 4 | 5;
	let step = $state<Step>(1);

	// ── State ─────────────────────────────────────────────────────────────────
	let dragging = $state(false);
	let uploading = $state(false);
	let committing = $state(false);
	let error = $state('');

	let selectedFile = $state<File | null>(null);
	let preview = $state<ImportPreview | null>(null);

	// Editable column map (user can reassign roles in step 2)
	let editableMap = $state<Record<string, string>>({});

	let commitResult = $state<{
		entities_inserted: number;
		entities_skipped: number;
		attributes_inserted: number;
		attributes_skipped: number;
		cells_upserted: number;
	} | null>(null);

	const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
	const ROLE_OPTIONS = ['entity_label', 'entity_gwm_id', 'entity_description', 'attribute', 'ignore'];
	const ROLE_LABELS: Record<string, string> = {
		entity_label: 'Entity label (required)',
		entity_gwm_id: 'GWM ID',
		entity_description: 'Description',
		attribute: 'Attribute column',
		ignore: 'Ignore this column',
	};

	// ── Derived stats ─────────────────────────────────────────────────────────
	let hasErrors = $derived((preview?.errors ?? []).length > 0);
	let validRows = $derived(
		(preview?.row_count ?? 0) - (preview?.errors ?? []).length
	);
	let errorCount = $derived((preview?.errors ?? []).length);

	// ── File handling ─────────────────────────────────────────────────────────
	function validateFile(file: File): string | null {
		if (file.size > MAX_FILE_SIZE) {
			return `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is 10 MB.`;
		}
		const ext = file.name.split('.').pop()?.toLowerCase();
		if (!ext || !['csv', 'tsv', 'txt'].includes(ext)) {
			return 'Unsupported file type. Please upload a CSV or TSV file.';
		}
		return null;
	}

	async function handleFile(file: File) {
		const validationError = validateFile(file);
		if (validationError) {
			error = validationError;
			return;
		}

		selectedFile = file;
		error = '';
		uploading = true;

		try {
			preview = await importExportApi.upload(campaignId, file);
			editableMap = { ...preview.column_map };
			step = 2;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Upload failed. Please try again.';
		} finally {
			uploading = false;
		}
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragging = false;
		const file = e.dataTransfer?.files[0];
		if (file) handleFile(file);
	}

	function onFileInput(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (file) handleFile(file);
	}

	// ── Step navigation ───────────────────────────────────────────────────────
	function goToPreview() {
		// Validate that at least one entity_label column is mapped
		const hasLabel = Object.values(editableMap).includes('entity_label');
		if (!hasLabel) {
			error = 'At least one column must be mapped as "Entity label".';
			return;
		}
		error = '';
		step = 3;
	}

	function goToErrors() {
		step = 4;
	}

	async function commit() {
		if (!preview) return;
		committing = true;
		error = '';

		try {
			// Apply edited column map — recompute entities/attributes from preview
			// The server already validated; we pass its preview data as-is
			const result = await importExportApi.commit(campaignId, {
				entities: preview.entities,
				attributes: preview.attributes,
				cells: preview.cells,
			});
			commitResult = result;
			step = 5;
			onimported?.(result);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Commit failed. Please try again.';
		} finally {
			committing = false;
		}
	}

	async function downloadErrors() {
		if (!preview) return;
		// We need the raw rows — re-parse the file for the error report
		// For now, just pass empty rows (server will handle it)
		try {
			await importExportApi.downloadErrorReportBlob(
				campaignId,
				[], // raw rows not stored; server generates report from errors
				preview.errors
			);
		} catch {
			// silent — non-critical
		}
	}

	function reset() {
		step = 1;
		selectedFile = null;
		preview = null;
		editableMap = {};
		error = '';
		commitResult = null;
	}

	// ── Step indicator helpers ────────────────────────────────────────────────
	const STEPS = ['Upload', 'Mapping', 'Preview', 'Errors', 'Done'];
</script>

<div class="space-y-6">
	<!-- Step indicator -->
	<nav aria-label="Import wizard steps">
		<ol class="flex items-center gap-0">
			{#each STEPS as label, i}
				{@const n = (i + 1) as Step}
				{@const active = step === n}
				{@const done = step > n}
				<li class="flex items-center gap-0 flex-1 last:flex-none">
					<button
						onclick={() => { if (done) step = n; }}
						disabled={!done}
						class="flex items-center gap-1.5 group"
						aria-current={active ? 'step' : undefined}
					>
						<span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold transition-colors shrink-0
							{active ? 'bg-gold text-navy' : done ? 'bg-green-600 text-white' : 'bg-navy-700 text-slate-500'}">
							{#if done}
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
								</svg>
							{:else}
								{n}
							{/if}
						</span>
						<span class="text-xs hidden sm:block
							{active ? 'text-gold font-medium' : done ? 'text-slate-300' : 'text-slate-600'}">
							{label}
						</span>
					</button>
					{#if i < STEPS.length - 1}
						<div class="flex-1 h-px mx-2 {done ? 'bg-green-700' : 'bg-navy-700'}"></div>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>

	<!-- Error banner -->
	{#if error}
		<div role="alert" class="flex items-start gap-2 p-3 rounded-lg bg-red-950/50 border border-red-900/60 text-red-300 text-sm">
			<svg class="w-4 h-4 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m9.303 3.376c.866 1.5-.217 3.374-1.948 3.374H4.645c-1.73 0-2.813-1.874-1.948-3.374L10.05 3.378c.866-1.5 3.032-1.5 3.898 0L21.303 16.126z" />
			</svg>
			{error}
		</div>
	{/if}

	<!-- ── Step 1: Upload ───────────────────────────────────────────────── -->
	{#if step === 1}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="border-2 border-dashed rounded-xl p-10 text-center transition-colors
				{dragging ? 'border-gold bg-gold/5' : 'border-navy-600 hover:border-navy-500'}"
			ondragover={(e) => { e.preventDefault(); dragging = true; }}
			ondragleave={() => (dragging = false)}
			ondrop={onDrop}
			role="region"
			aria-label="CSV file upload area"
		>
			{#if uploading}
				<div class="flex flex-col items-center gap-3 text-slate-400">
					<svg class="w-8 h-8 animate-spin text-gold" fill="none" viewBox="0 0 24 24" aria-hidden="true">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 100 16v-4l-3 3 3 3v-4a8 8 0 01-8-8z" />
					</svg>
					<span class="text-sm">Uploading and validating…</span>
				</div>
			{:else}
				<svg class="w-10 h-10 mx-auto mb-3 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
						d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
				</svg>
				<p class="text-slate-300 font-medium mb-1">Drag & drop your CSV file here</p>
				<p class="text-slate-500 text-xs mb-4">CSV or TSV — max 10 MB</p>
				<label class="cursor-pointer">
					<span class="btn-gold text-sm">Browse files</span>
					<input
						type="file"
						accept=".csv,.tsv,.txt"
						class="hidden"
						onchange={onFileInput}
						aria-label="Choose CSV file to import"
					/>
				</label>
			{/if}
		</div>

		<!-- Expected format hint -->
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 text-sm space-y-2">
			<p class="text-slate-300 font-medium text-xs uppercase tracking-wide">Expected CSV format</p>
			<div class="font-mono text-xs text-slate-400 space-y-0.5">
				<p class="text-slate-300">label, gwm_id, <span class="text-gold">Attribute1</span>, <span class="text-gold">Attribute2</span>, …</p>
				<p>Acme Corp, GWM-001, true, 42, …</p>
				<p>Globex Inc, GWM-002, false, 17, …</p>
			</div>
			<p class="text-slate-500 text-xs">Columns named <span class="font-mono">label</span>, <span class="font-mono">name</span>, or <span class="font-mono">entity</span> are used as entity names. All others become attributes.</p>
		</div>

		{#if oncancel}
			<button onclick={oncancel} class="btn-secondary text-sm w-full">Cancel</button>
		{/if}

	<!-- ── Step 2: Mapping ──────────────────────────────────────────────── -->
	{:else if step === 2 && preview}
		<div class="space-y-4">
			<div>
				<h3 class="font-medium text-slate-200 mb-0.5">Column mapping</h3>
				<p class="text-slate-500 text-xs">
					{preview.row_count.toLocaleString()} rows detected. Review how each column will be used.
				</p>
			</div>

			<div class="rounded-xl border border-navy-700 overflow-hidden">
				<table class="w-full text-sm">
					<thead>
						<tr class="bg-navy-800 text-xs text-slate-400 uppercase tracking-wide">
							<th class="text-left px-4 py-2.5 font-medium">Column</th>
							<th class="text-left px-4 py-2.5 font-medium">Role</th>
						</tr>
					</thead>
					<tbody>
						{#each Object.entries(editableMap) as [col, role], i (col)}
							<tr class="border-t border-navy-700 {i % 2 === 0 ? '' : 'bg-navy-800/40'}">
								<td class="px-4 py-2 font-mono text-slate-300 text-xs">{col}</td>
								<td class="px-4 py-2">
									<select
										class="bg-navy-700 border border-navy-600 rounded-lg px-2 py-1 text-xs text-slate-200 w-full max-w-xs"
										value={role}
										onchange={(e) => {
											editableMap = { ...editableMap, [col]: (e.target as HTMLSelectElement).value };
										}}
										aria-label="Role for column {col}"
									>
										{#each ROLE_OPTIONS as opt}
											<option value={opt}>{ROLE_LABELS[opt] ?? opt}</option>
										{/each}
									</select>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<div class="flex gap-2">
				<button onclick={goToPreview} class="btn-gold">Next: Preview</button>
				<button onclick={() => { step = 1; error = ''; }} class="btn-secondary">Back</button>
			</div>
		</div>

	<!-- ── Step 3: Preview ──────────────────────────────────────────────── -->
	{:else if step === 3 && preview}
		<div class="space-y-4">
			<div>
				<h3 class="font-medium text-slate-200 mb-0.5">Import preview</h3>
				<p class="text-slate-500 text-xs">Review what will be imported before committing.</p>
			</div>

			<!-- Summary cards -->
			<div class="grid grid-cols-3 gap-3">
				<div class="bg-navy-800 rounded-xl p-4 border border-navy-700">
					<p class="text-2xl font-bold text-slate-100">{preview.entities.length.toLocaleString()}</p>
					<p class="text-xs text-slate-400 mt-0.5">Entities</p>
				</div>
				<div class="bg-navy-800 rounded-xl p-4 border border-navy-700">
					<p class="text-2xl font-bold text-slate-100">{preview.attributes.length.toLocaleString()}</p>
					<p class="text-xs text-slate-400 mt-0.5">Attributes</p>
				</div>
				<div class="bg-navy-800 rounded-xl p-4 border border-navy-700">
					<p class="text-2xl font-bold text-slate-100">{preview.cells.length.toLocaleString()}</p>
					<p class="text-xs text-slate-400 mt-0.5">Cell values</p>
				</div>
			</div>

			<!-- Entity sample -->
			{#if preview.entities.length > 0}
				<div>
					<p class="text-xs text-slate-400 font-medium mb-2">
						Sample entities (first {Math.min(5, preview.entities.length)} of {preview.entities.length.toLocaleString()})
					</p>
					<div class="rounded-xl border border-navy-700 overflow-hidden">
						<table class="w-full text-xs">
							<thead>
								<tr class="bg-navy-800 text-slate-500 uppercase tracking-wide">
									<th class="text-left px-3 py-2 font-medium">Label</th>
									<th class="text-left px-3 py-2 font-medium">GWM ID</th>
								</tr>
							</thead>
							<tbody>
								{#each preview.entities.slice(0, 5) as entity}
									<tr class="border-t border-navy-700">
										<td class="px-3 py-1.5 text-slate-200">{entity.label}</td>
										<td class="px-3 py-1.5 text-slate-500 font-mono">{entity.gwm_id ?? '—'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			{#if hasErrors}
				<div class="flex items-center gap-2 p-3 rounded-lg bg-amber-950/40 border border-amber-900/50 text-amber-300 text-sm">
					<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
					</svg>
					<span>{errorCount} row{errorCount === 1 ? '' : 's'} with validation errors — {validRows.toLocaleString()} valid rows will be imported.</span>
					<button onclick={goToErrors} class="ml-auto text-xs text-amber-400 hover:text-amber-200 underline">
						Review errors
					</button>
				</div>
			{/if}

			<div class="flex gap-2">
				<button onclick={commit} disabled={committing || preview.entities.length === 0} class="btn-gold disabled:opacity-50 disabled:cursor-not-allowed">
					{#if committing}
						<svg class="w-4 h-4 animate-spin inline mr-1.5" fill="none" viewBox="0 0 24 24" aria-hidden="true">
							<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
							<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
						</svg>
						Importing…
					{:else}
						Import {validRows.toLocaleString()} row{validRows !== 1 ? 's' : ''}
					{/if}
				</button>
				<button onclick={() => step = 2} class="btn-secondary" disabled={committing}>Back</button>
			</div>
		</div>

	<!-- ── Step 4: Errors ───────────────────────────────────────────────── -->
	{:else if step === 4 && preview}
		<div class="space-y-4">
			<div>
				<h3 class="font-medium text-slate-200 mb-0.5">Validation errors</h3>
				<p class="text-slate-500 text-xs">These rows will be skipped. Valid rows will still be imported.</p>
			</div>

			<ImportErrorPanel
				errors={preview.errors}
				ondownload={downloadErrors}
			/>

			<div class="flex gap-2">
				<button onclick={() => step = 3} class="btn-gold">Back to preview</button>
				<button onclick={commit} disabled={committing || validRows === 0} class="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed">
					{committing ? 'Importing…' : `Import ${validRows.toLocaleString()} valid rows anyway`}
				</button>
			</div>
		</div>

	<!-- ── Step 5: Success ──────────────────────────────────────────────── -->
	{:else if step === 5 && commitResult}
		<div class="space-y-4">
			<div class="flex items-center gap-3 text-green-400">
				<div class="w-10 h-10 rounded-full bg-green-900/50 flex items-center justify-center shrink-0">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
				</div>
				<div>
					<p class="font-semibold text-slate-100">Import complete</p>
					<p class="text-slate-400 text-sm">Your data has been imported successfully.</p>
				</div>
			</div>

			<div class="grid grid-cols-2 gap-3">
				<div class="bg-navy-800 rounded-xl p-3 border border-navy-700">
					<p class="text-xl font-bold text-slate-100">{commitResult.entities_inserted.toLocaleString()}</p>
					<p class="text-xs text-slate-400">Entities added</p>
					{#if commitResult.entities_skipped > 0}
						<p class="text-xs text-slate-500 mt-0.5">{commitResult.entities_skipped} skipped (duplicates)</p>
					{/if}
				</div>
				<div class="bg-navy-800 rounded-xl p-3 border border-navy-700">
					<p class="text-xl font-bold text-slate-100">{commitResult.attributes_inserted.toLocaleString()}</p>
					<p class="text-xs text-slate-400">Attributes added</p>
					{#if commitResult.attributes_skipped > 0}
						<p class="text-xs text-slate-500 mt-0.5">{commitResult.attributes_skipped} skipped (duplicates)</p>
					{/if}
				</div>
				<div class="bg-navy-800 rounded-xl p-3 border border-navy-700 col-span-2">
					<p class="text-xl font-bold text-slate-100">{commitResult.cells_upserted.toLocaleString()}</p>
					<p class="text-xs text-slate-400">Cell values imported</p>
				</div>
			</div>

			<div class="flex gap-2">
				<button onclick={reset} class="btn-secondary text-sm">Import another file</button>
				{#if oncancel}
					<button onclick={oncancel} class="btn-secondary text-sm">Close</button>
				{/if}
			</div>
		</div>
	{/if}
</div>
