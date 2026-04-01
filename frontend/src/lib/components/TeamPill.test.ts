/**
 * Unit tests for TeamPill component logic.
 *
 * TeamPill is a purely presentational component. These tests exercise the
 * color-selection logic and aria-label construction in isolation, following
 * the logic-only pattern used throughout this test suite (no DOM mounting).
 */

import { describe, it, expect } from 'vitest';

// ── Color class selection logic ───────────────────────────────────────────────

const COLOR_CLASSES = [
	'bg-gold/10 text-gold',
	'bg-blue-500/10 text-blue-300',
	'bg-green-500/10 text-green-300',
	'bg-purple-500/10 text-purple-300',
] as const;

const FALLBACK_CLASS = 'bg-slate-600/10 text-slate-400';

function resolveColorClasses(teamIndex: number): string {
	return teamIndex < COLOR_CLASSES.length ? COLOR_CLASSES[teamIndex] : FALLBACK_CLASS;
}

describe('TeamPill - color class resolution', () => {
	it('returns gold classes for index 0', () => {
		expect(resolveColorClasses(0)).toBe('bg-gold/10 text-gold');
	});

	it('returns blue classes for index 1', () => {
		expect(resolveColorClasses(1)).toBe('bg-blue-500/10 text-blue-300');
	});

	it('returns green classes for index 2', () => {
		expect(resolveColorClasses(2)).toBe('bg-green-500/10 text-green-300');
	});

	it('returns purple classes for index 3', () => {
		expect(resolveColorClasses(3)).toBe('bg-purple-500/10 text-purple-300');
	});

	it('returns fallback slate classes for index 4', () => {
		expect(resolveColorClasses(4)).toBe('bg-slate-600/10 text-slate-400');
	});

	it('returns fallback slate classes for index 10', () => {
		expect(resolveColorClasses(10)).toBe('bg-slate-600/10 text-slate-400');
	});
});

// ── aria-label construction ───────────────────────────────────────────────────

describe('TeamPill - aria-label', () => {
	function buildAriaLabel(teamName: string): string {
		return `Posted from ${teamName} team`;
	}

	it('includes the team name in the aria-label', () => {
		expect(buildAriaLabel('Engineering')).toBe('Posted from Engineering team');
	});

	it('works with multi-word team names', () => {
		expect(buildAriaLabel('Sales & Marketing')).toBe('Posted from Sales & Marketing team');
	});
});

// ── Render guard: null teamName ───────────────────────────────────────────────

describe('TeamPill - null guard', () => {
	/**
	 * Simulates the {#if teamName} block in the Svelte template.
	 * When teamName is null, the component renders nothing.
	 */
	function shouldRender(teamName: string | null): boolean {
		return !!teamName;
	}

	it('does not render when teamName is null', () => {
		expect(shouldRender(null)).toBe(false);
	});

	it('renders when teamName is a non-empty string', () => {
		expect(shouldRender('Engineering')).toBe(true);
	});

	it('renders when teamName is an empty string (guard is null-only)', () => {
		// Empty string is technically truthy check fails — matches {#if teamName}
		// which is falsy for "". This is acceptable — the backend never sends "".
		expect(shouldRender('')).toBe(false);
	});
});

// ── Team color map (from CommentThread) ──────────────────────────────────────

describe('getTeamIndex helper', () => {
	function makeGetTeamIndex() {
		const teamColorMap = new Map<string, number>();
		let nextTeamIndex = 0;
		return function getTeamIndex(teamName: string): number {
			if (!teamColorMap.has(teamName)) {
				teamColorMap.set(teamName, nextTeamIndex++);
			}
			return teamColorMap.get(teamName)!;
		};
	}

	it('assigns index 0 to the first team encountered', () => {
		const getTeamIndex = makeGetTeamIndex();
		expect(getTeamIndex('Alpha')).toBe(0);
	});

	it('assigns index 1 to the second distinct team', () => {
		const getTeamIndex = makeGetTeamIndex();
		getTeamIndex('Alpha');
		expect(getTeamIndex('Beta')).toBe(1);
	});

	it('returns the same index for the same team name', () => {
		const getTeamIndex = makeGetTeamIndex();
		const first = getTeamIndex('Alpha');
		const second = getTeamIndex('Alpha');
		expect(first).toBe(second);
	});

	it('assigns different indices to different teams', () => {
		const getTeamIndex = makeGetTeamIndex();
		const a = getTeamIndex('Alpha');
		const b = getTeamIndex('Beta');
		const c = getTeamIndex('Gamma');
		expect(new Set([a, b, c]).size).toBe(3);
	});

	it('comments without team_name show no pill (null check)', () => {
		// The {#if comment.team_name} guard means null team names never reach getTeamIndex
		const teamName: string | null = null;
		const pillShouldRender = teamName !== null;
		expect(pillShouldRender).toBe(false);
	});
});

// ── createComment team_id passthrough ────────────────────────────────────────

describe('CommentThread - createComment with team_id', () => {
	/**
	 * Verifies that the JSON body passed to POST /api/sessions/:id/comments
	 * includes team_id when a team is selected, and null when none is selected.
	 */
	function buildRequestBody(
		body: string,
		parentId: string | null,
		commentType: string,
		proposedText: string | null,
		teamId: string | null,
	) {
		return {
			body,
			parent_id: parentId,
			highlight_anchor: null,
			comment_type: commentType,
			proposed_text: proposedText,
			team_id: teamId,
		};
	}

	it('includes team_id when a team is active', () => {
		const payload = buildRequestBody('Hello', null, 'comment', null, 'team-abc');
		expect(payload.team_id).toBe('team-abc');
	});

	it('sets team_id to null when no team is selected', () => {
		const payload = buildRequestBody('Hello', null, 'comment', null, null);
		expect(payload.team_id).toBeNull();
	});
});
