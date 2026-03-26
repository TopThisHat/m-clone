<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { jobsApi, type Score } from '$lib/api/jobs';
	import { attributesApi, type Attribute } from '$lib/api/attributes';

	let campaignId = $derived(page.params.id as string);
	let scores = $state<Score[]>([]);
	let attributes = $state<Attribute[]>([]);
	let loading = $state(true);
	let error = $state('');

	// ── Sort state ────────────────────────────────────────────────────────
	type SortKey = 'rank' | 'label' | 'score' | 'present' | 'checked' | 'coverage' | 'updated';
	let sortKey = $state<SortKey>('score');
	let sortAsc = $state(false);

	// ── Search ────────────────────────────────────────────────────────────
	let searchQuery = $state('');

	let filteredScores = $derived.by(() => {
		let s = scores;
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			s = s.filter((sc) =>
				(sc.entity_label ?? '').toLowerCase().includes(q) ||
				(sc.gwm_id ?? '').toLowerCase().includes(q)
			);
		}
		return s;
	});

	let sortedScores = $derived.by(() => {
		const sorted = [...filteredScores];
		const dir = sortAsc ? 1 : -1;
		sorted.sort((a, b) => {
			switch (sortKey) {
				case 'label':
					return dir * (a.entity_label ?? '').localeCompare(b.entity_label ?? '');
				case 'score':
					return dir * (a.total_score - b.total_score);
				case 'present':
					return dir * (a.attributes_present - b.attributes_present);
				case 'checked':
					return dir * (a.attributes_checked - b.attributes_checked);
				case 'coverage':
					return dir * (coverage(a) - coverage(b));
				case 'updated':
					return dir * ((a.last_updated ?? '').localeCompare(b.last_updated ?? ''));
				default:
					return dir * (b.total_score - a.total_score);
			}
		});
		return sorted;
	});

	let totalAttributes = $derived(attributes.length);

	function coverage(sc: Score): number {
		return totalAttributes > 0 ? sc.attributes_checked / totalAttributes : 0;
	}

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortAsc = !sortAsc;
		} else {
			sortKey = key;
			sortAsc = key === 'label';
		}
	}

	function sortArrow(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortAsc ? ' \u2191' : ' \u2193';
	}

	function scoreColor(score: number): string {
		if (score >= 0.8) return 'text-green-400';
		if (score >= 0.5) return 'text-gold';
		if (score >= 0.3) return 'text-orange-400';
		return 'text-red-400';
	}

	function scoreBg(score: number): string {
		if (score >= 0.8) return 'bg-green-500';
		if (score >= 0.5) return 'bg-gold';
		if (score >= 0.3) return 'bg-orange-400';
		return 'bg-red-500';
	}

	function timeAgo(iso: string | null): string {
		if (!iso) return '\u2014';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}

	function medalEmoji(rank: number): string {
		if (rank === 1) return '\uD83E\uDD47';
		if (rank === 2) return '\uD83E\uDD48';
		if (rank === 3) return '\uD83E\uDD49';
		return '';
	}

	onMount(async () => {
		try {
			const [scoresResult, attributesResult] = await Promise.all([
				jobsApi.getScores(campaignId),
				attributesApi.list(campaignId, { limit: 0 }),
			]);
			scores = scoresResult.sort((a, b) => b.total_score - a.total_score);
			attributes = attributesResult.items;
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to load rankings';
		} finally {
			loading = false;
		}
	});
</script>

