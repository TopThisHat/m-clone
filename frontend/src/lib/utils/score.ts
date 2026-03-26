/**
 * Client-side score calculation — mirrors db_recalculate_scores_from_matrix.
 *
 * Formula: score = sum(normalised_i * weight_i) / sum(weight_i)
 *
 * Normalisation rules:
 *   boolean : true → 1.0,  false → 0.0
 *   numeric (bounded)  : clamp((v - min) / (max - min), 0, 1)
 *   numeric (unbounded): v / max(all values for that attribute)
 *   select  : ordinal_index / (option_count - 1)
 *   text    : excluded from scoring
 */

import type { MatrixCell, AttributeType } from '$lib/api/matrix';

export interface ScoreAttribute {
	id: string;
	attribute_type: AttributeType;
	/** Effective weight (after any campaign-level override) */
	weight: number;
	numeric_min?: number | null;
	numeric_max?: number | null;
	options?: string[] | null;
}

/**
 * Compute the score for one entity given the current set of cells.
 *
 * @param entityId   The entity to score
 * @param cells      Cells relevant to this entity (or all cells — filtered internally)
 * @param attributes All campaign attributes with their types and weights
 * @param allCells   Full cell set across all entities — used for unbounded numeric
 *                   normalisation. Defaults to `cells` when omitted.
 * @returns A value in [0, 1], or 0 when no scoreable cells exist
 */
export function computeClientScore(
	entityId: string,
	cells: MatrixCell[],
	attributes: ScoreAttribute[],
	allCells: MatrixCell[] = cells
): number {
	const attrMap = new Map(attributes.map((a) => [a.id, a]));
	const entityCells = cells.filter((c) => c.entity_id === entityId);

	let weightedSum = 0;
	let totalWeight = 0;

	for (const cell of entityCells) {
		const attr = attrMap.get(cell.attribute_id);
		if (!attr) continue;
		if (attr.attribute_type === 'text') continue;

		const norm = normaliseValue(cell, attr, allCells);
		if (norm === null) continue;

		weightedSum += norm * attr.weight;
		totalWeight += attr.weight;
	}

	return totalWeight > 0 ? weightedSum / totalWeight : 0;
}

/**
 * Normalise a single cell value to [0, 1].
 * Returns null when the cell has no value or normalisation is not possible.
 */
function normaliseValue(
	cell: MatrixCell,
	attr: ScoreAttribute,
	allCells: MatrixCell[]
): number | null {
	switch (attr.attribute_type) {
		case 'boolean':
			if (cell.value_boolean === null) return null;
			return cell.value_boolean ? 1.0 : 0.0;

		case 'numeric': {
			if (cell.value_numeric === null) return null;
			const v = cell.value_numeric;
			if (attr.numeric_min != null && attr.numeric_max != null) {
				const range = attr.numeric_max - attr.numeric_min;
				if (range === 0) return 0;
				return Math.max(0, Math.min(1, (v - attr.numeric_min) / range));
			}
			// Unbounded: normalise by the maximum value across all entities
			const maxVal = allCells
				.filter((c) => c.attribute_id === attr.id && c.value_numeric !== null)
				.reduce((m, c) => Math.max(m, c.value_numeric as number), 0);
			return maxVal > 0 ? Math.max(0, Math.min(1, v / maxVal)) : 0;
		}

		case 'select': {
			if (!cell.value_select || !attr.options?.length) return null;
			const idx = attr.options.indexOf(cell.value_select);
			if (idx < 0) return null;
			const total = attr.options.length;
			return total <= 1 ? 1.0 : idx / (total - 1);
		}

		default:
			return null;
	}
}
