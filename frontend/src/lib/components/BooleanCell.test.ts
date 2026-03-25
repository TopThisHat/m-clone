import { describe, it, expect } from 'vitest';

// Test pure logic from BooleanCell

type TriState = boolean | null;

function triStateToggle(current: TriState): TriState {
	if (current === null) return true;
	if (current === true) return false;
	return null;
}

function ariaChecked(value: TriState): 'true' | 'false' | 'mixed' {
	if (value === null) return 'mixed';
	return value ? 'true' : 'false';
}

function stateLabel(value: TriState): string {
	if (value === null) return 'indeterminate';
	return value ? 'checked' : 'unchecked';
}

function buildAriaLabel(label: string, value: TriState): string {
	const state = stateLabel(value);
	return label ? `${label}: ${state}` : state;
}

describe('BooleanCell tri-state toggle', () => {
	it('toggles null -> true', () => {
		expect(triStateToggle(null)).toBe(true);
	});

	it('toggles true -> false', () => {
		expect(triStateToggle(true)).toBe(false);
	});

	it('toggles false -> null', () => {
		expect(triStateToggle(false)).toBe(null);
	});

	it('completes full cycle', () => {
		let state: TriState = null;
		state = triStateToggle(state); // true
		expect(state).toBe(true);
		state = triStateToggle(state); // false
		expect(state).toBe(false);
		state = triStateToggle(state); // null
		expect(state).toBe(null);
	});

	it('always returns one of three states', () => {
		const results = new Set([
			triStateToggle(null),
			triStateToggle(true),
			triStateToggle(false),
		]);
		expect(results).toEqual(new Set([true, false, null]));
	});
});

describe('BooleanCell ariaChecked', () => {
	it('returns "mixed" for null', () => {
		expect(ariaChecked(null)).toBe('mixed');
	});

	it('returns "true" for true', () => {
		expect(ariaChecked(true)).toBe('true');
	});

	it('returns "false" for false', () => {
		expect(ariaChecked(false)).toBe('false');
	});
});

describe('BooleanCell stateLabel', () => {
	it('returns "indeterminate" for null', () => {
		expect(stateLabel(null)).toBe('indeterminate');
	});

	it('returns "checked" for true', () => {
		expect(stateLabel(true)).toBe('checked');
	});

	it('returns "unchecked" for false', () => {
		expect(stateLabel(false)).toBe('unchecked');
	});
});

describe('BooleanCell aria-label', () => {
	it('includes label and state when label is provided', () => {
		expect(buildAriaLabel('Active', true)).toBe('Active: checked');
	});

	it('shows only state when no label', () => {
		expect(buildAriaLabel('', null)).toBe('indeterminate');
	});

	it('handles false with label', () => {
		expect(buildAriaLabel('Verified', false)).toBe('Verified: unchecked');
	});
});
