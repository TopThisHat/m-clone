/**
 * OptimisticStore — reusable optimistic state management for async saves.
 *
 * Pattern:
 *   1. User edits a value → store applies it immediately (optimistic)
 *   2. API call fires in background
 *   3. Success + no conflict → clear pending, done
 *   4. Success + server returned different value → flash conflict, adopt server value
 *   5. Error → roll back to previous value, expose error message
 *
 * Usage in a .svelte file:
 *   const labels = new OptimisticStore<string, string>();
 *
 *   // Read effective value (pending overrides server):
 *   const display = labels.get(entity.id, entity.label);
 *
 *   // Save with optimistic update:
 *   await labels.update(entity.id, 'New Label', () =>
 *     entitiesApi.update(campaignId, entity.id, { label: 'New Label' })
 *       .then(e => e.label)
 *   );
 */
import { SvelteMap, SvelteSet } from 'svelte/reactivity';

export class OptimisticStore<K extends string = string, V = unknown> {
	/** Pending optimistic values not yet confirmed by server */
	pending: SvelteMap<K, V> = new SvelteMap();
	/** Keys currently awaiting server response */
	saving: SvelteSet<K> = new SvelteSet();
	/** Per-key error messages from failed saves */
	errors: SvelteMap<K, string> = new SvelteMap();
	/**
	 * Keys where server returned a different value than optimistic.
	 * Use to drive a brief yellow-flash animation.
	 */
	conflicts: SvelteSet<K> = new SvelteSet();
	/** Per-key conflict clear timers — cleared on new update to avoid races */
	private conflictTimers: Map<K, ReturnType<typeof setTimeout>> = new Map();

	/** Effective value: pending takes priority over the server value. */
	get(key: K, serverValue: V): V {
		return this.pending.has(key) ? (this.pending.get(key) as V) : serverValue;
	}

	isSaving(key: K): boolean {
		return this.saving.has(key);
	}

	errorOf(key: K): string | undefined {
		return this.errors.get(key);
	}

	isConflicted(key: K): boolean {
		return this.conflicts.has(key);
	}

	hasPending(key: K): boolean {
		return this.pending.has(key);
	}

	/**
	 * Optimistically apply `value`, fire `saveFn`, roll back on error.
	 *
	 * If the server returns a different value (conflict), the store adopts
	 * the server value and marks the key as conflicted for 2 s so the UI
	 * can flash yellow.
	 *
	 * @returns true on success, false on error
	 */
	async update(key: K, value: V, saveFn: () => Promise<V>): Promise<boolean> {
		// Clear any pending conflict timer for this key to avoid stale cleanup
		const existingTimer = this.conflictTimers.get(key);
		if (existingTimer !== undefined) {
			clearTimeout(existingTimer);
			this.conflictTimers.delete(key);
		}
		this.pending.set(key, value);
		this.errors.delete(key);
		this.conflicts.delete(key);
		this.saving.add(key);

		try {
			const serverVal = await saveFn();
			this.saving.delete(key);

			// Conflict: server normalised / rejected the exact value we sent
			if (JSON.stringify(serverVal) !== JSON.stringify(value)) {
				this.pending.set(key, serverVal as V);
				this.conflicts.add(key);
				const timer = setTimeout(() => {
					this.conflicts.delete(key);
					// Adopt server value permanently after flash
					this.pending.delete(key);
					this.conflictTimers.delete(key);
				}, 2000);
				this.conflictTimers.set(key, timer);
			} else {
				this.pending.delete(key);
			}
			return true;
		} catch (err) {
			this.saving.delete(key);
			// Roll back — remove optimistic value so server value shows again
			this.pending.delete(key);
			this.errors.set(key, err instanceof Error ? err.message : 'Save failed');
			return false;
		}
	}

	clearError(key: K): void {
		this.errors.delete(key);
	}

	clearConflict(key: K): void {
		this.conflicts.delete(key);
	}
}
