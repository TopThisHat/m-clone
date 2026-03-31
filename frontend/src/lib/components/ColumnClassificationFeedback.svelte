<script lang="ts">
	import type { ColumnClassificationDetail } from '$lib/api/documents';
	import { confidenceColor, confidenceBarColor } from '$lib/utils/confidence';

	/** All valid import roles a user can assign to a column */
	type ColumnRole = 'entity_label' | 'entity_gwm_id' | 'entity_description' | 'attribute';

	const ROLE_LABELS: Record<ColumnRole, string> = {
		entity_label: 'Entity Label',
		entity_gwm_id: 'GWM ID',
		entity_description: 'Description',
		attribute: 'Attribute',
	};

	const ROLE_HINTS: Record<ColumnRole, string> = {
		entity_label: 'Required — entity name or identifier',
		entity_gwm_id: 'Internal GWM identifier',
		entity_description: 'Short description or bio',
		attribute: 'Extra metadata field',
	};

	const ALL_ROLES: ColumnRole[] = [
		'entity_label',
		'entity_gwm_id',
		'entity_description',
		'attribute',
	];

	let {
		classifications,
		onConfirm,
	}: {
		/** Map of column header -> LLM classification detail */
		classifications: Record<string, ColumnClassificationDetail>;
		/** Emitted when user confirms the column map. Receives the finalized role per column. */
		onConfirm?: (columnMap: Record<string, ColumnRole>) => void;
	} = $props();

	/** User-editable overrides — pre-populated from LLM classification, resets when classifications change */
	let overrides = $state<Record<string, ColumnRole>>({});

	$effect(() => {
		overrides = Object.fromEntries(
			Object.entries(classifications).map(([col, detail]) => [col, detail.role])
		);
	});

	/** Whether any override differs from the LLM suggestion */
	let hasOverrides = $derived(
		Object.entries(overrides).some(
			([col, role]) => role !== classifications[col]?.role
		)
	);

	/** Whether at least one column is mapped to entity_label (required for import) */
	let hasEntityLabel = $derived(
		Object.values(overrides).some((r) => r === 'entity_label')
	);

	/** True when the user's current role assignment for this column differs from LLM suggestion */
	function isOverridden(col: string): boolean {
		return overrides[col] !== classifications[col]?.role;
	}

	function handleConfirm() {
		onConfirm?.({ ...overrides });
	}

	const columns = $derived(Object.keys(classifications));
</script>

<div class="space-y-4">
	<!-- Header -->
	<div class="flex items-start justify-between gap-2">
		<div>
			<h3 class="font-medium text-slate-200">Column Roles</h3>
			<p class="text-xs text-slate-500 mt-0.5">
				AI-assigned roles based on column names and sample values. Override any before importing.
			</p>
		</div>
		{#if hasOverrides}
			<span class="shrink-0 text-xs px-2 py-0.5 rounded border border-amber-800 bg-amber-950 text-amber-400">
				Modified
			</span>
		{/if}
	</div>

	<!-- Column list -->
	<div class="space-y-2" role="list" aria-label="Column classifications">
		{#each columns as col (col)}
			{@const detail = classifications[col]}
			{@const overrideRole = overrides[col]}
			{@const modified = isOverridden(col)}
			<div
				class="bg-navy-800 border rounded-xl px-4 py-3 space-y-2.5 transition-colors
					{modified ? 'border-amber-800/60' : 'border-navy-700'}"
				role="listitem"
			>
				<!-- Column name row -->
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<span class="font-mono text-sm text-gold-light truncate block" title={col}>{col}</span>
						{#if modified}
							<span class="text-xs text-slate-400 line-through">
								<span class="sr-only">AI suggested: </span>{ROLE_LABELS[detail.role]}
							</span>
						{/if}
					</div>

					<!-- Confidence badge (always shows LLM confidence) -->
					<span
						class="shrink-0 text-xs px-2 py-0.5 rounded border font-mono {confidenceColor(detail.confidence)}"
						title="AI confidence: {(detail.confidence * 100).toFixed(0)}%"
					>
						{(detail.confidence * 100).toFixed(0)}%
					</span>
				</div>

				<!-- Confidence bar -->
				<div
					class="w-full bg-navy-700 rounded-full h-1"
					role="progressbar"
					aria-valuenow={Math.round(detail.confidence * 100)}
					aria-valuemin={0}
					aria-valuemax={100}
					aria-label="AI confidence for {col}: {(detail.confidence * 100).toFixed(0)}%"
				>
					<div
						class="h-1 rounded-full transition-all {confidenceBarColor(detail.confidence)}"
						style="width: {detail.confidence * 100}%"
					></div>
				</div>

				<!-- Role selector + reasoning -->
				<div class="flex items-center gap-3">
					<div class="flex-1 min-w-0">
						<label for="role-{col}" class="sr-only">Role for column {col}</label>
						<select
							id="role-{col}"
							class="input-field w-full px-2 py-1.5 text-sm
								{modified ? 'text-amber-300 border-amber-800' : ''}"
							value={overrideRole}
							onchange={(e) => {
								overrides[col] = (e.target as HTMLSelectElement).value as ColumnRole;
							}}
						>
							{#each ALL_ROLES as role (role)}
								<option value={role}>{ROLE_LABELS[role]}</option>
							{/each}
						</select>
						<p class="text-xs text-slate-400 mt-0.5">{ROLE_HINTS[overrideRole]}</p>
					</div>

					<!-- Reset override button -->
					{#if modified}
						<button
							onclick={() => { overrides[col] = detail.role; }}
							class="shrink-0 text-xs text-slate-500 hover:text-slate-300 transition-colors"
							title="Reset to AI suggestion"
							aria-label="Reset {col} to AI suggestion"
						>
							Reset
						</button>
					{/if}
				</div>

				<!-- LLM reasoning (collapsed by default for low-confidence columns) -->
				{#if detail.reasoning}
					<details class="group">
						<summary
							class="text-xs text-slate-400 hover:text-slate-300 cursor-pointer list-none flex items-center gap-1 transition-colors"
							aria-label="Toggle AI reasoning for {col}"
						>
							<svg
								class="w-3 h-3 transition-transform group-open:rotate-90"
								fill="none" stroke="currentColor" viewBox="0 0 24 24"
							>
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
							</svg>
							AI reasoning
						</summary>
						<p class="mt-1.5 text-xs text-slate-500 pl-4 border-l border-navy-600">
							{detail.reasoning}
						</p>
					</details>
				{/if}
			</div>
		{/each}
	</div>

	<!-- Validation notice -->
	{#if !hasEntityLabel}
		<div class="flex items-start gap-2 bg-amber-950 border border-amber-800 rounded-xl px-4 py-3" role="alert">
			<svg class="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
					d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
			</svg>
			<p class="text-amber-300 text-xs">
				At least one column must be assigned the <strong>Entity Label</strong> role before importing.
			</p>
		</div>
	{/if}

	<!-- Confirm button -->
	{#if onConfirm}
		<button
			onclick={handleConfirm}
			disabled={!hasEntityLabel}
			class="btn-gold w-full disabled:opacity-40 disabled:cursor-not-allowed"
		>
			Confirm column roles and import
		</button>
	{/if}
</div>
