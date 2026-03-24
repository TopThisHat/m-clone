import { describe, it, expect } from 'vitest';

describe('JobProgress logic', () => {
	describe('percentage calculation', () => {
		it('returns 0 when total_pairs is 0', () => {
			const total_pairs = 0;
			const completed_pairs = 0;
			const pct =
				typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
					? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
					: 0;
			expect(pct).toBe(0);
		});

		it('returns correct percentage', () => {
			const total_pairs = 100;
			const completed_pairs = 75;
			const pct =
				typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
					? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
					: 0;
			expect(pct).toBe(75);
		});

		it('caps at 100%', () => {
			const total_pairs = 50;
			const completed_pairs = 55; // edge case: completed > total
			const pct =
				typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
					? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
					: 0;
			expect(pct).toBe(100);
		});

		it('returns 0 for null total_pairs', () => {
			const total_pairs = null as unknown as number;
			const completed_pairs = 10;
			const pct =
				typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
					? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
					: 0;
			expect(pct).toBe(0);
		});

		it('returns 0 for undefined completed_pairs', () => {
			const total_pairs = 100;
			const completed_pairs = undefined as unknown as number;
			const pct =
				typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
					? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
					: 0;
			expect(pct).toBe(0);
		});

		it('never produces NaN', () => {
			const cases = [
				{ total: 0, completed: 0 },
				{ total: null, completed: 5 },
				{ total: 100, completed: null },
				{ total: undefined, completed: undefined },
				{ total: -1, completed: 5 },
			];
			for (const c of cases) {
				const total_pairs = c.total as unknown as number;
				const completed_pairs = c.completed as unknown as number;
				const pct =
					typeof total_pairs === 'number' && total_pairs > 0 && typeof completed_pairs === 'number'
						? Math.min(100, Math.round((completed_pairs / total_pairs) * 100))
						: 0;
				expect(Number.isNaN(pct)).toBe(false);
			}
		});
	});

	describe('queued timeout', () => {
		const QUEUED_TIMEOUT_MS = 5 * 60 * 1000;

		it('detects stuck job after 5 minutes', () => {
			const queuedSince = Date.now() - QUEUED_TIMEOUT_MS - 1;
			expect(Date.now() - queuedSince >= QUEUED_TIMEOUT_MS).toBe(true);
		});

		it('does not flag job as stuck within 5 minutes', () => {
			const queuedSince = Date.now() - (QUEUED_TIMEOUT_MS - 1000);
			expect(Date.now() - queuedSince >= QUEUED_TIMEOUT_MS).toBe(false);
		});
	});
});
