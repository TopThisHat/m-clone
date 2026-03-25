import { describe, it, expect } from 'vitest';

// Test pure logic from TextCell

const MAX_LENGTH = 500;

function remaining(draft: string): number {
	return MAX_LENGTH - draft.length;
}

function overLimit(draft: string): boolean {
	return draft.length > MAX_LENGTH;
}

function shouldSave(draft: string, currentValue: string): boolean {
	if (overLimit(draft)) return false;
	const trimmed = draft.trim();
	return trimmed !== currentValue;
}

describe('TextCell remaining characters', () => {
	it('returns 500 for empty string', () => {
		expect(remaining('')).toBe(500);
	});

	it('returns correct count for partial text', () => {
		expect(remaining('hello')).toBe(495);
	});

	it('returns 0 at exactly 500 characters', () => {
		expect(remaining('a'.repeat(500))).toBe(0);
	});

	it('returns negative when over limit', () => {
		expect(remaining('a'.repeat(501))).toBe(-1);
	});
});

describe('TextCell overLimit', () => {
	it('returns false for empty string', () => {
		expect(overLimit('')).toBe(false);
	});

	it('returns false at exactly 500 characters', () => {
		expect(overLimit('a'.repeat(500))).toBe(false);
	});

	it('returns true for 501 characters', () => {
		expect(overLimit('a'.repeat(501))).toBe(true);
	});
});

describe('TextCell shouldSave', () => {
	it('blocks save when over limit', () => {
		const longText = 'a'.repeat(501);
		expect(shouldSave(longText, '')).toBe(false);
	});

	it('detects change from original value', () => {
		expect(shouldSave('new value', 'old value')).toBe(true);
	});

	it('does not save when trimmed value is same', () => {
		expect(shouldSave('  hello  ', 'hello')).toBe(false);
	});

	it('does not save when value is unchanged', () => {
		expect(shouldSave('same', 'same')).toBe(false);
	});

	it('saves when value changes from empty', () => {
		expect(shouldSave('new', '')).toBe(true);
	});

	it('saves when value changes to empty', () => {
		expect(shouldSave('', 'old')).toBe(true);
	});

	it('trims whitespace before comparison', () => {
		expect(shouldSave('  ', '')).toBe(false);
	});
});

describe('TextCell display logic', () => {
	it('shows placeholder when value is empty', () => {
		const value = '';
		const placeholder = 'Enter text...';
		const display = value || placeholder;
		expect(display).toBe('Enter text...');
	});

	it('shows value when present', () => {
		const value = 'Hello world';
		const placeholder = 'Enter text...';
		const display = value || placeholder;
		expect(display).toBe('Hello world');
	});
});

describe('TextCell character count threshold', () => {
	it('shows warning color when remaining <= 50', () => {
		const rem = remaining('a'.repeat(451));
		expect(rem).toBe(49);
		expect(rem <= 50).toBe(true);
	});

	it('shows normal color when remaining > 50', () => {
		const rem = remaining('a'.repeat(400));
		expect(rem).toBe(100);
		expect(rem <= 50).toBe(false);
	});
});
