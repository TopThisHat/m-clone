<script lang="ts">
	type Step = {
		step_number: number;
		description: string;
		status: 'pending' | 'running' | 'done' | 'skipped' | 'failed';
	};

	type Plan = {
		task_summary: string;
		steps: Step[];
	};

	let { plan }: { plan: Plan } = $props();

	const allDone = $derived(plan.steps.length > 0 && plan.steps.every((s) => s.status === 'done' || s.status === 'skipped'));
	const doneCount = $derived(plan.steps.filter((s) => s.status === 'done').length);
</script>

<div class="my-3 border border-gold/20 rounded-lg bg-navy-800/60 overflow-hidden">
	<!-- Header -->
	<div class="flex items-center gap-2 px-4 py-3 border-b border-navy-700 bg-navy-800/80">
		<div class="w-6 h-6 rounded-sm bg-gold/10 border border-gold/30 flex items-center justify-center flex-shrink-0">
			<svg class="w-3.5 h-3.5 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
			</svg>
		</div>
		<span class="text-xs font-medium text-gold tracking-wide uppercase">Execution Plan</span>
	</div>

	<div class="px-4 py-3 space-y-3">
		<!-- Task summary -->
		<p class="text-sm text-slate-300 leading-relaxed">{plan.task_summary}</p>

		{#if allDone}
			<!-- Collapsed summary when all steps complete -->
			<div class="flex items-center gap-2 text-xs text-green-400 bg-green-900/20 border border-green-700/30 rounded px-3 py-2">
				<svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
				</svg>
				<span>{doneCount} step{doneCount !== 1 ? 's' : ''} completed</span>
			</div>
		{:else}
			<!-- Step list -->
			<ol class="space-y-2">
				{#each plan.steps as step (step.step_number)}
					<li class="flex items-start gap-3">
						<!-- Step number circle -->
						<span
							class="flex-shrink-0 w-5 h-5 rounded-full border text-xs flex items-center justify-center font-medium mt-0.5
								{step.status === 'done'    ? 'bg-green-900/40 border-green-700/50 text-green-400' :
								 step.status === 'running' ? 'bg-gold/10 border-gold/40 text-gold' :
								 step.status === 'failed'  ? 'bg-red-900/40 border-red-700/50 text-red-400' :
								 step.status === 'skipped' ? 'bg-navy-700 border-navy-600 text-slate-600' :
								                             'bg-navy-700 border-navy-600 text-slate-500'}"
						>
							{step.step_number}
						</span>

						<!-- Description + badge -->
						<div class="flex-1 flex items-start justify-between gap-2 min-w-0">
							<span
								class="text-sm leading-relaxed
									{step.status === 'done'    ? 'text-slate-400 line-through' :
									 step.status === 'skipped' ? 'text-slate-600 line-through' :
									 step.status === 'running' ? 'text-slate-200' :
									 step.status === 'failed'  ? 'text-slate-300' :
									                             'text-slate-400'}"
							>
								{step.description}
							</span>

							<!-- Status badge -->
							{#if step.status === 'running'}
								<span class="flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-gold/10 border border-gold/30 text-gold animate-pulse">
									<span class="w-1.5 h-1.5 rounded-full bg-gold"></span>
									Running
								</span>
							{:else if step.status === 'done'}
								<span class="flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-green-900/30 border border-green-700/30 text-green-400">
									&#10003; Done
								</span>
							{:else if step.status === 'failed'}
								<span class="flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-red-900/30 border border-red-700/30 text-red-400">
									&#10007; Failed
								</span>
							{:else if step.status === 'skipped'}
								<span class="flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-navy-700 border border-navy-600 text-slate-600">
									Skipped
								</span>
							{:else}
								<span class="flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-navy-700 border border-navy-600 text-slate-500">
									Pending
								</span>
							{/if}
						</div>
					</li>
				{/each}
			</ol>
		{/if}
	</div>
</div>
