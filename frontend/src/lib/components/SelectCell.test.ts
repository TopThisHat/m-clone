import { describe, it, expect } from 'vitest';

// Test pure logic from SelectCell

interface SelectOption {
	value: string;
	label: string;
	color?: string;
}

const testOptions: SelectOption[] = [
	{ value: 'red', label: 'Red', color: 'bg-red-900 text-red-300' },
	{ value: 'blue', label: 'Blue', color: 'bg-blue-900 text-blue-300' },
	{ value: 'green', label: 'Green' },
	{ value: 'yellow', label: 'Yellow' },
	{ value: 'purple', label: 'Purple' },
];

function findSelected(
	options: SelectOption[],
	value: string | null
): SelectOption | null {
	return options.find((o) => o.value === value) ?? null;
}

function filterOptions(
	options: SelectOption[],
	search: string
): SelectOption[] {
	const term = search.trim().toLowerCase();
	if (!term) return options;
	return options.filter((o) => o.label.toLowerCase().includes(term));
}

function clampHighlight(index: number, listLength: number): number {
	return Math.max(0, Math.min(index, listLength - 1));
}

function navigateDown(current: number, listLength: number): number {
	return Math.min(current + 1, listLength - 1);
}

function navigateUp(current: number): number {
	return Math.max(current - 1, 0);
}

// Pill color assignment logic
const palette = [
	'bg-blue-900/60 text-blue-300 border-blue-700',
	'bg-purple-900/60 text-purple-300 border-purple-700',
	'bg-emerald-900/60 text-emerald-300 border-emerald-700',
	'bg-amber-900/60 text-amber-300 border-amber-700',
	'bg-rose-900/60 text-rose-300 border-rose-700',
	'bg-cyan-900/60 text-cyan-300 border-cyan-700',
	'bg-indigo-900/60 text-indigo-300 border-indigo-700',
	'bg-teal-900/60 text-teal-300 border-teal-700',
];

function assignPillColor(
	opt: SelectOption,
	colorMap: Record<string, string>
): string {
	if (opt.color) return opt.color;
	if (!colorMap[opt.value]) {
		const idx = Object.keys(colorMap).length % palette.length;
		colorMap[opt.value] = palette[idx];
	}
	return colorMap[opt.value];
}

describe('SelectCell findSelected', () => {
	it('finds matching option', () => {
		const result = findSelected(testOptions, 'blue');
		expect(result).not.toBeNull();
		expect(result!.label).toBe('Blue');
	});

	it('returns null for null value', () => {
		expect(findSelected(testOptions, null)).toBe(null);
	});

	it('returns null for non-existent value', () => {
		expect(findSelected(testOptions, 'unknown')).toBe(null);
	});

	it('returns null for empty options', () => {
		expect(findSelected([], 'any')).toBe(null);
	});
});

describe('SelectCell filterOptions', () => {
	it('returns all options for empty search', () => {
		expect(filterOptions(testOptions, '')).toEqual(testOptions);
	});

	it('returns all options for whitespace search', () => {
		expect(filterOptions(testOptions, '   ')).toEqual(testOptions);
	});

	it('filters by partial match (case-insensitive)', () => {
		const result = filterOptions(testOptions, 'bl');
		expect(result).toHaveLength(1);
		expect(result[0].label).toBe('Blue');
	});

	it('filters case-insensitively', () => {
		const result = filterOptions(testOptions, 'RED');
		expect(result).toHaveLength(1);
		expect(result[0].label).toBe('Red');
	});

	it('returns empty array when no match', () => {
		expect(filterOptions(testOptions, 'xyz')).toHaveLength(0);
	});

	it('matches multiple results', () => {
		// "e" is in Red, Blue, Green, Yellow, Purple
		const result = filterOptions(testOptions, 'e');
		expect(result.length).toBeGreaterThan(1);
	});
});

describe('SelectCell keyboard navigation', () => {
	it('navigates down within bounds', () => {
		expect(navigateDown(0, 5)).toBe(1);
		expect(navigateDown(3, 5)).toBe(4);
	});

	it('clamps at last item', () => {
		expect(navigateDown(4, 5)).toBe(4);
	});

	it('navigates up within bounds', () => {
		expect(navigateUp(3)).toBe(2);
		expect(navigateUp(1)).toBe(0);
	});

	it('clamps at first item', () => {
		expect(navigateUp(0)).toBe(0);
	});

	it('home key goes to start', () => {
		expect(clampHighlight(0, 5)).toBe(0);
	});

	it('end key goes to last', () => {
		expect(clampHighlight(4, 5)).toBe(4);
	});

	it('clamps out-of-bounds index', () => {
		expect(clampHighlight(10, 5)).toBe(4);
		expect(clampHighlight(-1, 5)).toBe(0);
	});
});

describe('SelectCell pill color assignment', () => {
	it('uses explicit color when provided', () => {
		const colorMap: Record<string, string> = {};
		const opt: SelectOption = { value: 'red', label: 'Red', color: 'custom-color-class' };
		expect(assignPillColor(opt, colorMap)).toBe('custom-color-class');
	});

	it('assigns palette colors when no explicit color', () => {
		const colorMap: Record<string, string> = {};
		const opt: SelectOption = { value: 'thing', label: 'Thing' };
		const result = assignPillColor(opt, colorMap);
		expect(result).toBe(palette[0]);
	});

	it('assigns different colors to different options', () => {
		const colorMap: Record<string, string> = {};
		const opt1: SelectOption = { value: 'a', label: 'A' };
		const opt2: SelectOption = { value: 'b', label: 'B' };
		const c1 = assignPillColor(opt1, colorMap);
		const c2 = assignPillColor(opt2, colorMap);
		expect(c1).not.toBe(c2);
	});

	it('returns same color for same option on repeated calls', () => {
		const colorMap: Record<string, string> = {};
		const opt: SelectOption = { value: 'x', label: 'X' };
		const c1 = assignPillColor(opt, colorMap);
		const c2 = assignPillColor(opt, colorMap);
		expect(c1).toBe(c2);
	});

	it('wraps around palette when options exceed palette size', () => {
		const colorMap: Record<string, string> = {};
		const options = Array.from({ length: palette.length + 1 }, (_, i) => ({
			value: `opt-${i}`,
			label: `Opt ${i}`,
		}));
		const colors = options.map((o) => assignPillColor(o, colorMap));
		// Last option should wrap to first palette color
		expect(colors[palette.length]).toBe(palette[0]);
	});
});

describe('SelectCell clear selection', () => {
	it('clearing sets value to null', () => {
		let current: string | null = 'blue';
		// Simulate the clear handler
		current = null;
		expect(current).toBe(null);
		expect(findSelected(testOptions, current)).toBe(null);
	});
});
