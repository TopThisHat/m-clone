<script lang="ts">
	import type { Team } from '$lib/api/teams';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';

	let {
		teams = [],
		onswitch,
	}: {
		teams?: Team[] | null;
		/** Called after the active team changes, with the new team ID (null = personal). */
		onswitch?: (teamId: string | null) => void;
	} = $props();

	const safeTeams: Team[] = $derived(Array.isArray(teams) ? teams : []);

	function select(teamId: string | null) {
		scoutTeam.select(teamId);
		onswitch?.(teamId);
	}
</script>

{#if safeTeams.length === 0}
	<!-- Empty state: user has no teams -->
	<div class="flex items-center gap-2 text-xs text-slate-500">
		<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
				d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
		</svg>
		<span>No teams —
			<a href="/teams" class="text-gold hover:text-gold-light underline transition-colors">create one</a>
		</span>
	</div>
{:else}
	<div class="flex items-center gap-2">
		<span id="team-switcher-label" class="text-xs text-slate-500 uppercase tracking-wide shrink-0">Team</span>
		<div
			role="group"
			aria-labelledby="team-switcher-label"
			class="flex items-center gap-1.5 flex-wrap"
		>
			<button
				onclick={() => select(null)}
				aria-pressed={$scoutTeam === null}
				class="text-xs px-3 py-1 rounded-full border transition-colors
					{$scoutTeam === null
						? 'bg-gold text-navy border-gold font-semibold'
						: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
			>
				Personal
			</button>
			{#each safeTeams as team (team.id)}
				<button
					onclick={() => select(team.id)}
					aria-pressed={$scoutTeam === team.id}
					class="text-xs px-3 py-1 rounded-full border transition-colors
						{$scoutTeam === team.id
							? 'bg-gold text-navy border-gold font-semibold'
							: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
					title={team.role ? `${team.display_name} (${team.role})` : team.display_name}
				>
					{team.display_name}
				</button>
			{/each}
		</div>
	</div>
{/if}
