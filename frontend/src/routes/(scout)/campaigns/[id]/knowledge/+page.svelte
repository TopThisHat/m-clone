<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { jobsApi, type Knowledge } from '$lib/api/jobs';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let campaignId = $derived(page.params.id as string);
	let knowledge = $state<Knowledge[]>([]);
	let loading = $state(true);
	let error = $state('');
	let collapsed = $state<Set<string>>(new Set());

	onMount(async () => {
		try {
			knowledge = await jobsApi.getKnowledge(campaignId);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load knowledge';
		} finally {
			loading = false;
		}
	});

	// Group by entity label
	let grouped = $derived(() => {
		const map = new Map<string, Knowledge[]>();
		for (const k of knowledge) {
			const label = k.entity_label ?? k.gwm_id;
			if (!map.has(label)) map.set(label, []);
			map.get(label)!.push(k);
		}
		return map;
	});

	function toggleCollapse(label: string) {
		const next = new Set(collapsed);
		if (next.has(label)) next.delete(label); else next.add(label);
		collapsed = next;
	}

	function relativeTime(dateStr: string | null): string {
		if (!dateStr) return '—';
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days} day${days === 1 ? '' : 's'} ago`;
	}
</script>

<div class="max-w-4xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaign</a>
	</div>

	<h2 class="font-serif text-gold text-xl font-bold mb-6">Knowledge Cache</h2>

	{#if loading}
		<LoadingSpinner />
	{:else if error}
		<p class="text-red-400" role="alert">{error}</p>
	{:else if knowledge.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No cached knowledge yet. Run a job to populate the knowledge cache.</p>
		</div>
	{:else}
		<p class="text-slate-500 text-sm mb-4">{knowledge.length} cached result{knowledge.length === 1 ? '' : 's'} across {grouped().size} entities</p>
		<div class="space-y-3">
			{#each [...grouped().entries()] as [label, items] (label)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
					<button
						onclick={() => toggleCollapse(label)}
						aria-expanded={!collapsed.has(label)}
						class="w-full flex items-center justify-between px-4 py-3 hover:bg-navy-700 transition-colors text-left"
					>
						<div class="flex items-center gap-3">
							<span class="font-medium text-slate-200">{label}</span>
							{#if items[0].gwm_id}
								<span class="text-xs text-slate-500 font-mono">{items[0].gwm_id}</span>
							{/if}
							<span class="text-xs text-slate-500">{items.length} attribute{items.length === 1 ? '' : 's'}</span>
						</div>
						<svg
							class="w-4 h-4 text-slate-500 transition-transform {collapsed.has(label) ? '' : 'rotate-180'}"
							fill="none" stroke="currentColor" viewBox="0 0 24 24"
							aria-hidden="true"
						>
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</button>

					{#if !collapsed.has(label)}
						<div class="border-t border-navy-700">
							<table class="w-full text-sm" aria-label="Knowledge for {label}">
								<thead>
									<tr class="text-slate-500 text-xs border-b border-navy-700">
										<th scope="col" class="text-left px-4 py-2">Attribute</th>
										<th scope="col" class="px-4 py-2 text-center">Present</th>
										<th scope="col" class="px-4 py-2 text-center">Confidence</th>
										<th scope="col" class="text-left px-4 py-2">Source Campaign</th>
										<th scope="col" class="text-left px-4 py-2">Last Updated</th>
									</tr>
								</thead>
								<tbody>
									{#each items as k (k.attribute_label + k.gwm_id)}
										<tr class="border-t border-navy-700/50 hover:bg-navy-700/30">
											<td class="px-4 py-2 text-slate-300">{k.attribute_label}</td>
											<td class="px-4 py-2 text-center">
												<span class="{k.present ? 'text-green-400' : 'text-red-400'} font-medium">
													{k.present ? '✓' : '✗'}
												</span>
											</td>
											<td class="px-4 py-2 text-center text-slate-400">
												{k.confidence != null ? (k.confidence * 100).toFixed(0) + '%' : '—'}
											</td>
											<td class="px-4 py-2 text-slate-500 text-xs">
												{k.source_campaign_name ?? k.source_campaign_id ?? '—'}
											</td>
											<td class="px-4 py-2 text-slate-500 text-xs">
												{relativeTime(k.last_updated)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
