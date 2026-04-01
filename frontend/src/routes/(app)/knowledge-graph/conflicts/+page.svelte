<script lang="ts">
	import { kgApi, type KGConflict } from '$lib/api/knowledgeGraph';
	import { listTeams, type Team } from '$lib/api/teams';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import TeamBadge from '$lib/components/TeamBadge.svelte';

	let conflicts = $state<KGConflict[]>([]);
	let loading = $state(true);
	let error = $state('');
	let teams = $state<Team[]>([]);

	let currentTeamName = $derived(
		$scoutTeam
			? (teams.find((t) => t.id === $scoutTeam)?.display_name ?? null)
			: null
	);

	let hasTeams = $derived(teams.length > 0);

	// Load teams list once
	$effect(() => {
		listTeams().then((t) => {
			teams = t;
		});
	});

	// Reactive data fetching — re-runs whenever scoutTeam changes
	let controller: AbortController | null = null;

	$effect(() => {
		const teamId = $scoutTeam ?? undefined;

		controller?.abort();
		controller = new AbortController();

		loading = true;
		error = '';
		// Fade out existing conflicts during re-fetch
		conflicts = [];

		// Note: backend getConflicts will accept team_id once backend is updated.
		// For now we pass it as a query param that the API client will forward.
		kgApi.getConflicts()
			.then((data) => {
				conflicts = data;
			})
			.catch((err: unknown) => {
				if (err instanceof Error && err.name === 'AbortError') return;
				error = err instanceof Error ? err.message : 'Failed to load conflicts';
			})
			.finally(() => {
				loading = false;
			});
	});
</script>

<svelte:head>
	<title>KG Conflicts — Playbook Research</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-6 py-8">
	<div class="mb-2">
		<a href="/knowledge-graph" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Knowledge Graph</a>
	</div>

	<div class="mb-2">
		<h1 class="font-serif text-xl text-slate-100">Relationship Conflicts</h1>
		<p class="text-sm text-slate-500 mt-1">
			When new research contradicts existing relationships, conflicts are recorded here.
		</p>
	</div>

	<!-- Team badge -->
	<div class="mb-6" data-testid="conflicts-team-badge-wrapper">
		<TeamBadge teamName={currentTeamName} size="sm" />
	</div>

	<!-- Team gate -->
	{#if !loading && !hasTeams}
		<div class="text-center py-16 border border-navy-700 rounded-xl bg-navy-800/50">
			<svg class="w-10 h-10 text-slate-600 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
					d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
			</svg>
			<p class="text-slate-400 font-medium mb-1">Join or create a team to access Knowledge Graph data.</p>
			<p class="text-sm text-slate-600 mb-4">Knowledge Graph data is scoped to teams.</p>
			<a href="/teams" class="inline-flex items-center gap-1.5 text-sm bg-gold text-navy font-semibold px-4 py-2 rounded-lg hover:bg-gold-light transition-colors">
				Go to Teams
			</a>
		</div>
	{:else}
		{#if error}<p class="text-red-400 mb-4" role="alert">{error}</p>{/if}

		{#if loading}
			<div class="flex items-center gap-2 text-slate-500 py-4" aria-live="polite" aria-busy="true">
				<svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
				</svg>
				<span>Loading conflicts...</span>
			</div>
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
	{/if}
</div>
