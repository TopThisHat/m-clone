<script lang="ts">
	import { onMount } from 'svelte';
	import { notifications, unreadCount } from '$lib/stores/notifStore';
	import { markRead, markAllRead } from '$lib/api/notifications';

	onMount(() => {
		notifications.refresh();
	});

	async function handleMarkRead(id: string) {
		await markRead(id);
		notifications.markOneRead(id);
	}

	async function handleMarkAll() {
		await markAllRead();
		notifications.markAllRead();
	}
</script>

<svelte:head>
	<title>Notifications — Playbook Research</title>
</svelte:head>

<div class="max-w-2xl mx-auto px-6 py-8">
	<div class="flex items-center justify-between mb-6">
		<h1 class="font-serif text-2xl text-gold">Notifications</h1>
		{#if $unreadCount > 0}
			<button
				onclick={handleMarkAll}
				class="px-3 py-1.5 border border-gold/30 text-gold text-xs rounded hover:bg-gold/10 transition-colors"
			>
				Mark all read
			</button>
		{/if}
	</div>

	<div class="divide-y divide-navy-800 bg-navy-900 border border-navy-700 rounded-xl overflow-hidden">
		{#each $notifications as notif (notif.id)}
			<button
				onclick={() => handleMarkRead(notif.id)}
				class="w-full text-left flex gap-4 px-5 py-4 hover:bg-navy-800 transition-colors {notif.read ? 'opacity-60' : ''}"
			>
				<div class="mt-0.5 flex-shrink-0">
					{#if !notif.read}
						<span class="w-2 h-2 bg-gold rounded-full block"></span>
					{:else}
						<span class="w-2 h-2 rounded-full block"></span>
					{/if}
				</div>
				<div class="flex-1 min-w-0">
					<p class="text-sm text-slate-200">
						{#if notif.type === 'mention'}
							<span class="font-medium">{notif.payload.author_name}</span> mentioned you in
							<span class="text-gold">"{notif.payload.session_title}"</span>
						{:else if notif.type === 'reply'}
							<span class="font-medium">{notif.payload.author_name}</span> replied to your comment in
							<span class="text-gold">"{notif.payload.session_title}"</span>
						{:else if notif.type === 'share'}
							A session was shared with your team
						{:else if notif.type === 'comment'}
							New comment on a shared session
						{:else if notif.type === 'invite'}
							You were invited to a team
						{:else if notif.type === 'shared_session'}
							<span class="font-medium">{notif.payload.shared_by_name}</span> shared
							<span class="text-gold">"{notif.payload.session_title}"</span>
							with <span class="font-medium">{notif.payload.team_name}</span>
						{:else if notif.type === 'new_comment'}
							<span class="font-medium">{notif.payload.author_name}</span> commented on
							<span class="text-gold">"{notif.payload.session_title}"</span>
						{:else}
							{notif.type}
						{/if}
					</p>
					{#if notif.payload.body_preview}
						<p class="text-xs text-slate-500 mt-0.5 truncate">"{notif.payload.body_preview}"</p>
					{/if}
					<p class="text-xs text-slate-700 mt-1">{new Date(notif.created_at).toLocaleString()}</p>
				</div>
			</button>
		{/each}

		{#if $notifications.length === 0}
			<div class="py-16 text-center">
				<p class="text-slate-500 text-sm">No notifications yet</p>
				<p class="text-slate-700 text-xs mt-1">Mentions and team activity will appear here</p>
			</div>
		{/if}
	</div>
</div>
