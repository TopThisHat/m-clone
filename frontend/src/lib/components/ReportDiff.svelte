<script lang="ts">
	/**
	 * Word-level diff between two markdown strings.
	 * Uses simple LCS to mark additions (green) and removals (red strikethrough).
	 * No external diff library needed.
	 */

	let {
		currentMarkdown,
		previousMarkdown,
		mode = 'unified',
	}: {
		currentMarkdown: string;
		previousMarkdown: string;
		mode?: 'unified' | 'side' | 'off';
	} = $props();

	type DiffToken = { text: string; type: 'same' | 'add' | 'remove' };

	function tokenize(text: string): string[] {
		// Split on whitespace but keep the whitespace tokens for display
		return text.split(/(\s+)/);
	}

	function lcs(a: string[], b: string[]): number[][] {
		const m = a.length;
		const n = b.length;
		const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
		for (let i = 1; i <= m; i++) {
			for (let j = 1; j <= n; j++) {
				if (a[i - 1] === b[j - 1]) {
					dp[i][j] = dp[i - 1][j - 1] + 1;
				} else {
					dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
				}
			}
		}
		return dp;
	}

	function buildDiff(a: string[], b: string[]): DiffToken[] {
		const dp = lcs(a, b);
		const result: DiffToken[] = [];
		let i = a.length;
		let j = b.length;
		const ops: DiffToken[] = [];

		while (i > 0 || j > 0) {
			if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
				ops.push({ text: a[i - 1], type: 'same' });
				i--; j--;
			} else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
				ops.push({ text: b[j - 1], type: 'add' });
				j--;
			} else {
				ops.push({ text: a[i - 1], type: 'remove' });
				i--;
			}
		}
		return ops.reverse();
	}

	let diff = $derived.by((): DiffToken[] => {
		if (mode === 'off') return [];
		const aTokens = tokenize(previousMarkdown);
		const bTokens = tokenize(currentMarkdown);
		// Limit for performance (very large reports)
		if (aTokens.length + bTokens.length > 10000) {
			// Fallback: line-level diff for large docs
			const aLines = previousMarkdown.split('\n');
			const bLines = currentMarkdown.split('\n');
			const dp = lcs(aLines, bLines);
			return buildDiff(aLines, bLines).map((t) => ({
				...t,
				text: t.text + (t.text.endsWith('\n') ? '' : '\n'),
			}));
		}
		return buildDiff(aTokens, bTokens);
	});

	let hasChanges = $derived(diff.some((t) => t.type !== 'same'));

	let leftHtml = $derived.by((): string => {
		if (mode !== 'side') return '';
		return diff
			.filter((t) => t.type !== 'add')
			.map((t) =>
				t.type === 'remove'
					? `<span class="bg-red-900/30 text-red-400 line-through">${escHtml(t.text)}</span>`
					: escHtml(t.text)
			)
			.join('');
	});

	let rightHtml = $derived.by((): string => {
		if (mode !== 'side') return '';
		return diff
			.filter((t) => t.type !== 'remove')
			.map((t) =>
				t.type === 'add'
					? `<span class="bg-green-900/30 text-green-400">${escHtml(t.text)}</span>`
					: escHtml(t.text)
			)
			.join('');
	});

	let unifiedHtml = $derived.by((): string => {
		if (mode !== 'unified') return '';
		return diff
			.map((t) => {
				if (t.type === 'add') return `<span class="bg-green-900/30 text-green-400">${escHtml(t.text)}</span>`;
				if (t.type === 'remove') return `<span class="bg-red-900/30 text-red-400 line-through">${escHtml(t.text)}</span>`;
				return escHtml(t.text);
			})
			.join('');
	});

	function escHtml(text: string): string {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');
	}
</script>

{#if mode !== 'off'}
	<div class="rounded-lg border border-navy-700 bg-navy-900/50 overflow-hidden">
		<div class="px-4 py-2 border-b border-navy-700 flex items-center gap-3">
			<span class="text-xs text-slate-400 font-medium">Diff from previous version</span>
			{#if !hasChanges}
				<span class="text-xs text-slate-600">No changes detected</span>
			{:else}
				<span class="text-[10px] text-green-400">
					+{diff.filter((t) => t.type === 'add').length} tokens added
				</span>
				<span class="text-[10px] text-red-400">
					−{diff.filter((t) => t.type === 'remove').length} tokens removed
				</span>
			{/if}
		</div>

		{#if mode === 'unified'}
			<div class="px-5 py-4 font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto">
				<!-- eslint-disable-next-line svelte/no-at-html-tags -->
				{@html unifiedHtml}
			</div>
		{:else if mode === 'side'}
			<div class="grid grid-cols-2 divide-x divide-navy-700 max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh] overflow-y-auto">
				<div class="px-4 py-3">
					<p class="text-[10px] text-slate-600 uppercase tracking-wide mb-2">Previous</p>
					<div class="font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html leftHtml}
					</div>
				</div>
				<div class="px-4 py-3">
					<p class="text-[10px] text-slate-600 uppercase tracking-wide mb-2">Current</p>
					<div class="font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html rightHtml}
					</div>
				</div>
			</div>
		{/if}
	</div>
{/if}
