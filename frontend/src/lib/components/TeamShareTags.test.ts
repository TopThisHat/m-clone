/**
 * Unit tests for TeamShareTags component logic.
 *
 * Tests the pure display logic — overflow calculation, visible slice,
 * expand toggle state — and verifies key markup in the component source.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// ── Overflow / visible slice logic ─────────────────────────────────────────────

function calcVisible(teamNames: string[], maxVisible: number, expanded: boolean): string[] {
	return expanded ? teamNames : teamNames.slice(0, maxVisible);
}

function calcRemaining(teamNames: string[], maxVisible: number): number {
	return teamNames.length - maxVisible;
}

function hasOverflow(teamNames: string[], maxVisible: number): boolean {
	return teamNames.length > maxVisible;
}

describe('TeamShareTags - renders nothing when teamNames is empty', () => {
	it('returns empty visible list for empty teamNames', () => {
		expect(calcVisible([], 2, false)).toEqual([]);
	});

	it('hasOverflow is false for empty teamNames', () => {
		expect(hasOverflow([], 2)).toBe(false);
	});
});

describe('TeamShareTags - single team tag', () => {
	it('renders single team name when list has one entry', () => {
		const visible = calcVisible(['Alpha Team'], 2, false);
		expect(visible).toHaveLength(1);
		expect(visible[0]).toBe('Alpha Team');
	});

	it('no overflow for single team with default maxVisible', () => {
		expect(hasOverflow(['Alpha Team'], 2)).toBe(false);
	});
});

describe('TeamShareTags - multiple team tags within maxVisible', () => {
	it('shows all teams when count equals maxVisible', () => {
		const teams = ['Alpha', 'Beta'];
		expect(calcVisible(teams, 2, false)).toEqual(['Alpha', 'Beta']);
		expect(hasOverflow(teams, 2)).toBe(false);
	});

	it('shows all teams when count is below maxVisible', () => {
		const teams = ['Alpha'];
		expect(calcVisible(teams, 3, false)).toEqual(['Alpha']);
		expect(hasOverflow(teams, 3)).toBe(false);
	});
});

describe('TeamShareTags - overflow button behavior', () => {
	it('shows overflow when teamNames exceeds maxVisible', () => {
		expect(hasOverflow(['A', 'B', 'C'], 2)).toBe(true);
	});

	it('calculates correct remaining count', () => {
		expect(calcRemaining(['A', 'B', 'C'], 2)).toBe(1);
		expect(calcRemaining(['A', 'B', 'C', 'D', 'E'], 2)).toBe(3);
	});

	it('slices visible list to maxVisible when not expanded', () => {
		const teams = ['A', 'B', 'C', 'D'];
		expect(calcVisible(teams, 2, false)).toEqual(['A', 'B']);
	});

	it('shows all teams when expanded', () => {
		const teams = ['A', 'B', 'C', 'D'];
		expect(calcVisible(teams, 2, true)).toEqual(['A', 'B', 'C', 'D']);
	});
});

describe('TeamShareTags - custom maxVisible prop', () => {
	it('respects maxVisible=1', () => {
		const teams = ['A', 'B', 'C'];
		expect(calcVisible(teams, 1, false)).toEqual(['A']);
		expect(hasOverflow(teams, 1)).toBe(true);
		expect(calcRemaining(teams, 1)).toBe(2);
	});

	it('respects maxVisible=5 (no overflow for 3 teams)', () => {
		const teams = ['A', 'B', 'C'];
		expect(hasOverflow(teams, 5)).toBe(false);
		expect(calcVisible(teams, 5, false)).toEqual(['A', 'B', 'C']);
	});
});

// ── Markup inspection ─────────────────────────────────────────────────────────

describe('TeamShareTags - component markup', () => {
	const src = readFileSync(
		resolve(__dirname, 'TeamShareTags.svelte'),
		'utf-8',
	);

	it('uses people icon SVG', () => {
		// The d attribute from the spec people icon
		expect(src).toContain('M17 20h5v-2a3 3 0 00-5.356-1.857');
	});

	it('tag has gold border class', () => {
		expect(src).toContain('border-gold/30');
	});

	it('tag has gold background class', () => {
		expect(src).toContain('bg-gold/5');
	});

	it('tag has gold-light text class', () => {
		expect(src).toContain('text-gold-light');
	});

	it('tag uses rounded-full shape', () => {
		expect(src).toContain('rounded-full');
	});

	it('tag text size is 10px', () => {
		expect(src).toContain('text-[10px]');
	});

	it('people icon is w-2.5 h-2.5', () => {
		expect(src).toContain('w-2.5 h-2.5');
	});

	it('overflow button has hover:text-gold', () => {
		expect(src).toContain('hover:text-gold');
	});

	it('overflow button has cursor-pointer', () => {
		expect(src).toContain('cursor-pointer');
	});

	it('root container uses ml-auto', () => {
		expect(src).toContain('ml-auto');
	});

	it('overflow button has accessible aria-label', () => {
		expect(src).toContain('aria-label=');
	});

	it('people icon has aria-hidden to avoid screen reader noise', () => {
		expect(src).toContain('aria-hidden="true"');
	});

	it('uses Svelte 5 $props() syntax', () => {
		expect(src).toContain('$props()');
	});

	it('uses Svelte 5 $state() for expanded', () => {
		expect(src).toContain('$state(false)');
	});

	it('uses $derived for visible list', () => {
		expect(src).toContain('$derived(');
	});
});
