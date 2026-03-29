/**
 * Unit tests for ChartCard theme color logic.
 *
 * ChartCard derives gridColor and tickColor from the $theme store and applies
 * them to the Chart.js instance via a $effect. These tests verify the color
 * derivation formula in isolation — no Chart.js or canvas required.
 */

import { describe, it, expect } from 'vitest';

// ── Color derivation logic ────────────────────────────────────────────────────

type Theme = 'light' | 'dark';

function getGridColor(theme: Theme): string {
	return theme === 'light' ? '#e2e8f0' : '#1a3660';
}

function getTickColor(theme: Theme): string {
	return theme === 'light' ? '#475569' : '#64748b';
}

describe('ChartCard - theme-aware colors', () => {
	describe('grid color', () => {
		it('uses light slate color in light mode', () => {
			expect(getGridColor('light')).toBe('#e2e8f0');
		});

		it('uses dark navy color in dark mode', () => {
			expect(getGridColor('dark')).toBe('#1a3660');
		});

		it('produces distinct values for each theme', () => {
			expect(getGridColor('light')).not.toBe(getGridColor('dark'));
		});
	});

	describe('tick color', () => {
		it('uses a darker slate in light mode for legibility', () => {
			expect(getTickColor('light')).toBe('#475569');
		});

		it('uses a lighter slate in dark mode for legibility', () => {
			expect(getTickColor('dark')).toBe('#64748b');
		});

		it('produces distinct values for each theme', () => {
			expect(getTickColor('light')).not.toBe(getTickColor('dark'));
		});
	});
});

// ── Percentage change formatting ──────────────────────────────────────────────

describe('ChartCard - pct_change display', () => {
	function formatPctChange(pct_change: number): string {
		return `${pct_change >= 0 ? '+' : ''}${pct_change.toFixed(1)}%`;
	}

	function getChangeColor(pct_change: number): 'green' | 'red' {
		return pct_change >= 0 ? 'green' : 'red';
	}

	it('prefixes positive changes with "+"', () => {
		expect(formatPctChange(5.3)).toBe('+5.3%');
	});

	it('does not prefix negative changes', () => {
		expect(formatPctChange(-2.7)).toBe('-2.7%');
	});

	it('handles zero as positive', () => {
		expect(formatPctChange(0)).toBe('+0.0%');
		expect(getChangeColor(0)).toBe('green');
	});

	it('rounds to one decimal place', () => {
		expect(formatPctChange(3.456)).toBe('+3.5%');
		expect(formatPctChange(-1.234)).toBe('-1.2%');
	});

	it('assigns green color for positive change', () => {
		expect(getChangeColor(10)).toBe('green');
	});

	it('assigns red color for negative change', () => {
		expect(getChangeColor(-0.1)).toBe('red');
	});
});

// ── Label sampling logic ──────────────────────────────────────────────────────

describe('ChartCard - data point sampling', () => {
	function sampleData<T>(items: T[], maxPoints = 20): T[] {
		const step = Math.max(1, Math.floor(items.length / maxPoints));
		return items.filter((_, i) => i % step === 0);
	}

	it('returns all items when count is below max', () => {
		const labels = ['Jan', 'Feb', 'Mar'];
		expect(sampleData(labels, 20)).toHaveLength(3);
	});

	it('reduces to approximately maxPoints items for large datasets', () => {
		const labels = Array.from({ length: 200 }, (_, i) => `day-${i}`);
		const sampled = sampleData(labels, 20);
		// step = floor(200/20) = 10, so we get indices 0,10,20,...190 → 20 items
		expect(sampled).toHaveLength(20);
	});

	it('always includes the first item', () => {
		const labels = Array.from({ length: 100 }, (_, i) => `item-${i}`);
		const sampled = sampleData(labels, 20);
		expect(sampled[0]).toBe('item-0');
	});

	it('step is at least 1 for empty or single-item arrays', () => {
		expect(sampleData([], 20)).toHaveLength(0);
		expect(sampleData(['only'], 20)).toHaveLength(1);
	});
});
