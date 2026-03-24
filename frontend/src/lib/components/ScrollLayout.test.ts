import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

/**
 * Verify scroll/overflow CSS conventions across the frontend.
 *
 * These tests enforce two patterns established in commit 7d1fb9d:
 * 1. Page-level table containers use responsive max-height breakpoints
 * 2. All flex-1 overflow-y-auto containers include min-h-0
 */

function readComponent(relPath: string): string {
	return readFileSync(resolve(__dirname, '..', '..', relPath), 'utf-8');
}

describe('Scroll layout conventions', () => {
	describe('Scout table containers use responsive max-height', () => {
		it('entities page table uses responsive max-h breakpoints', () => {
			const src = readComponent('routes/(scout)/entities/+page.svelte');
			expect(src).toContain('max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]');
			// Must NOT have standalone max-h-[60vh] without responsive prefix
			const standaloneMaxH = src.match(/(?<!sm:)(?<!lg:)max-h-\[60vh\](?!\s*sm:)/g);
			expect(standaloneMaxH).toBeNull();
		});

		it('attributes page table uses responsive max-h breakpoints', () => {
			const src = readComponent('routes/(scout)/attributes/+page.svelte');
			expect(src).toContain('max-h-[50vh] sm:max-h-[60vh] lg:max-h-[70vh]');
			const standaloneMaxH = src.match(/(?<!sm:)(?<!lg:)max-h-\[60vh\](?!\s*sm:)/g);
			expect(standaloneMaxH).toBeNull();
		});
	});

	describe('Flex scroll containers include min-h-0', () => {
		it('SessionSidebar has min-h-0 on its scroll container', () => {
			const src = readComponent('lib/components/SessionSidebar.svelte');
			// Find lines with flex-1 and overflow-y-auto — they must also have min-h-0
			const scrollLines = src.split('\n').filter(
				(line) => line.includes('flex-1') && line.includes('overflow-y-auto')
			);
			expect(scrollLines.length).toBeGreaterThan(0);
			for (const line of scrollLines) {
				expect(line).toContain('min-h-0');
			}
		});

		it('RulesPanel has min-h-0 on its scroll container', () => {
			const src = readComponent('lib/components/RulesPanel.svelte');
			const scrollLines = src.split('\n').filter(
				(line) => line.includes('flex-1') && line.includes('overflow-y-auto')
			);
			expect(scrollLines.length).toBeGreaterThan(0);
			for (const line of scrollLines) {
				expect(line).toContain('min-h-0');
			}
		});

		it('TracePanel area on main page has min-h-0', () => {
			const src = readComponent('routes/+page.svelte');
			const scrollLines = src.split('\n').filter(
				(line) => line.includes('flex-1') && line.includes('overflow-y-auto')
			);
			expect(scrollLines.length).toBeGreaterThan(0);
			for (const line of scrollLines) {
				expect(line).toContain('min-h-0');
			}
		});

		it('CommentThread has min-h-0 on its scroll container', () => {
			const src = readComponent('lib/components/CommentThread.svelte');
			const scrollLines = src.split('\n').filter(
				(line) => line.includes('flex-1') && line.includes('overflow-y-auto')
			);
			expect(scrollLines.length).toBeGreaterThan(0);
			for (const line of scrollLines) {
				expect(line).toContain('min-h-0');
			}
		});
	});

	describe('No regressions across codebase', () => {
		const componentFiles = [
			'lib/components/SessionSidebar.svelte',
			'lib/components/RulesPanel.svelte',
			'lib/components/CommentThread.svelte',
			'routes/+page.svelte',
		];

		it('no flex-1 overflow-y-auto without min-h-0 in key components', () => {
			for (const file of componentFiles) {
				const src = readComponent(file);
				const lines = src.split('\n');
				for (let i = 0; i < lines.length; i++) {
					const line = lines[i];
					if (line.includes('flex-1') && line.includes('overflow-y-auto')) {
						expect(
							line.includes('min-h-0'),
							`${file}:${i + 1} has flex-1 overflow-y-auto without min-h-0`
						).toBe(true);
					}
				}
			}
		});
	});
});
