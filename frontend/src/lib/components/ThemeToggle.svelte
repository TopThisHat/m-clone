<script lang="ts">
	import { theme } from '$lib/stores/themeStore';

	function toggle() {
		theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
	}
</script>

<button
	onclick={toggle}
	class="w-8 h-8 flex items-center justify-center rounded-md border border-navy-600 hover:border-gold/40 text-slate-400 hover:text-gold transition-all"
	title="Toggle theme"
	aria-label="Toggle light/dark theme"
>
	{#if $theme === 'dark'}
		<!-- Sun icon -->
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<circle cx="12" cy="12" r="5" stroke-width="2" />
			<path
				stroke-linecap="round"
				stroke-width="2"
				d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
			/>
		</svg>
	{:else}
		<!-- Moon icon -->
		<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="2"
				d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
			/>
		</svg>
	{/if}
</button>
