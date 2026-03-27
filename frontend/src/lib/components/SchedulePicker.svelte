<script lang="ts">
	/**
	 * Friendly schedule picker that converts to/from cron strings.
	 * Bind to `value` for the cron string (empty string = manual only).
	 */
	let { value = $bindable('') }: { value?: string } = $props();

	type Freq = 'manual' | 'daily' | 'weekdays' | 'weekly' | 'monthly';

	const HOURS = Array.from({ length: 16 }, (_, i) => i + 5); // 5am–8pm
	const DAYS_OF_WEEK = [
		{ label: 'Sunday', v: 0 },
		{ label: 'Monday', v: 1 },
		{ label: 'Tuesday', v: 2 },
		{ label: 'Wednesday', v: 3 },
		{ label: 'Thursday', v: 4 },
		{ label: 'Friday', v: 5 },
		{ label: 'Saturday', v: 6 },
	];
	const DAYS_OF_MONTH = [1, 2, 5, 10, 15, 20, 25, 28];

	function formatHour(h: number): string {
		if (h === 0) return '12:00 AM';
		if (h < 12) return `${h}:00 AM`;
		if (h === 12) return '12:00 PM';
		return `${h - 12}:00 PM`;
	}

	function dayLabel(dom: number): string {
		if (dom === 28) return '28th (approx. last)';
		const suffix = dom === 1 ? 'st' : dom === 2 ? 'nd' : dom === 3 ? 'rd' : 'th';
		return `${dom}${suffix}`;
	}

	// Parse incoming cron → internal state
	function parseCron(cron: string): { freq: Freq; hour: number; dow: number; dom: number } {
		const defaults = { freq: 'manual' as Freq, hour: 9, dow: 1, dom: 1 };
		if (!cron) return defaults;
		const m = cron.match(/^0 (\d+) (\S+) \* (\S+)$/);
		if (!m) return defaults;
		const [, h, domPart, dowPart] = m;
		const hour = parseInt(h);
		if (dowPart === '*' && domPart !== '*') {
			return { freq: 'monthly', hour, dow: 1, dom: parseInt(domPart) };
		}
		if (domPart === '*') {
			if (dowPart === '1-5') return { freq: 'weekdays', hour, dow: 1, dom: 1 };
			if (dowPart === '*') return { freq: 'daily', hour, dow: 1, dom: 1 };
			return { freq: 'weekly', hour, dow: parseInt(dowPart), dom: 1 };
		}
		return defaults;
	}

	function buildCron(freq: Freq, hour: number, dow: number, dom: number): string {
		if (freq === 'manual') return '';
		if (freq === 'daily') return `0 ${hour} * * *`;
		if (freq === 'weekdays') return `0 ${hour} * * 1-5`;
		if (freq === 'weekly') return `0 ${hour} * * ${dow}`;
		if (freq === 'monthly') return `0 ${hour} ${dom} * *`;
		return '';
	}

	const _initial = parseCron(value);
	let freq = $state<Freq>(_initial.freq);
	let hour = $state(_initial.hour);
	let dow = $state(_initial.dow);
	let dom = $state(_initial.dom);

	// Push changes out
	$effect(() => {
		const next = buildCron(freq, hour, dow, dom);
		if (next !== value) value = next;
	});

	const FREQ_OPTIONS: { key: Freq; label: string; desc: string }[] = [
		{ key: 'manual', label: 'Manual', desc: 'Run only when triggered manually' },
		{ key: 'daily', label: 'Daily', desc: 'Once every day' },
		{ key: 'weekdays', label: 'Weekdays', desc: 'Mon – Fri' },
		{ key: 'weekly', label: 'Weekly', desc: 'Once per week' },
		{ key: 'monthly', label: 'Monthly', desc: 'Once per month' },
	];
</script>

<div class="space-y-3">
	<!-- Frequency pills -->
	<div class="flex flex-wrap gap-2">
		{#each FREQ_OPTIONS as opt}
			<button
				type="button"
				onclick={() => (freq = opt.key)}
				class="px-3 py-1.5 rounded-full text-sm border transition-colors
					{freq === opt.key
						? 'bg-gold text-navy border-gold font-semibold'
						: 'border-navy-600 text-slate-400 hover:border-navy-500 hover:text-slate-300'}"
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- Context controls -->
	{#if freq !== 'manual'}
		<div class="flex flex-wrap items-center gap-3 text-sm text-slate-300 pl-1">
			{#if freq === 'weekly'}
				<span class="text-slate-500">Every</span>
				<select
					bind:value={dow}
					class="bg-navy-700 border border-navy-600 rounded-lg px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-gold"
				>
					{#each DAYS_OF_WEEK as d}
						<option value={d.v}>{d.label}</option>
					{/each}
				</select>
			{/if}
			{#if freq === 'monthly'}
				<span class="text-slate-500">On the</span>
				<select
					bind:value={dom}
					class="bg-navy-700 border border-navy-600 rounded-lg px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-gold"
				>
					{#each DAYS_OF_MONTH as d}
						<option value={d}>{dayLabel(d)}</option>
					{/each}
				</select>
			{/if}
			<span class="text-slate-500">{freq === 'monthly' || freq === 'weekly' ? 'at' : 'At'}</span>
			<select
				bind:value={hour}
				class="bg-navy-700 border border-navy-600 rounded-lg px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-gold"
			>
				{#each HOURS as h}
					<option value={h}>{formatHour(h)}</option>
				{/each}
			</select>
		</div>
		<p class="text-xs text-slate-600 pl-1 font-mono">{value}</p>
	{:else}
		<p class="text-xs text-slate-500 pl-1">This campaign will only run when you click "Run Now".</p>
	{/if}
</div>
