<script lang="ts">
	import { onMount } from 'svelte';
	import { notifications, unreadCount } from '$lib/stores/notifStore';
	import { markRead, markAllRead } from '$lib/api/notifications';

	let open = $state(false);

	onMount(() => {
		notifications.startPolling();
		return () => notifications.stopPolling();
	});

	async function handleMarkRead(id: string) {
		await markRead(id);
		notifications.markOneRead(id);
	}

	async function handleMarkAll() {
		await markAllRead();
		notifications.markAllRead();
	}

	function toggle() {
		open = !open;
	}

	function close(e: MouseEvent) {
		if (!(e.target as HTMLElement).closest('.notif-bell')) {
			open = false;
		}
	}

	const recentNotifs = $derived($notifications.slice(0, 8));
</script>

<svelte:window onclick={close} />

<div class="notif-bell relative">
	<button
		onclick={toggle}
		class="relative p-1.5 rounded hover:bg-navy-800 transition-colors text-slate-400 hover:text-gold"
		aria-label="Notifications"
	>
		<!-- Bell SVG -->
		<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
				d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
		</svg>
		{#if $unreadCount > 0}
			<span class="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center leading-none">
				{$unreadCount > 9 ? '9+' : $unreadCount}
			</span>
		{/if}
	</button>

	{#if open}
		<div class="absolute right-0 top-8 w-80 bg-navy-900 border border-navy-700 rounded-lg shadow-xl z-50 overflow-hidden">
			<div class="flex items-center justify-between px-4 py-2.5 border-b border-navy-700">
				<span class="text-xs font-medium text-slate-300 uppercase tracking-wide">Notifications</span>
				{#if $unreadCount > 0}
					<button
						onclick={handleMarkAll}
						class="text-xs text-gold hover:underline"
					>
						Mark all read
					</button>
				{/if}
			</div>

			<div class="max-h-72 overflow-y-auto divide-y divide-navy-800">
				{#each recentNotifs as notif (notif.id)}
					<button
						onclick={() => handleMarkRead(notif.id)}
						class="w-full text-left px-4 py-3 hover:bg-navy-800 transition-colors {notif.read ? 'opacity-60' : ''}"
					>
						<div class="flex items-start gap-2">
							{#if !notif.read}
								<span class="mt-1.5 w-1.5 h-1.5 bg-gold rounded-full flex-shrink-0"></span>
							{:else}
								<span class="mt-1.5 w-1.5 h-1.5 flex-shrink-0"></span>
							{/if}
							<div class="flex-1 min-w-0">
								<p class="text-xs text-slate-200 leading-snug">
									{#if notif.type === 'mention'}
										<span class="font-medium">{notif.payload.author_name as string}</span> mentioned you
									{:else if notif.type === 'share'}
										A session was shared with your team
									{:else if notif.type === 'comment'}
										New comment on a session
									{:else if notif.type === 'invite'}
										You were invited to a team
									{:else}
										{notif.type}
									{/if}
								</p>
								{#if notif.payload.body_preview}
									<p class="text-[11px] text-slate-500 truncate mt-0.5">"{notif.payload.body_preview as string}"</p>
								{/if}
								<p class="text-[10px] text-slate-700 mt-1">
									{new Date(notif.created_at).toLocaleString()}
								</p>
							</div>
						</div>
					</button>
				{/each}

				{#if recentNotifs.length === 0}
					<p class="px-4 py-6 text-xs text-slate-600 text-center">No notifications yet</p>
				{/if}
			</div>

			<div class="border-t border-navy-700 px-4 py-2">
				<a href="/notifications" class="text-xs text-gold hover:underline">View all</a>
			</div>
		</div>
	{/if}
</div>
