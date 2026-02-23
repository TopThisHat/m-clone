<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { getTeam, getTeamActivity, getTeamSessions, type TeamDetail } from '$lib/api/teams';

	interface ActivityItem {
		id: string;
		actor_sid: string;
		actor_name?: string;
		action: string;
		payload: Record<string, unknown>;
		created_at: string;
	}

	interface SharedSession {
		id: string;
		title: string;
		query: string;
		shared_at?: string;
		updated_at: string;
	}

	let slug = $derived($page.params.slug);
	let team = $state<TeamDetail | null>(null);
	let activity = $state<ActivityItem[]>([]);
	let sessions = $state<SharedSession[]>([]);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			const [t, a, s] = await Promise.all([
				getTeam(slug),
				getTeamActivity(slug).catch(() => [] as Record<string, unknown>[]),
				getTeamSessions(slug).catch(() => [] as Record<string, unknown>[]),
			]);
			team = t;
			activity = a as unknown as ActivityItem[];
			sessions = s as unknown as SharedSession[];
		} catch (e: unknown) {
			const msg = (e as Error).message || '';
			// 403 means the user isn't a member; 404 means the team doesn't exist
			error = msg.includes('permission')
				? "You're not a member of this team."
				: msg.includes('Not found') || msg.includes('not found')
				  ? 'This team does not exist.'
				  : 'Could not load team — please try again.';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function activityLabel(action: string, payload: Record<string, unknown>): string {
		switch (action) {
			case 'shared_session': return `shared "${payload.session_title}"`;
			case 'commented': return 'posted a comment';
			case 'pinned': return 'pinned a session';
			case 'joined': return `invited ${payload.invited_sid}`;
			default: return action;
		}
	}
</script>

<svelte:head>
	<title>{team?.display_name ?? slug} — Teams</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-6 py-8">
	{#if loading}
		<div class="flex items-center gap-2 text-slate-500 text-sm py-8">
			<span class="w-4 h-4 border-2 border-slate-600 border-t-gold rounded-full animate-spin"></span>
			<span>Loading team…</span>
		</div>
	{:else if error}
		<div class="text-center py-16 border border-dashed border-navy-700 rounded-lg">
			<p class="text-slate-400 text-sm">{error}</p>
			<a href="/teams" class="mt-4 inline-block text-xs text-gold hover:underline">← Back to Teams</a>
		</div>
	{:else if team}
		<!-- Header -->
		<div class="flex items-start justify-between mb-8">
			<div class="flex items-center gap-4">
				<div class="w-12 h-12 rounded-xl bg-gold/10 border border-gold/20 flex items-center justify-center text-gold font-serif font-bold text-2xl">
					{team.display_name.charAt(0)}
				</div>
				<div>
					<h1 class="font-serif text-2xl text-gold">{team.display_name}</h1>
					<p class="text-xs text-slate-600 mt-0.5">@{team.slug} · {team.members.length} member{team.members.length !== 1 ? 's' : ''} · you are {team.your_role}</p>
					{#if team.description}
						<p class="text-sm text-slate-400 mt-1">{team.description}</p>
					{/if}
				</div>
			</div>
			{#if team.your_role === 'owner' || team.your_role === 'admin'}
				<a
					href="/teams/{slug}/settings"
					class="px-3 py-1.5 border border-navy-700 text-slate-400 text-xs rounded hover:border-gold/30 hover:text-gold transition-colors"
				>
					Settings
				</a>
			{/if}
		</div>

		<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
			<!-- Shared Sessions -->
			<div class="lg:col-span-2 space-y-4">
				<h2 class="text-xs font-medium text-slate-400 uppercase tracking-wide">Shared Research</h2>
				{#if sessions.length === 0}
					<div class="border border-dashed border-navy-700 rounded-lg py-10 text-center">
						<p class="text-sm text-slate-600">No sessions shared yet</p>
						<p class="text-xs text-slate-700 mt-1">Share a research session from the main app</p>
					</div>
				{:else}
					{#each sessions as session (session.id)}
						<a
							href="/?session={session.id}"
							class="block p-4 bg-navy-900 border border-navy-700 rounded-lg hover:border-gold/30 transition-colors"
						>
							<h3 class="text-sm font-medium text-slate-200 truncate">{session.title}</h3>
							<p class="text-xs text-slate-600 mt-0.5 truncate">{session.query}</p>
							<p class="text-[10px] text-slate-700 mt-1.5">{new Date(session.shared_at ?? session.updated_at).toLocaleString()}</p>
						</a>
					{/each}
				{/if}
			</div>

			<!-- Sidebar -->
			<div class="space-y-6">
				<!-- Members -->
				<div>
					<h2 class="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">Members</h2>
					<div class="space-y-2">
						{#each team.members as m (m.sid)}
							<div class="flex items-center gap-2">
								<div class="w-7 h-7 rounded-full bg-navy-700 flex items-center justify-center text-xs text-gold font-bold flex-shrink-0">
									{m.display_name.charAt(0).toUpperCase()}
								</div>
								<div class="flex-1 min-w-0">
									<p class="text-xs text-slate-200 truncate">{m.display_name}</p>
								</div>
								<span class="text-[10px] text-slate-600">{m.role}</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- Activity Feed -->
				<div>
					<h2 class="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">Activity</h2>
					{#if activity.length === 0}
						<p class="text-xs text-slate-700">No activity yet</p>
					{:else}
						<div class="space-y-2">
							{#each activity.slice(0, 15) as item (item.id)}
								<div class="flex gap-2 text-xs">
									<div class="w-5 h-5 rounded-full bg-navy-700 flex items-center justify-center text-[9px] text-gold font-bold flex-shrink-0 mt-0.5">
										{(item.actor_name ?? item.actor_sid ?? '?').charAt(0).toUpperCase()}
									</div>
									<div>
										<span class="text-slate-300">{item.actor_name ?? item.actor_sid}</span>
										<span class="text-slate-500"> {activityLabel(item.action, item.payload)}</span>
										<br />
										<span class="text-[10px] text-slate-700">{new Date(item.created_at).toLocaleString()}</span>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>
