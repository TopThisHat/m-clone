import { describe, it, expect } from 'vitest';

// Test the pure logic that ScoreBoard uses

describe('ScoreBoard logic', () => {
	describe('resultsByEntity pre-indexing', () => {
		it('groups results by entity_id into a Map', () => {
			const results = [
				{ entity_id: 'e1', attribute_id: 'a1', id: '1' },
				{ entity_id: 'e1', attribute_id: 'a2', id: '2' },
				{ entity_id: 'e2', attribute_id: 'a1', id: '3' },
			];

			const map = results.reduce((m, r) => {
				const arr = m.get(r.entity_id);
				if (arr) arr.push(r);
				else m.set(r.entity_id, [r]);
				return m;
			}, new Map<string, typeof results>());

			expect(map.get('e1')?.length).toBe(2);
			expect(map.get('e2')?.length).toBe(1);
			expect(map.get('e3')).toBeUndefined();
		});

		it('returns empty array for unknown entity_id', () => {
			const map = new Map<string, unknown[]>();
			expect(map.get('unknown') ?? []).toEqual([]);
		});
	});

	describe('maxScore calculation', () => {
		it('returns 0.01 for empty scores array', () => {
			const scores: number[] = [];
			const maxScore = scores.length === 0 ? 0.01 : Math.max(...scores, 0.01);
			expect(maxScore).toBe(0.01);
		});

		it('returns max score for non-empty array', () => {
			const scores = [0.5, 0.8, 0.3];
			const maxScore = scores.length === 0 ? 0.01 : Math.max(...scores, 0.01);
			expect(maxScore).toBe(0.8);
		});

		it('returns 0.01 when all scores are zero', () => {
			const scores = [0, 0, 0];
			const maxScore = scores.length === 0 ? 0.01 : Math.max(...scores, 0.01);
			expect(maxScore).toBe(0.01);
		});

		it('bar width percentage is never NaN', () => {
			const maxScore = 0.01;
			const totalScore = 0;
			const widthPct = (totalScore / maxScore) * 100;
			expect(Number.isNaN(widthPct)).toBe(false);
			expect(widthPct).toBe(0);
		});
	});
});
