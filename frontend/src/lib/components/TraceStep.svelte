<script lang="ts">
	import type { TraceStep } from '$lib/stores/traceStore';
	import ToolIcon from './ToolIcon.svelte';

	let { step }: { step: TraceStep } = $props();

	const statusBorder: Record<string, string> = {
		pending: 'border-navy-600',
		running: 'border-gold/50',
		done: 'border-green-700/40',
		error: 'border-red-700/40'
	};

	const statusText: Record<string, string> = {
		pending: 'text-slate-500',
		running: 'text-gold',
		done: 'text-green-400',
		error: 'text-red-400'
	};

	function formatArgs(args: Record<string, unknown>): string {
		const entries = Object.entries(args);
		if (entries.length === 0) return '';
		if (entries.length === 1) {
			const [, val] = entries[0];
			return String(val);
		}
		return entries.map(([k, v]) => `${k}: ${String(v)}`).join(' · ');
	}
</script>

<div
	class="border rounded-lg p-4 transition-all duration-300 bg-navy-800/60 {statusBorder[step.status]}"
>
	<div class="flex items-start gap-3">
		<!-- Tool icon -->
		<div
			class="flex-shrink-0 w-8 h-8 rounded-md bg-navy-700 border border-navy-600 flex items-center justify-center mt-0.5"
		>
			<ToolIcon icon={step.icon} class="w-4 h-4 {statusText[step.status]}" />
		</div>

		<!-- Content -->
		<div class="flex-1 min-w-0">
			<div class="flex items-center justify-between gap-2 mb-1">
				<span class="text-xs font-medium uppercase tracking-widest text-gold/60">
					{step.toolLabel}
				</span>

				{#if step.status === 'running'}
					<span class="flex gap-1 flex-shrink-0">
						{#each [0, 1, 2] as i}
							<span
								class="w-1.5 h-1.5 bg-gold rounded-full animate-bounce"
								style="animation-delay: {i * 0.12}s; animation-duration: 0.8s"
							></span>
						{/each}
					</span>
				{:else if step.status === 'done'}
					<span class="text-green-500 text-xs flex-shrink-0">&#10003;</span>
				{:else if step.status === 'error'}
					<span class="text-red-400 text-xs flex-shrink-0">&#10007;</span>
				{/if}
			</div>

			{#if step.args && Object.keys(step.args).length > 0}
				<p class="text-xs text-slate-400 font-mono mt-1 truncate">
					{formatArgs(step.args)}
				</p>
			{/if}

			{#if step.preview}
				<p class="text-xs text-slate-300 mt-2 leading-relaxed line-clamp-3 font-light">
					{step.preview}
				</p>
			{/if}
		</div>
	</div>
</div>
