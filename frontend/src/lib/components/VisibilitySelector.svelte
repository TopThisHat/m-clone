<script lang="ts">
	type Visibility = 'private' | 'team' | 'public';

	let {
		value = $bindable<Visibility>('private'),
		onchange,
	}: { value?: Visibility; onchange?: (v: Visibility) => void } = $props();

	const options: { value: Visibility; label: string; icon: string; desc: string }[] = [
		{ value: 'private', label: 'Private', icon: '🔒', desc: 'Only you' },
		{ value: 'team', label: 'Team', icon: '👥', desc: 'Team members' },
		{ value: 'public', label: 'Public', icon: '🌐', desc: 'Anyone with link' },
	];

	function select(v: Visibility) {
		value = v;
		onchange?.(v);
	}
</script>

<div class="flex items-center gap-1 bg-navy-900 rounded border border-navy-700 p-0.5">
	{#each options as opt (opt.value)}
		<button
			onclick={() => select(opt.value)}
			title={opt.desc}
			class="flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors
				{value === opt.value
					? 'bg-gold text-navy font-medium'
					: 'text-slate-500 hover:text-slate-300 hover:bg-navy-800'}"
		>
			<span class="text-[11px]">{opt.icon}</span>
			<span>{opt.label}</span>
		</button>
	{/each}
</div>
