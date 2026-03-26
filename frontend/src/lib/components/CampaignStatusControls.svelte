<script lang="ts">
	type CampaignStatus = 'draft' | 'active' | 'paused' | 'completed' | 'archived';

	let {
		status = 'draft' as CampaignStatus,
		disabled = false,
		onstatuschange,
	}: {
		status?: CampaignStatus;
		disabled?: boolean;
		onstatuschange?: (newStatus: CampaignStatus) => void;
	} = $props();

	let confirming = $state<CampaignStatus | null>(null);
	let confirmBtn: HTMLButtonElement | undefined = $state();

	const statusConfig: Record<CampaignStatus, { label: string; dot: string; badge: string }> = {
		draft: { label: 'Draft', dot: 'bg-slate-400', badge: 'bg-navy-700 text-slate-400 border-navy-600' },
		active: { label: 'Active', dot: 'bg-green-400', badge: 'bg-green-950 text-green-400 border-green-800' },
		paused: { label: 'Paused', dot: 'bg-yellow-400', badge: 'bg-yellow-950 text-yellow-400 border-yellow-700' },
		completed: { label: 'Completed', dot: 'bg-gold', badge: 'bg-gold/10 text-gold border-gold/30' },
		archived: { label: 'Archived', dot: 'bg-slate-600', badge: 'bg-navy-700 text-slate-500 border-navy-600' },
	};

	// Define valid transitions
	const transitions: Record<CampaignStatus, { target: CampaignStatus; label: string; destructive: boolean }[]> = {
		draft: [
			{ target: 'active', label: 'Activate', destructive: false },
		],
		active: [
			{ target: 'paused', label: 'Pause', destructive: false },
			{ target: 'completed', label: 'Complete', destructive: true },
		],
		paused: [
			{ target: 'active', label: 'Resume', destructive: false },
			{ target: 'completed', label: 'Complete', destructive: true },
		],
		completed: [
			{ target: 'archived', label: 'Archive', destructive: true },
			{ target: 'active', label: 'Reopen', destructive: false },
		],
		archived: [
			{ target: 'active', label: 'Reopen', destructive: false },
		],
	};

	let availableTransitions = $derived(transitions[status] ?? []);
	let currentConfig = $derived(statusConfig[status]);

	function requestTransition(target: CampaignStatus, destructive: boolean) {
		if (destructive) {
			confirming = target;
			queueMicrotask(() => confirmBtn?.focus());
		} else {
			onstatuschange?.(target);
		}
	}

	function confirmTransition() {
		if (confirming) {
			onstatuschange?.(confirming);
			confirming = null;
		}
	}

	function cancelConfirm() {
		confirming = null;
	}
</script>

<div class="flex flex-col gap-2">
	<!-- Current status badge -->
	<div class="flex items-center gap-2">
		<span class="status-badge border {currentConfig.badge}">
			<span class="w-1.5 h-1.5 rounded-full {currentConfig.dot}" aria-hidden="true"></span>
			{currentConfig.label}
		</span>
	</div>

	<!-- Transition buttons -->
	{#if availableTransitions.length > 0 && !confirming}
		<div class="flex flex-wrap items-center gap-2">
			{#each availableTransitions as t (t.target)}
				<button
					onclick={() => requestTransition(t.target, t.destructive)}
					{disabled}
					class="text-xs px-3 py-1.5 rounded-lg border transition-all
						{t.destructive
							? 'border-red-800 text-red-400 hover:bg-red-950 hover:border-red-700'
							: 'border-navy-600 text-slate-300 hover:bg-navy-700 hover:text-gold hover:border-gold/30'}
						disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{t.label}
				</button>
			{/each}
		</div>
	{/if}

	<!-- Confirmation dialog -->
	{#if confirming}
		{@const targetConfig = statusConfig[confirming]}
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="flex items-center gap-2 p-2.5 rounded-lg border border-red-800 bg-red-950/50"
			role="alert"
			onkeydown={(e) => { if (e.key === 'Escape') cancelConfirm(); }}
		>
			<p class="text-xs text-red-300 flex-1">
				Change status to <span class="font-medium">{targetConfig.label}</span>?
			</p>
			<button
				bind:this={confirmBtn}
				onclick={confirmTransition}
				class="text-xs px-2.5 py-1 rounded border border-red-700 text-red-300 hover:bg-red-900 transition-colors"
			>
				Confirm
			</button>
			<button
				onclick={cancelConfirm}
				class="text-xs px-2.5 py-1 rounded border border-navy-600 text-slate-400 hover:bg-navy-700 transition-colors"
			>
				Cancel
			</button>
		</div>
	{/if}
</div>
