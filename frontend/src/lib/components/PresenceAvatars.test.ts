/**
 * Unit tests for PresenceAvatars logic.
 *
 * PresenceAvatars renders a row of avatar circles with accessible tooltips.
 * These tests cover the pure helper functions and display rules extracted
 * from the component without mounting the DOM.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// ── initials() logic ──────────────────────────────────────────────────────────

function initials(name: string): string {
	return name
		.split(' ')
		.slice(0, 2)
		.map((w) => w[0]?.toUpperCase() ?? '')
		.join('');
}

describe('PresenceAvatars - initials()', () => {
	it('returns first letter of single name', () => {
		expect(initials('Alice')).toBe('A');
	});

	it('returns first letters of first two words', () => {
		expect(initials('Alice Smith')).toBe('AS');
	});

	it('uppercases both initials', () => {
		expect(initials('alice smith')).toBe('AS');
	});

	it('ignores words beyond the second', () => {
		expect(initials('Alice Smith Jones')).toBe('AS');
	});

	it('handles empty string gracefully', () => {
		expect(initials('')).toBe('');
	});

	it('handles single-character name', () => {
		expect(initials('A')).toBe('A');
	});
});

// ── overflow calculation ──────────────────────────────────────────────────────

const MAX_SHOWN = 4;

function calcOverflow(viewerCount: number): number {
	return Math.max(0, viewerCount - MAX_SHOWN);
}

function getShown<T>(viewers: T[]): T[] {
	return viewers.slice(0, MAX_SHOWN);
}

describe('PresenceAvatars - overflow display', () => {
	it('shows no overflow when viewers count is at or below MAX_SHOWN', () => {
		expect(calcOverflow(0)).toBe(0);
		expect(calcOverflow(1)).toBe(0);
		expect(calcOverflow(4)).toBe(0);
	});

	it('calculates overflow for more than MAX_SHOWN viewers', () => {
		expect(calcOverflow(5)).toBe(1);
		expect(calcOverflow(10)).toBe(6);
	});

	it('slices shown list to MAX_SHOWN', () => {
		const viewers = ['a', 'b', 'c', 'd', 'e', 'f'];
		expect(getShown(viewers)).toHaveLength(4);
		expect(getShown(viewers)).toEqual(['a', 'b', 'c', 'd']);
	});

	it('returns all viewers when count is below MAX_SHOWN', () => {
		const viewers = ['a', 'b'];
		expect(getShown(viewers)).toHaveLength(2);
	});
});

// ── Accessibility attributes in component source ──────────────────────────────

describe('PresenceAvatars - accessibility markup', () => {
	const src = readFileSync(
		resolve(__dirname, 'PresenceAvatars.svelte'),
		'utf-8',
	);

	it('avatar wrapper has role="img"', () => {
		expect(src).toContain('role="img"');
	});

	it('avatar wrapper has aria-label for the viewer name', () => {
		expect(src).toContain('aria-label={viewer.display_name}');
	});

	it('avatar wrapper has tabindex="0" for keyboard access', () => {
		expect(src).toContain('tabindex="0"');
	});

	it('tooltip appears on group-focus-within (keyboard) as well as hover', () => {
		expect(src).toContain('group-focus-within:opacity-100');
	});

	it('tooltip is pointer-events-none so it does not block interaction', () => {
		expect(src).toContain('pointer-events-none');
	});

	it('outer container has a descriptive title listing all viewer names', () => {
		// The container div has title="{viewers.map(v => v.display_name)...} viewing"
		expect(src).toMatch(/title=.+viewing/);
	});

	it('avatar image has an alt attribute', () => {
		expect(src).toContain('alt={viewer.display_name}');
	});
});

// ── "you" indicator logic ─────────────────────────────────────────────────────

describe('PresenceAvatars - current user indicator', () => {
	function tooltipText(displayName: string, isSelf: boolean): string {
		return `${displayName}${isSelf ? ' (you)' : ''}`;
	}

	it('appends "(you)" for the current user', () => {
		expect(tooltipText('Alice', true)).toBe('Alice (you)');
	});

	it('does not append "(you)" for other users', () => {
		expect(tooltipText('Bob', false)).toBe('Bob');
	});
});
