import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { dropzone, type DropzoneOptions } from './dropzone';

// jsdom does not implement DragEvent — provide a minimal polyfill
if (typeof DragEvent === 'undefined') {
	class DragEventPolyfill extends MouseEvent {
		dataTransfer: DataTransfer | null = null;
		constructor(type: string, init?: DragEventInit) {
			super(type, init);
		}
	}
	Object.defineProperty(globalThis, 'DragEvent', { value: DragEventPolyfill, configurable: true });
}

// Creates a DragEvent with a mocked dataTransfer.
// includeFiles=true puts 'Files' in types (simulates file drag).
// includeFiles=false puts 'text/plain' instead (simulates text/link drag).
function makeDragEvent(type: string, includeFiles = true, files: File[] = []): DragEvent {
	const event = new DragEvent(type, { bubbles: true, cancelable: true });
	const types = includeFiles ? ['Files'] : ['text/plain'];
	Object.defineProperty(event, 'dataTransfer', {
		configurable: true,
		value: {
			types,
			files: includeFiles ? (files.length ? files : [new File([''], 'test.pdf')]) : [],
			get dropEffect() {
				return 'none';
			},
			set dropEffect(_: string) {},
		},
	});
	return event;
}

describe('dropzone action', () => {
	let el: HTMLDivElement;
	let onEnter: ReturnType<typeof vi.fn>;
	let onLeave: ReturnType<typeof vi.fn>;
	let onDrop: ReturnType<typeof vi.fn>;
	let action: ReturnType<typeof dropzone>;

	beforeEach(() => {
		el = document.createElement('div');
		document.body.appendChild(el);
		onEnter = vi.fn();
		onLeave = vi.fn();
		onDrop = vi.fn();
		action = dropzone(el, { onEnter, onLeave, onDrop });
	});

	afterEach(() => {
		action.destroy();
		document.body.removeChild(el);
	});

	// ── onEnter ────────────────────────────────────────────────────────────
	describe('onEnter', () => {
		it('fires on the first dragenter with files', () => {
			el.dispatchEvent(makeDragEvent('dragenter'));
			expect(onEnter).toHaveBeenCalledOnce();
		});

		it('does not fire again on a second dragenter (ref-counting)', () => {
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('dragenter'));
			expect(onEnter).toHaveBeenCalledOnce();
		});

		it('does not fire for non-file drags', () => {
			el.dispatchEvent(makeDragEvent('dragenter', false));
			expect(onEnter).not.toHaveBeenCalled();
		});
	});

	// ── onLeave ────────────────────────────────────────────────────────────
	describe('onLeave (enterCount ref-counting)', () => {
		it('fires onLeave when enterCount returns to 0', () => {
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('dragleave'));
			expect(onLeave).toHaveBeenCalledOnce();
		});

		it('does NOT fire onLeave while still inside nested children', () => {
			el.dispatchEvent(makeDragEvent('dragenter')); // outer enter → count=1
			el.dispatchEvent(makeDragEvent('dragenter')); // child enter → count=2
			el.dispatchEvent(makeDragEvent('dragleave')); // child leave → count=1
			expect(onLeave).not.toHaveBeenCalled();
		});

		it('fires once after all nested leaves balance entries', () => {
			el.dispatchEvent(makeDragEvent('dragenter')); // count=1
			el.dispatchEvent(makeDragEvent('dragenter')); // count=2
			el.dispatchEvent(makeDragEvent('dragleave')); // count=1
			el.dispatchEvent(makeDragEvent('dragleave')); // count=0 → fire
			expect(onLeave).toHaveBeenCalledOnce();
		});

		it('does not fire onLeave for non-file dragleave events', () => {
			// Drag text over element (no file) — should not fire any callbacks
			el.dispatchEvent(makeDragEvent('dragleave', false));
			expect(onLeave).not.toHaveBeenCalled();
		});

		it('enterCount never goes below 0 (Math.max guard)', () => {
			// Spurious dragleave without a preceding dragenter should not fire onLeave
			el.dispatchEvent(makeDragEvent('dragleave'));
			expect(onLeave).not.toHaveBeenCalled();
		});
	});

	// ── onDrop ─────────────────────────────────────────────────────────────
	describe('onDrop', () => {
		it('fires onDrop with the dropped File array', () => {
			const file = new File(['content'], 'test.pdf');
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('drop', true, [file]));
			expect(onDrop).toHaveBeenCalledOnce();
			const [files] = onDrop.mock.calls[0] as [File[]];
			expect(files).toHaveLength(1);
			expect(files[0].name).toBe('test.pdf');
		});

		it('calls onLeave on drop (resets drag state)', () => {
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('drop'));
			expect(onLeave).toHaveBeenCalledOnce();
		});

		it('resets enterCount to 0 so onEnter fires again on next drag', () => {
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('drop'));
			onEnter.mockClear();
			el.dispatchEvent(makeDragEvent('dragenter'));
			expect(onEnter).toHaveBeenCalledOnce();
		});
	});

	// ── disabled ───────────────────────────────────────────────────────────
	describe('disabled option', () => {
		it('suppresses all callbacks when disabled at construction', () => {
			action.destroy();
			action = dropzone(el, { onEnter, onLeave, onDrop, disabled: true });
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('dragover'));
			el.dispatchEvent(makeDragEvent('drop'));
			expect(onEnter).not.toHaveBeenCalled();
			expect(onLeave).not.toHaveBeenCalled();
			expect(onDrop).not.toHaveBeenCalled();
		});

		it('respects disabled updated via action.update()', () => {
			action.update({ onEnter, onLeave, onDrop, disabled: true });
			el.dispatchEvent(makeDragEvent('dragenter'));
			expect(onEnter).not.toHaveBeenCalled();
		});

		it('re-enables when disabled is set back to false', () => {
			action.update({ onEnter, onLeave, onDrop, disabled: true });
			action.update({ onEnter, onLeave, onDrop, disabled: false });
			el.dispatchEvent(makeDragEvent('dragenter'));
			expect(onEnter).toHaveBeenCalledOnce();
		});
	});

	// ── destroy ────────────────────────────────────────────────────────────
	describe('destroy', () => {
		it('removes all event listeners — no callbacks fire after destroy', () => {
			action.destroy();
			el.dispatchEvent(makeDragEvent('dragenter'));
			el.dispatchEvent(makeDragEvent('drop'));
			expect(onEnter).not.toHaveBeenCalled();
			expect(onDrop).not.toHaveBeenCalled();
		});

		it('does not throw when called', () => {
			expect(() => action.destroy()).not.toThrow();
		});
	});
});

describe('DropzoneOptions interface', () => {
	it('onDrop is the only required option — action mounts without onEnter/onLeave', () => {
		const el = document.createElement('div');
		const opts: DropzoneOptions = { onDrop: vi.fn() };
		expect(() => {
			const a = dropzone(el, opts);
			a.destroy();
		}).not.toThrow();
	});
});
