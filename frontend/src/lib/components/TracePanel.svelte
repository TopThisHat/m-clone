<script lang="ts">
	import type { TraceStep } from '$lib/stores/traceStore';
	import TraceStepCard from './TraceStep.svelte';
	import ResearchSwimlane from './ResearchSwimlane.svelte';
	import MemoryPanel from './MemoryPanel.svelte';
	import ChartCard from './ChartCard.svelte';
	import CommentThread from './CommentThread.svelte';
	import { isStreaming, memoryContext, chartData } from '$lib/stores/reportStore';
	import { activeSessionId } from '$lib/stores/sessionStore';
	import { currentUser } from '$lib/stores/authStore';
	import { listTeams, type Team } from '$lib/api/teams';

	let { steps }: { steps: TraceStep[] } = $props();

	let swimlaneView = $state(false);

	// Share to team
	let showShareModal = $state(false);
	let teams = $state<Team[]>([]);
	let selectedTeamId = $state('');
	let sharing = $state(false);
	let shareError = $state('');
	let shareSuccess = $state(false);

	async function openShareModal() {
		shareError = '';
		shareSuccess = false;
		selectedTeamId = '';
		try {
			teams = await listTeams();
		} catch {
			teams = [];
		}
		showShareModal = true;
	}

	async function shareToTeam() {
		if (!selectedTeamId || !$activeSessionId) return;
		sharing = true;
		shareError = '';
		try {
			const { assertOk } = await import('$lib/api/errors');
			const res = await fetch(`/api/sessions/${$activeSessionId}/teams`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({ team_id: selectedTeamId }),
			});
			await assertOk(res, 'Failed to share session.');
			shareSuccess = true;
			setTimeout(() => (showShareModal = false), 1200);
		} catch (e: unknown) {
			shareError = (e as Error).message || 'Failed to share session.';
		} finally {
			sharing = false;
		}
	}
</script>

<div class="flex flex-col gap-3 flex-1">
	<!-- Memory panel (shown when prior context injected) -->
	<MemoryPanel context={$memoryContext} />

	<!-- Charts from financial tool calls -->
	{#each $chartData as chart}
		<ChartCard {chart} />
	{/each}

	{#if steps.length === 0}
		<div class="flex-1 flex flex-col items-center justify-center py-24 gap-4">
			<div class="w-16 h-16 rounded-full border border-navy-600 flex items-center justify-center">
				<svg
					class="w-7 h-7 text-navy-500"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1.5"
						d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
					/>
				</svg>
			</div>
			<div class="text-center">
				<p class="text-slate-500 text-sm font-light">
					{$isStreaming ? 'Research in progress...' : 'Live agent trace will appear here'}
				</p>
				{#if !$isStreaming}
					<p class="text-slate-600 text-xs mt-1">Submit a research query to begin</p>
				{/if}
			</div>
		</div>
	{:else}
		<!-- View toggle + share button -->
		<div class="flex items-center justify-between mb-1">
			<span class="text-xs text-slate-600 uppercase tracking-widest">Trace</span>
			<div class="flex items-center gap-2">
				{#if $activeSessionId && $currentUser}
					<button
						onclick={openShareModal}
						class="flex items-center gap-1 text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded border border-navy-700 hover:border-gold/30"
						title="Share to team"
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
						</svg>
						Share
					</button>
				{/if}
				<button
					onclick={() => (swimlaneView = !swimlaneView)}
					class="flex items-center gap-1.5 text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded border border-navy-700 hover:border-gold/30"
					title={swimlaneView ? 'List view' : 'Swimlane view'}
				>
					{#if swimlaneView}
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
						</svg>
						List
					{:else}
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
						</svg>
						Lanes
					{/if}
				</button>
			</div>
		</div>

		{#if swimlaneView}
			<ResearchSwimlane {steps} />
		{:else}
			{#each steps as step (step.id)}
				<TraceStepCard {step} />
			{/each}
		{/if}

		{#if $isStreaming}
			<div class="flex items-center gap-2 px-4 py-2">
				<span class="flex gap-1">
					{#each [0, 1, 2] as i}
						<span
							class="w-1 h-1 bg-gold/40 rounded-full animate-bounce"
							style="animation-delay: {i * 0.15}s"
						></span>
					{/each}
				</span>
				<span class="text-xs text-slate-600 italic">Analysing...</span>
			</div>
		{/if}
	{/if}

	<!-- Comment thread (shown when session is loaded) -->
	{#if $activeSessionId}
		<CommentThread sessionId={$activeSessionId} />
	{/if}
</div>

<!-- Share to Team Modal -->
{#if showShareModal}
	<div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
		<div class="bg-navy-900 border border-navy-700 rounded-xl p-5 w-full max-w-sm shadow-2xl">
			<h3 class="font-serif text-gold text-base mb-4">Share to Team</h3>

			{#if teams.length === 0}
				<p class="text-xs text-slate-500 mb-4">
					You're not in any teams yet.
					<a href="/teams" class="text-gold hover:underline">Create or join a team</a>.
				</p>
			{:else}
				<select
					bind:value={selectedTeamId}
					class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-gold/40 mb-3"
				>
					<option value="">Select a team…</option>
					{#each teams as t (t.id)}
						<option value={t.id}>{t.display_name}</option>
					{/each}
				</select>
			{/if}

			{#if shareError}
				<p class="text-xs text-red-400 mb-2">{shareError}</p>
			{/if}
			{#if shareSuccess}
				<p class="text-xs text-green-400 mb-2">Shared successfully!</p>
			{/if}

			<div class="flex gap-2">
				<button
					onclick={() => (showShareModal = false)}
					class="flex-1 py-2 border border-navy-600 text-slate-400 text-xs rounded hover:text-slate-200 transition-colors"
				>
					Cancel
				</button>
				<button
					onclick={shareToTeam}
					disabled={!selectedTeamId || sharing || teams.length === 0}
					class="flex-1 py-2 bg-gold text-navy text-xs font-medium rounded hover:bg-gold/90 disabled:opacity-50 transition-colors"
				>
					{sharing ? 'Sharing…' : 'Share'}
				</button>
			</div>
		</div>
	</div>
{/if}
