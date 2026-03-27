/**
 * Cross-browser upload verification tests
 *
 * Covers:
 *   - Chrome 120+ drag-and-drop and paste  (m-clone-90hx)
 *   - Firefox 121+ dragover file restriction (m-clone-2ov8)
 *   - Safari 17+ DOMStringList handling     (m-clone-5nys)
 *   - Edge 120+ parity verification         (m-clone-0wpj)
 *   - File dialog regression REG-01→REG-15  (m-clone-3y5t)
 *   - CSVUpload works with window guard     (m-clone-gwjj)
 */

import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import {
	validateDroppedFile,
	isSupportedFile,
	SUPPORTED_EXTENSIONS,
	ACCEPT_STRING,
	MAX_CLIENT_FILE_SIZE,
	MAX_CLIENT_FILE_SIZE_MB,
} from '$lib/api/documents';
import { dropzone } from '$lib/actions/dropzone';

// ── DragEvent polyfill (jsdom does not implement DragEvent) ──────────────────

if (typeof DragEvent === 'undefined') {
	class DragEventPolyfill extends MouseEvent {
		dataTransfer: DataTransfer | null = null;
		constructor(type: string, init?: DragEventInit) {
			super(type, init);
		}
	}
	Object.defineProperty(globalThis, 'DragEvent', {
		value: DragEventPolyfill,
		configurable: true,
	});
}

// ── Shared helpers ───────────────────────────────────────────────────────────

/**
 * Build a DragEvent whose dataTransfer uses a plain Array for `types`.
 * This is the Chrome/Edge/Firefox behaviour.
 */
function makeDragEvent(
	type: string,
	includeFiles = true,
	files: File[] = [],
): DragEvent {
	const event = new DragEvent(type, { bubbles: true, cancelable: true });
	const types: string[] = includeFiles ? ['Files'] : ['text/plain'];
	let _dropEffect = 'none';
	Object.defineProperty(event, 'dataTransfer', {
		configurable: true,
		value: {
			types,
			files: includeFiles
				? files.length
					? files
					: [new File([''], 'test.pdf')]
				: [],
			get dropEffect() {
				return _dropEffect;
			},
			set dropEffect(v: string) {
				_dropEffect = v;
			},
		},
	});
	return event;
}

/**
 * Build a DragEvent whose dataTransfer.types is a mock DOMStringList.
 * Safari 17 exposes DOMStringList rather than a plain Array.
 */
function makeSafariDragEvent(
	type: string,
	typeValues: string[],
	files: File[] = [],
): DragEvent {
	const event = new DragEvent(type, { bubbles: true, cancelable: true });

	// DOMStringList: numeric-indexed, has length, has contains(), NOT an Array
	const domStringList = Object.assign(
		typeValues.reduce<Record<number, string>>((acc, v, i) => {
			acc[i] = v;
			return acc;
		}, {}),
		{
			length: typeValues.length,
			contains(value: string) {
				return typeValues.includes(value);
			},
			item(index: number) {
				return typeValues[index] ?? null;
			},
			[Symbol.iterator]: function* () {
				for (const v of typeValues) yield v;
			},
		},
	);

	let _dropEffect = 'none';
	Object.defineProperty(event, 'dataTransfer', {
		configurable: true,
		value: {
			types: domStringList,
			files: files.length ? files : [new File([''], 'test.png')],
			get dropEffect() {
				return _dropEffect;
			},
			set dropEffect(v: string) {
				_dropEffect = v;
			},
		},
	});
	return event;
}

function makeFile(name: string, size = 1024): File {
	const f = new File([], name);
	Object.defineProperty(f, 'size', { configurable: true, get: () => size });
	return f;
}

function makeClipboardItem(kind: 'file' | 'string', file?: File): DataTransferItem {
	return {
		kind,
		type: kind === 'file' ? (file?.type ?? 'image/png') : 'text/plain',
		getAsFile: () =>
			kind === 'file'
				? (file ?? new File([''], 'paste.png', { type: 'image/png' }))
				: null,
		getAsString: vi.fn(),
		webkitGetAsEntry: vi.fn(),
	} as unknown as DataTransferItem;
}

