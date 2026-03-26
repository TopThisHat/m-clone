<script lang="ts">
	import { onMount } from 'svelte';
	import { templatesApi, type AttributeTemplate } from '$lib/api/templates';

	let {
		onselect,
		ondelete,
	}: {
		onselect?: (template: AttributeTemplate) => void;
		ondelete?: (template: AttributeTemplate) => void;
	} = $props();

	let templates = $state<AttributeTemplate[]>([]);
	let loading = $state(true);
	let error = $state('');
	let deletingId = $state<string | null>(null);

	onMount(async () => {
		try {
			templates = await templatesApi.list();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load templates';
		} finally {
			loading = false;
		}
	});

	async function handleDelete(template: AttributeTemplate) {
		if (!confirm(`Delete template "${template.name}"? This cannot be undone.`)) return;
		deletingId = template.id;
		try {
			await templatesApi.delete(template.id);
			templates = templates.filter((t) => t.id !== template.id);
			ondelete?.(template);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to delete template';
		} finally {
			deletingId = null;
		}
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
	}
</script>

{#if error}
	<div class="mb-4 bg-red-950 border border-red-700 rounded-xl px-4 py-2.5 text-red-300 text-sm flex items-center justify-between" role="alert">
		<span>{error}</span>
		<button onclick={() => (error = '')} class="text-red-400 hover:text-red-200 ml-2">Dismiss</button>
	</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12" aria-live="polite" aria-busy="true">
		<span class="flex gap-1" aria-hidden="true">
			{#each [0, 1, 2] as j (j)}
				<span class="w-2 h-2 bg-gold/40 rounded-full animate-bounce" style="animation-delay:{j * 0.15}s"></span>
			{/each}
		</span>
	</div>
{:else if templates.length === 0}
	<div class="bg-navy-800 border border-navy-700 rounded-xl p-8 text-center">
		<p class="text-slate-500">No templates saved yet.</p>
		<p class="text-slate-600 text-sm mt-1">Create a campaign with attributes, then save them as a template.</p>
	</div>
{:else}
	<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
		<table class="w-full text-sm" role="grid" aria-label="Attribute templates">
			<thead>
				<tr class="border-b border-navy-700 bg-navy-900">
					<th class="px-4 py-3 text-left text-xs text-slate-500 uppercase tracking-wider">Name</th>
					<th class="px-4 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-24">Attributes</th>
					<th class="px-4 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-32">Created</th>
					<th class="px-4 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-24">
						<span class="sr-only">Actions</span>
					</th>
				</tr>
			</thead>
			<tbody>
				{#each templates as template (template.id)}
					<tr class="border-b border-navy-700/50 hover:bg-navy-700/30 transition-colors">
						<td class="px-4 py-3">
							{#if onselect}
								<button
									onclick={() => onselect?.(template)}
									class="font-medium text-slate-200 hover:text-gold transition-colors text-left"
								>
									{template.name}
								</button>
							{:else}
								<span class="font-medium text-slate-200">{template.name}</span>
							{/if}
							{#if template.team_id}
								<span class="text-xs text-slate-600 ml-2">Team</span>
							{/if}
						</td>
						<td class="px-4 py-3 text-right font-mono text-slate-400">
							{template.attributes.length}
						</td>
						<td class="px-4 py-3 text-right text-xs text-slate-500">
							{formatDate(template.created_at)}
						</td>
						<td class="px-4 py-3 text-right">
							<button
								onclick={() => handleDelete(template)}
								disabled={deletingId === template.id}
								class="min-w-[44px] min-h-[44px] flex items-center justify-center ml-auto text-slate-600 hover:text-red-400 transition-colors disabled:opacity-50"
								aria-label="Delete template {template.name}"
							>
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
								</svg>
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}
