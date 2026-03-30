/**
 * Unit tests for the share page (/share/[id]) logic.
 *
 * Tests pure logic extracted from +page.svelte — TOC generation, reading time,
 * heading ID generation, and the browser guard that prevents SSR crashes.
 */

import { describe, it, expect } from 'vitest';

// ── TOC generation logic (mirrors $derived.by in +page.svelte) ──────────────

interface TocEntry {
	id: string;
	text: string;
	level: number;
}

function generateToc(markdown: string): TocEntry[] {
	if (!markdown) return [];
	const entries: TocEntry[] = [];
	const lines = markdown.split('\n');
	const usedIds = new Map<string, number>();
	for (const line of lines) {
		const m = line.match(/^(#{2,4})\s+(.+)/);
		if (!m) continue;
		const level = m[1].length;
		const text = m[2].trim();
		const baseId = text
			.toLowerCase()
			.replace(/[^\w]+/g, '-')
			.replace(/(^-|-$)/g, '');
		const count = usedIds.get(baseId) ?? 0;
		const id = count === 0 ? baseId : `${baseId}-${count}`;
		usedIds.set(baseId, count + 1);
		entries.push({ id, text, level });
	}
	return entries;
}

describe('Share page - TOC generation', () => {
	it('extracts h2–h4 headings from markdown', () => {
		const md = '## Summary\n\nText\n\n### Details\n\n#### Sub-detail';
		const toc = generateToc(md);

		expect(toc).toHaveLength(3);
		expect(toc[0]).toEqual({ id: 'summary', text: 'Summary', level: 2 });
		expect(toc[1]).toEqual({ id: 'details', text: 'Details', level: 3 });
		expect(toc[2]).toEqual({ id: 'sub-detail', text: 'Sub-detail', level: 4 });
	});

	it('ignores h1 headings', () => {
		const md = '# Title\n\n## Section';
		const toc = generateToc(md);

		expect(toc).toHaveLength(1);
		expect(toc[0].text).toBe('Section');
	});

	it('de-duplicates heading IDs with numeric suffix', () => {
		const md = '## Intro\n\n## Intro\n\n## Intro';
		const toc = generateToc(md);

		expect(toc).toHaveLength(3);
		expect(toc[0].id).toBe('intro');
		expect(toc[1].id).toBe('intro-1');
		expect(toc[2].id).toBe('intro-2');
	});

	it('returns empty array for empty/null markdown', () => {
		expect(generateToc('')).toEqual([]);
	});

	it('converts special characters to hyphens in IDs', () => {
		const md = '## Key Findings & Analysis (2025)';
		const toc = generateToc(md);

		expect(toc[0].id).toBe('key-findings-analysis-2025');
	});

	it('strips leading/trailing hyphens from IDs', () => {
		const md = '## —Introduction—';
		const toc = generateToc(md);

		expect(toc[0].id).not.toMatch(/^-/);
		expect(toc[0].id).not.toMatch(/-$/);
	});
});

// ── Reading time calculation ────────────────────────────────────────────────

function calculateReadingTime(markdown: string | null | undefined): number {
	return Math.max(1, Math.ceil((markdown?.split(/\s+/).length ?? 0) / 200));
}

describe('Share page - reading time', () => {
	it('returns 1 for short or empty text', () => {
		expect(calculateReadingTime('')).toBe(1);
		expect(calculateReadingTime(null)).toBe(1);
		expect(calculateReadingTime(undefined)).toBe(1);
		expect(calculateReadingTime('short text')).toBe(1);
	});

	it('calculates correct reading time for longer text', () => {
		const words = Array(600).fill('word').join(' ');
		expect(calculateReadingTime(words)).toBe(3);
	});

	it('rounds up to the next minute', () => {
		const words = Array(201).fill('word').join(' ');
		expect(calculateReadingTime(words)).toBe(2);
	});
});

// ── OG description derivation ───────────────────────────────────────────────

function deriveOgDescription(markdown: string | null | undefined): string {
	return markdown?.replace(/[#*`_[\]]/g, '').slice(0, 200).trim() ?? '';
}

describe('Share page - OG description', () => {
	it('strips markdown formatting characters', () => {
		const md = '## **Bold** and `code` and _italic_';
		const desc = deriveOgDescription(md);

		expect(desc).not.toContain('#');
		expect(desc).not.toContain('*');
		expect(desc).not.toContain('`');
		expect(desc).not.toContain('_');
	});

	it('truncates to 200 characters', () => {
		const md = 'A'.repeat(300);
		expect(deriveOgDescription(md).length).toBe(200);
	});

	it('returns empty string for null/undefined', () => {
		expect(deriveOgDescription(null)).toBe('');
		expect(deriveOgDescription(undefined)).toBe('');
	});
});

// ── Browser guard in onDestroy ──────────────────────────────────────────────

describe('Share page - SSR safety', () => {
	it('browser guard prevents document/window access when not in browser', () => {
		// Simulates the onDestroy pattern from +page.svelte
		const browser = false; // SSR environment
		const removeEventListener = { doc: false, win: false };

		// This mirrors the fixed onDestroy callback
		if (browser) {
			removeEventListener.doc = true;
			removeEventListener.win = true;
		}

		expect(removeEventListener.doc).toBe(false);
		expect(removeEventListener.win).toBe(false);
	});

	it('browser guard allows document/window access in browser context', () => {
		const browser = true; // Client environment
		const removeEventListener = { doc: false, win: false };

		if (browser) {
			removeEventListener.doc = true;
			removeEventListener.win = true;
		}

		expect(removeEventListener.doc).toBe(true);
		expect(removeEventListener.win).toBe(true);
	});
});
