<script lang="ts">
	import * as XLSX from 'xlsx';
	import { attributesApi, type AttributeCreate } from '$lib/api/attributes';

	let {
		campaignId = '',
		onUploaded,
		onBulkCreate,
	}: {
		campaignId?: string;
		onUploaded: () => void;
		onBulkCreate?: (rows: AttributeCreate[]) => Promise<{ inserted: unknown[]; skipped: number }>;
	} = $props();

	type Stage = 'idle' | 'mapping' | 'preview' | 'uploading' | 'done';
	let stage = $state<Stage>('idle');
	let error = $state('');
	let dragging = $state(false);

	let headers = $state<string[]>([]);
	let rows = $state<Record<string, string>[]>([]);

	let labelCol = $state('');
	let descCol = $state('');
	let weightCol = $state('');

	let uploadedCount = $state(0);
	let totalCount = $state(0);
	let insertedCount = $state(0);
	let skippedCount = $state(0);

	const BATCH_SIZE = 500;

	const SAMPLE_CSV =
		'label,description,weight\n' +
		'Has board experience,Serves or has served on a public company board,1.5\n' +
		'ESG certified,Holds a recognized ESG or sustainability certification,1.0\n' +
		'Revenue > $100M,Annual revenue exceeds $100 million,2.0\n';

	function downloadSample() {
		const blob = new Blob([SAMPLE_CSV], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'attributes_sample.csv';
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

	async function handleFile(file: File) {
		error = '';
		try {
			const ext = file.name.split('.').pop()?.toLowerCase();
			let parsed: { headers: string[]; rows: Record<string, string>[] };
			if (ext === 'csv' || ext === 'tsv' || ext === 'txt') {
				parsed = parseCSV(await file.text());
			} else if (ext === 'xlsx' || ext === 'xls' || ext === 'ods') {
				parsed = parseExcel(await file.arrayBuffer());
			} else {
				error = 'Unsupported file type. Please upload a CSV or Excel file.';
				return;
			}
			headers = parsed.headers;
			rows = parsed.rows;

			labelCol = headers.find((h) => /^(label|name|attribute|criterion)/i.test(h)) ?? headers[0] ?? '';
			descCol = headers.find((h) => /^(desc|description|notes|prompt)/i.test(h)) ?? '';
			weightCol = headers.find((h) => /^(weight|score|priority)/i.test(h)) ?? '';

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

	function mappedAttributes(): AttributeCreate[] {
		const result: AttributeCreate[] = [];
		for (const row of rows) {
			const label = row[labelCol] ?? '';
			if (!label) continue;
			const weight = weightCol ? parseFloat(row[weightCol]) : NaN;
			result.push({
				label,
				description: descCol ? (row[descCol] || undefined) : undefined,
				weight: isNaN(weight) ? 1.0 : weight,
			});
		}
		return result;
	}

	async function upload() {
		const attributes = mappedAttributes();
		if (!attributes.length) { error = 'No valid rows to upload.'; return; }

		stage = 'uploading';
		error = '';
		uploadedCount = 0;
		totalCount = attributes.length;

		try {
			for (let i = 0; i < attributes.length; i += BATCH_SIZE) {
				const batch = attributes.slice(i, i + BATCH_SIZE);
				const result = onBulkCreate
					? await onBulkCreate(batch)
					: await attributesApi.bulkCreate(campaignId, batch);
				insertedCount += result.inserted.length;
				skippedCount += result.skipped;
				uploadedCount = Math.min(i + BATCH_SIZE, attributes.length);
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
				<input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.ods" class="hidden" onchange={onFileInput} />
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
						<p class="text-slate-400 text-xs mt-0.5">Attribute name (e.g. "Has board experience")</p>
					</div>
				</div>
				<div class="flex items-start gap-3">
					<span class="text-slate-400 font-mono text-xs mt-0.5 w-24 shrink-0">description</span>
					<div>
						<span class="text-xs bg-navy-700 text-slate-400 px-1.5 py-0.5 rounded font-medium">optional</span>
						<p class="text-slate-400 text-xs mt-0.5">Detailed prompt fed to the LLM when evaluating this attribute</p>
					</div>
				</div>
				<div class="flex items-start gap-3">
					<span class="text-slate-400 font-mono text-xs mt-0.5 w-24 shrink-0">weight</span>
					<div>
						<span class="text-xs bg-navy-700 text-slate-400 px-1.5 py-0.5 rounded font-medium">optional</span>
						<p class="text-slate-400 text-xs mt-0.5">Numeric scoring weight (default 1.0)</p>
					</div>
				</div>
			</div>

			<div>
				<p class="text-slate-500 text-xs mb-1.5">Sample</p>
				<div class="overflow-x-auto">
					<table class="text-xs w-full font-mono">
						<thead>
							<tr class="text-slate-500">
								<th class="text-left pr-6 pb-1">label</th>
								<th class="text-left pr-6 pb-1">description</th>
								<th class="text-left pb-1">weight</th>
							</tr>
						</thead>
						<tbody class="text-slate-400">
							<tr><td class="pr-6">Has board experience</td><td class="pr-6">Serves on a public company board</td><td>1.5</td></tr>
							<tr><td class="pr-6">ESG certified</td><td class="pr-6">Holds a sustainability certification</td><td>1.0</td></tr>
							<tr><td class="pr-6">Revenue &gt; $100M</td><td class="pr-6">Annual revenue exceeds $100M</td><td>2.0</td></tr>
						</tbody>
					</table>
				</div>
				<button onclick={downloadSample} class="mt-2 text-xs text-gold hover:text-gold-light underline transition-colors">
					Download sample CSV
				</button>
			</div>
		</div>

		{#if error}<p class="text-red-400 text-sm">{error}</p>{/if}

	{:else if stage === 'mapping'}
		<div class="flex items-center justify-between">
			<h3 class="font-medium text-slate-200">Map columns
				<span class="text-slate-500 font-normal text-sm ml-1">({rows.length.toLocaleString()} rows detected)</span>
			</h3>
		</div>
		<div class="grid grid-cols-3 gap-4">
			{#each [
				{ label: 'Label', hint: 'required', bind: 'labelCol' },
				{ label: 'Description', hint: 'optional', bind: 'descCol' },
				{ label: 'Weight', hint: 'optional', bind: 'weightCol' },
			] as col}
				<div>
					<label class="block text-xs mb-1">
						<span class="text-slate-400">{col.label}</span>
						<span class="ml-1 {col.hint === 'required' ? 'text-amber-400' : 'text-slate-600'}">{col.hint}</span>
					<select
						class="w-full bg-navy-700 border border-navy-600 rounded-lg px-2 py-1.5 text-sm text-slate-200"
						value={col.bind === 'labelCol' ? labelCol : col.bind === 'descCol' ? descCol : weightCol}
						onchange={(e) => {
							const v = (e.target as HTMLSelectElement).value;
							if (col.bind === 'labelCol') labelCol = v;
							else if (col.bind === 'descCol') descCol = v;
							else weightCol = v;
						}}
					>
						<option value="">— none —</option>
						{#each headers as h}
							<option value={h}>{h}</option>
						{/each}
					</select>
					</label>
				</div>
			{/each}
		</div>
		{#if error}<p class="text-red-400 text-sm">{error}</p>{/if}
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
						<th class="text-left px-2 py-1">Description</th>
						<th class="text-left px-2 py-1">Weight</th>
					</tr>
				</thead>
				<tbody>
					{#each previewRows as row}
						{@const w = weightCol ? parseFloat(row[weightCol]) : NaN}
						<tr class="border-t border-navy-700">
							<td class="px-2 py-1.5 text-slate-200">{row[labelCol] ?? ''}</td>
							<td class="px-2 py-1.5 text-slate-500 truncate max-w-xs">{descCol ? (row[descCol] ?? '—') : '—'}</td>
							<td class="px-2 py-1.5 text-slate-300 font-mono text-xs">{isNaN(w) ? '1.0' : w.toFixed(1)}</td>
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
		{#if error}<p class="text-red-400 text-sm">{error}</p>{/if}
		<div class="flex gap-2">
			<button onclick={upload} class="btn-gold">Upload {rows.length.toLocaleString()} attributes</button>
			<button onclick={() => (stage = 'mapping')} class="btn-secondary">Back</button>
		</div>

	{:else if stage === 'uploading'}
		<div class="space-y-3">
			<div class="flex items-center justify-between text-sm">
				<span class="text-slate-400">Uploading attributes…</span>
				<span class="text-slate-300 font-mono">{uploadedCount.toLocaleString()} / {totalCount.toLocaleString()}</span>
			</div>
			<div class="h-2 bg-navy-700 rounded-full overflow-hidden">
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
				<span>{insertedCount.toLocaleString()} {insertedCount === 1 ? 'attribute' : 'attributes'} added.</span>
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

