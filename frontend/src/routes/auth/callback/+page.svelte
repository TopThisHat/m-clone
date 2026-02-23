<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	// The backend already handles the OIDC callback at /api/auth/callback,
	// sets the JWT cookie, and redirects to /.
	// This page exists only as a fallback in case the redirect lands here.
	onMount(() => {
		goto('/');
	});
</script>

<div class="min-h-screen bg-navy flex items-center justify-center">
	<p class="text-slate-500 text-sm">Completing sign-in…</p>
</div>
