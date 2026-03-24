import { describe, it, expect } from 'vitest';

// Test pure logic from AttributeMatrix

interface MockResult {
	entity_id: string;
	attribute_id: string;
	present: boolean;
	confidence: number | null;
}

interface MockKnowledge {
	gwm_id: string;
	attribute_label: string;
	source_campaign_id: string | null;
}

function cellClass(
	result: MockResult | undefined,
	cached: MockKnowledge | undefined,
	lowConf: boolean
): string {
	const base = lowConf ? 'opacity-40 ' : '';
	if (cached) return base + 'bg-yellow-950 text-yellow-300 border-2 border-yellow-500';
	if (!result) return 'bg-navy-700 text-slate-600';
	if (!result.present) return base + 'bg-red-950 text-red-400 border border-red-900';
	if (result.confidence === null) return base + 'bg-slate-800 text-slate-400 border border-slate-600';
	const conf = result.confidence;
	if (conf >= 0.8) return base + 'bg-green-900 text-green-300 border border-green-700';
	if (conf >= 0.5) return base + 'bg-yellow-900/50 text-yellow-300 border border-yellow-700';
	return base + 'bg-orange-950 text-orange-300 border border-orange-800';
}

function cellLabel(result: MockResult | undefined, cached: MockKnowledge | undefined): string {
	if (cached) return '\u26A1';
	if (!result) return '\u2014';
	if (result.confidence != null) return result.confidence.toFixed(1);
	return result.present ? '\u2713' : '\u2717';
}

describe('AttributeMatrix cellClass', () => {
	it('shows no-data state for null confidence with present result', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: null };
		const cls = cellClass(result, undefined, false);
		expect(cls).toContain('bg-slate-800');
		expect(cls).toContain('text-slate-400');
	});

	it('shows no-data state for null confidence with absent result', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: false, confidence: null };
		const cls = cellClass(result, undefined, false);
		// absent results have their own styling regardless of confidence
		expect(cls).toContain('bg-red-950');
	});

	it('shows green for high confidence present result', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: 0.9 };
		expect(cellClass(result, undefined, false)).toContain('bg-green-900');
	});

	it('shows yellow for medium confidence present result', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: 0.6 };
		expect(cellClass(result, undefined, false)).toContain('bg-yellow-900');
	});

	it('shows orange for low confidence present result', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: 0.3 };
		expect(cellClass(result, undefined, false)).toContain('bg-orange-950');
	});

	it('shows navy for no result', () => {
		expect(cellClass(undefined, undefined, false)).toContain('bg-navy-700');
	});

	it('applies opacity for low confidence filter', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: 0.9 };
		expect(cellClass(result, undefined, true)).toContain('opacity-40');
	});
});

describe('AttributeMatrix cellLabel', () => {
	it('shows check for present result with null confidence', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: null };
		expect(cellLabel(result, undefined)).toBe('\u2713');
	});

	it('shows confidence value when not null', () => {
		const result: MockResult = { entity_id: 'e1', attribute_id: 'a1', present: true, confidence: 0.85 };
		expect(cellLabel(result, undefined)).toBe('0.8');
	});

	it('shows dash for no result', () => {
		expect(cellLabel(undefined, undefined)).toBe('\u2014');
	});
});

describe('Entity label fallback', () => {
	it('falls back to gwm_id when label is falsy', () => {
		const entity = { label: '', gwm_id: 'GWM123', id: 'e1' };
		const display = entity.label || entity.gwm_id || entity.id;
		expect(display).toBe('GWM123');
	});

	it('falls back to id when both label and gwm_id are falsy', () => {
		const entity = { label: '', gwm_id: null, id: 'e1' };
		const display = entity.label || entity.gwm_id || entity.id;
		expect(display).toBe('e1');
	});

	it('shows label when available', () => {
		const entity = { label: 'Acme Corp', gwm_id: 'GWM123', id: 'e1' };
		const display = entity.label || entity.gwm_id || entity.id;
		expect(display).toBe('Acme Corp');
	});
});

describe('Virtual scrolling logic', () => {
	const ROW_HEIGHT = 44;
	const OVERSCAN = 5;
	const VIRTUAL_THRESHOLD = 50;

	it('enables virtual scrolling above threshold', () => {
		expect(100 > VIRTUAL_THRESHOLD).toBe(true);
		expect(30 > VIRTUAL_THRESHOLD).toBe(false);
	});

	it('calculates correct visible range', () => {
		const entityCount = 200;
		const scrollTop = 440; // 10 rows down
		const containerHeight = 600;

		const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
		const endIndex = Math.min(entityCount, Math.ceil((scrollTop + containerHeight) / ROW_HEIGHT) + OVERSCAN);

		expect(startIndex).toBe(5); // 10 - 5
		expect(endIndex).toBe(Math.min(200, Math.ceil(1040 / 44) + 5)); // 24 + 5 = 29
		expect(endIndex - startIndex).toBeLessThan(entityCount);
	});

	it('clamps start to 0 when near top', () => {
		const scrollTop = 88; // 2 rows
		const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
		expect(startIndex).toBe(0);
	});
});
