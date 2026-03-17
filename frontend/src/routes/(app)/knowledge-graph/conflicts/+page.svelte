<script lang="ts">
	import { onMount } from 'svelte';
	import { kgApi, type KGConflict } from '$lib/api/knowledgeGraph';

	let conflicts = $state<KGConflict[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			conflicts = await kgApi.getConflicts();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load conflicts';
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>KG Conflicts — Playbook Research</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-6 py-8">
	<div class="mb-2">
		<a href="/knowledge-graph" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Knowledge Graph</a>
	</div>

	<div class="mb-6">
		<h1 class="font-serif text-xl text-slate-100">Relationship Conflicts</h1>
		<p class="text-sm text-slate-500 mt-1">
			When new research contradicts existing relationships, conflicts are recorded here.
		</p>
	</div>

	{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

	{#if loading}
		<p class="text-slate-500" aria-live="polite" aria-busy="true">Loading...</p>
	{:else if conflicts.length === 0}
		<div class="text-center py-12 text-slate-500">
			<p>No conflicts detected.</p>
		</div>
	{:else}
		<div class="space-y-3">
			{#each conflicts as conflict (conflict.id)}
				<div class="bg-navy-800 border border-navy-700 rounded-xl p-4">
					<div class="flex items-center gap-2 mb-2">
						<span class="text-sm font-medium text-slate-200">{conflict.subject_name}</span>
						<span class="text-slate-600">&rarr;</span>
						<span class="text-sm font-medium text-slate-200">{conflict.object_name}</span>
					</div>
					<div class="flex items-center gap-3 text-xs">
						<div class="flex items-center gap-1.5">
							<span class="text-red-400 line-through">{conflict.old_predicate}</span>
						</div>
						<span class="text-slate-600">&rarr;</span>
						<div class="flex items-center gap-1.5">
							<span class="text-green-400">{conflict.new_predicate}</span>
						</div>
						<span class="ml-auto text-slate-600">
							{new Date(conflict.detected_at).toLocaleDateString()}
						</span>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
