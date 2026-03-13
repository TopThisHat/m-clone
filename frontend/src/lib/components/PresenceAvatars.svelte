<script lang="ts">
	import type { PresenceViewer } from '$lib/api/sessions';

	let {
		viewers = [],
		currentSid = '',
	}: {
		viewers: PresenceViewer[];
		currentSid: string;
	} = $props();

	const MAX_SHOWN = 4;
	let shown = $derived(viewers.slice(0, MAX_SHOWN));
	let overflow = $derived(Math.max(0, viewers.length - MAX_SHOWN));

	function initials(name: string): string {
		return name
			.split(' ')
			.slice(0, 2)
			.map((w) => w[0]?.toUpperCase() ?? '')
			.join('');
	}
</script>

{#if viewers.length > 0}
	<div class="flex items-center gap-1" title="{viewers.map(v => v.display_name).join(', ')} viewing">
		{#each shown as viewer (viewer.user_sid)}
			<div
				class="relative group"
				title={viewer.display_name}
			>
				<div
					class="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold border-2 transition-all
						{viewer.user_sid === currentSid
							? 'bg-navy-700 border-navy-600 text-slate-500 opacity-50'
							: 'bg-gold/20 border-gold/40 text-gold'}"
				>
					{#if viewer.avatar_url}
						<img src={viewer.avatar_url} alt={viewer.display_name} class="w-full h-full rounded-full object-cover" />
					{:else}
						{initials(viewer.display_name)}
					{/if}
				</div>
				<!-- Tooltip -->
				<div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-1.5 py-0.5 bg-navy-900 border border-navy-700 rounded text-[10px] text-slate-300 whitespace-nowrap z-30 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
					{viewer.display_name}{viewer.user_sid === currentSid ? ' (you)' : ''}
				</div>
			</div>
		{/each}
		{#if overflow > 0}
			<div class="w-6 h-6 rounded-full bg-navy-700 border-2 border-navy-600 flex items-center justify-center text-[9px] text-slate-400 font-medium">
				+{overflow}
			</div>
		{/if}
		<span class="text-[10px] text-slate-600 ml-0.5">viewing</span>
	</div>
{/if}