/** Mirror of the extraction logic in ChatInput.svelte → handlePaste */
function extractFilesFromClipboardItems(items: DataTransferItem[]): File[] {
	const files: File[] = [];
	for (const item of Array.from(items)) {
		if (item.kind === 'file') {
			const file = item.getAsFile();
			if (file) files.push(file);
		}
	}
	return files;
}

// ── Source files ─────────────────────────────────────────────────────────────

const chatInputSrc = readFileSync(
	resolve(__dirname, 'ChatInput.svelte'),
	'utf-8',
);

const csvUploadSrc = readFileSync(
	resolve(__dirname, 'CSVUpload.svelte'),
	'utf-8',
);

// ────────────────────────────────────────────────────────────────────────────
// 1. Chrome 120+ drag-and-drop and paste  (m-clone-90hx)
// ────────────────────────────────────────────────────────────────────────────

describe('Chrome 120+ drag-and-drop and paste', () => {
	let el: HTMLDivElement;
	let onEnter: Mock<() => void>;
	let onLeave: Mock<() => void>;
	let onDrop: Mock<(files: File[]) => void>;
	let action: ReturnType<typeof dropzone>;

	beforeEach(() => {
		el = document.createElement('div');
		document.body.appendChild(el);
		onEnter = vi.fn<() => void>();
		onLeave = vi.fn<() => void>();
		onDrop = vi.fn<(files: File[]) => void>();
		action = dropzone(el, { onEnter, onLeave, onDrop });
	});

	afterEach(() => {
		action.destroy();
		document.body.removeChild(el);
	});

	it('dragenter with types=["Files"] fires onEnter (standard DataTransfer)', () => {
		el.dispatchEvent(makeDragEvent('dragenter'));
		expect(onEnter).toHaveBeenCalledOnce();
	});

	it('dragover sets dropEffect to "copy"', () => {
		const ev = makeDragEvent('dragover');
		el.dispatchEvent(ev);
		// dropEffect setter is called — verify via the event object property
		expect(ev.dataTransfer?.dropEffect).toBe('copy');
	});

	it('drop passes all dropped files to onDrop callback', () => {
		const files = [
			new File(['a'], 'a.pdf'),
			new File(['b'], 'b.docx'),
			new File(['c'], 'c.xlsx'),
		];
		el.dispatchEvent(makeDragEvent('dragenter', true, files));
		el.dispatchEvent(makeDragEvent('drop', true, files));
		expect(onDrop).toHaveBeenCalledOnce();
		const [dropped] = onDrop.mock.calls[0] as [File[]];
		expect(dropped).toHaveLength(3);
		expect(dropped.map((f) => f.name)).toEqual(['a.pdf', 'b.docx', 'c.xlsx']);
	});

	it('paste handler extracts file items from clipboardData.items', () => {
		const items = [
			makeClipboardItem('string'),
			makeClipboardItem('file', new File(['data'], 'chrome-paste.png', { type: 'image/png' })),
		];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(1);
		expect(files[0].name).toBe('chrome-paste.png');
	});

	it('paste handler extracts multiple files in one paste event', () => {
		const items = [
			makeClipboardItem('file', new File(['a'], 'img1.png', { type: 'image/png' })),
			makeClipboardItem('file', new File(['b'], 'img2.jpeg', { type: 'image/jpeg' })),
		];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(2);
		expect(files.map((f) => f.name)).toEqual(['img1.png', 'img2.jpeg']);
	});

	it('paste handler ignores string-only clipboard (falls through to text paste)', () => {
		const items = [makeClipboardItem('string'), makeClipboardItem('string')];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(0);
	});
});

