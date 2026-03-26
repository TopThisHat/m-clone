<script lang="ts">
	let { text = '' }: { text?: string } = $props();
</script>

<div class="flex flex-col items-center justify-center py-16 gap-3" aria-live="polite" aria-busy="true">
	<span class="w-6 h-6 rounded-full border-2 border-gold border-t-transparent animate-spin" aria-hidden="true"></span>
	{#if text}
		<p class="text-sm text-slate-500">{text}</p>
	{/if}
</div>
