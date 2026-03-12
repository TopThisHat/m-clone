<script lang="ts">
	import { entitiesApi, type EntityCreate } from '$lib/api/entities';

	let {
		campaignId,
		onUploaded,
	}: {
		campaignId: string;
		onUploaded: () => void;
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

	async function handleFile(file: File) {
		error = '';
		const text = await file.text();
		const lines = text.trim().split('\n');
		if (lines.length < 2) { error = 'CSV must have a header row and at least one data row.'; return; }

		// Simple CSV parser (handles quoted fields)
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

		headers = parseRow(lines[0]);
		rows = lines.slice(1).map((line) => {
			const vals = parseRow(line);
			return Object.fromEntries(headers.map((h, i) => [h, vals[i] ?? '']));
		});

		// Auto-detect common column names
		labelCol = headers.find((h) => /^(label|name|entity|person|org)/i.test(h)) ?? headers[0] ?? '';
		descCol = headers.find((h) => /^(desc|description|bio)/i.test(h)) ?? '';
		gwmIdCol = headers.find((h) => /^(gwm_id|gwm|id)/i.test(h)) ?? '';

		stage = 'mapping';
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
		return rows.map((row) => ({
			label: row[labelCol] ?? '',
			description: descCol ? (row[descCol] ?? undefined) : undefined,
			gwm_id: gwmIdCol ? (row[gwmIdCol] ?? undefined) : undefined,
			metadata: Object.fromEntries(metaCols.map((h) => [h, row[h]])),
		})).filter((e) => e.label);
	}

	async function upload() {
		const entities = mappedEntities();
		if (!entities.length) { error = 'No valid rows to upload.'; return; }
		stage = 'uploading';
		error = '';
		try {
			await entitiesApi.bulkCreate(campaignId, entities);
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
	}

	let previewRows = $derived(rows.slice(0, 5));
</script>

<div class="space-y-4">
	{#if stage === 'idle'}
		<div
			role="region"
			aria-label="CSV drop zone"
			class="border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer
				{dragging ? 'border-gold bg-navy-700' : 'border-navy-600 hover:border-navy-500'}"
			ondragover={(e) => { e.preventDefault(); dragging = true; }}
			ondragleave={() => (dragging = false)}
			ondrop={onDrop}
		>
			<p class="text-slate-400 mb-2">Drag & drop a CSV file here</p>
			<label class="cursor-pointer">
				<span class="text-gold hover:text-gold-light underline text-sm">or browse</span>
				<input type="file" accept=".csv" class="hidden" onchange={onFileInput} />
			</label>
		</div>

	{:else if stage === 'mapping'}
		<h3 class="font-medium text-slate-200">Map CSV columns ({rows.length} rows detected)</h3>
		<div class="grid grid-cols-3 gap-4">
			{#each [
				{ label: 'Label (required)', bind: 'labelCol' },
				{ label: 'Description', bind: 'descCol' },
				{ label: 'GWM ID', bind: 'gwmIdCol' },
			] as col}
				<div>
					<label class="block text-xs text-slate-400 mb-1">{col.label}</label>
					<select
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
		{#if error}<p class="text-red-400 text-sm">{error}</p>{/if}
		<div class="flex gap-2">
			<button onclick={toPreview} class="btn-gold">Preview</button>
			<button onclick={reset} class="btn-secondary">Cancel</button>
		</div>

	{:else if stage === 'preview'}
		<h3 class="font-medium text-slate-200">Preview (first 5 of {rows.length} rows)</h3>
		<div class="overflow-x-auto">
			<table class="text-sm w-full">
				<thead>
					<tr class="text-slate-400">
						<th class="text-left px-2 py-1">Label</th>
						<th class="text-left px-2 py-1">GWM ID</th>
						<th class="text-left px-2 py-1">Description</th>
					</tr>
				</thead>
				<tbody>
					{#each previewRows as row}
						<tr class="border-t border-navy-700">
							<td class="px-2 py-1 text-slate-200">{row[labelCol] ?? ''}</td>
							<td class="px-2 py-1 text-slate-400 font-mono text-xs">{gwmIdCol ? (row[gwmIdCol] ?? '') : ''}</td>
							<td class="px-2 py-1 text-slate-500 truncate max-w-xs">{descCol ? (row[descCol] ?? '') : ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if error}<p class="text-red-400 text-sm">{error}</p>{/if}
		<div class="flex gap-2">
			<button onclick={upload} class="btn-gold">Upload {rows.length} entities</button>
			<button onclick={() => (stage = 'mapping')} class="btn-secondary">Back</button>
		</div>

	{:else if stage === 'uploading'}
		<p class="text-slate-400">Uploading {rows.length} entities…</p>

	{:else if stage === 'done'}
		<p class="text-green-400">✓ {rows.length} entities uploaded successfully.</p>
		<button onclick={reset} class="btn-secondary text-sm">Upload another file</button>
	{/if}
</div>

<style>
	.btn-gold {
		@apply bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors text-sm;
	}
	.btn-secondary {
		@apply bg-navy-700 text-slate-300 px-4 py-2 rounded-lg hover:bg-navy-600 transition-colors text-sm border border-navy-600;
	}
</style>