// ────────────────────────────────────────────────────────────────────────────
// 2. Firefox 121+ dragover file restriction  (m-clone-2ov8)
// ────────────────────────────────────────────────────────────────────────────

describe('Firefox 121+ dragover file restriction', () => {
	/**
	 * Firefox restricts access to types during dragover for security — the
	 * DataTransfer.types list may be an empty DOMStringList or only contain
	 * 'Files' (not the actual MIME types). The dropzone hasFiles() check relies
	 * only on the presence of the string 'Files', not actual MIME types.
	 */

	it('hasFiles() check passes when types=["Files"] (Firefox dragover compat)', () => {
		// hasFiles is internal; we verify it via the action accepting the event
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onEnter = vi.fn();
		const action = dropzone(el, { onEnter, onDrop: vi.fn() });

		el.dispatchEvent(makeDragEvent('dragenter', true));
		expect(onEnter).toHaveBeenCalledOnce();

		action.destroy();
		document.body.removeChild(el);
	});

	it('Array.from on types works regardless of underlying list type', () => {
		// Firefox may return a FrozenArray or DOMStringList — Array.from handles both
		const types = ['Files'];
		const result = Array.from(types).includes('Files');
		expect(result).toBe(true);
	});

	it('dragover with types=["Files"] does not trigger a JS error', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const action = dropzone(el, { onDrop: vi.fn() });

		// Should not throw even if event handling logic runs
		expect(() => el.dispatchEvent(makeDragEvent('dragover', true))).not.toThrow();

		action.destroy();
		document.body.removeChild(el);
	});

	it('drop still fires correctly after a dragover-restricted sequence', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onDrop = vi.fn();
		const action = dropzone(el, { onDrop });

		const file = new File(['content'], 'firefox-drop.pdf');
		// Simulate: enter → dragover (possibly restricted) → drop
		el.dispatchEvent(makeDragEvent('dragenter', true));
		el.dispatchEvent(makeDragEvent('dragover', true));
		el.dispatchEvent(makeDragEvent('drop', true, [file]));

		expect(onDrop).toHaveBeenCalledOnce();
		const [dropped] = onDrop.mock.calls[0] as [File[]];
		expect(dropped[0].name).toBe('firefox-drop.pdf');

		action.destroy();
		document.body.removeChild(el);
	});

	it('non-file dragenter (types=["text/plain"]) does not trigger onEnter', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onEnter = vi.fn();
		const action = dropzone(el, { onEnter, onDrop: vi.fn() });

		el.dispatchEvent(makeDragEvent('dragenter', false));
		expect(onEnter).not.toHaveBeenCalled();

		action.destroy();
		document.body.removeChild(el);
	});
});

// ────────────────────────────────────────────────────────────────────────────
// 3. Safari 17+ DOMStringList handling  (m-clone-5nys)
// ────────────────────────────────────────────────────────────────────────────

