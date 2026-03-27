<script lang="ts">
	import type { LayoutData } from './$types';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import TeamSwitcher from '$lib/components/TeamSwitcher.svelte';
	import SearchOverlay from '$lib/components/SearchOverlay.svelte';

	let { data, children }: { data: LayoutData; children: import('svelte').Snippet } = $props();

	// Normalize teams to always be an array, guarding against null/undefined from the server
	const safeTeams = $derived(Array.isArray(data.teams) ? data.teams : []);

	// Validate stored team is still one the user belongs to
	onMount(() => {
		const stored = $scoutTeam;
		if (stored && !safeTeams.some((t: { id: string }) => t.id === stored)) {
			scoutTeam.select(null);
		}
	});

	const NAV = [
		{ label: 'Campaigns', href: '/campaigns' },
		{ label: 'Entities', href: '/entities' },
		{ label: 'Attributes', href: '/attributes' },
	];

	let searchOpen = $state(false);

	let currentPath = $derived(page.url.pathname);

	function isActive(href: string) {
		if (href === '/campaigns') return currentPath.startsWith('/campaigns');
		return currentPath.startsWith(href);
	}
</script>

<div class="p-6 h-full overflow-y-auto">
	<!-- Top bar: nav + team -->
	<div class="flex items-center justify-between mb-5 flex-wrap gap-3">
		<!-- Page nav -->
		<nav aria-label="Scout" class="flex items-center gap-1">
			{#each NAV as item (item.href)}
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

		<!-- Team switcher -->
		<TeamSwitcher teams={safeTeams} />
	</div>

	{@render children()}
</div>

<SearchOverlay
	open={searchOpen}
	onopen={() => (searchOpen = true)}
	onclose={() => (searchOpen = false)}
/>
