<script lang="ts">
	import type { KGGraphNode, KGRelationship, DealPartnerGroup } from '$lib/api/knowledgeGraph';

	const ENTITY_TYPES = ['person', 'company', 'sports_team', 'location', 'product', 'other'];

	const TYPE_LABELS: Record<string, string> = {
		person: 'Person',
		company: 'Company',
		sports_team: 'Sports Team',
		location: 'Location',
		product: 'Product',
		other: 'Other',
	};

	const TYPE_COLORS: Record<string, string> = {
		person: 'bg-[#1e3a5f] text-[#60A5FA]',
		company: 'bg-[#0e3a42] text-[#22D3EE]',
		sports_team: 'bg-[#3d2e05] text-[#FBBF24]',
		location: 'bg-[#0f2e1a] text-[#4ADE80]',
		product: 'bg-[#2a1a42] text-[#C084FC]',
		other: 'bg-navy-700 text-[#CBD5E1]',
	};

	let {
		node,
		relationships,
		loadingRels,
		dealPartners,
		isAdmin,
		editingEntity,
		editForm,
		entitySaving,
		deleteConfirmEntity,
		entityDeleting,
		editingRelId,
		editRelPredicate,
		relSaving,
		deleteConfirmRelId,
		relDeleting,
		onclose,
		onstarteditenity,
		oncanceleditentity,
		onsaveentity,
		ondeleteentityconfirm,
		onsetdeleteconfirm,
		onstarteditrel,
		oncanceleditrel,
		onsaverel,
		ondeleterelconfirm,
		onsetdeleterelconfirm,
	}: {
		node: KGGraphNode;
		relationships: KGRelationship[];
		loadingRels: boolean;
		dealPartners: DealPartnerGroup[];
		isAdmin: boolean;
		editingEntity: boolean;
		editForm: { name: string; entity_type: string; description: string; aliases: string };
		entitySaving: boolean;
		deleteConfirmEntity: boolean;
		entityDeleting: boolean;
		editingRelId: string | null;
		editRelPredicate: string;
		relSaving: boolean;
		deleteConfirmRelId: string | null;
		relDeleting: boolean;
		onclose: () => void;
		onstarteditenity: () => void;
		oncanceleditentity: () => void;
		onsaveentity: () => void;
		ondeleteentityconfirm: () => void;
		onsetdeleteconfirm: (val: boolean) => void;
		onstarteditrel: (rel: KGRelationship) => void;
		oncanceleditrel: () => void;
		onsaverel: (relId: string) => void;
		ondeleterelconfirm: (relId: string) => void;
		onsetdeleterelconfirm: (relId: string | null) => void;
	} = $props();

	function typeLabel(type: string): string {
		return TYPE_LABELS[type.toLowerCase()] ?? type;
	}

	function typeColor(type: string): string {
		return TYPE_COLORS[type.toLowerCase()] ?? 'bg-[#7B8794]';
	}

	function sourceBadgeClass(source: string): string {
		return source === 'team'
			? 'bg-gold/20 text-gold border-gold/30'
			: 'bg-slate-700/50 text-slate-300 border-slate-600';
	}

	let nodeDealPartners = $derived(
		dealPartners.filter((dp) => dp.person1.id === node.id || dp.person2.id === node.id)
	);
</script>

<!-- Right-edge overlay: positioned absolute inside the graph container -->
<div
	class="absolute right-0 top-0 bottom-0 w-80 z-20 bg-navy-900 border-l border-navy-700 overflow-y-auto flex flex-col shadow-2xl"
	role="complementary"
	aria-label="Entity detail panel"
	data-testid="kg-entity-panel"
