<script lang="ts">
	import TracePanel from '$lib/components/TracePanel.svelte';
	import SessionSidebar from '$lib/components/SessionSidebar.svelte';
	import ChatThread from '$lib/components/ChatThread.svelte';
	import ChatInput from '$lib/components/ChatInput.svelte';
	import { traceStore } from '$lib/stores/traceStore';
	import { isStreaming } from '$lib/stores/reportStore';
	import { newResearch } from '$lib/stores/sessionStore';

	let traceVisible = $state(true);

	function handleKeydown(e: KeyboardEvent) {
		// Cmd+Shift+N (Mac) or Ctrl+Shift+N (Win/Linux) → new research
		if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'N') {
			e.preventDefault();
			newResearch();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div
	class="h-full grid divide-x divide-navy-700 overflow-hidden"
	style="grid-template-columns: 220px 1fr{traceVisible ? ' 1fr' : ''};"
>
	<!-- ── SIDEBAR: Past Sessions ──────────────────────────────────────── -->
	<SessionSidebar />

	<!-- ── CENTRE PANE: Chat ──────────────────────────────────────────── -->
	<section class="flex flex-col overflow-hidden">
		<!-- Top bar with trace toggle -->
		<div class="flex items-center justify-end px-4 py-2 border-b border-navy-700 flex-shrink-0">
			<button
				onclick={() => (traceVisible = !traceVisible)}
				class="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-300 transition-colors px-2 py-1 rounded hover:bg-navy-800"
				title={traceVisible ? 'Hide agent trace' : 'Show agent trace'}
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1.5"
						d="M4 6h16M4 12h16M4 18h7"
					/>
				</svg>
				{traceVisible ? 'Hide trace' : 'Show trace'}
			</button>
		</div>

		<!-- Scrollable chat thread -->
		<ChatThread />

		<!-- Sticky input at bottom -->
		<div class="border-t border-navy-700 px-6 py-4 flex-shrink-0">
			<ChatInput />
		</div>
	</section>

	<!-- ── RIGHT PANE: Live Agent Trace ────────────────────────────────── -->
	{#if traceVisible}
		<section class="flex flex-col overflow-hidden p-8 gap-4">
			<div class="flex items-center justify-between flex-shrink-0">
				<div>
					<h2 class="font-serif text-2xl text-gold tracking-wide">Agent Trace</h2>
					<p class="text-slate-500 text-sm mt-1 font-light">
						Live reasoning steps and tool calls
					</p>
				</div>

				{#if $isStreaming}
					<div
						class="flex items-center gap-2 px-3 py-1.5 bg-gold/10 border border-gold/20 rounded-full"
					>
						<span class="w-2 h-2 bg-gold rounded-full animate-pulse"></span>
						<span class="text-xs text-gold font-medium">Researching</span>
					</div>
				{:else if $traceStore.length > 0}
					<div
						class="flex items-center gap-2 px-3 py-1.5 bg-green-900/20 border border-green-800/30 rounded-full"
					>
						<span class="w-2 h-2 bg-green-500 rounded-full"></span>
						<span class="text-xs text-green-400 font-medium">Complete</span>
					</div>
				{/if}
			</div>

			<div class="gold-divider flex-shrink-0"></div>

			<div class="flex-1 overflow-y-auto pr-1">
				<TracePanel steps={$traceStore} />
			</div>
		</section>
	{/if}
</div>
