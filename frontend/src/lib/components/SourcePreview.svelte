<script lang="ts" module>
	// Svelte action for inline source preview on hover
	import type { TraceStep } from '$lib/stores/traceStore';

	export interface SourcePreviewOptions {
		urlMap: Map<string, string>;
	}

	function escapeHtml(str: string): string {
		return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
	}

	export function sourcePreview(node: HTMLElement, options: SourcePreviewOptions) {
		let tooltip: HTMLDivElement | null = null;
		let cleanup: (() => void)[] = [];

		function showTooltip(anchor: HTMLAnchorElement, snippet: string) {
			removeTooltip();

			const domain = (() => {
				try {
					return new URL(anchor.href).hostname.replace(/^www\./, '');
				} catch {
					return anchor.href;
				}
			})();

			tooltip = document.createElement('div');
			tooltip.className =
				'fixed z-50 max-w-xs bg-navy-900 border border-navy-600 rounded-lg shadow-xl p-3 pointer-events-none';

			const domainEl = document.createElement('div');
			domainEl.className = 'text-xs text-gold/70 font-medium mb-1';
			domainEl.textContent = domain;

			const snippetEl = document.createElement('div');
			snippetEl.className = 'text-xs text-slate-400 leading-relaxed line-clamp-4';
			snippetEl.textContent = snippet;

			tooltip.appendChild(domainEl);
			tooltip.appendChild(snippetEl);

			const rect = anchor.getBoundingClientRect();
			tooltip.style.left = `${Math.min(rect.left, window.innerWidth - 320)}px`;
			tooltip.style.top = `${rect.bottom + 6}px`;
			document.body.appendChild(tooltip);
		}

		function removeTooltip() {
			tooltip?.remove();
			tooltip = null;
		}

		function attach() {
			cleanup.forEach((fn) => fn());
			cleanup = [];

			const anchors = node.querySelectorAll<HTMLAnchorElement>('a[href^="http"]');
			anchors.forEach((a) => {
				const snippet = options.urlMap.get(a.href) || options.urlMap.get(a.href + '/') || '';
				if (!snippet) return;

				const enter = () => showTooltip(a, snippet);
				const leave = () => removeTooltip();
				a.addEventListener('mouseenter', enter);
				a.addEventListener('mouseleave', leave);
				cleanup.push(() => {
					a.removeEventListener('mouseenter', enter);
					a.removeEventListener('mouseleave', leave);
				});
			});
		}

		// Observe DOM changes to reattach after markdown re-renders
		const observer = new MutationObserver(attach);
		observer.observe(node, { childList: true, subtree: true });
		attach();

		return {
			update(newOptions: SourcePreviewOptions) {
				options = newOptions;
				attach();
			},
			destroy() {
				cleanup.forEach((fn) => fn());
				observer.disconnect();
				removeTooltip();
			}
		};
	}
</script>
