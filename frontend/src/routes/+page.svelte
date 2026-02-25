<script lang="ts">
	import TracePanel from '$lib/components/TracePanel.svelte';
	import SessionSidebar from '$lib/components/SessionSidebar.svelte';
	import ChatThread from '$lib/components/ChatThread.svelte';
	import ChatInput from '$lib/components/ChatInput.svelte';
	import RulesPanel from '$lib/components/RulesPanel.svelte';
	import { traceStore } from '$lib/stores/traceStore';
	import { isStreaming } from '$lib/stores/reportStore';
	import { newResearch } from '$lib/stores/sessionStore';
	import { sidebarOpen } from '$lib/stores/uiStore';
	import { rules } from '$lib/stores/rulesStore';

	let traceVisible = $state(true);
	let rulesOpen = $state(false);

	function handleKeydown(e: KeyboardEvent) {
		// Cmd+Shift+N (Mac) or Ctrl+Shift+N (Win/Linux) → new research
		if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'N') {
			e.preventDefault();
			newResearch();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="h-full flex overflow-hidden">
	<!-- Mobile overlay backdrop -->
	{#if $sidebarOpen}
		<div
			class="fixed inset-0 bg-black/50 z-30 md:hidden"
			onclick={() => sidebarOpen.set(false)}
			role="button"
			tabindex="-1"
			aria-label="Close sidebar"
			onkeydown={() => {}}
		></div>
	{/if}

	<!-- Sidebar: drawer on mobile, static column on desktop -->
	<div
		class="fixed inset-y-0 left-0 z-40 md:relative md:z-auto md:flex-shrink-0
		       transition-transform duration-200
		       {$sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}"
	>
		<SessionSidebar onclose={() => sidebarOpen.set(false)} />
	</div>

	<!-- ── CENTRE PANE: Chat ──────────────────────────────────────────── -->
	<section class="flex-1 flex flex-col overflow-hidden min-w-0 border-l border-navy-700 md:border-l-0">
		<!-- Top bar with rules + trace toggles -->
		<div class="flex items-center justify-end gap-1 px-4 py-2 border-b border-navy-700 flex-shrink-0">
			<!-- Rules button -->
			<button
				onclick={() => (rulesOpen = true)}
				class="flex items-center gap-1.5 text-xs transition-colors px-2 py-1 rounded hover:bg-navy-800
				       {$rules.length > 0 ? 'text-gold hover:text-gold' : 'text-slate-600 hover:text-slate-300'}"
				title="Manage research rules"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
						d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
				</svg>
				Rules{$rules.length > 0 ? ` (${$rules.length})` : ''}
			</button>

			<!-- Trace toggle (desktop only) -->
			<button
				onclick={() => (traceVisible = !traceVisible)}
				class="hidden md:flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-300 transition-colors px-2 py-1 rounded hover:bg-navy-800"
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
		<div class="border-t border-navy-700 px-4 sm:px-6 py-4 flex-shrink-0">
			<ChatInput />
		</div>
	</section>

	<!-- ── RIGHT PANE: Live Agent Trace ────────────────────────────────── -->
	{#if traceVisible}
		<section class="hidden md:flex flex-col overflow-hidden p-8 gap-4 w-[40%] flex-shrink-0 border-l border-navy-700">
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

<!-- Rules panel slide-over -->
{#if rulesOpen}
	<RulesPanel onclose={() => (rulesOpen = false)} />
{/if}

<!-- Floating Trace toggle button on mobile -->
{#if !traceVisible}
	<button
		class="fixed bottom-20 right-4 md:hidden z-20 px-3 py-2 bg-navy-800 border border-navy-600 hover:border-gold/40 rounded-lg text-xs text-slate-400 hover:text-gold shadow-lg transition-all"
		onclick={() => (traceVisible = true)}
	>
		Show trace
	</button>
{/if}
