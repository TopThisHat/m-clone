<script lang="ts">
	import { goto } from '$app/navigation';
	import { campaignsApi } from '$lib/api/campaigns';

	let name = $state('');
	let description = $state('');
	let schedule = $state('');
	let error = $state('');
	let saving = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		if (!name.trim()) { error = 'Campaign name is required'; return; }
		saving = true;
		error = '';
		try {
			const campaign = await campaignsApi.create({
				name: name.trim(),
				description: description.trim() || undefined,
				schedule: schedule.trim() || undefined,
			});
			goto(`/campaigns/${campaign.id}`);
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to create campaign';
			saving = false;
		}
	}
</script>

<div class="max-w-lg mx-auto">
	<div class="mb-6">
		<a href="/campaigns" class="text-slate-500 hover:text-gold text-sm transition-colors">← Campaigns</a>
		<h1 class="font-serif text-gold text-2xl font-bold mt-2">New Campaign</h1>
	</div>

	<form onsubmit={submit} class="bg-navy-800 border border-navy-700 rounded-xl p-6 space-y-5">
		<div>
			<label class="block text-sm text-slate-400 mb-1" for="name">Campaign Name *</label>
			<input
				id="name"
				type="text"
				bind:value={name}
				required
				placeholder="e.g. Q1 Pipeline"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-slate-200
				       placeholder-slate-500 focus:outline-none focus:border-gold"
			/>
		</div>

		<div>
			<label class="block text-sm text-slate-400 mb-1" for="description">Description</label>
			<textarea
				id="description"
				bind:value={description}
				rows="3"
				placeholder="What is this campaign for?"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-slate-200
				       placeholder-slate-500 focus:outline-none focus:border-gold resize-none"
			></textarea>
		</div>

		<div>
			<label class="block text-sm text-slate-400 mb-1" for="schedule">
				Cron Schedule <span class="text-slate-500">(optional)</span>
			</label>
			<input
				id="schedule"
				type="text"
				bind:value={schedule}
				placeholder="e.g. 0 9 * * 1  (weekly Monday 9am)"
				class="w-full bg-navy-700 border border-navy-600 rounded-lg px-3 py-2 text-slate-200
				       placeholder-slate-500 focus:outline-none focus:border-gold font-mono text-sm"
			/>
			<p class="text-xs text-slate-500 mt-1">
				Leave blank for manual runs only.
				Examples: <code class="text-gold-muted">0 9 * * 1</code> (weekly Mon 9am),
				<code class="text-gold-muted">0 8 * * *</code> (daily 8am)
			</p>
		</div>

		{#if error}
			<p class="text-red-400 text-sm">{error}</p>
		{/if}

		<div class="flex gap-3 pt-2">
			<button
				type="submit"
				disabled={saving}
				class="bg-gold text-navy font-semibold px-5 py-2 rounded-lg hover:bg-gold-light
				       transition-colors disabled:opacity-50"
			>
				{saving ? 'Creating…' : 'Create Campaign'}
			</button>
			<a
				href="/campaigns"
				class="bg-navy-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-navy-600
				       transition-colors border border-navy-600"
			>
				Cancel
			</a>
		</div>
	</form>
</div>
