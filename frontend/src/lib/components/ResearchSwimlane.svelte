<script lang="ts">
	import type { TraceStep } from '$lib/stores/traceStore';
	import ToolIcon from './ToolIcon.svelte';

	let { steps }: { steps: TraceStep[] } = $props();

	// Lane definitions
	const LANES: { id: string; label: string; tools: string[] }[] = [
		{ id: 'planning', label: 'Planning', tools: ['create_research_plan'] },
		{
			id: 'searching',
			label: 'Searching',
			tools: ['web_search', 'wiki_lookup', 'get_financials', 'sec_edgar_search', 'search_uploaded_documents']
		},
		{ id: 'evaluating', label: 'Evaluating', tools: ['evaluate_research_completeness'] },
		{ id: 'writing', label: 'Writing', tools: ['__text__'] }
	];

	const laneColors: Record<string, string> = {
		planning: 'border-blue-500/40 bg-blue-500/5',
		searching: 'border-gold/30 bg-gold/5',
		evaluating: 'border-purple-500/40 bg-purple-500/5',
		writing: 'border-green-500/40 bg-green-500/5'
	};

	const laneHeaderColors: Record<string, string> = {
		planning: 'text-blue-400',
		searching: 'text-gold',
		evaluating: 'text-purple-400',
		writing: 'text-green-400'
	};

	function getLane(step: TraceStep): string {
		for (const lane of LANES) {
			if (lane.tools.includes(step.toolName)) return lane.id;
		}
		return 'searching';
	}

	const grouped = $derived.by(() => {
		const map = new Map<string, TraceStep[]>();
		for (const lane of LANES) map.set(lane.id, []);
		for (const step of steps) {
			const laneId = getLane(step);
			map.get(laneId)?.push(step);
		}
		return map;
	});

	function duration(step: TraceStep, allSteps: TraceStep[]): string {
		const idx = allSteps.indexOf(step);
		if (idx < 0 || idx === allSteps.length - 1) return '';
		const next = allSteps[idx + 1];
		const ms = next.timestamp - step.timestamp;
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	}

	const statusIcon: Record<string, string> = {
		pending: '○',
		running: '◎',
		done: '✓',
		error: '✗'
	};

	const statusColor: Record<string, string> = {
		pending: 'text-slate-500',
		running: 'text-gold',
		done: 'text-green-400',
		error: 'text-red-400'
	};
</script>

<div class="grid grid-cols-4 gap-2">
	{#each LANES as lane}
		{@const laneSteps = grouped?.get(lane.id) ?? []}
		<div class="flex flex-col gap-2">
			<div class="text-xs uppercase tracking-widest font-medium {laneHeaderColors[lane.id]} mb-1">
				{lane.label}
				{#if laneSteps.length > 0}
					<span class="text-slate-600 font-normal ml-1">({laneSteps.length})</span>
				{/if}
			</div>

			<div
				class="flex-1 border rounded-lg p-2 min-h-16 {laneColors[lane.id]} flex flex-col gap-1.5"
			>
				{#each laneSteps as step}
					<div class="bg-navy-800/80 border border-navy-600/50 rounded p-2 text-xs">
						<div class="flex items-center justify-between gap-1 mb-0.5">
							<span class="font-medium text-slate-300 truncate">{step.toolLabel}</span>
							<span class="flex-shrink-0 {statusColor[step.status]}">
								{statusIcon[step.status]}
							</span>
						</div>
						{#if step.args}
							{@const firstArg = Object.values(step.args)[0]}
							{#if firstArg}
								<p class="text-slate-500 font-mono truncate text-[10px]">
									{String(firstArg).slice(0, 40)}
								</p>
							{/if}
						{/if}
						{#if duration(step, steps)}
							<p class="text-slate-600 text-[10px] mt-0.5">{duration(step, steps)}</p>
						{/if}
					</div>
				{/each}

				{#if laneSteps.length === 0}
					<div class="flex-1 flex items-center justify-center">
						<span class="text-slate-700 text-[10px]">—</span>
					</div>
				{/if}
			</div>

			<!-- Lane total -->
			{#if laneSteps.length > 0}
				<div class="text-[10px] text-slate-600 text-center">
					{laneSteps.filter((s) => s.status === 'done').length}/{laneSteps.length} done
				</div>
			{/if}
		</div>
	{/each}
</div>
