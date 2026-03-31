/** Shared confidence display utilities for query results and classification components. */

/** Returns Tailwind color classes for a confidence badge based on level */
export function confidenceColor(confidence: number): string {
	if (confidence >= 0.85) return 'text-green-400 bg-green-950 border-green-800';
	if (confidence >= 0.6) return 'text-gold bg-amber-950 border-amber-800';
	return 'text-orange-400 bg-orange-950 border-orange-800';
}

/** Returns a Tailwind background class for a confidence progress bar fill */
export function confidenceBarColor(confidence: number): string {
	if (confidence >= 0.85) return 'bg-green-500';
	if (confidence >= 0.6) return 'bg-gold';
	return 'bg-orange-400';
}
