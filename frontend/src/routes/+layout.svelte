<script lang="ts">
	import '../app.css';
	import { untrack } from 'svelte';
	import { theme, initTheme } from '$lib/stores/themeStore';
	import { currentUser } from '$lib/stores/authStore';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import NotificationBell from '$lib/components/NotificationBell.svelte';
	import { sidebarOpen } from '$lib/stores/uiStore';
	import type { LayoutData } from './$types';

	let { children, data }: { children: import('svelte').Snippet; data: LayoutData } = $props();

	// Hydrate store from SSR — runs on every page in the app
	$effect(() => {
		const incoming = data.user ?? null;
		untrack(() => {
			currentUser.update((prev) => {
				if (prev === incoming) return prev;
				if (prev && incoming && (prev as { sid?: string }).sid === (incoming as { sid?: string }).sid) return prev;
				return incoming;
			});
			initTheme((incoming as { theme?: string } | null)?.theme);
		});
	});
</script>

<svelte:window
	ondragover={(e) => e.preventDefault()}
	ondrop={(e) => e.preventDefault()}
/>

<svelte:head>
	<title>Playbook Research — Private Intelligence</title>
</svelte:head>

<div class="h-screen bg-navy flex flex-col" class:light={$theme === 'light'}>
	<!-- Header -->
	<header class="border-b border-navy-700 px-4 sm:px-8 py-4 flex items-center justify-between flex-shrink-0">
		<div class="flex items-center gap-3">
			<!-- Hamburger (mobile only) -->
			<button
				class="md:hidden text-slate-400 hover:text-gold p-1 transition-colors"
				onclick={() => sidebarOpen.update((v) => !v)}
				aria-label="Toggle sidebar"
			>
				<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 12h16M4 18h7" />
				</svg>
			</button>
			<!-- Logo mark -->
			<a href="/" class="flex items-center gap-3">
				<div
					class="w-8 h-8 bg-gold rounded-sm flex items-center justify-center shadow-lg shadow-gold/10"
				>
					<span class="text-navy font-serif font-bold text-sm select-none">P</span>
				</div>
				<div>
					<h1 class="font-serif text-gold text-lg leading-none tracking-wide">Playbook Research</h1>
					<p class="text-navy-500 text-xs tracking-widest uppercase mt-0.5">Powered by DaVinci</p>
				</div>
			</a>
		</div>

		<!-- Status / version -->
		<div class="flex items-center gap-6">
			<div class="hidden sm:flex items-center gap-4 text-xs text-slate-600">
				<span>GPT-4o</span>
				<span class="w-px h-3 bg-navy-600"></span>
				<span>Tavily Search</span>
				<span class="w-px h-3 bg-navy-600"></span>
				<span>Yahoo Finance</span>
			</div>
			<div class="flex items-center gap-2">
				<div class="flex items-center gap-1.5">
					<div class="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></div>
					<span class="text-xs text-slate-500">Live</span>
				</div>
				{#if $currentUser}
					<a
						href="/teams"
						class="text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded hover:bg-navy-800"
					>
						Teams
					</a>
					<a
						href="/campaigns"
						class="text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded hover:bg-navy-800"
					>
						Scout
					</a>
					<a
						href="/knowledge-graph"
						class="text-xs text-slate-500 hover:text-gold transition-colors px-2 py-1 rounded hover:bg-navy-800"
					>
						KG
					</a>
					<NotificationBell />
				{/if}
				<ThemeToggle />
				{#if $currentUser}
					<span class="text-xs text-slate-600 hidden sm:block">{$currentUser.display_name}</span>
				{/if}
			</div>
		</div>
	</header>

	<!-- Main Content -->
	<main class="flex-1 overflow-hidden">
		{@render children()}
	</main>

	<!-- Footer -->
	<footer class="border-t border-navy-700 px-8 py-3 flex items-center justify-between flex-shrink-0">
		<span class="text-xs text-slate-700">
			For informational purposes only. Not investment advice.
		</span>
		<div class="flex items-center gap-4">
			<a href="/dashboard" class="text-xs text-slate-600 hover:text-gold transition-colors">Dashboard</a>
			{#if $currentUser}
				<a href="/teams" class="text-xs text-slate-600 hover:text-gold transition-colors">Teams</a>
			{/if}
			<span class="text-xs text-slate-700 font-light">AWM AI Engineering</span>
		</div>
	</footer>
</div>
