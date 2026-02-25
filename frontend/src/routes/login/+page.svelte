<script lang="ts">
	import { goto } from '$app/navigation';
	import { devLogin } from '$lib/api/auth';
	import { currentUser } from '$lib/stores/authStore';

	let sid = $state('');
	let displayName = $state('');
	let email = $state('');
	let loading = $state(false);
	let error = $state('');

	async function handleDevLogin() {
		error = '';
		if (!sid.trim() || !displayName.trim()) {
			error = 'SID and Display Name are required';
			return;
		}
		loading = true;
		try {
			const ok = await devLogin(sid.trim(), displayName.trim(), email.trim());
			if (ok) {
				currentUser.set({ sid: sid.trim(), display_name: displayName.trim(), email: email.trim() });
				goto('/');
			} else {
				error = 'Dev login failed — is DEV_AUTH_BYPASS=true on the backend?';
			}
		} catch {
			error = 'Login failed';
		} finally {
			loading = false;
		}
	}

	function handleSSOLogin() {
		window.location.href = '/api/auth/login';
	}
</script>

<svelte:head>
	<title>Sign In — Playbook Research</title>
</svelte:head>

<div class="min-h-screen bg-navy flex items-center justify-center p-6">
	<div class="w-full max-w-sm">
		<!-- Logo -->
		<div class="flex items-center gap-3 mb-8 justify-center">
			<div class="w-10 h-10 bg-gold rounded flex items-center justify-center shadow-lg shadow-gold/10">
				<span class="text-navy font-serif font-bold">P</span>
			</div>
			<div>
				<h1 class="font-serif text-gold text-xl leading-none">Playbook Research</h1>
				<p class="text-navy-500 text-xs tracking-widest uppercase mt-0.5">Powered by DaVinci</p>
			</div>
		</div>

		<!-- SSO Button -->
		<button
			onclick={handleSSOLogin}
			class="w-full flex items-center justify-center gap-2 py-3 border border-gold/40 text-gold text-sm font-medium rounded-lg hover:bg-gold/10 transition-colors mb-6"
		>
			<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
			</svg>
			Sign in with SSO
		</button>

		<div class="relative mb-6">
			<div class="absolute inset-0 flex items-center">
				<div class="w-full border-t border-navy-700"></div>
			</div>
			<div class="relative flex justify-center">
				<span class="px-3 bg-navy text-xs text-slate-600">or dev bypass</span>
			</div>
		</div>

		<!-- Dev Login Form -->
		<div class="space-y-3">
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="sid">User SID</label>
				<input
					id="sid"
					bind:value={sid}
					placeholder="alice"
					class="w-full bg-navy-800 border border-navy-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
				/>
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="display-name">Display Name</label>
				<input
					id="display-name"
					bind:value={displayName}
					placeholder="Alice Smith"
					class="w-full bg-navy-800 border border-navy-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
				/>
			</div>
			<div>
				<label class="block text-xs text-slate-400 mb-1" for="email">Email (optional)</label>
				<input
					id="email"
					bind:value={email}
					type="email"
					placeholder="alice@company.com"
					class="w-full bg-navy-800 border border-navy-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40"
				/>
			</div>

			{#if error}
				<p class="text-xs text-red-400">{error}</p>
			{/if}

			<button
				onclick={handleDevLogin}
				disabled={loading}
				class="w-full py-3 bg-navy-800 border border-navy-600 text-slate-300 text-sm rounded-lg hover:border-gold/30 hover:text-gold disabled:opacity-50 transition-colors mt-1"
			>
				{loading ? 'Signing in…' : 'Dev Login'}
			</button>
		</div>

		<p class="mt-6 text-center text-xs text-slate-700">
			Dev bypass only works when <code class="text-gold">DEV_AUTH_BYPASS=true</code> in backend
		</p>
	</div>
</div>
