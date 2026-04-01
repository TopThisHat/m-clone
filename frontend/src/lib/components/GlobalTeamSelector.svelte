<script lang="ts">
	import type { Team } from '$lib/api/teams';
	import { scoutTeam } from '$lib/stores/scoutTeamStore';
	import { goto } from '$app/navigation';
	import { tick } from 'svelte';

	let {
		teams = [],
	}: {
		teams?: Team[] | null;
	} = $props();

	const safeTeams: Team[] = $derived(Array.isArray(teams) ? teams : []);

	let open = $state(false);
	let searchQuery = $state('');
	let highlightIndex = $state(0);
	let triggerEl = $state<HTMLButtonElement | null>(null);
	let dropdownEl = $state<HTMLDivElement | null>(null);
	let searchEl = $state<HTMLInputElement | null>(null);

	const showSearch = $derived(safeTeams.length >= 6);

	const filteredTeams = $derived.by(() => {
		if (!searchQuery.trim()) return safeTeams;
		const q = searchQuery.toLowerCase();
		return safeTeams.filter((t) => t.display_name.toLowerCase().includes(q));
	});

	// All items for keyboard nav: Personal first, then filtered teams
	const allItems = $derived([null, ...filteredTeams.map((t) => t.id)]);

	const activeTeamId = $derived($scoutTeam);

	const activeTeam = $derived(safeTeams.find((t) => t.id === activeTeamId) ?? null);

	const isSingleTeam = $derived(safeTeams.length === 1);
	const hasNoTeams = $derived(safeTeams.length === 0);

	function getInitial(name: string): string {
		return name.trim().charAt(0).toUpperCase();
	}

	function getRoleBadgeClass(role: string | undefined): string {
		if (!role) return 'bg-navy-700 text-slate-400';
		if (role === 'admin' || role === 'owner') return 'bg-gold/15 text-gold';
		return 'bg-navy-700 text-slate-400';
	}

	function select(teamId: string | null) {
		scoutTeam.select(teamId);
		close();
		// Announce selection to screen readers
		const name = teamId ? (safeTeams.find((t) => t.id === teamId)?.display_name ?? teamId) : 'Personal';
		announceSelection(name);
	}

	let announcement = $state('');

	function announceSelection(name: string) {
		announcement = `Switched to ${name}`;
		setTimeout(() => {
			announcement = '';
		}, 2000);
	}

	function toggle() {
		if (isSingleTeam) {
			const team = safeTeams[0];
			goto(`/teams/${team.slug}`);
			return;
		}
		if (hasNoTeams) {
			goto('/teams');
			return;
		}
		if (open) {
			close();
		} else {
			openDropdown();
		}
	}

	function openDropdown() {
		open = true;
		highlightIndex = 0;
		searchQuery = '';
		// Focus search if available, else dropdown
		tick().then(() => {
			if (showSearch && searchEl) {
				searchEl.focus();
			} else {
				dropdownEl?.focus();
			}
		});
	}

	function close() {
		open = false;
		searchQuery = '';
		highlightIndex = 0;
		tick().then(() => triggerEl?.focus());
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) {
			if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
				e.preventDefault();
				openDropdown();
			}
			return;
		}

		switch (e.key) {
			case 'Escape':
				e.preventDefault();
				close();
				break;
			case 'ArrowDown':
				e.preventDefault();
				highlightIndex = Math.min(highlightIndex + 1, allItems.length - 1);
				scrollHighlightedIntoView();
				break;
			case 'ArrowUp':
				e.preventDefault();
				highlightIndex = Math.max(highlightIndex - 1, 0);
				scrollHighlightedIntoView();
				break;
			case 'Enter':
				e.preventDefault();
				if (allItems[highlightIndex] !== undefined) {
					select(allItems[highlightIndex]);
				}
				break;
			case 'Tab':
				trapFocus(e);
				break;
		}
	}

	function trapFocus(e: KeyboardEvent) {
		if (!dropdownEl) return;
		const focusable = dropdownEl.querySelectorAll<HTMLElement>(
			'button, [href], input, [tabindex]:not([tabindex="-1"])'
		);
		if (focusable.length === 0) return;
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		if (e.shiftKey) {
			if (document.activeElement === first) {
				e.preventDefault();
				last.focus();
			}
		} else {
			if (document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}

	function scrollHighlightedIntoView() {
		tick().then(() => {
			const el = dropdownEl?.querySelector('[data-highlighted="true"]');
			el?.scrollIntoView({ block: 'nearest' });
		});
	}

	let wrapperEl = $state<HTMLElement | null>(null);

	function handleOutsideClick(e: MouseEvent) {
		if (open && wrapperEl && !wrapperEl.contains(e.target as Node)) {
			close();
		}
	}

	// Validate stored team still exists in user's teams
	$effect(() => {
		const stored = $scoutTeam;
		if (stored && safeTeams.length > 0 && !safeTeams.some((t) => t.id === stored)) {
			scoutTeam.select(null);
		}
	});
</script>

<svelte:window onclick={handleOutsideClick} />

<!-- Screen reader live region -->
<div role="status" aria-live="polite" aria-atomic="true" class="sr-only">{announcement}</div>

<div bind:this={wrapperEl} class="global-team-selector relative">
	<!-- Trigger button -->
	<button
		bind:this={triggerEl}
		onclick={toggle}
		onkeydown={handleKeydown}
		aria-haspopup={isSingleTeam || hasNoTeams ? undefined : 'listbox'}
		aria-expanded={isSingleTeam || hasNoTeams ? undefined : open}
		aria-label={activeTeamId && activeTeam
			? `Current team: ${activeTeam.display_name}. Click to switch teams.`
			: 'Current workspace: Personal. Click to switch teams.'}
		class="inline-flex items-center gap-2 px-2 py-1 rounded-lg border border-navy-600 hover:border-navy-500 bg-navy-800/50 hover:bg-navy-800 cursor-pointer transition-all duration-150 max-w-44
			{activeTeamId || open ? 'ring-1 ring-gold/20' : ''}"
	>
		<!-- Avatar / Icon -->
		{#if activeTeamId && activeTeam}
			<!-- Team initial circle -->
			<span
				class="w-5 h-5 rounded-md bg-gold flex items-center justify-center flex-shrink-0 text-navy text-[10px] font-bold select-none"
				aria-hidden="true"
			>
				{getInitial(activeTeam.display_name)}
			</span>
		{:else}
			<!-- Personal / user icon -->
			<span
				class="w-5 h-5 rounded-md bg-navy-600 flex items-center justify-center flex-shrink-0 text-slate-400"
				aria-hidden="true"
			>
				<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
						d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
				</svg>
			</span>
		{/if}

		<!-- Label: hidden on mobile/tablet -->
		{#if hasNoTeams}
			<span class="hidden md:block text-xs text-slate-500 truncate">No teams</span>
		{:else if activeTeamId && activeTeam}
			<span class="hidden md:block text-xs text-slate-300 truncate">{activeTeam.display_name}</span>
		{:else}
			<span class="hidden md:block text-xs text-slate-300 truncate">Personal</span>
		{/if}

		<!-- Chevron: only when there are multiple teams to switch to -->
		{#if !isSingleTeam && !hasNoTeams}
			<svg
				class="hidden md:block w-3 h-3 text-slate-500 flex-shrink-0 transition-transform {open ? 'rotate-180' : ''}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				aria-hidden="true"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		{/if}
	</button>

	<!-- Dropdown -->
	{#if open && !isSingleTeam && !hasNoTeams}
		<div
			bind:this={dropdownEl}
			role="listbox"
			aria-label="Select team"
			tabindex="-1"
			onkeydown={handleKeydown}
			class="absolute right-0 top-9 z-50 w-64 bg-navy-900 border border-navy-600 rounded-xl shadow-[0_8px_32px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col max-h-[calc(100vh-80px)]
				sm:right-0
				max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:w-full max-sm:rounded-b-none max-sm:rounded-t-xl"
		>
			<!-- Mobile drag handle -->
			<div class="hidden max-sm:block w-10 h-1 rounded-full bg-navy-600 mx-auto mt-2 mb-1"></div>

			<!-- Search (shown when 6+ teams) -->
			{#if showSearch}
				<div class="px-3 pt-3 pb-2 border-b border-navy-700/50">
					<div class="flex items-center gap-2 bg-navy-800 rounded-lg px-2.5 py-1.5">
						<svg class="w-3.5 h-3.5 text-slate-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
						</svg>
						<input
							bind:this={searchEl}
							bind:value={searchQuery}
							oninput={() => { highlightIndex = 0; }}
							type="text"
							placeholder="Filter teams..."
							class="flex-1 bg-transparent text-xs text-slate-200 placeholder-slate-500 focus:outline-none"
							aria-label="Filter teams"
							autocomplete="off"
						/>
					</div>
				</div>
			{/if}

			<!-- Team list -->
			<div class="overflow-y-auto" style="max-height: 320px" role="group">
				<!-- Personal option (always first) -->
				<button
					onclick={() => select(null)}
					onmouseenter={() => { highlightIndex = 0; }}
					role="option"
					aria-selected={activeTeamId === null}
					data-highlighted={highlightIndex === 0}
					class="w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-navy-800
						{activeTeamId === null ? 'bg-gold/5 border-l-2 border-gold' : 'border-l-2 border-transparent'}
						{highlightIndex === 0 ? 'bg-navy-800' : ''}"
				>
					<!-- User icon -->
					<span
						class="w-6 h-6 rounded-md bg-navy-700 flex items-center justify-center flex-shrink-0 text-slate-400"
						aria-hidden="true"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
								d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
						</svg>
					</span>

					<div class="flex-1 min-w-0">
						<p class="text-xs font-medium text-slate-200 truncate">Personal</p>
						<p class="text-[10px] text-slate-500 truncate">Your personal workspace</p>
					</div>

					{#if activeTeamId === null}
						<svg class="w-3.5 h-3.5 text-gold flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
						</svg>
					{/if}
				</button>

				<!-- Divider -->
				{#if filteredTeams.length > 0}
					<div class="h-px bg-navy-700/50 mx-3"></div>
				{/if}

				<!-- Team rows -->
				{#each filteredTeams as team, i (team.id)}
					{@const itemIndex = i + 1}
					{@const isActive = activeTeamId === team.id}
					<button
						onclick={() => select(team.id)}
						onmouseenter={() => { highlightIndex = itemIndex; }}
						role="option"
						aria-selected={isActive}
						data-highlighted={highlightIndex === itemIndex}
						class="w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-navy-800
							{isActive ? 'bg-gold/5 border-l-2 border-gold' : 'border-l-2 border-transparent'}
							{highlightIndex === itemIndex ? 'bg-navy-800' : ''}"
					>
						<!-- Team initial circle -->
						<span
							class="w-6 h-6 rounded-md bg-navy-700 flex items-center justify-center flex-shrink-0 text-gold text-[10px] font-medium select-none"
							aria-hidden="true"
						>
							{getInitial(team.display_name)}
						</span>

						<div class="flex-1 min-w-0">
							<p class="text-xs font-medium text-slate-200 truncate">{team.display_name}</p>
							{#if team.role}
								<span class="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full mt-0.5 {getRoleBadgeClass(team.role)}">
									{team.role}
								</span>
							{/if}
						</div>

						{#if isActive}
							<svg class="w-3.5 h-3.5 text-gold flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
							</svg>
						{/if}
					</button>
				{/each}

				{#if filteredTeams.length === 0 && searchQuery.trim()}
					<p class="px-3 py-4 text-xs text-slate-500 text-center">No teams match "{searchQuery}"</p>
				{/if}
			</div>

			<!-- Footer -->
			<div class="border-t border-navy-700/50 px-3 py-2">
				<a
					href="/teams"
					onclick={() => { open = false; }}
					class="text-xs text-gold hover:text-gold-light transition-colors flex items-center gap-1"
				>
					Manage Teams
				</a>
			</div>
		</div>
	{/if}
</div>
