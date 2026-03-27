<script lang="ts">
	export interface Program {
		id: string;
		name: string;
		campaign_count: number;
		created_at: string;
	}

	let {
		programs = [],
		selectedId = null,
		loading = false,
		oncreate,
		onselect,
	}: {
		programs?: Program[];
		selectedId?: string | null;
		loading?: boolean;
		oncreate?: () => void;
		onselect?: (id: string | null) => void;
	} = $props();

	let collapsed = $state(false);
	let searchQuery = $state('');

	let filtered = $derived(
		searchQuery.trim()
			? programs.filter((p) =>
					p.name.toLowerCase().includes(searchQuery.trim().toLowerCase())
				)
			: programs
	);

	function select(id: string | null) {
		onselect?.(id);
	}

	function handleItemKeydown(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			select(id);
		}
	}

	function toggleCollapse() {
		collapsed = !collapsed;
	}
</script>

<aside class="flex flex-col h-full border-r border-navy-700 bg-navy-950 overflow-hidden w-56">
	<!-- Header -->
	<div class="px-4 py-3 border-b border-navy-700 flex items-center justify-between flex-shrink-0">
		<button
			onclick={toggleCollapse}
			class="flex items-center gap-1.5 text-sm font-serif text-gold tracking-wide uppercase hover:text-gold-light transition-colors"
			aria-expanded={!collapsed}
			aria-controls="programs-list"
		>
			<svg
				class="w-3 h-3 transition-transform {collapsed ? '-rotate-90' : 'rotate-0'}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				aria-hidden="true"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
			Programs
		</button>
		{#if oncreate}
			<button
				onclick={oncreate}
				class="text-slate-500 hover:text-gold hover:bg-navy-800 rounded min-w-[44px] min-h-[44px] flex items-center justify-center transition-colors"
				aria-label="Create new program"
				title="New program"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
				</svg>
			</button>
		{/if}
	</div>

	{#if !collapsed}
		<!-- Search filter -->
		{#if programs.length > 5}
			<div class="px-3 pt-2 pb-1 flex-shrink-0">
				<input
					bind:value={searchQuery}
					type="text"
					placeholder="Filter programs..."
					aria-label="Filter programs"
					class="w-full bg-navy-800 border border-navy-700 rounded px-2.5 py-1 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-gold/40 transition-colors"
				/>
			</div>
		{/if}

		<!-- "All" option -->
		<div id="programs-list" role="listbox" aria-label="Programs" class="flex-1 min-h-0 overflow-y-auto px-2 py-1.5 space-y-0.5">
			<div
				role="option"
				tabindex="0"
				aria-selected={selectedId === null}
				onclick={() => select(null)}
				onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(null); } }}
				class="flex items-center gap-2 px-3 min-h-[44px] rounded cursor-pointer transition-colors text-xs
					{selectedId === null
						? 'bg-navy-800 text-gold font-medium border-l-2 border-gold'
						: 'text-slate-400 hover:bg-navy-800/50 hover:text-slate-300 border-l-2 border-transparent'}"
			>
				<span class="text-xs" aria-hidden="true">◈</span>
				All Programs
				<span class="ml-auto text-xs text-slate-600 font-mono">{programs.length}</span>
			</div>

			<!-- Program list -->
			{#if loading}
				<div class="flex justify-center py-6" aria-live="polite" aria-busy="true">
					<span class="flex gap-1" aria-hidden="true">
						{#each [0, 1, 2] as j (j)}
							<span class="w-1.5 h-1.5 bg-gold/40 rounded-full animate-bounce" style="animation-delay:{j * 0.15}s"></span>
						{/each}
					</span>
					<span class="sr-only">Loading programs</span>
				</div>
			{:else if filtered.length === 0 && searchQuery.trim()}
				<p class="text-xs text-slate-600 px-3 py-4 text-center">No matching programs.</p>
			{:else if programs.length === 0}
				<p class="text-xs text-slate-600 px-3 py-4 text-center leading-relaxed">
					No programs yet.
				</p>
			{:else}
				{#each filtered as program (program.id)}
					{@const isSelected = selectedId === program.id}
					<div
						role="option"
						tabindex="0"
						aria-selected={isSelected}
						onclick={() => select(program.id)}
						onkeydown={(e) => handleItemKeydown(e, program.id)}
						class="group flex items-center gap-2 px-3 min-h-[44px] rounded cursor-pointer transition-colors text-xs
							{isSelected
								? 'bg-navy-800 text-gold font-medium border-l-2 border-gold'
								: 'text-slate-400 hover:bg-navy-800/50 hover:text-slate-300 border-l-2 border-transparent'}"
					>
						<span class="truncate flex-1" title={program.name}>{program.name}</span>
						<span class="text-xs text-slate-600 font-mono flex-shrink-0">{program.campaign_count}</span>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</aside>