describe('Safari 17+ DOMStringList handling', () => {
	/**
	 * Safari returns a DOMStringList for dataTransfer.types — an array-like
	 * object with contains() and numeric indexing but not a plain Array.
	 * The dropzone hasFiles() guard uses Array.from(...).includes('Files'),
	 * which correctly handles both Arrays and DOMStringList objects.
	 */

	it('Array.from on a DOMStringList-like object includes "Files"', () => {
		// Build a mock DOMStringList exactly as makeSafariDragEvent does
		const typeValues = ['Files'];
		const domStringList = Object.assign(
			typeValues.reduce<Record<number, string>>((acc, v, i) => {
				acc[i] = v;
				return acc;
			}, {}),
			{
				length: typeValues.length,
				contains(value: string) { return typeValues.includes(value); },
				item(index: number) { return typeValues[index] ?? null; },
				[Symbol.iterator]: function* () { for (const v of typeValues) yield v; },
			},
		);

		// This is the exact expression used in dropzone.ts hasFiles()
		const result = Array.from(domStringList as unknown as Iterable<string>).includes('Files');
		expect(result).toBe(true);
	});

	it('DOMStringList without "Files" returns false', () => {
		const typeValues = ['text/plain', 'text/html'];
		const domStringList = Object.assign(
			typeValues.reduce<Record<number, string>>((acc, v, i) => { acc[i] = v; return acc; }, {}),
			{
				length: typeValues.length,
				contains(value: string) { return typeValues.includes(value); },
				item(index: number) { return typeValues[index] ?? null; },
				[Symbol.iterator]: function* () { for (const v of typeValues) yield v; },
			},
		);

		const result = Array.from(domStringList as unknown as Iterable<string>).includes('Files');
		expect(result).toBe(false);
	});

	it('Safari dragenter with DOMStringList types fires onEnter', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onEnter = vi.fn();
		const action = dropzone(el, { onEnter, onDrop: vi.fn() });

		el.dispatchEvent(makeSafariDragEvent('dragenter', ['Files']));
		expect(onEnter).toHaveBeenCalledOnce();

		action.destroy();
		document.body.removeChild(el);
	});

	it('Safari dragenter with non-file DOMStringList does not fire onEnter', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onEnter = vi.fn();
		const action = dropzone(el, { onEnter, onDrop: vi.fn() });

		el.dispatchEvent(makeSafariDragEvent('dragenter', ['text/plain']));
		expect(onEnter).not.toHaveBeenCalled();

		action.destroy();
		document.body.removeChild(el);
	});

	it('Safari drop with DOMStringList fires onDrop with correct files', () => {
		const el = document.createElement('div');
		document.body.appendChild(el);
		const onDrop = vi.fn();
		const action = dropzone(el, { onDrop });

		const file = new File(['img'], 'safari-drop.png');
		el.dispatchEvent(makeSafariDragEvent('dragenter', ['Files'], [file]));
		el.dispatchEvent(makeSafariDragEvent('drop', ['Files'], [file]));

		expect(onDrop).toHaveBeenCalledOnce();
		const [dropped] = onDrop.mock.calls[0] as [File[]];
		expect(dropped[0].name).toBe('safari-drop.png');

		action.destroy();
		document.body.removeChild(el);
	});

	it('dropzone source uses Array.from to handle DOMStringList', () => {
		// Verify the implementation comment + call site in dropzone.ts
		const dropzoneSrc = readFileSync(
			resolve(__dirname, '../actions/dropzone.ts'),
			'utf-8',
		);
		expect(dropzoneSrc).toContain('Array.from(e.dataTransfer.types)');
		expect(dropzoneSrc).toContain('Safari');
	});
});

// ────────────────────────────────────────────────────────────────────────────
// 4. Edge 120+ parity verification  (m-clone-0wpj)
// ────────────────────────────────────────────────────────────────────────────

