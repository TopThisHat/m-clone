<script lang="ts">
	let username = $state('');
	let error = $state('');
	let loading = $state(false);

	async function handleLogin(e: Event) {
		e.preventDefault();
		loading = true;
		error = '';
		try {
			const res = await fetch('/api/auth/dev-login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sid: username, display_name: username }),
				credentials: 'include',
			});
			if (res.ok) {
				window.location.href = '/campaigns';
			} else {
				const data = await res.json().catch(() => ({}));
				const detail = data.detail;
				error = typeof detail === 'string' ? detail : (Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(', ') : 'Login failed');
			}
		} catch {
			error = 'Network error';
		} finally {
			loading = false;
		}
	}
</script>

<div class="min-h-screen bg-navy flex items-center justify-center">
	<div class="w-full max-w-sm bg-navy-800 border border-navy-600 rounded-xl p-8 shadow-xl">
		<h1 class="font-serif text-gold text-2xl font-bold mb-6 text-center">Playbook Scout</h1>
		<form onsubmit={handleLogin} class="space-y-4">
			<div>
				<label class="block text-sm text-slate-400 mb-1" for="username">Username</label>
				<input
					id="username"
					type="text"
					bind:value={username}
					required
					placeholder="dev"
					class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2
					       text-slate-200 placeholder-slate-500 focus:outline-none focus:border-gold"
				/>
			</div>
			{#if error}
				<p class="text-red-400 text-sm">{error}</p>
			{/if}
			<button
				type="submit"
				disabled={loading}
				class="w-full bg-gold text-navy font-semibold py-2 rounded-lg
				       hover:bg-gold-light transition-colors disabled:opacity-50"
			>
				{loading ? 'Signing in…' : 'Sign In'}
			</button>
		</form>
		<p class="text-slate-500 text-xs text-center mt-4">
			Uses DEV_AUTH_BYPASS — for development only.
		</p>
	</div>
</div>
