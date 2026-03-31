import type { QueryResult } from '$lib/api/documents';

export type ResultType = 'count' | 'list' | 'table' | 'prose' | 'empty' | 'error';

/**
 * Infers the best display format for a QueryResult based on its structure.
 *
 * - error:  result.error is non-null
 * - empty:  no matches
 * - table:  multi-column paired values, or array source_column
 * - prose:  matches include text_positions (excerpt from a prose document)
 * - count:  single match whose value looks like a number / currency / percentage
 * - list:   everything else
 */
export function detectResultType(result: QueryResult): ResultType {
	if (result.error) return 'error';

	const matches = result.matches ?? [];
	if (matches.length === 0) return 'empty';

	const first = matches[0];

	if (typeof first.value === 'object' && first.value !== null && !Array.isArray(first.value)) return 'table';
	if (Array.isArray(first.source_column)) return 'table';

	if (first.text_positions && first.text_positions.length > 0) return 'prose';

	if (
		matches.length === 1 &&
		/^\$?[\d,]+\.?\d*\s*[KMBkmb%]?$/.test(String(first.value).trim())
	)
		return 'count';

	return 'list';
}