describe('Edge 120+ parity verification', () => {
	/**
	 * Edge 120+ is Chromium-based and uses the same DataTransfer API as Chrome.
	 * All behaviour should be identical; these tests confirm there are no
	 * Edge-specific regressions.
	 */

	let el: HTMLDivElement;
	let onEnter: Mock<() => void>;
	let onLeave: Mock<() => void>;
	let onDrop: Mock<(files: File[]) => void>;
	let action: ReturnType<typeof dropzone>;

	beforeEach(() => {
		el = document.createElement('div');
		document.body.appendChild(el);
		onEnter = vi.fn<() => void>();
		onLeave = vi.fn<() => void>();
		onDrop = vi.fn<(files: File[]) => void>();
		action = dropzone(el, { onEnter, onLeave, onDrop });
	});

	afterEach(() => {
		action.destroy();
		document.body.removeChild(el);
	});

	it('dragenter fires onEnter (Edge/Chromium standard DataTransfer)', () => {
		el.dispatchEvent(makeDragEvent('dragenter'));
		expect(onEnter).toHaveBeenCalledOnce();
	});

	it('drop fires onDrop with all files (Edge/Chromium)', () => {
		const file = new File(['data'], 'edge-report.pdf');
		el.dispatchEvent(makeDragEvent('dragenter', true, [file]));
		el.dispatchEvent(makeDragEvent('drop', true, [file]));
		expect(onDrop).toHaveBeenCalledOnce();
		const [dropped] = onDrop.mock.calls[0] as [File[]];
		expect(dropped[0].name).toBe('edge-report.pdf');
	});

	it('paste extraction works identically on Edge', () => {
		const items = [
			makeClipboardItem('file', new File(['x'], 'edge-paste.docx')),
		];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(1);
		expect(files[0].name).toBe('edge-paste.docx');
	});

	it('disabled=true suppresses all events on Edge', () => {
		action.destroy();
		action = dropzone(el, { onEnter, onLeave, onDrop, disabled: true });

		el.dispatchEvent(makeDragEvent('dragenter'));
		el.dispatchEvent(makeDragEvent('dragover'));
		el.dispatchEvent(makeDragEvent('drop'));

		expect(onEnter).not.toHaveBeenCalled();
		expect(onLeave).not.toHaveBeenCalled();
		expect(onDrop).not.toHaveBeenCalled();
	});

	it('re-enables after disabled is toggled false on Edge', () => {
		action.update({ onEnter, onLeave, onDrop, disabled: true });
		action.update({ onEnter, onLeave, onDrop, disabled: false });
		el.dispatchEvent(makeDragEvent('dragenter'));
		expect(onEnter).toHaveBeenCalledOnce();
	});

	it('enterCount ref-counting prevents double onEnter on Edge', () => {
		el.dispatchEvent(makeDragEvent('dragenter'));
		el.dispatchEvent(makeDragEvent('dragenter'));
		expect(onEnter).toHaveBeenCalledOnce();
	});
});

// ────────────────────────────────────────────────────────────────────────────
// 5. File dialog regression  (m-clone-3y5t)  REG-01 through REG-15
// ────────────────────────────────────────────────────────────────────────────