>
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-3 border-b border-navy-700 sticky top-0 bg-navy-900 z-10">
		<h3 class="text-sm font-semibold text-slate-200 truncate flex-1 mr-2">{node.name}</h3>
		<button
			onclick={onclose}
			class="text-slate-500 hover:text-slate-300 transition-colors shrink-0 w-6 h-6 flex items-center justify-center"
			aria-label="Close entity detail panel"
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<!-- Content -->
	<div class="p-4 flex-1 space-y-3">
		<span class="inline-block text-xs px-2 py-0.5 rounded font-medium {typeColor(node.entity_type)}">
			{typeLabel(node.entity_type)}
		</span>

		{#if node.description}
			<p class="text-xs text-slate-400">{node.description}</p>
		{/if}

		{#if node.aliases && node.aliases.length > 0}
			<p class="text-xs text-slate-500">Also known as: {node.aliases.join(', ')}</p>
		{/if}

		{#if node.metadata && Object.keys(node.metadata).length > 0}
			<div>
				<h4 class="text-[10px] text-slate-600 uppercase tracking-widest mb-1.5">Metadata</h4>
				<div class="space-y-1">
					{#each Object.entries(node.metadata) as [key, value] (key)}
						<div class="flex items-start gap-2 text-xs">
							<span class="text-slate-500 font-mono shrink-0">{key}:</span>
							<span class="text-slate-300 break-all">
								{typeof value === 'object' ? JSON.stringify(value) : String(value)}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Admin actions -->
		{#if isAdmin && !editingEntity}
			<div class="flex gap-2">
				<button
					onclick={onstarteditenity}
					class="text-xs px-2 py-1 rounded border border-gold/30 text-gold hover:bg-gold/10 transition-colors"
				>
					Edit
				</button>
				<button
					onclick={() => onsetdeleteconfirm(true)}
					class="text-xs px-2 py-1 rounded border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
				>
					Delete
				</button>
			</div>
		{/if}

		<!-- Delete confirmation -->
		{#if deleteConfirmEntity}
			<div class="p-2 bg-red-950/30 border border-red-500/30 rounded">
				<p class="text-xs text-red-300 mb-2">Delete "{node.name}"? This cannot be undone.</p>
				<div class="flex gap-2">
					<button
						onclick={ondeleteentityconfirm}
						disabled={entityDeleting}
						class="text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50"
					>
						{entityDeleting ? 'Deleting...' : 'Confirm'}
					</button>
					<button
						onclick={() => onsetdeleteconfirm(false)}
						class="text-xs px-2 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors"
					>
						Cancel
					</button>
				</div>
			</div>
		{/if}

		<!-- Entity edit form -->
		{#if editingEntity}
			<div class="space-y-2">
				<div>
					<label for="kg-edit-name" class="text-[10px] text-slate-500 block mb-0.5">Name</label>
					<input
						id="kg-edit-name"
						bind:value={editForm.name}
						class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
					/>
				</div>
				<div>
					<label for="kg-edit-type" class="text-[10px] text-slate-500 block mb-0.5">Type</label>
					<select
						id="kg-edit-type"
						bind:value={editForm.entity_type}
						class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
					>
						{#each ENTITY_TYPES as t (t)}
							<option value={t}>{typeLabel(t)}</option>
						{/each}
					</select>
				</div>
				<div>
					<label for="kg-edit-desc" class="text-[10px] text-slate-500 block mb-0.5">Description</label>
					<textarea
						id="kg-edit-desc"
						bind:value={editForm.description}
						rows={2}
						class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold resize-none"
					></textarea>
				</div>
				<div>
					<label for="kg-edit-aliases" class="text-[10px] text-slate-500 block mb-0.5">
						Aliases (comma-separated)
					</label>
					<input
						id="kg-edit-aliases"
						bind:value={editForm.aliases}
						class="w-full bg-navy-800 border border-navy-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-gold"
					/>
				</div>
				<div class="flex gap-2 pt-1">
					<button
						onclick={onsaveentity}
						disabled={entitySaving}
						class="text-xs px-3 py-1 rounded bg-gold/20 text-gold border border-gold/30 hover:bg-gold/30 transition-colors disabled:opacity-50"
					>
						{entitySaving ? 'Saving...' : 'Save'}
					</button>
					<button
						onclick={oncanceleditentity}
						class="text-xs px-3 py-1 rounded border border-navy-600 text-slate-400 hover:text-slate-200 transition-colors"
					>
						Cancel
					</button>
				</div>
			</div>
		{/if}

		<hr class="border-navy-700" />

		<!-- Relationships -->
		<h4 class="text-xs font-semibold text-slate-400">Relationships</h4>
		{#if loadingRels}
			<p class="text-xs text-slate-500">Loading...</p>
		{:else if relationships.length === 0}
			<p class="text-xs text-slate-600">No relationships.</p>
		{:else}
			<div class="space-y-1.5">
				{#each relationships as rel (rel.id)}
					<div class="text-xs bg-navy-800 rounded px-2 py-1.5">
						<div class="flex items-center gap-1">
							<span class="text-slate-300 truncate">{rel.subject_name}</span>
							{#if editingRelId === rel.id}
								<input
									bind:value={editRelPredicate}
									onkeydown={(e) => {
										if (e.key === 'Enter') onsaverel(rel.id);
										if (e.key === 'Escape') oncanceleditrel();
									}}
									class="bg-navy-700 border border-gold/40 rounded px-1 py-0.5 text-[11px] text-gold w-24 focus:outline-none"
								/>
								<button
									onclick={() => onsaverel(rel.id)}
									disabled={relSaving}
									class="text-[10px] text-gold hover:text-gold-light shrink-0"
								>
									{relSaving ? '...' : 'ok'}
								</button>
								<button
									onclick={oncanceleditrel}
									class="text-[10px] text-slate-500 hover:text-slate-300 shrink-0"
								>
									esc
								</button>
							{:else}
								<button
									onclick={() => isAdmin && onstarteditrel(rel)}
									class="text-gold font-medium shrink-0 {isAdmin
										? 'hover:underline cursor-pointer'
										: 'cursor-default'}"
								>
									{rel.predicate}
								</button>
							{/if}
							<span class="text-slate-300 truncate">{rel.object_name}</span>
							{#if rel.graph_source}
								<span class="text-[10px] px-1 py-0.5 rounded border shrink-0 ml-auto {sourceBadgeClass(rel.graph_source)}">
									{rel.graph_source === 'team' ? 'Team' : 'Master'}
								</span>
							{/if}
							{#if isAdmin && editingRelId !== rel.id}
								{#if deleteConfirmRelId === rel.id}
									<button
										onclick={() => ondeleterelconfirm(rel.id)}
										disabled={relDeleting}
										class="text-[10px] text-red-400 hover:text-red-300 shrink-0"
									>
										{relDeleting ? '...' : 'yes'}
									</button>
									<button
										onclick={() => onsetdeleterelconfirm(null)}
										class="text-[10px] text-slate-500 hover:text-slate-300 shrink-0"
									>
										no
									</button>
								{:else}
									<button
										onclick={() => onsetdeleterelconfirm(rel.id)}
										class="text-[10px] text-red-400/60 hover:text-red-400 shrink-0 ml-auto"
										title="Delete relationship"
									>
										&times;
									</button>
								{/if}
							{/if}
						</div>
						{#if rel.confidence < 1}
							<span class="text-slate-600 text-[10px]">
								{(rel.confidence * 100).toFixed(0)}% confidence
							</span>
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		<!-- Deal partners for this node -->
		{#if nodeDealPartners.length > 0}
			<hr class="border-navy-700" />
			<h4 class="text-xs font-semibold text-[#C0922B]">Deal Partners</h4>
			{#each nodeDealPartners as dp (dp.person1.id + '-' + dp.person2.id)}
				{@const partner = dp.person1.id === node.id ? dp.person2 : dp.person1}
				<div class="text-xs bg-navy-800 rounded px-2 py-1.5 mb-1">
					<span class="text-slate-200">{partner.name}</span>
					<span class="text-slate-600 ml-1">
						({dp.shared_deals.length} shared deal{dp.shared_deals.length !== 1 ? 's' : ''})
					</span>
					{#each dp.shared_deals as deal (deal.entity_id)}
						<div class="text-[10px] text-slate-500 mt-0.5 pl-2">{deal.entity_name}</div>
					{/each}
				</div>
			{/each}
		{/if}
	</div>
</div>
