<script lang="ts">
	import { startResearch } from '$lib/api/research';
	import { isStreaming, errorMessage, messageHistory } from '$lib/stores/reportStore';

	let followUpQuery = $state('');

	async function handleSubmit() {
		const q = followUpQuery.trim();
		if (!q || $isStreaming) return;
		followUpQuery = '';
		errorMessage.set(null);
		try {
			await startResearch(q, undefined, $messageHistory);
		} catch (err) {
			if (err instanceof Error && err.name === 'AbortError') return;
			errorMessage.set(err instanceof Error ? err.message : 'An error occurred');
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
	}
</script>

<div class="mt-6 border-t border-navy-700 pt-6 space-y-3">
	<h3 class="font-serif text-lg text-gold tracking-wide">Ask a Follow-up</h3>
	<div class="relative">
		<textarea
			bind:value={followUpQuery}
			onkeydown={handleKeydown}
			placeholder="Ask a follow-up question about this research…"
			rows="2"
			class="input-base w-full px-5 py-4 text-sm resize-none font-light leading-relaxed"
		></textarea>
		<span class="absolute bottom-3 right-4 text-slate-600 text-xs select-none">
			{#if navigator.platform.toLowerCase().includes('mac')}&#8984;{:else}Ctrl{/if}+&crarr; to submit
		</span>
	</div>
	<button
		onclick={handleSubmit}
		disabled={!followUpQuery.trim() || $isStreaming}
		class="btn-gold w-full"
	>
		Ask Follow-up
	</button>
</div>