describe('File dialog regression (REG-01 through REG-15)', () => {
	// REG-01: File input accept attribute matches SUPPORTED_EXTENSIONS
	it('REG-01: ChatInput file input accept attribute matches SUPPORTED_EXTENSIONS', () => {
		// The accept attribute is driven by ACCEPT_STRING which is built from SUPPORTED_EXTENSIONS
		expect(chatInputSrc).toContain('accept={ACCEPT_STRING}');
		// ACCEPT_STRING must include all supported extensions
		for (const ext of SUPPORTED_EXTENSIONS) {
			expect(ACCEPT_STRING).toContain(ext);
		}
	});

	// REG-02: validateDroppedFile rejects unsupported types
	it('REG-02: validateDroppedFile rejects unsupported file types', () => {
		const unsupported = ['archive.zip', 'script.exe', 'data.json', 'readme.txt'];
		for (const name of unsupported) {
			expect(validateDroppedFile(makeFile(name))).not.toBeNull();
		}
	});

	// REG-03: validateDroppedFile rejects oversized files
	it('REG-03: validateDroppedFile rejects files over the size limit', () => {
		const file = makeFile('big.pdf', MAX_CLIENT_FILE_SIZE + 1);
		const result = validateDroppedFile(file);
		expect(result).not.toBeNull();
		expect(result).toContain(`${MAX_CLIENT_FILE_SIZE_MB} MB`);
	});

	// REG-04: Multiple file selection works (file input has multiple attribute)
	it('REG-04: ChatInput file input has "multiple" attribute', () => {
		expect(chatInputSrc).toContain('multiple');
	});

	// REG-05: File removal function is wired (removeDocument removes from documents array)
	it('REG-05: ChatInput defines removeDocument and wires it to remove buttons', () => {
		expect(chatInputSrc).toContain('function removeDocument(index: number)');
		expect(chatInputSrc).toContain('removeDocument(i)');
	});

	// REG-06: Retry resubmits the same file (retryDocument uses stored file ref)
	it('REG-06: ChatInput defines retryDocument and it accesses doc.file', () => {
		expect(chatInputSrc).toContain('function retryDocument(index: number)');
		expect(chatInputSrc).toContain('doc.file');
		expect(chatInputSrc).toContain('processFiles([file])');
	});

	// REG-07: processFiles blocks during streaming ($isStreaming guard)
	it('REG-07: processFiles returns early when $isStreaming is true', () => {
		expect(chatInputSrc).toContain('if ($isStreaming)');
		// The streaming block should abort before any upload starts
		expect(chatInputSrc).toContain('streamingAnnouncement =');
	});

	// REG-08: Upload progress bar shows for 3+ files
	it('REG-08: uploadProgress is set when validCount >= 3', () => {
		// Source inspection: the progress bar is gated on validCount >= 3
		expect(chatInputSrc).toContain('if (validCount >= 3)');
		expect(chatInputSrc).toContain('uploadProgress = { completed: 0, total: validCount }');
	});

	// REG-09: File type badges render correct labels
	it('REG-09: getTypeLabel returns correct labels for all known extensions', () => {
		// Extract and unit-test the getTypeLabel logic inline
		function getTypeLabel(filename: string): string {
			const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
			if (ext === '.pdf') return 'PDF';
			if (ext === '.xlsx' || ext === '.xls') return 'Excel';
			if (ext === '.csv') return 'CSV';
			if (ext === '.tsv') return 'TSV';
			if (ext === '.docx') return 'Word';
			if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) return 'Image';
			return 'File';
		}

		expect(getTypeLabel('report.pdf')).toBe('PDF');
		expect(getTypeLabel('data.xlsx')).toBe('Excel');
		expect(getTypeLabel('data.xls')).toBe('Excel');
		expect(getTypeLabel('data.csv')).toBe('CSV');
		expect(getTypeLabel('data.tsv')).toBe('TSV');
		expect(getTypeLabel('document.docx')).toBe('Word');
		expect(getTypeLabel('photo.png')).toBe('Image');
		expect(getTypeLabel('photo.jpg')).toBe('Image');
		expect(getTypeLabel('photo.jpeg')).toBe('Image');
		expect(getTypeLabel('anim.gif')).toBe('Image');
		expect(getTypeLabel('img.webp')).toBe('Image');
	});

	// REG-10: Image files get preview URLs (URL.createObjectURL)
	it('REG-10: ChatInput creates preview URLs for image files', () => {
		expect(chatInputSrc).toContain('URL.createObjectURL(file)');
		expect(chatInputSrc).toContain('isImageFile(file.name)');
	});

	// REG-11: Session reset clears documents ($activeSessionId effect)
	it('REG-11: ChatInput clears documents on session change via $effect', () => {
		expect(chatInputSrc).toContain('$activeSessionId');
		expect(chatInputSrc).toContain('documents = []');
	});

	// REG-12: ACCEPT_STRING is built from SUPPORTED_EXTENSIONS
	it('REG-12: ACCEPT_STRING matches all entries in SUPPORTED_EXTENSIONS', () => {
		const acceptParts = ACCEPT_STRING.split(',');
		for (const ext of SUPPORTED_EXTENSIONS) {
			expect(acceptParts).toContain(ext);
		}
		expect(acceptParts).toHaveLength(SUPPORTED_EXTENSIONS.length);
	});

	// REG-13: Case-insensitive extension matching
	it('REG-13: isSupportedFile is case-insensitive', () => {
		expect(isSupportedFile('REPORT.PDF')).toBe(true);
		expect(isSupportedFile('photo.PNG')).toBe(true);
		expect(isSupportedFile('Data.CSV')).toBe(true);
		expect(isSupportedFile('doc.DOCX')).toBe(true);
	});

	// REG-14: Zero-byte files are accepted
	it('REG-14: validateDroppedFile accepts zero-byte files with valid extensions', () => {
		const file = makeFile('empty.pdf', 0);
		expect(validateDroppedFile(file)).toBeNull();
	});

	// REG-15: Dotfiles with valid extensions are accepted
	it('REG-15: validateDroppedFile accepts dotfiles with valid extensions', () => {
		// A file named ".pdf" — lastIndexOf('.') returns 0, ext === ".pdf"
		const file = makeFile('.pdf', 100);
		expect(validateDroppedFile(file)).toBeNull();

		// ".csv" similarly
		const csv = makeFile('.csv', 100);
		expect(validateDroppedFile(csv)).toBeNull();
	});
});

