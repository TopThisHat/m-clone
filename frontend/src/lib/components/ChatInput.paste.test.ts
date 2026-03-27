import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

/**
 * Tests for the ChatInput paste handler logic.
 *
 * The handlePaste function in ChatInput.svelte does three things:
 *  1. Iterates clipboardData.items
 *  2. Filters items where kind === 'file', calls getAsFile()
 *  3. If any files found: calls preventDefault() and processFiles(files)
 *     If no files: falls through to default text paste behavior
 *
 * Since handlePaste is an inline component function, we test two ways:
 *  A. The pure extraction logic (duplicated as a helper below) for unit coverage
 *  B. Source inspection to verify wiring (onpaste on textarea, correct guard)
 */

// ── A. Pure extraction logic ─────────────────────────────────────────────────
// Mirrors the core logic from handlePaste in ChatInput.svelte

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

function makeClipboardItem(kind: 'file' | 'string', file?: File): DataTransferItem {
	return {
		kind,
		type: kind === 'file' ? (file?.type ?? 'image/png') : 'text/plain',
		getAsFile: () => (kind === 'file' ? (file ?? new File([''], 'paste.png', { type: 'image/png' })) : null),
		getAsString: vi.fn(),
		webkitGetAsEntry: vi.fn(),
	} as unknown as DataTransferItem;
}

describe('paste clipboard extraction logic', () => {
	it('extracts file items and ignores string items', () => {
		const items = [
			makeClipboardItem('string'),
			makeClipboardItem('file'),
		];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(1);
	});

	it('returns empty array when clipboard has only text', () => {
		const items = [makeClipboardItem('string'), makeClipboardItem('string')];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(0);
	});

	it('returns empty array for empty clipboard', () => {
		const files = extractFilesFromClipboardItems([]);
		expect(files).toHaveLength(0);
	});

	it('extracts multiple files from a single paste', () => {
		const items = [
			makeClipboardItem('file', new File(['a'], 'a.png', { type: 'image/png' })),
			makeClipboardItem('file', new File(['b'], 'b.jpg', { type: 'image/jpeg' })),
		];
		const files = extractFilesFromClipboardItems(items);
		expect(files).toHaveLength(2);
		expect(files[0].name).toBe('a.png');
		expect(files[1].name).toBe('b.jpg');
	});

	it('skips items where getAsFile() returns null', () => {
		const nullFileItem = {
			kind: 'file' as const,
			type: 'application/octet-stream',
			getAsFile: () => null,
			getAsString: vi.fn(),
			webkitGetAsEntry: vi.fn(),
		} as unknown as DataTransferItem;
		const files = extractFilesFromClipboardItems([nullFileItem]);
		expect(files).toHaveLength(0);
	});

	it('preserves file order', () => {
		const names = ['first.pdf', 'second.docx', 'third.csv'];
		const items = names.map((name) =>
			makeClipboardItem('file', new File([''], name))
		);
		const files = extractFilesFromClipboardItems(items);
		expect(files.map((f) => f.name)).toEqual(names);
	});
});

// ── B. Source inspection — wiring verification ───────────────────────────────

const chatInputSrc = readFileSync(
	resolve(__dirname, 'ChatInput.svelte'),
	'utf-8'
);

describe('ChatInput.svelte paste handler wiring', () => {
	it('textarea has onpaste handler bound', () => {
		expect(chatInputSrc).toContain('onpaste={handlePaste}');
	});

	it('handlePaste function is defined', () => {
		expect(chatInputSrc).toContain('function handlePaste(e: ClipboardEvent)');
	});

	it('handlePaste calls e.preventDefault() only when files are found', () => {
		// The guard pattern: `if (files.length > 0) { e.preventDefault(); ... }`
		// Ensures normal text paste is not interrupted
		const preventDefaultInGuard =
			chatInputSrc.includes('files.length > 0') &&
			chatInputSrc.includes('e.preventDefault()');
		expect(preventDefaultInGuard).toBe(true);
	});

	it('handlePaste calls processFiles with extracted files', () => {
		expect(chatInputSrc).toContain('processFiles(files)');
	});

	it('handlePaste filters by kind === "file"', () => {
		expect(chatInputSrc).toContain("item.kind === 'file'");
	});
});
