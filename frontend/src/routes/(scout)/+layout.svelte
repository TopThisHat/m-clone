<script lang="ts">
	import type { LayoutData } from './$types';
	let { data, children }: { data: LayoutData; children: import('svelte').Snippet } = $props();
</script>

<div class="min-h-screen bg-navy-900">
	<!-- Compact top nav (~48px) -->
	<nav class="border-b border-navy-700 bg-navy-800 px-6 py-3 flex items-center justify-between">
		<div class="flex items-center gap-4">
			<a href="/" class="text-slate-400 hover:text-gold text-sm transition-colors">← Research</a>
			<span class="text-navy-600">|</span>
			<span class="font-serif text-gold text-lg font-bold tracking-wide">Playbook Scout</span>
		</div>
		<div class="flex items-center gap-4 text-sm text-slate-400">
			<span>{data.user?.display_name ?? data.user?.sub ?? ''}</span>
			<a href="/api/auth/logout" class="hover:text-gold transition-colors">Sign out</a>
		</div>
	</nav>

	<main class="p-6">
		{@render children()}
	</main>
</div>