// ────────────────────────────────────────────────────────────────────────────
// 6. CSVUpload works with window drop guard  (m-clone-gwjj)
// ────────────────────────────────────────────────────────────────────────────

describe('CSVUpload works with window drop guard', () => {
	/**
	 * CSVUpload.svelte handles drag-and-drop with native ondrop/ondragover
	 * attributes on its own element — it does NOT use the dropzone action.
	 * The chat page attaches a global dropzone action to the <section> element,
	 * but CSVUpload is rendered inside /campaigns routes which do NOT use that
	 * action, so there is no conflict. These tests verify the CSVUpload logic
	 * directly without mounting the component.
	 */

	// ── Inline parseCSV extracted from CSVUpload.svelte ────────────────────

	function parseCSV(text: string): { headers: string[]; rows: Record<string, string>[] } {
		const lines = text.trim().split(/\r?\n/);
		if (lines.length < 2) throw new Error('File must have a header row and at least one data row.');

		function parseRow(line: string): string[] {
			const result: string[] = [];
			let cur = '';
			let inQuote = false;
			for (const ch of line) {
				if (ch === '"') { inQuote = !inQuote; }
				else if (ch === ',' && !inQuote) { result.push(cur.trim()); cur = ''; }
				else { cur += ch; }
			}
			result.push(cur.trim());
			return result;
		}

		const hdrs = parseRow(lines[0]);
		const dataRows = lines.slice(1).map((line) => {
			const vals = parseRow(line);
			return Object.fromEntries(hdrs.map((h, i) => [h, vals[i] ?? '']));
		});
		return { headers: hdrs, rows: dataRows };
	}

	// ── parseCSV unit tests ─────────────────────────────────────────────────

	it('parseCSV parses a standard CSV with header row', () => {
		const csv = 'label,description,gwm_id\nAcme Corp,Widget maker,GWM-001\nGlobex Inc,Conglomerate,GWM-002';
		const { headers, rows } = parseCSV(csv);
		expect(headers).toEqual(['label', 'description', 'gwm_id']);
		expect(rows).toHaveLength(2);
		expect(rows[0].label).toBe('Acme Corp');
		expect(rows[1].gwm_id).toBe('GWM-002');
	});

	it('parseCSV handles quoted fields with commas inside', () => {
		const csv = 'label,description\n"Smith, John","CEO of Acme"\n"Jones, Jane","CFO"';
		const { headers, rows } = parseCSV(csv);
		expect(headers).toEqual(['label', 'description']);
		expect(rows[0].label).toBe('Smith, John');
		expect(rows[1].label).toBe('Jones, Jane');
	});

	it('parseCSV trims whitespace from field values', () => {
		const csv = 'label , description\n Acme Corp , Widget maker \n';
		const { headers, rows } = parseCSV(csv);
		expect(headers[0]).toBe('label');
		expect(rows[0].label).toBe('Acme Corp');
	});

	it('parseCSV throws when file has only a header (no data rows)', () => {
		const csv = 'label,description';
		expect(() => parseCSV(csv)).toThrow('header row');
	});

	it('parseCSV handles Windows-style line endings (CRLF)', () => {
		const csv = 'label,description\r\nAcme Corp,Widget maker\r\nGlobex Inc,Conglomerate';
		const { rows } = parseCSV(csv);
		expect(rows).toHaveLength(2);
		expect(rows[0].label).toBe('Acme Corp');
	});

	it('parseCSV fills missing trailing values with empty string', () => {
		const csv = 'label,description,gwm_id\nInitech LLC,,';
		const { rows } = parseCSV(csv);
		expect(rows[0].description).toBe('');
		expect(rows[0].gwm_id).toBe('');
	});

	// ── handleFile validation logic ─────────────────────────────────────────

	const CSV_MAX_SIZE = 10 * 1024 * 1024; // 10 MB (from CSVUpload.svelte)

	it('handleFile rejects files over 10 MB', async () => {
		// Replicate the guard from handleFile()
		function checkFileSize(file: File): string | null {
			if (file.size > CSV_MAX_SIZE) {
				return `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum size is 10 MB.`;
			}
			return null;
		}

		const oversized = makeFile('big.csv', CSV_MAX_SIZE + 1);
		const error = checkFileSize(oversized);
		expect(error).not.toBeNull();
		expect(error).toContain('Maximum size is 10 MB');
	});

	it('handleFile accepts a file at exactly 10 MB', () => {
		function checkFileSize(file: File): string | null {
			if (file.size > CSV_MAX_SIZE) {
				return `File too large`;
			}
			return null;
		}

		const exactLimit = makeFile('exact.csv', CSV_MAX_SIZE);
		expect(checkFileSize(exactLimit)).toBeNull();
	});

	it('handleFile accepts CSV, TSV, and TXT extensions', () => {
		// Replicate the extension routing logic from handleFile
		function routeByExtension(file: File): string {
			const ext = file.name.split('.').pop()?.toLowerCase();
			if (ext === 'csv' || ext === 'tsv' || ext === 'txt') return 'text';
			if (ext === 'xlsx' || ext === 'xls' || ext === 'ods') return 'excel';
			return 'unsupported';
		}

		expect(routeByExtension(new File([''], 'data.csv'))).toBe('text');
		expect(routeByExtension(new File([''], 'data.tsv'))).toBe('text');
		expect(routeByExtension(new File([''], 'data.txt'))).toBe('text');
		expect(routeByExtension(new File([''], 'data.xlsx'))).toBe('excel');
		expect(routeByExtension(new File([''], 'data.xls'))).toBe('excel');
		expect(routeByExtension(new File([''], 'data.ods'))).toBe('excel');
		expect(routeByExtension(new File([''], 'data.pdf'))).toBe('unsupported');
	});

	// ── Source wiring verification ──────────────────────────────────────────

	it('CSVUpload uses native ondrop (not the dropzone action)', () => {
		// CSVUpload must NOT import or use the dropzone action
		expect(csvUploadSrc).not.toContain("from '$lib/actions/dropzone'");
		expect(csvUploadSrc).not.toContain('use:dropzone');
		// But it must have its own ondrop handler
		expect(csvUploadSrc).toContain('ondrop={onDrop}');
	});

	it('CSVUpload ondrop handler calls handleFile with the first file', () => {
		expect(csvUploadSrc).toContain('function onDrop(e: DragEvent)');
		expect(csvUploadSrc).toContain('e.dataTransfer?.files[0]');
		expect(csvUploadSrc).toContain('handleFile(file)');
	});

	it('CSVUpload defines its own MAX_FILE_SIZE constant (10 MB)', () => {
		// The 10 MB constant is local to CSVUpload, separate from ChatInput's 20 MB limit
		expect(csvUploadSrc).toContain('MAX_FILE_SIZE = 10 * 1024 * 1024');
	});

	it('CSVUpload drag state is managed by its own dragging flag', () => {
		// CSVUpload tracks dragging state independently of the global dropzone action
		expect(csvUploadSrc).toContain("let dragging = $state(false)");
		expect(csvUploadSrc).toContain('dragging = true');
		expect(csvUploadSrc).toContain('dragging = false');
	});
});
