<script lang="ts">
	import type { LayoutData } from './$types';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import { page } from '$app/state';
	import { onMount } from 'svelte';

	let { data, children }: { data: LayoutData; children: import('svelte').Snippet } = $props();

	// Validate stored team is still one the user belongs to
	onMount(() => {
		const stored = $scoutTeam;
		if (stored && !data.teams.some((t: { id: string }) => t.id === stored)) {
			scoutTeam.select(null);
		}
	});

	const NAV = [
		{ label: 'Campaigns', href: '/campaigns' },
		{ label: 'Entities', href: '/entities' },
		{ label: 'Attributes', href: '/attributes' },
	];

	let currentPath = $derived(page.url.pathname);

	function isActive(href: string) {
		if (href === '/campaigns') return currentPath.startsWith('/campaigns');
		return currentPath.startsWith(href);
	}
</script>

<div class="p-6">
	<!-- Top bar: nav + team -->
	<div class="flex items-center justify-between mb-5 flex-wrap gap-3">
		<!-- Page nav -->
		<nav aria-label="Scout" class="flex items-center gap-1">
			{#each NAV as item}
				<a
					href={item.href}
					aria-current={isActive(item.href) ? 'page' : undefined}
					class="text-sm px-3 py-1.5 rounded-lg transition-colors
						{isActive(item.href)
							? 'bg-navy-700 text-slate-200 font-medium'
							: 'text-slate-500 hover:text-slate-300 hover:bg-navy-800'}"
				>
					{item.label}
				</a>
			{/each}
		</nav>

		<!-- Team picker -->
		{#if data.teams.length > 0}
			<div class="flex items-center gap-2">
				<span id="team-picker-label" class="text-xs text-slate-500 uppercase tracking-wide">Team</span>
				<div role="group" aria-labelledby="team-picker-label" class="flex items-center gap-1.5 flex-wrap">
					<button
						onclick={() => scoutTeam.select(null)}
						aria-pressed={$scoutTeam === null}
						class="text-xs px-3 py-1 rounded-full border transition-colors
							{$scoutTeam === null
								? 'bg-gold text-navy border-gold font-semibold'
								: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
					>
						Personal
					</button>
					{#each data.teams as team (team.id)}
						<button
							onclick={() => scoutTeam.select(team.id)}
							aria-pressed={$scoutTeam === team.id}
							class="text-xs px-3 py-1 rounded-full border transition-colors
								{$scoutTeam === team.id
									? 'bg-gold text-navy border-gold font-semibold'
									: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
						>
							{team.display_name}
						</button>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	{@render children()}
</div>
