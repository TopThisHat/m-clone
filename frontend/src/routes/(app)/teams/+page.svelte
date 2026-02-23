<script lang="ts">
	import { onMount } from 'svelte';
	import { listTeams, createTeam, type Team } from '$lib/api/teams';

	let teams = $state<Team[]>([]);
	let loading = $state(true);
	// No top-level error — listTeams returns [] on failure so we show the empty state

	// Create modal
	let showCreate = $state(false);
	let newSlug = $state('');
	let newName = $state('');
	let newDesc = $state('');
	let creating = $state(false);
	let createError = $state('');

	async function load() {
		loading = true;
		try {
			teams = await listTeams();
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function closeModal() {
		showCreate = false;
		newSlug = '';
		newName = '';
		newDesc = '';
		createError = '';
	}

	async function handleCreate() {
		createError = '';
		const slug = newSlug.trim();
		const name = newName.trim();
		if (!slug) { createError = 'Slug is required.'; return; }
		if (!name) { createError = 'Display name is required.'; return; }
		if (!/^[a-z0-9-]+$/.test(slug)) { createError = 'Slug can only contain lowercase letters, numbers, and hyphens.'; return; }

		creating = true;
		try {
			const t = await createTeam({ slug, display_name: name, description: newDesc.trim() });
			teams = [...teams, t];
			closeModal();
		} catch (e: unknown) {
			createError = (e as Error).message || 'Failed to create team.';
		} finally {
			creating = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') closeModal();
	}
</script>

<svelte:head>
	<title>Teams — Manus Research</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} />

<div class="max-w-3xl mx-auto px-6 py-8">
	<div class="flex items-center justify-between mb-6">
		<h1 class="font-serif text-2xl text-gold">Teams</h1>
		<button
			onclick={() => (showCreate = true)}
			class="px-4 py-2 bg-gold text-navy text-sm font-medium rounded hover:bg-gold/90 transition-colors"
		>
			+ New Team
		</button>
	</div>

	{#if loading}
		<div class="flex items-center gap-2 text-slate-500 text-sm py-8">
			<span class="w-4 h-4 border-2 border-slate-600 border-t-gold rounded-full animate-spin"></span>
			<span>Loading teams…</span>
		</div>
	{:else if teams.length === 0}
		<div class="text-center py-16 border border-dashed border-navy-700 rounded-lg">
			<div class="w-12 h-12 rounded-full border border-navy-600 flex items-center justify-center mx-auto mb-4">
				<svg class="w-5 h-5 text-navy-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
				</svg>
			</div>
			<p class="text-slate-400 text-sm font-medium">No teams yet</p>
			<p class="text-slate-600 text-xs mt-1">Create a team to start collaborating on research</p>
			<button
				onclick={() => (showCreate = true)}
				class="mt-5 px-4 py-2 border border-gold/30 text-gold text-sm rounded hover:bg-gold/10 transition-colors"
			>
				Create your first team
			</button>
		</div>
	{:else}
		<div class="grid gap-3">
			{#each teams as team (team.id)}
				<a
					href="/teams/{team.slug}"
					class="block p-4 bg-navy-900 border border-navy-700 rounded-lg hover:border-gold/30 transition-colors"
				>
					<div class="flex items-center gap-3">
						<div class="w-10 h-10 rounded-lg bg-gold/10 border border-gold/20 flex items-center justify-center text-gold font-serif font-bold text-lg flex-shrink-0">
							{team.display_name.charAt(0).toUpperCase()}
						</div>
						<div class="flex-1 min-w-0">
							<h2 class="text-sm font-medium text-slate-100 truncate">{team.display_name}</h2>
							<p class="text-xs text-slate-600">@{team.slug}</p>
						</div>
						{#if team.role}
							<span class="text-xs text-slate-500 bg-navy-800 px-2 py-0.5 rounded flex-shrink-0">{team.role}</span>
						{/if}
					</div>
					{#if team.description}
						<p class="mt-2 text-xs text-slate-500 leading-relaxed line-clamp-2">{team.description}</p>
					{/if}
				</a>
			{/each}
		</div>
	{/if}
</div>

<!-- Create Team Modal -->
{#if showCreate}
	<div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
		<div class="bg-navy-900 border border-navy-700 rounded-xl p-6 w-full max-w-md shadow-2xl">
			<h2 class="font-serif text-gold text-lg mb-4">Create Team</h2>

			<div class="space-y-4">
				<div>
					<label class="block text-xs text-slate-400 mb-1" for="team-slug">
						Slug <span class="text-slate-600">(used in the URL — lowercase letters, numbers, hyphens)</span>
					</label>
					<input
						id="team-slug"
						bind:value={newSlug}
						placeholder="e.g. quant-research"
						class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
					/>
				</div>
				<div>
					<label class="block text-xs text-slate-400 mb-1" for="team-name">Display Name</label>
					<input
						id="team-name"
						bind:value={newName}
						placeholder="e.g. Quant Research"
						class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
					/>
				</div>
				<div>
					<label class="block text-xs text-slate-400 mb-1" for="team-desc">Description <span class="text-slate-600">(optional)</span></label>
					<textarea
						id="team-desc"
						bind:value={newDesc}
						placeholder="What does this team research?"
						rows="2"
						class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40 resize-none"
					></textarea>
				</div>
			</div>

			{#if createError}
				<p class="mt-3 text-xs text-red-400 flex items-center gap-1.5">
					<svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
					{createError}
				</p>
			{/if}

			<div class="flex gap-3 mt-5">
				<button
					onclick={closeModal}
					class="flex-1 py-2 border border-navy-600 text-slate-400 text-sm rounded hover:text-slate-200 transition-colors"
				>
					Cancel
				</button>
				<button
					onclick={handleCreate}
					disabled={creating}
					class="flex-1 py-2 bg-gold text-navy text-sm font-medium rounded hover:bg-gold/90 disabled:opacity-50 transition-colors"
				>
					{creating ? 'Creating…' : 'Create Team'}
				</button>
			</div>
		</div>
	</div>
{/if}
