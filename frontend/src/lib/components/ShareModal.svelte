<script lang="ts">
	import { listTeams, type Team } from '$lib/api/teams';
	import {
		shareSession,
		unshareSession,
		shareSessionToTeam,
		unshareSessionFromTeam,
		getSessionTeams
	} from '$lib/api/sessions';

	interface Props {
		sessionId: string;
		currentVisibility: string; // 'private' | 'team' | 'public'
		onClose: () => void;
		onVisibilityChange?: (v: string) => void;
	}

	let { sessionId, currentVisibility, onClose, onVisibilityChange }: Props = $props();

	type Mode = 'private' | 'team' | 'public';

	let mode = $state<Mode>(currentVisibility as Mode);
	let teams = $state<Team[]>([]);
	let sharedTeamIds = $state<string[]>([]);
	let loading = $state(true);
	let saving = $state(false);
	let copied = $state(false);
	let error = $state('');

	const shareUrl = $derived(`${typeof window !== 'undefined' ? window.location.origin : ''}/share/${sessionId}`);

	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		try {
			[teams, sharedTeamIds] = await Promise.all([
				listTeams(),
				getSessionTeams(sessionId)
			]);
		} catch {
			// ignore — empty lists
		} finally {
			loading = false;
		}
	}

	async function applyMode(newMode: Mode) {
		saving = true;
		error = '';
		try {
			if (newMode === 'public') {
				await shareSession(sessionId);
				mode = 'public';
			} else if (newMode === 'private') {
				await unshareSession(sessionId);
				// Also remove all team shares
				for (const tid of sharedTeamIds) {
					await unshareSessionFromTeam(sessionId, tid);
				}
				sharedTeamIds = [];
				mode = 'private';
			} else {
				// team — just switch the UI mode; team toggles handle sharing
				if (mode === 'public') await unshareSession(sessionId);
				mode = 'team';
			}
			onVisibilityChange?.(newMode);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update sharing';
		} finally {
			saving = false;
		}
	}

	async function toggleTeam(teamId: string) {
		saving = true;
		error = '';
		try {
			if (sharedTeamIds.includes(teamId)) {
				await unshareSessionFromTeam(sessionId, teamId);
				sharedTeamIds = sharedTeamIds.filter((id) => id !== teamId);
				if (sharedTeamIds.length === 0) {
					mode = 'private';
					onVisibilityChange?.('private');
				}
			} else {
				await shareSessionToTeam(sessionId, teamId);
				sharedTeamIds = [...sharedTeamIds, teamId];
				mode = 'team';
				onVisibilityChange?.('team');
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to update team sharing';
		} finally {
			saving = false;
		}
	}

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(shareUrl);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch {
			// ignore
		}
	}

	function backdropClick(e: MouseEvent) {
		if ((e.target as HTMLElement).dataset.backdrop) onClose();
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
	data-backdrop="true"
	onmousedown={backdropClick}
	role="dialog"
	aria-modal="true"
	aria-label="Share report"
>
	<div class="bg-navy-900 border border-navy-600 rounded-xl shadow-2xl w-full max-w-md mx-4">
		<!-- Header -->
		<div class="flex items-center justify-between px-5 py-4 border-b border-navy-700">
			<div>
				<h2 class="text-sm font-medium text-slate-200">Share report</h2>
				<p class="text-xs text-slate-500 mt-0.5">Control who can access this research report</p>
			</div>
			<button
				onclick={onClose}
				class="text-slate-500 hover:text-slate-300 transition-colors"
				aria-label="Close"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<div class="px-5 py-4 space-y-4">
			{#if loading}
				<div class="flex justify-center py-6">
					<span class="flex gap-1">
						{#each [0, 1, 2] as j}
							<span class="w-1.5 h-1.5 bg-gold/40 rounded-full animate-bounce" style="animation-delay: {j * 0.15}s"></span>
						{/each}
					</span>
				</div>
			{:else}
				<!-- Visibility toggle -->
				<div class="grid grid-cols-3 gap-2">
					{#each [['private', 'Private', 'Only you'], ['team', 'Team', 'Shared teams'], ['public', 'Public', 'Anyone with link']] as [val, label, sub]}
						<button
							onclick={() => applyMode(val as Mode)}
							disabled={saving}
							class="flex flex-col items-center gap-1 px-3 py-3 rounded-lg border text-center transition-all
								{mode === val
									? 'border-gold/60 bg-gold/5 text-gold'
									: 'border-navy-600 hover:border-navy-500 text-slate-400 hover:text-slate-300'}"
						>
							{#if val === 'private'}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
								</svg>
							{:else if val === 'team'}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
								</svg>
							{:else}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
								</svg>
							{/if}
							<span class="text-xs font-medium">{label}</span>
							<span class="text-[10px] opacity-60 leading-tight">{sub}</span>
						</button>
					{/each}
				</div>

				<!-- Team selector (visible when mode is team) -->
				{#if mode === 'team' || (mode !== 'public' && teams.length > 0)}
					{#if teams.length > 0}
						<div>
							<p class="text-xs text-slate-500 mb-2 uppercase tracking-widest">Share with teams</p>
							<div class="space-y-1.5">
								{#each teams as team (team.id)}
									<button
										onclick={() => toggleTeam(team.id)}
										disabled={saving}
										class="w-full flex items-center gap-3 px-3 py-2 rounded-lg border transition-all
											{sharedTeamIds.includes(team.id)
												? 'border-gold/40 bg-gold/5'
												: 'border-navy-700 hover:border-navy-600'}"
									>
										<div class="w-7 h-7 rounded-md bg-navy-700 flex items-center justify-center flex-shrink-0">
											<span class="text-xs font-medium text-gold">{team.display_name[0].toUpperCase()}</span>
										</div>
										<span class="text-sm text-slate-300 flex-1 text-left">{team.display_name}</span>
										{#if sharedTeamIds.includes(team.id)}
											<svg class="w-4 h-4 text-gold flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
											</svg>
										{/if}
									</button>
								{/each}
							</div>
						</div>
					{:else}
						<p class="text-xs text-slate-600 italic">You have no teams yet. Create a team to share with colleagues.</p>
					{/if}
				{/if}

				<!-- Public link copy -->
				{#if mode === 'public' || mode === 'team'}
					<div>
						<p class="text-xs text-slate-500 mb-2 uppercase tracking-widest">Share link</p>
						<div class="flex gap-2">
							<input
								type="text"
								readonly
								value={shareUrl}
								class="flex-1 bg-navy-800 border border-navy-600 rounded-lg px-3 py-2 text-xs text-slate-400 font-mono truncate"
							/>
							<button
								onclick={copyLink}
								class="px-3 py-2 rounded-lg border text-xs font-medium transition-all
									{copied
										? 'border-green-600/40 text-green-400 bg-green-900/10'
										: 'border-navy-600 hover:border-gold/30 text-slate-400 hover:text-gold'}"
							>
								{copied ? 'Copied!' : 'Copy'}
							</button>
						</div>
						{#if mode === 'team'}
							<p class="text-[11px] text-slate-600 mt-1.5">Team members with access can use this link to view and comment.</p>
						{:else}
							<p class="text-[11px] text-slate-600 mt-1.5">Anyone with this link can view the report (read-only).</p>
						{/if}
					</div>
				{/if}

				{#if error}
					<p class="text-xs text-red-400">{error}</p>
				{/if}
			{/if}
		</div>
	</div>
</div>
