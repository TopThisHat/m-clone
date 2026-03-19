<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		getTeam,
		updateTeam,
		deleteTeam,
		inviteMember,
		updateMemberRole,
		removeMember,
		type TeamDetail,
	} from '$lib/api/teams';
	import { currentUser } from '$lib/stores/authStore';

	let slug = $derived(page.params.slug as string);
	let team = $state<TeamDetail | null>(null);
	let loading = $state(true);
	let error = $state('');
	let saving = $state(false);

	// Edit fields
	let editName = $state('');
	let editDesc = $state('');

	// Invite
	let inviteSid = $state('');
	let inviteRole = $state('member');
	let inviting = $state(false);
	let inviteError = $state('');

	// Delete
	let confirmDelete = $state(false);
	let deleting = $state(false);

	async function load() {
		loading = true;
		error = '';
		try {
			team = await getTeam(slug);
			editName = team.display_name;
			editDesc = team.description;
		} catch (e: unknown) {
			const msg = (e as Error).message || '';
			error = msg.includes('permission')
				? "You don't have permission to view these settings."
				: msg.includes('Not found') || msg.includes('not found')
				  ? 'This team does not exist.'
				  : 'Could not load settings — please try again.';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	let saveError = $state('');
	let saveSuccess = $state(false);

	async function saveSettings() {
		if (!team) return;
		saving = true;
		saveError = '';
		saveSuccess = false;
		try {
			await updateTeam(slug, { display_name: editName, description: editDesc });
			team = { ...team, display_name: editName, description: editDesc };
			saveSuccess = true;
			setTimeout(() => (saveSuccess = false), 2000);
		} catch (e: unknown) {
			saveError = (e as Error).message || 'Failed to save changes.';
		} finally {
			saving = false;
		}
	}

	async function handleInvite() {
		if (!inviteSid.trim()) return;
		inviteError = '';
		inviting = true;
		try {
			await inviteMember(slug, inviteSid.trim(), inviteRole);
			inviteSid = '';
			await load();
		} catch (e: unknown) {
			inviteError = (e as Error).message || 'Failed to invite';
		} finally {
			inviting = false;
		}
	}

	let memberError = $state('');

	async function changeRole(sid: string, role: string) {
		memberError = '';
		try {
			await updateMemberRole(slug, sid, role);
			await load();
		} catch (e: unknown) {
			memberError = (e as Error).message || 'Failed to update role.';
		}
	}

	async function kick(sid: string) {
		memberError = '';
		try {
			await removeMember(slug, sid);
			await load();
		} catch (e: unknown) {
			memberError = (e as Error).message || 'Failed to remove member.';
		}
	}

	async function handleDelete() {
		deleting = true;
		try {
			await deleteTeam(slug);
			goto('/teams');
		} catch {
			error = 'Failed to delete team';
			deleting = false;
		}
	}
</script>

<svelte:head>
	<title>Settings — {team?.display_name ?? slug}</title>
</svelte:head>

<div class="max-w-2xl mx-auto px-6 py-8 space-y-8">
	<div class="flex items-center gap-3">
		<a href="/teams/{slug}" class="text-slate-500 hover:text-gold text-xs">← Back</a>
		<h1 class="font-serif text-xl text-gold">Team Settings</h1>
	</div>

	{#if loading}
		<p class="text-slate-500 text-sm">Loading…</p>
	{:else if error && !team}
		<p class="text-red-400 text-sm">{error}</p>
	{:else if team}
		<!-- General Settings -->
		<section class="bg-navy-900 border border-navy-700 rounded-xl p-6 space-y-4">
			<h2 class="text-sm font-medium text-slate-300">General</h2>
			<div>
				<label for="edit-team-name" class="block text-xs text-slate-400 mb-1">Display Name</label>
				<input
					id="edit-team-name"
					bind:value={editName}
					class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-gold/40"
				/>
			</div>
			<div>
				<label for="edit-team-desc" class="block text-xs text-slate-400 mb-1">Description</label>
				<textarea
					id="edit-team-desc"
					bind:value={editDesc}
					rows="2"
					class="w-full bg-navy-800 border border-navy-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-gold/40 resize-none"
				></textarea>
			</div>
			<div class="flex items-center gap-3">
				<button
					onclick={saveSettings}
					disabled={saving}
					class="px-4 py-2 bg-gold text-navy text-sm font-medium rounded hover:bg-gold/90 disabled:opacity-50 transition-colors"
				>
					{saving ? 'Saving…' : 'Save Changes'}
				</button>
				{#if saveSuccess}
					<span class="text-xs text-green-400">Saved!</span>
				{/if}
				{#if saveError}
					<span class="text-xs text-red-400">{saveError}</span>
				{/if}
			</div>
		</section>

		<!-- Members -->
		<section class="bg-navy-900 border border-navy-700 rounded-xl p-6 space-y-4">
			<h2 class="text-sm font-medium text-slate-300">Members</h2>
			{#if memberError}
				<p class="text-xs text-red-400 flex items-center gap-1">
					<svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
					{memberError}
				</p>
			{/if}

			<div class="divide-y divide-navy-700">
				{#each team.members as m (m.sid)}
					<div class="flex items-center gap-3 py-3">
						<div class="w-8 h-8 rounded-full bg-navy-700 flex items-center justify-center text-xs text-gold font-bold">
							{m.display_name.charAt(0).toUpperCase()}
						</div>
						<div class="flex-1 min-w-0">
							<p class="text-sm text-slate-200">{m.display_name}</p>
							<p class="text-xs text-slate-600">{m.sid}</p>
						</div>
						{#if m.role === 'owner'}
							<span class="text-xs text-gold font-medium">owner</span>
						{:else if team.your_role === 'owner' || team.your_role === 'admin'}
							<select
								value={m.role}
								onchange={(e) => changeRole(m.sid, (e.target as HTMLSelectElement).value)}
								class="bg-navy-800 border border-navy-700 text-xs text-slate-300 rounded px-2 py-1 focus:outline-none focus:border-gold/40"
							>
								<option value="viewer">viewer</option>
								<option value="member">member</option>
								<option value="admin">admin</option>
							</select>
							{#if m.sid !== $currentUser?.sid}
								<button
									onclick={() => kick(m.sid)}
									class="text-xs text-slate-600 hover:text-red-400 transition-colors ml-1"
								>
									Remove
								</button>
							{/if}
						{:else}
							<span class="text-xs text-slate-500">{m.role}</span>
						{/if}
					</div>
				{/each}
			</div>

			<!-- Invite -->
			{#if team.your_role === 'owner' || team.your_role === 'admin'}
				<div class="pt-3 border-t border-navy-700">
					<h3 class="text-xs text-slate-400 mb-2">Invite by SID</h3>
					<div class="flex gap-2">
						<input
							bind:value={inviteSid}
							placeholder="User SID (must have logged in)"
							class="flex-1 bg-navy-800 border border-navy-700 rounded px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
						/>
						<select
							bind:value={inviteRole}
							class="bg-navy-800 border border-navy-700 text-xs text-slate-300 rounded px-2 py-2 focus:outline-none focus:border-gold/40"
						>
							<option value="viewer">viewer</option>
							<option value="member">member</option>
							<option value="admin">admin</option>
						</select>
						<button
							onclick={handleInvite}
							disabled={inviting || !inviteSid.trim()}
							class="px-3 py-2 bg-gold text-navy text-xs font-medium rounded hover:bg-gold/90 disabled:opacity-50 transition-colors"
						>
							{inviting ? '…' : 'Invite'}
						</button>
					</div>
					{#if inviteError}
						<p class="mt-1.5 text-xs text-red-400">{inviteError}</p>
					{/if}
				</div>
			{/if}
		</section>

		<!-- Danger Zone -->
		{#if team.your_role === 'owner'}
			<section class="bg-navy-900 border border-red-900/40 rounded-xl p-6">
				<h2 class="text-sm font-medium text-red-400 mb-3">Danger Zone</h2>
				{#if !confirmDelete}
					<button
						onclick={() => (confirmDelete = true)}
						class="px-4 py-2 border border-red-800 text-red-400 text-sm rounded hover:bg-red-900/20 transition-colors"
					>
						Delete Team
					</button>
				{:else}
					<p class="text-sm text-slate-300 mb-3">Are you sure? This action cannot be undone.</p>
					<div class="flex gap-3">
						<button
							onclick={() => (confirmDelete = false)}
							class="px-4 py-2 border border-navy-600 text-slate-400 text-sm rounded"
						>
							Cancel
						</button>
						<button
							onclick={handleDelete}
							disabled={deleting}
							class="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700 disabled:opacity-50 transition-colors"
						>
							{deleting ? 'Deleting…' : 'Yes, delete forever'}
						</button>
					</div>
				{/if}
			</section>
		{/if}
	{/if}
</div>
