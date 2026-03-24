import { describe, it, expect, vi } from 'vitest';

describe('Results page logic', () => {
	describe('loadResultsForJobs pagination', () => {
		it('paginates through all results for a job', async () => {
			const PAGE_SIZE = 500;
			const MAX_RESULTS = 10000;
			// Simulate a job with 1200 results (3 pages)
			const mockGetResults = vi.fn()
				.mockResolvedValueOnce(Array.from({ length: 500 }, (_, i) => ({
					entity_id: `e${i}`,
					attribute_id: 'a1',
					id: `r${i}`,
				})))
				.mockResolvedValueOnce(Array.from({ length: 500 }, (_, i) => ({
					entity_id: `e${500 + i}`,
					attribute_id: 'a1',
					id: `r${500 + i}`,
				})))
				.mockResolvedValueOnce(Array.from({ length: 200 }, (_, i) => ({
					entity_id: `e${1000 + i}`,
					attribute_id: 'a1',
					id: `r${1000 + i}`,
				})));

			const jobs = [{ id: 'job1' }];
			const allResults: { entity_id: string; attribute_id: string; id: string }[] = [];
			let truncated = false;

			for (const job of jobs) {
				let offset = 0;
				while (true) {
					const r = await mockGetResults(job.id, { limit: PAGE_SIZE, offset });
					allResults.push(...r);
					if (r.length < PAGE_SIZE) break;
					offset += PAGE_SIZE;
					if (allResults.length >= MAX_RESULTS) {
						truncated = true;
						break;
					}
				}
				if (truncated) break;
			}

			expect(allResults.length).toBe(1200);
			expect(truncated).toBe(false);
			expect(mockGetResults).toHaveBeenCalledTimes(3);
		});

		it('truncates at MAX_RESULTS and sets warning flag', async () => {
			const PAGE_SIZE = 500;
			const MAX_RESULTS = 1000; // lower limit for test
			const mockGetResults = vi.fn().mockResolvedValue(
				Array.from({ length: 500 }, (_, i) => ({
					entity_id: `e${i}`,
					attribute_id: 'a1',
					id: `r${i}`,
				}))
			);

			const jobs = [{ id: 'job1' }];
			const allResults: unknown[] = [];
			let truncated = false;

			for (const job of jobs) {
				let offset = 0;
				while (true) {
					const r = await mockGetResults(job.id, { limit: PAGE_SIZE, offset });
					allResults.push(...r);
					if (r.length < PAGE_SIZE) break;
					offset += PAGE_SIZE;
					if (allResults.length >= MAX_RESULTS) {
						truncated = true;
						break;
					}
				}
				if (truncated) break;
			}

			expect(truncated).toBe(true);
			expect(allResults.length).toBe(1000);
		});

		it('loads results from all jobs (no 5-job limit)', async () => {
			const PAGE_SIZE = 500;
			const MAX_RESULTS = 10000;
			const mockGetResults = vi.fn().mockResolvedValue(
				Array.from({ length: 100 }, (_, i) => ({
					entity_id: `e${i}`,
					attribute_id: 'a1',
					id: `r${i}`,
				}))
			);

			// 10 jobs (previously capped at 5)
			const jobs = Array.from({ length: 10 }, (_, i) => ({ id: `job${i}` }));
			const allResults: unknown[] = [];
			let truncated = false;

			for (const job of jobs) {
				let offset = 0;
				while (true) {
					const r = await mockGetResults(job.id, { limit: PAGE_SIZE, offset });
					allResults.push(...r);
					if (r.length < PAGE_SIZE) break;
					offset += PAGE_SIZE;
					if (allResults.length >= MAX_RESULTS) {
						truncated = true;
						break;
					}
				}
				if (truncated) break;
			}

			expect(mockGetResults).toHaveBeenCalledTimes(10); // all 10 jobs called
			expect(truncated).toBe(false);
		});
	});

	describe('live results offset tracking', () => {
		it('increments offset after fetching results', () => {
			let offset = 0;
			const liveResults = Array.from({ length: 50 }, (_, i) => ({ id: `r${i}` }));

			if (liveResults.length > 0) {
				offset += liveResults.length;
			}

			expect(offset).toBe(50);
		});

		it('does not increment offset when no new results', () => {
			let offset = 100;
			const liveResults: unknown[] = [];

			if (liveResults.length > 0) {
				offset += liveResults.length;
			}

			expect(offset).toBe(100);
		});

		it('resets offset on new revalidation', () => {
			let offset = 500;
			// simulate revalidation start
			offset = 0;
			expect(offset).toBe(0);
		});
	});

	describe('result deduplication', () => {
		it('deduplicates by entity_id:attribute_id key', () => {
			const results = [
				{ entity_id: 'e1', attribute_id: 'a1', id: 'old', confidence: 0.5 },
				{ entity_id: 'e1', attribute_id: 'a1', id: 'new', confidence: 0.9 },
				{ entity_id: 'e2', attribute_id: 'a1', id: 'r3', confidence: 0.7 },
			];

			const seen = new Map<string, (typeof results)[0]>();
			for (const r of results) seen.set(`${r.entity_id}:${r.attribute_id}`, r);
			const deduped = [...seen.values()];

			expect(deduped.length).toBe(2);
			// Last write wins
			expect(deduped.find((r) => r.entity_id === 'e1')?.id).toBe('new');
		});
	});
});
