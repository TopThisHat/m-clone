<script lang="ts">
	import { rules, addRule, deleteRule } from '$lib/stores/rulesStore';

	let { onclose }: { onclose: () => void } = $props();

	let newRuleText = $state('');
	let inputEl = $state<HTMLTextAreaElement | undefined>();

	function handleAdd() {
		const text = newRuleText.trim();
		if (!text) return;
		addRule(text);
		newRuleText = '';
		inputEl?.focus();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleAdd();
		}
		if (e.key === 'Escape') onclose();
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 bg-black/50 z-40"
	onclick={onclose}
	role="button"
	tabindex="-1"
	aria-label="Close rules panel"
	onkeydown={() => {}}
></div>

<!-- Panel -->
<aside
	class="fixed inset-y-0 right-0 z-50 w-full max-w-md flex flex-col bg-navy-950 border-l border-navy-700 shadow-2xl"
>
	<!-- Header -->
	<div class="flex items-center justify-between px-5 py-4 border-b border-navy-700 flex-shrink-0">
		<div>
			<h2 class="font-serif text-lg text-gold tracking-wide">Research Rules</h2>
			<p class="text-xs text-slate-500 mt-0.5">
				Rules are applied automatically when relevant to your query
			</p>
		</div>
		<button
			onclick={onclose}
			class="text-slate-500 hover:text-slate-300 text-xl leading-none p-1 transition-colors"
			aria-label="Close"
		>
			×
		</button>
	</div>

	<!-- Rules list -->
	<div class="flex-1 overflow-y-auto px-5 py-4 space-y-2">
		{#if $rules.length === 0}
			<div class="text-center py-12">
				<p class="text-slate-600 text-sm">No rules yet.</p>
				<p class="text-slate-700 text-xs mt-1">
					Add domain knowledge the agent should factor into relevant research.
				</p>
			</div>
		{:else}
			{#each $rules as rule (rule.id)}
				<div
					class="group flex items-start gap-3 px-4 py-3 rounded-lg border border-navy-700 bg-navy-900/50 hover:border-navy-600 transition-colors"
				>
					<span class="text-gold text-xs mt-0.5 flex-shrink-0">⚑</span>
					<p class="flex-1 text-sm text-slate-300 leading-relaxed">{rule.text}</p>
					<button
						onclick={() => deleteRule(rule.id)}
						class="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400 text-xs transition-all flex-shrink-0 mt-0.5"
						aria-label="Delete rule"
					>
						✕
					</button>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Add rule input -->
	<div class="px-5 py-4 border-t border-navy-700 flex-shrink-0">
		<p class="text-xs text-slate-600 mb-2 uppercase tracking-widest">Add a rule</p>
		<div class="flex gap-2 items-end">
			<textarea
				bind:this={inputEl}
				bind:value={newRuleText}
				onkeydown={handleKeydown}
				placeholder="e.g. NFL owners cannot own multiple teams or casinos"
				rows="2"
				class="input-base flex-1 px-3 py-2.5 text-sm resize-none leading-relaxed"
			></textarea>
			<button
				onclick={handleAdd}
				disabled={!newRuleText.trim()}
				class="btn-gold px-4 py-2.5 flex-shrink-0 text-sm"
			>
				Add
			</button>
		</div>
		<p class="text-xs text-slate-700 mt-2">Enter to add · Shift+Enter for new line</p>
	</div>
</aside>
