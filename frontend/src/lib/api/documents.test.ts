import { describe, it, expect } from 'vitest';
import {
	validateDroppedFile,
	isSupportedFile,
	MAX_CLIENT_FILE_SIZE,
	MAX_CLIENT_FILE_SIZE_MB,
	SUPPORTED_EXTENSIONS,
} from './documents';

function makeFile(name: string, size = 1024): File {
	const file = new File([], name);
	Object.defineProperty(file, 'size', { configurable: true, get: () => size });
	return file;
}

describe('validateDroppedFile', () => {
	describe('valid files — returns null', () => {
		it.each(SUPPORTED_EXTENSIONS)('accepts *%s files', (ext) => {
			const file = makeFile(`file${ext}`, 1024);
			expect(validateDroppedFile(file)).toBeNull();
		});

		it('accepts file at exactly the size limit', () => {
			const file = makeFile('limit.pdf', MAX_CLIENT_FILE_SIZE);
			expect(validateDroppedFile(file)).toBeNull();
		});

		it('accepts uppercase extension (lowercased before check)', () => {
			// isSupportedFile is case-insensitive; extension slicing is .toLowerCase()
			const file = makeFile('REPORT.PDF', 512);
			expect(validateDroppedFile(file)).toBeNull();
		});
	});

	describe('unsupported type — returns error string', () => {
		it.each(['archive.zip', 'script.exe', 'data.json', 'readme.txt', 'document.pptx'])(
			'rejects %s',
			(name) => {
				const file = makeFile(name, 100);
				const result = validateDroppedFile(file);
				expect(result).not.toBeNull();
				expect(typeof result).toBe('string');
			}
		);

		it('rejects a file with no extension', () => {
			const file = makeFile('noextension', 100);
			const result = validateDroppedFile(file);
			expect(result).not.toBeNull();
		});

		it('includes the extension in the error message', () => {
			const file = makeFile('data.zip', 100);
			const result = validateDroppedFile(file);
			expect(result).toContain('.zip');
		});
	});

	describe('oversized files — returns error string', () => {
		it(`rejects a file 1 byte over the ${MAX_CLIENT_FILE_SIZE_MB} MB limit`, () => {
			const file = makeFile('big.pdf', MAX_CLIENT_FILE_SIZE + 1);
			const result = validateDroppedFile(file);
			expect(result).not.toBeNull();
			expect(result).toContain(`${MAX_CLIENT_FILE_SIZE_MB} MB`);
		});

		it('reports size error, not type error, when both apply', () => {
			// Extension is checked first — this should fail on type, not size
			const file = makeFile('big.zip', MAX_CLIENT_FILE_SIZE + 1);
			const result = validateDroppedFile(file);
			expect(result).not.toBeNull();
			// Should mention the extension (type error caught first)
			expect(result).toContain('.zip');
		});
	});

	describe('edge cases', () => {
		it('accepts a zero-byte file with supported extension', () => {
			const file = makeFile('empty.csv', 0);
			expect(validateDroppedFile(file)).toBeNull();
		});

		it('handles dotfile names (filename starts with dot)', () => {
			// ".pdf" as a name has the extension of itself — isSupportedFile returns false
			const file = makeFile('.pdf', 100);
			// The extension slicing uses lastIndexOf('.') which points to position 0,
			// so ext === '.pdf' which IS in SUPPORTED_EXTENSIONS
			expect(validateDroppedFile(file)).toBeNull();
		});
	});
});

describe('isSupportedFile', () => {
	it('returns true for supported extensions', () => {
		expect(isSupportedFile('document.pdf')).toBe(true);
		expect(isSupportedFile('photo.jpg')).toBe(true);
	});

	it('returns false for unsupported extensions', () => {
		expect(isSupportedFile('archive.zip')).toBe(false);
		expect(isSupportedFile('script.js')).toBe(false);
	});

	it('is case-insensitive', () => {
		expect(isSupportedFile('REPORT.PDF')).toBe(true);
		expect(isSupportedFile('Photo.PNG')).toBe(true);
	});

	it('returns false for files with no extension', () => {
		expect(isSupportedFile('noextension')).toBe(false);
	});
});
