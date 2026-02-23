<script lang="ts">
	let { slug, display_name, role }: { slug: string; display_name: string; role?: string } = $props();
</script>

<a
	href="/teams/{slug}"
	class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-navy-800 border border-navy-600 text-xs text-slate-300 hover:border-gold/40 hover:text-gold transition-colors"
>
	<span class="w-4 h-4 rounded-full bg-gold/20 text-gold text-[9px] font-bold flex items-center justify-center leading-none">
		{display_name.charAt(0).toUpperCase()}
	</span>
	<span>{display_name}</span>
	{#if role}
		<span class="text-[9px] text-slate-600">{role}</span>
	{/if}
</a>
