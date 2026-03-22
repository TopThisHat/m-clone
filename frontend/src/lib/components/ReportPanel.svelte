<script lang="ts">
	import { reportHtml, reportMarkdown, isStreaming, streamingText } from '$lib/stores/reportStore';

	let copySuccess = $state(false);

	async function copyReport() {
		await navigator.clipboard.writeText($reportMarkdown);
		copySuccess = true;
		setTimeout(() => (copySuccess = false), 2000);
	}
</script>

{#if $reportHtml || ($isStreaming && $streamingText)}
	<div class="border border-navy-600 rounded-lg overflow-hidden mt-2">
		<!-- Header -->
		<div
			class="bg-navy-700 border-b border-navy-600 px-5 py-3 flex items-center justify-between"
		>
			<div class="flex items-center gap-2">
				<div class="w-2 h-2 bg-gold rounded-full"></div>
				<h3 class="font-serif text-gold text-sm font-medium tracking-wide">
					Research Report
				</h3>
			</div>

			{#if $reportHtml && !$isStreaming}
				<button
					onclick={copyReport}
					class="text-xs text-slate-400 hover:text-gold transition-colors flex items-center gap-1.5"
				>
					{#if copySuccess}
						<span class="text-green-400">Copied</span>
					{:else}
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
							/>
						</svg>
						Copy
					{/if}
				</button>
			{/if}
		</div>

		<!-- Report content -->
		<div class="p-6 max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto">
			{#if $reportHtml}
				<article class="prose prose-sm max-w-none">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -->
					{@html $reportHtml}
				</article>
			{:else if $isStreaming && $streamingText}
				<p class="text-slate-300 text-sm font-light leading-relaxed whitespace-pre-wrap">
					{$streamingText}<span class="inline-block w-1.5 h-4 bg-gold/60 ml-0.5 animate-pulse align-text-bottom"></span>
				</p>
			{/if}
		</div>
	</div>
{/if}
