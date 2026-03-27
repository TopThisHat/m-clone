<script lang="ts">
	import * as XLSX from 'xlsx';
	import { entitiesApi, type EntityCreate } from '$lib/api/entities';

	let {
		campaignId = '',
		onUploaded,
		onBulkCreate,
	}: {
		campaignId?: string;
		onUploaded: () => void;
		onBulkCreate?: (rows: EntityCreate[]) => Promise<{ inserted: unknown[]; skipped: number }>;
	} = $props();

	type Stage = 'idle' | 'mapping' | 'preview' | 'uploading' | 'done';
	let stage = $state<Stage>('idle');
	let error = $state('');
	let dragging = $state(false);

	let headers = $state<string[]>([]);
	let rows = $state<Record<string, string>[]>([]);

	// Column mapping
	let labelCol = $state('');
	let descCol = $state('');
	let gwmIdCol = $state('');

	// Upload progress
	let uploadedCount = $state(0);
	let totalCount = $state(0);
	let insertedCount = $state(0);
	let skippedCount = $state(0);

	const BATCH_SIZE = 500;

	const SAMPLE_CSV =
		'label,description,gwm_id\n' +
		'Acme Corp,Leading widget manufacturer,GWM-001\n' +
		'Globex Inc,Industrial conglomerate,GWM-002\n' +
		'Initech LLC,Software solutions provider,';

	function downloadSample() {
		const blob = new Blob([SAMPLE_CSV], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'entities_sample.csv';
		a.click();
		URL.revokeObjectURL(url);
	}

	function parseCSV(text: string): { headers: string[]; rows: Record<string, string>[] } {
		const lines = text.trim().split(/\r?\n/);
		if (lines.length < 2) throw new Error('File must have a header row and at least one data row.');

		function parseRow(line: string): string[] {
			const result: string[] = [];
			let cur = '';
			let inQuote = false;
			for (const ch of line) {
				if (ch === '"') { inQuote = !inQuote; }
				else if (ch === ',' && !inQuote) { result.push(cur.trim()); cur = ''; }
				else { cur += ch; }
			}
			result.push(cur.trim());
			return result;
		}

		const hdrs = parseRow(lines[0]);
		const dataRows = lines.slice(1).map((line) => {
			const vals = parseRow(line);
			return Object.fromEntries(hdrs.map((h, i) => [h, vals[i] ?? '']));
		});
		return { headers: hdrs, rows: dataRows };
	}

	function parseExcel(buffer: ArrayBuffer): { headers: string[]; rows: Record<string, string>[] } {
		const workbook = XLSX.read(buffer, { type: 'array' });
		const sheet = workbook.Sheets[workbook.SheetNames[0]];
		const data = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' });
		if (!data.length) throw new Error('Spreadsheet appears to be empty.');
		const hdrs = Object.keys(data[0]);
		const dataRows = data.map((r) =>
			Object.fromEntries(hdrs.map((h) => [h, String(r[h] ?? '')]))
		);
		return { headers: hdrs, rows: dataRows };
	}

	const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

	async function handleFile(file: File) {
		error = '';
		if (file.size > MAX_FILE_SIZE) {
			error = `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is 10 MB.`;
			return;
		}
		try {
			let parsed: { headers: string[]; rows: Record<string, string>[] };
			const ext = file.name.split('.').pop()?.toLowerCase();
			if (ext === 'csv' || ext === 'tsv' || ext === 'txt') {
				const text = await file.text();
				parsed = parseCSV(text);
			} else if (ext === 'xlsx' || ext === 'xls' || ext === 'ods') {
				const buffer = await file.arrayBuffer();
				parsed = parseExcel(buffer);
			} else {
				error = 'Unsupported file type. Please upload a CSV or Excel file.';
				return;
			}

			headers = parsed.headers;
			rows = parsed.rows;

			// Auto-detect common column names
			labelCol = headers.find((h) => /^(label|name|entity|company|person|org)/i.test(h)) ?? headers[0] ?? '';
			descCol = headers.find((h) => /^(desc|description|bio|notes)/i.test(h)) ?? '';
			gwmIdCol = headers.find((h) => /^(gwm_id|gwm[-_]?id|gwm)$/i.test(h)) ?? '';

			stage = 'mapping';
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to parse file.';
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

	function toPreview() {
		if (!labelCol) { error = 'Please select a "Label" column.'; return; }
		error = '';
		stage = 'preview';
	}

	function mappedEntities(): EntityCreate[] {
		const metaCols = headers.filter((h) => h !== labelCol && h !== descCol && h !== gwmIdCol);
		return rows
			.map((row) => ({
				label: row[labelCol] ?? '',
				description: descCol ? (row[descCol] || undefined) : undefined,
				gwm_id: gwmIdCol ? (row[gwmIdCol] || undefined) : undefined,
				metadata: Object.fromEntries(metaCols.map((h) => [h, row[h]])),
			}))
			.filter((e) => e.label);
	}

	async function upload() {
		const entities = mappedEntities();
		if (!entities.length) { error = 'No valid rows to upload.'; return; }

		stage = 'uploading';
		error = '';
		uploadedCount = 0;
		totalCount = entities.length;

		try {
			for (let i = 0; i < entities.length; i += BATCH_SIZE) {
				const batch = entities.slice(i, i + BATCH_SIZE);
				const result = onBulkCreate
					? await onBulkCreate(batch)
					: await entitiesApi.bulkCreate(campaignId, batch);
				insertedCount += result.inserted.length;
				skippedCount += result.skipped;
				uploadedCount = Math.min(i + BATCH_SIZE, entities.length);
			}
			stage = 'done';
			onUploaded();
		} catch (err: unknown) {
			stage = 'preview';
			error = err instanceof Error ? err.message : 'Upload failed';
		}
	}

	function reset() {
		stage = 'idle';
		headers = [];
		rows = [];
		error = '';
		uploadedCount = 0;
		totalCount = 0;
		insertedCount = 0;
		skippedCount = 0;
	}

	let previewRows = $derived(rows.slice(0, 5));
	let uploadPct = $derived(totalCount > 0 ? Math.round((uploadedCount / totalCount) * 100) : 0);
</script>

<div class="space-y-4">
	{#if stage === 'idle'}
		<!-- Drop zone -->
		<div
			role="region"
			aria-label="File drop zone"
			class="border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer
				{dragging ? 'border-gold bg-navy-700' : 'border-navy-600 hover:border-navy-500'}"
			ondragover={(e) => { e.preventDefault(); dragging = true; }}
			ondragleave={() => (dragging = false)}
			ondrop={onDrop}
		>
			<p class="text-slate-300 font-medium mb-1">Drag & drop a file here</p>
			<p class="text-slate-500 text-xs mb-3">CSV, TSV, Excel (.xlsx / .xls) supported</p>
			<label class="cursor-pointer">
				<span class="text-gold hover:text-gold-light underline text-sm">or browse files</span>
				<input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.ods" class="hidden" onchange={onFileInput} aria-label="Choose file to upload" />
			</label>
		</div>

		<!-- Schema reference -->
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-4 text-sm space-y-3">
			<p class="text-slate-300 font-medium">Expected columns</p>
			<div class="space-y-2">
				<div class="flex items-start gap-3">
					<span class="text-gold font-mono text-xs mt-0.5 w-24 shrink-0">label</span>
					<div>
						<span class="text-xs bg-amber-900/50 text-amber-400 px-1.5 py-0.5 rounded font-medium">required</span>
						<p class="text-slate-400 text-xs mt-0.5">Entity name (e.g. company, person, or fund name)</p>
					</div>
				</div>
				<div class="flex items-start gap-3">
					<span class="text-slate-400 font-mono text-xs mt-0.5 w-24 shrink-0">description</span>
					<div>
						<span class="text-xs bg-navy-700 text-slate-400 px-1.5 py-0.5 rounded font-medium">optional</span>
						<p class="text-slate-400 text-xs mt-0.5">Short description or bio</p>
					</div>
				</div>
				<div class="flex items-start gap-3">
					<span class="text-slate-400 font-mono text-xs mt-0.5 w-24 shrink-0">gwm_id</span>
					<div>
						<span class="text-xs bg-navy-700 text-slate-400 px-1.5 py-0.5 rounded font-medium">optional</span>
						<p class="text-slate-400 text-xs mt-0.5">Internal GWM identifier — enables cross-campaign knowledge cache</p>
					</div>
				</div>
				<div class="flex items-start gap-3">
					<span class="text-slate-400 font-mono text-xs mt-0.5 w-24 shrink-0">any other</span>
					<div>
						<span class="text-xs bg-navy-700 text-slate-400 px-1.5 py-0.5 rounded font-medium">optional</span>
						<p class="text-slate-400 text-xs mt-0.5">Extra columns are stored as metadata</p>
					</div>
				</div>
			</div>

			<!-- Sample preview -->
			<div>
				<p class="text-slate-500 text-xs mb-1.5">Sample</p>
				<div class="overflow-x-auto">
					<table class="text-xs w-full font-mono">
						<thead>
							<tr class="text-slate-500">
								<th class="text-left pr-6 pb-1">label</th>
								<th class="text-left pr-6 pb-1">description</th>
								<th class="text-left pb-1">gwm_id</th>
							</tr>
						</thead>
						<tbody class="text-slate-400">
							<tr><td class="pr-6">Acme Corp</td><td class="pr-6">Widget manufacturer</td><td>GWM-001</td></tr>
							<tr><td class="pr-6">Globex Inc</td><td class="pr-6">Industrial conglomerate</td><td>GWM-002</td></tr>
							<tr><td class="pr-6">Initech LLC</td><td class="pr-6 text-slate-600">(blank)</td><td class="text-slate-600">(blank)</td></tr>
						</tbody>
					</table>
				</div>
				<button onclick={downloadSample} class="mt-2 text-xs text-gold hover:text-gold-light underline transition-colors">
					Download sample CSV
				</button>
			</div>
		</div>

		{#if error}<p class="text-red-400 text-sm" role="alert">{error}</p>{/if}

	{:else if stage === 'mapping'}
		<div class="flex items-center justify-between">
			<h3 class="font-medium text-slate-200">Map columns
				<span class="text-slate-500 font-normal text-sm ml-1">({rows.length.toLocaleString()} rows detected)</span>
			</h3>
		</div>
		<div class="grid grid-cols-3 gap-4">
			{#each [
				{ label: 'Label', hint: 'required', bind: 'labelCol', id: 'csv-col-label' },
				{ label: 'Description', hint: 'optional', bind: 'descCol', id: 'csv-col-desc' },
				{ label: 'GWM ID', hint: 'optional', bind: 'gwmIdCol', id: 'csv-col-gwm' },
			] as col}
				<div>
					<label for={col.id} class="block text-xs mb-1">
						<span class="text-slate-400">{col.label}</span>
						<span class="ml-1 {col.hint === 'required' ? 'text-amber-400' : 'text-slate-600'}">{col.hint}</span>
					</label>
					<select
						id={col.id}
						class="w-full bg-navy-700 border border-navy-600 rounded-lg px-2 py-1.5 text-sm text-slate-200"
						value={col.bind === 'labelCol' ? labelCol : col.bind === 'descCol' ? descCol : gwmIdCol}
						onchange={(e) => {
							const v = (e.target as HTMLSelectElement).value;
							if (col.bind === 'labelCol') labelCol = v;
							else if (col.bind === 'descCol') descCol = v;
							else gwmIdCol = v;
						}}
					>
						<option value="">— none —</option>
						{#each headers as h}
							<option value={h}>{h}</option>
						{/each}
					</select>
				</div>
			{/each}
		</div>
		{#if error}<p class="text-red-400 text-sm" role="alert">{error}</p>{/if}
		<div class="flex gap-2">
			<button onclick={toPreview} class="btn-gold">Preview</button>
			<button onclick={reset} class="btn-secondary">Cancel</button>
		</div>

	{:else if stage === 'preview'}
		<h3 class="font-medium text-slate-200">
			Preview
			<span class="text-slate-500 font-normal text-sm ml-1">(first 5 of {rows.length.toLocaleString()} rows)</span>
		</h3>
		<div class="overflow-x-auto">
			<table class="text-sm w-full">
				<thead>
					<tr class="text-slate-400 text-xs uppercase tracking-wide">
						<th class="text-left px-2 py-1">Label</th>
						<th class="text-left px-2 py-1">GWM ID</th>
						<th class="text-left px-2 py-1">Description</th>
					</tr>
				</thead>
				<tbody>
					{#each previewRows as row}
						<tr class="border-t border-navy-700">
							<td class="px-2 py-1.5 text-slate-200">{row[labelCol] ?? ''}</td>
							<td class="px-2 py-1.5 text-slate-400 font-mono text-xs">{gwmIdCol ? (row[gwmIdCol] ?? '') : '—'}</td>
							<td class="px-2 py-1.5 text-slate-500 truncate max-w-xs">{descCol ? (row[descCol] ?? '') : '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if rows.length > BATCH_SIZE}
			<p class="text-xs text-slate-500">
				Large file — will be uploaded in {Math.ceil(rows.length / BATCH_SIZE)} batches of {BATCH_SIZE.toLocaleString()}.
			</p>
		{/if}
		{#if error}<p class="text-red-400 text-sm" role="alert">{error}</p>{/if}
		<div class="flex gap-2">
			<button onclick={upload} class="btn-gold">Upload {rows.length.toLocaleString()} entities</button>
			<button onclick={() => (stage = 'mapping')} class="btn-secondary">Back</button>
		</div>

	{:else if stage === 'uploading'}
		<div class="space-y-3">
			<div class="flex items-center justify-between text-sm">
				<span class="text-slate-400">Uploading entities…</span>
				<span class="text-slate-300 font-mono">{uploadedCount.toLocaleString()} / {totalCount.toLocaleString()}</span>
			</div>
			<!-- Progress bar -->
			<div
				class="h-2 bg-navy-700 rounded-full overflow-hidden"
				role="progressbar"
				aria-valuenow={uploadedCount}
				aria-valuemin={0}
				aria-valuemax={totalCount}
				aria-label="Uploading entities: {uploadPct}% complete"
			>
				<div
					class="h-full bg-gold rounded-full transition-all duration-300"
					style="width: {uploadPct}%"
				></div>
			</div>
			<p class="text-xs text-slate-500">{uploadPct}% complete</p>
		</div>

	{:else if stage === 'done'}
		<div class="space-y-1.5">
			<div class="flex items-center gap-2 text-green-400">
				<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
				</svg>
				<span>{insertedCount.toLocaleString()} {insertedCount === 1 ? 'entity' : 'entities'} added.</span>
			</div>
			{#if skippedCount > 0}
				<p class="text-xs text-amber-400 pl-6">
					{skippedCount.toLocaleString()} {skippedCount === 1 ? 'row' : 'rows'} skipped — duplicate label within this campaign.
				</p>
			{/if}
		</div>
		<button onclick={reset} class="btn-secondary text-sm">Upload another file</button>
	{/if}
</div>