<div class="max-w-5xl mx-auto">
	<div class="mb-2">
		<a href="/campaigns/{campaignId}" class="text-slate-500 hover:text-gold text-sm transition-colors">&larr; Campaign</a>
	</div>

	<div class="flex items-center justify-between mb-4 flex-wrap gap-2">
		<h2 class="font-serif text-gold text-xl font-bold">Rankings</h2>
		<div class="flex items-center gap-3">
			<span class="text-xs text-slate-500">{filteredScores.length} of {scores.length} entities</span>
			<input
				bind:value={searchQuery}
				placeholder="Search entities..."
				aria-label="Search entities"
				class="bg-navy-700 border border-navy-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold w-48"
			/>
		</div>
	</div>

	{#if error}
		<p class="text-red-400 mb-4" role="alert">{error}</p>
	{/if}

	{#if loading}
		<div class="flex justify-center py-16" aria-live="polite" aria-busy="true">
			<span class="flex gap-1" aria-hidden="true">
				{#each [0, 1, 2] as j (j)}
					<span class="w-2 h-2 bg-gold/40 rounded-full animate-bounce" style="animation-delay:{j * 0.15}s"></span>
				{/each}
			</span>
		</div>
	{:else if sortedScores.length === 0}
		<div class="bg-navy-800 border border-navy-700 rounded-xl p-8 text-center">
			<p class="text-slate-500">
				{searchQuery ? `No entities matching "${searchQuery}"` : 'No scored entities yet. Run a validation job first.'}
			</p>
		</div>
	{:else}
		<div class="bg-navy-800 border border-navy-700 rounded-xl overflow-hidden">
			<div class="overflow-x-auto">
				<table class="w-full text-sm" role="grid" aria-label="Entity rankings">
					<thead>
						<tr class="border-b border-navy-700 bg-navy-900">
							<th class="px-3 py-3 text-left text-xs text-slate-500 uppercase tracking-wider w-14">
								<button type="button" onclick={() => toggleSort('rank')} class="hover:text-gold transition-colors min-h-[44px] flex items-center">
									#{sortArrow('rank')}
								</button>
							</th>
							<th class="px-3 py-3 text-left text-xs text-slate-500 uppercase tracking-wider">
								<button type="button" onclick={() => toggleSort('label')} class="hover:text-gold transition-colors min-h-[44px] flex items-center">
									Entity{sortArrow('label')}
								</button>
							</th>
							<th class="px-3 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-28">
								<button type="button" onclick={() => toggleSort('score')} class="hover:text-gold transition-colors min-h-[44px] flex items-center justify-end w-full">
									Score{sortArrow('score')}
								</button>
							</th>
							<th class="px-3 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-24">
								<button type="button" onclick={() => toggleSort('present')} class="hover:text-gold transition-colors min-h-[44px] flex items-center justify-end w-full">
									Present{sortArrow('present')}
								</button>
							</th>
							<th class="px-3 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-24">
								<button type="button" onclick={() => toggleSort('coverage')} class="hover:text-gold transition-colors min-h-[44px] flex items-center justify-end w-full">
									Coverage{sortArrow('coverage')}
								</button>
							</th>
							<th class="px-3 py-3 text-right text-xs text-slate-500 uppercase tracking-wider w-24">
								<button type="button" onclick={() => toggleSort('updated')} class="hover:text-gold transition-colors min-h-[44px] flex items-center justify-end w-full">
									Updated{sortArrow('updated')}
								</button>
							</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedScores as score, i (score.entity_id)}
							{@const rank = i + 1}
							{@const pct = Math.round(score.total_score * 100)}
							{@const coveragePct = Math.round(coverage(score) * 100)}
							<tr class="border-b border-navy-700/50 hover:bg-navy-700/30 transition-colors">
								<td class="px-3 py-3 text-slate-500 font-mono text-xs tabular-nums">
									{#if medalEmoji(rank)}
										<span class="text-base">{medalEmoji(rank)}</span>
									{:else}
										{rank}
									{/if}
								</td>
								<td class="px-3 py-3">
									<div class="flex items-center gap-2 min-w-0">
										<a
											href="/campaigns/{campaignId}/results"
											class="font-medium text-slate-200 hover:text-gold truncate transition-colors"
										>
											{score.entity_label ?? score.entity_id}
										</a>
										{#if score.gwm_id}
											<span class="text-xs text-slate-600 font-mono flex-shrink-0">{score.gwm_id}</span>
										{/if}
										{#if score.score_stale}
											<span
												class="text-amber-400 text-xs px-1 py-0.5 rounded border border-amber-700 bg-amber-950 animate-pulse flex-shrink-0"
												role="status"
												tabindex="0"
												aria-label="Score is being recalculated"
											>stale</span>
										{/if}
									</div>
								</td>
								<td class="px-3 py-3 text-right">
									<div class="flex items-center justify-end gap-2">
										<div class="w-16 h-1.5 bg-navy-700 rounded-full overflow-hidden">
											<div class="h-1.5 rounded-full {scoreBg(score.total_score)} transition-all" style="width:{pct}%"></div>
										</div>
										<span class="font-mono font-semibold tabular-nums {scoreColor(score.total_score)} w-12 text-right">
											{score.total_score.toFixed(2)}
										</span>
									</div>
								</td>
								<td class="px-3 py-3 text-right font-mono tabular-nums text-slate-300">
									{score.attributes_present}<span class="text-slate-600">/{totalAttributes}</span>
								</td>
								<td class="px-3 py-3 text-right font-mono tabular-nums text-slate-300">
									{coveragePct}%
								</td>
								<td class="px-3 py-3 text-right text-xs text-slate-500">
									{timeAgo(score.last_updated)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
