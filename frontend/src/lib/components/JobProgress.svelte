<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { jobsApi, type Job } from '$lib/api/jobs';

	let { jobId, onDone, onProgress }: { jobId: string; onDone?: (job: Job) => void; onProgress?: (job: Job) => void } = $props();

	let job = $state<Job | null>(null);
	let interval: ReturnType<typeof setInterval> | null = null;

	async function poll() {
		try {
			job = await jobsApi.get(jobId);
			if (job && (job.status === 'done' || job.status === 'failed')) {
				if (interval) {
					clearInterval(interval);
					interval = null;
				}
				onDone?.(job);
			} else if (job && job.status === 'running') {
				onProgress?.(job);
			}
		} catch {
			// ignore polling errors
		}
	}

	onMount(() => {
		poll();
		interval = setInterval(poll, 3000);
	});

	onDestroy(() => {
		if (interval) clearInterval(interval);
	});

	let pct = $derived(
		job && job.total_pairs > 0 ? Math.round((job.completed_pairs / job.total_pairs) * 100) : 0
	);
</script>

{#if job}
	<div class="space-y-1">
		<div class="flex items-center justify-between text-sm">
			<span class="text-slate-400">
				{#if job.status === 'queued'}
					Queued…
				{:else if job.status === 'running'}
					Running — {job.completed_pairs}/{job.total_pairs} pairs
				{:else if job.status === 'done'}
					Done — {job.completed_pairs}/{job.total_pairs} pairs
				{:else}
					Failed
				{/if}
			</span>
			<span class="font-mono text-xs
				{job.status === 'done' ? 'text-green-400' :
				 job.status === 'failed' ? 'text-red-400' :
				 job.status === 'running' ? 'text-gold' : 'text-slate-500'}">
				{job.status}
			</span>
		</div>
		{#if job.status === 'running' || job.status === 'done'}
			<div class="w-full bg-navy-700 rounded-full h-2">
				<div
					class="h-2 rounded-full transition-all duration-300
						{job.status === 'done' ? 'bg-green-500' : 'bg-gold'}"
					style="width: {pct}%"
				></div>
			</div>
		{/if}
		{#if job.error}
			<p class="text-red-400 text-xs">{job.error}</p>
		{/if}
	</div>
{/if}
