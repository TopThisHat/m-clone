import { describe, it, expect } from 'vitest';

// Test pure logic from NumericCell

function parseDraft(draft: string): number | null | undefined {
	if (draft.trim() === '') return null;
	const n = Number(draft);
	return Number.isNaN(n) ? undefined : n;
}

function validateValue(
	draft: string,
	min?: number,
	max?: number
): string | null {
	const parsed = parseDraft(draft);
	if (parsed === undefined) return 'Invalid number';
	if (parsed === null) return null; // empty is valid (clears value)
	if (min !== undefined && parsed < min) return `Min: ${min}`;
	if (max !== undefined && parsed > max) return `Max: ${max}`;
	return null;
}

function shouldSave(
	draft: string,
	currentValue: number | null,
	min?: number,
	max?: number
): boolean {
	const error = validateValue(draft, min, max);
	if (error !== null) return false;
	const parsed = parseDraft(draft);
	const newVal = parsed === undefined ? null : parsed;
	return newVal !== currentValue;
}

describe('NumericCell parseDraft', () => {
	it('returns null for empty string', () => {
		expect(parseDraft('')).toBe(null);
	});

	it('returns null for whitespace', () => {
		expect(parseDraft('   ')).toBe(null);
	});

	it('parses integer strings', () => {
		expect(parseDraft('42')).toBe(42);
	});

	it('parses decimal strings', () => {
		expect(parseDraft('3.14')).toBe(3.14);
	});

	it('parses negative numbers', () => {
		expect(parseDraft('-10')).toBe(-10);
	});

	it('returns undefined for non-numeric input', () => {
		expect(parseDraft('abc')).toBe(undefined);
	});

	it('returns undefined for mixed input', () => {
		expect(parseDraft('12abc')).toBe(undefined);
	});

	it('parses zero', () => {
		expect(parseDraft('0')).toBe(0);
	});

	it('parses scientific notation', () => {
		expect(parseDraft('1e3')).toBe(1000);
	});
});

describe('NumericCell validateValue', () => {
	it('returns null for valid number within bounds', () => {
		expect(validateValue('50', 0, 100)).toBe(null);
	});

	it('returns error for non-numeric input', () => {
		expect(validateValue('abc')).toBe('Invalid number');
	});

	it('returns null for empty input (cleared value)', () => {
		expect(validateValue('')).toBe(null);
	});

	it('returns min error when below minimum', () => {
		expect(validateValue('-5', 0, 100)).toBe('Min: 0');
	});

	it('returns max error when above maximum', () => {
		expect(validateValue('200', 0, 100)).toBe('Max: 100');
	});

	it('allows exact min value', () => {
		expect(validateValue('0', 0, 100)).toBe(null);
	});

	it('allows exact max value', () => {
		expect(validateValue('100', 0, 100)).toBe(null);
	});

	it('allows any number when no bounds set', () => {
		expect(validateValue('999999')).toBe(null);
		expect(validateValue('-999999')).toBe(null);
	});

	it('validates with only min bound', () => {
		expect(validateValue('-1', 0)).toBe('Min: 0');
		expect(validateValue('5', 0)).toBe(null);
	});

	it('validates with only max bound', () => {
		expect(validateValue('101', undefined, 100)).toBe('Max: 100');
		expect(validateValue('50', undefined, 100)).toBe(null);
	});
});

describe('NumericCell shouldSave', () => {
	it('blocks save when validation fails', () => {
		expect(shouldSave('abc', null)).toBe(false);
	});

	it('blocks save when below minimum', () => {
		expect(shouldSave('-5', null, 0, 100)).toBe(false);
	});

	it('detects value change', () => {
		expect(shouldSave('42', null, 0, 100)).toBe(true);
	});

	it('does not save when value is unchanged', () => {
		expect(shouldSave('42', 42)).toBe(false);
	});

	it('saves when clearing value', () => {
		expect(shouldSave('', 42)).toBe(true);
	});

	it('saves when setting value from null', () => {
		expect(shouldSave('10', null)).toBe(true);
	});
});

describe('NumericCell display', () => {
	it('shows empty string for null value', () => {
		const value: number | null = null;
		const display = value !== null ? String(value) : '';
		expect(display).toBe('');
	});

	it('shows stringified number for non-null value', () => {
		const value: number | null = 42;
		const display = value !== null ? String(value) : '';
		expect(display).toBe('42');
	});

	it('shows "0" for zero value', () => {
		const value: number | null = 0;
		const display = value !== null ? String(value) : '';
		expect(display).toBe('0');
	});
});
