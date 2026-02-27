<script lang="ts">
	import { submitClarification } from '$lib/api/research';
	import type { ClarificationData } from '$lib/stores/reportStore';

	let { clarification }: { clarification: ClarificationData } = $props();

	let freeText = $state('');
	let submitting = $state(false);
	let submitError = $state<string | null>(null);

	async function submit(answer: string) {
		if (!answer.trim() || submitting || clarification.answered) return;
		submitting = true;
		submitError = null;
		try {
			await submitClarification(clarification.clarification_id, answer.trim());
			// SSE clarification_answered will finalize the UI state
		} catch (err) {
			submitError = err instanceof Error ? err.message : 'Failed to submit';
			submitting = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit(freeText);
		}
	}
</script>

<div class="my-3 border border-gold/30 rounded-lg bg-navy-800/60 overflow-hidden">
	<!-- Header -->
	<div class="flex items-center gap-2 px-4 py-3 border-b border-navy-700 bg-navy-800/80">
		<div
			class="w-6 h-6 rounded-sm bg-gold/10 border border-gold/30 flex items-center justify-center flex-shrink-0"
		>
			<svg
				class="w-3.5 h-3.5 text-gold"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
		</div>
		<span class="text-xs font-medium text-gold tracking-wide uppercase">Clarification Needed</span>
		{#if submitting}
			<span class="flex gap-1 ml-auto">
				{#each [0, 1, 2] as i}
					<span
						class="w-1 h-1 bg-gold/50 rounded-full animate-bounce"
						style="animation-delay:{i * 0.15}s"
					></span>
				{/each}
			</span>
		{/if}
	</div>

	<div class="px-4 py-4 space-y-4">
		<p class="text-sm text-slate-200 leading-relaxed">{clarification.question}</p>

		{#if clarification.context}
			<p class="text-xs text-slate-500 border-l-2 border-navy-600 pl-3 leading-relaxed">
				{clarification.context}
			</p>
		{/if}

		{#if clarification.answered}
			<!-- Answered state: green confirmation -->
			<div
				class="flex items-start gap-2 bg-green-900/20 border border-green-700/30 rounded-lg px-3 py-2"
			>
				<span class="text-green-400 text-sm flex-shrink-0 mt-0.5">&#10003;</span>
				<p class="text-sm text-green-300 leading-relaxed">{clarification.answer}</p>
			</div>
		{:else}
			<!-- Option buttons (if provided) -->
			{#if clarification.options.length > 0}
				<div class="flex flex-wrap gap-2">
					{#each clarification.options as option}
						<button
							onclick={() => submit(option)}
							disabled={submitting}
							class="text-sm px-4 py-2 border border-navy-600 rounded-lg text-slate-300
								   hover:text-gold hover:border-gold/40 hover:bg-navy-700
								   disabled:opacity-50 transition-all"
						>
							{option}
						</button>
					{/each}
				</div>
			{/if}
			<!-- Free-text input (always shown; placeholder adjusts when options present) -->
			<div class="flex gap-2">
				<input
					type="text"
					bind:value={freeText}
					onkeydown={handleKeydown}
					placeholder={clarification.options.length ? 'Or type a custom answer…' : 'Type your answer…'}
					disabled={submitting}
					class="flex-1 bg-navy-900 border border-navy-600 rounded px-3 py-2 text-sm
						   text-slate-200 placeholder-slate-600 focus:outline-none focus:border-gold/40
						   disabled:opacity-50"
				/>
				<button
					onclick={() => submit(freeText)}
					disabled={!freeText.trim() || submitting}
					class="px-4 py-2 rounded bg-gold text-navy text-xs font-medium
						   hover:bg-gold/90 disabled:opacity-50 transition-colors"
				>
					Send
				</button>
			</div>
		{/if}

		{#if submitError}
			<p class="text-xs text-red-400">{submitError}</p>
		{/if}
	</div>
</div>
