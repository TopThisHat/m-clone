<script lang="ts">
	import { onMount } from 'svelte';
	import { getTeamSessions } from '$lib/api/teams';

	let { data }: { data: { slug: string } } = $props();

	interface LibrarySession {
		id: string;
		title: string;
		query: string;
		shared_at?: string;
		updated_at: string;
		owner_sid: string;
	}

	let sessions = $state<LibrarySession[]>([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let sort = $state<'newest' | 'oldest'>('newest');

	onMount(async () => {
		try {
			const raw = await getTeamSessions(data.slug);
			sessions = raw as unknown as LibrarySession[];
		} catch (e: unknown) {
			error = (e as Error).message || 'Failed to load library';
		} finally {
			loading = false;
		}
	});

	let filtered = $derived.by(() => {
		let result = sessions;
		if (search.trim()) {
			const q = search.trim().toLowerCase();
			result = result.filter(
				(s) =>
					s.title.toLowerCase().includes(q) ||
					s.query.toLowerCase().includes(q)
			);
		}
		if (sort === 'oldest') {
			result = [...result].reverse();
		}
		return result;
	});
</script>

<svelte:head>
	<title>Library — {data.slug} — Playbook Research</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-6 py-8">
	<div class="flex items-center gap-3 mb-6">
		<a href="/teams/{data.slug}" class="text-slate-500 hover:text-gold text-xs transition-colors">
			← {data.slug}
		</a>
		<span class="text-slate-700">/</span>
		<h1 class="font-serif text-2xl text-gold">Research Library</h1>
	</div>

	<!-- Controls -->
	<div class="flex items-center gap-3 mb-6">
		<input
			bind:value={search}
			type="text"
			placeholder="Search by title or query…"
			class="flex-1 input-field text-sm"
		/>
		<select
			bind:value={sort}
			class="bg-navy-900 border border-navy-700 rounded px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-gold/40"
		>
			<option value="newest">Newest first</option>
			<option value="oldest">Oldest first</option>
		</select>
	</div>

	{#if loading}
		<div class="flex items-center gap-2 text-slate-500 text-sm py-8">
			<span class="w-4 h-4 border-2 border-slate-600 border-t-gold rounded-full animate-spin"></span>
			Loading library…
		</div>
	{:else if error}
		<div class="text-center py-16 border border-dashed border-navy-700 rounded-lg">
			<p class="text-slate-400 text-sm">{error}</p>
		</div>
	{:else if filtered.length === 0}
		<div class="text-center py-16 border border-dashed border-navy-700 rounded-lg">
			{#if search}
				<p class="text-slate-500 text-sm">No results for "{search}"</p>
			{:else}
				<p class="text-slate-500 text-sm">No sessions shared with this team yet</p>
				<p class="text-slate-700 text-xs mt-1">Share research sessions from the main app to populate the library</p>
			{/if}
		</div>
	{:else}
		<div class="space-y-3">
			{#each filtered as session (session.id)}
				<a
					href="/share/{session.id}"
					target="_blank"
					rel="noopener noreferrer"
					class="block p-4 bg-navy-900 border border-navy-700 rounded-lg hover:border-gold/30 transition-colors group"
				>
					<div class="flex items-start justify-between gap-3">
						<div class="flex-1 min-w-0">
							<h3 class="text-sm font-medium text-slate-200 group-hover:text-gold transition-colors truncate">
								{session.title}
							</h3>
							<p class="text-xs text-slate-500 mt-0.5 truncate">{session.query}</p>
						</div>
						<span class="text-[10px] text-slate-600 flex-shrink-0 mt-0.5">
							{new Date(session.shared_at ?? session.updated_at).toLocaleDateString('en-US', {
								year: 'numeric',
								month: 'short',
								day: 'numeric',
							})}
						</span>
					</div>
					<div class="mt-2 flex items-center gap-2">
						<span class="text-[10px] text-gold/50 group-hover:text-gold/80 transition-colors">Open report →</span>
					</div>
				</a>
			{/each}
		</div>
		<p class="text-xs text-slate-700 text-center mt-6">{filtered.length} session{filtered.length !== 1 ? 's' : ''}</p>
	{/if}
</div>
