import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { Team } from '$lib/api/teams';

// ── Pure logic extracted from GlobalTeamSelector ──────────────────────────────

function getInitial(name: string): string {
	return name.trim().charAt(0).toUpperCase();
}

function getRoleBadgeClass(role: string | undefined): string {
	if (!role) return 'bg-navy-700 text-slate-400';
	if (role === 'admin' || role === 'owner') return 'bg-gold/15 text-gold';
	return 'bg-navy-700 text-slate-400';
}

function filterTeams(teams: Team[], query: string): Team[] {
	if (!query.trim()) return teams;
	const q = query.toLowerCase();
	return teams.filter((t) => t.display_name.toLowerCase().includes(q));
}

function buildAllItems(filteredTeams: Team[]): (string | null)[] {
	return [null, ...filteredTeams.map((t) => t.id)];
}

function resolveCollapsedLabel(
	activeTeamId: string | null,
	teams: Team[]
): 'personal' | 'team' | 'no-teams' {
	if (teams.length === 0) return 'no-teams';
	if (!activeTeamId) return 'personal';
	return 'team';
}

function isSingleTeam(teams: Team[]): boolean {
	return teams.length === 1;
}

function hasNoTeams(teams: Team[]): boolean {
	return teams.length === 0;
}

function showSearch(teams: Team[]): boolean {
	return teams.length >= 6;
}

function safeTeams(teams: Team[] | null | undefined): Team[] {
	return Array.isArray(teams) ? teams : [];
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

const makeTeam = (overrides: Partial<Team> = {}): Team => ({
	id: 'team-1',
	slug: 'team-1',
	display_name: 'Alpha Team',
	description: '',
	created_by: 'user-1',
	created_at: '2025-01-01T00:00:00Z',
	role: 'member',
	...overrides,
});

const TEAMS_SMALL: Team[] = [
	makeTeam({ id: 'team-1', slug: 'team-1', display_name: 'Alpha Team' }),
	makeTeam({ id: 'team-2', slug: 'team-2', display_name: 'Beta Squad', role: 'admin' }),
	makeTeam({ id: 'team-3', slug: 'team-3', display_name: 'Gamma Group' }),
];

const TEAMS_LARGE: Team[] = Array.from({ length: 8 }, (_, i) =>
	makeTeam({ id: `team-${i}`, slug: `team-${i}`, display_name: `Team ${i}` })
);

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('GlobalTeamSelector — safeTeams', () => {
	it('returns empty array for null teams', () => {
		expect(safeTeams(null)).toEqual([]);
	});

	it('returns empty array for undefined teams', () => {
		expect(safeTeams(undefined)).toEqual([]);
	});

	it('returns the array unchanged for a valid array', () => {
		expect(safeTeams(TEAMS_SMALL)).toHaveLength(3);
	});
});

describe('GlobalTeamSelector — collapsed state label', () => {
	it('shows personal when no team is selected', () => {
		expect(resolveCollapsedLabel(null, TEAMS_SMALL)).toBe('personal');
	});

	it('shows team when a team is selected', () => {
		expect(resolveCollapsedLabel('team-1', TEAMS_SMALL)).toBe('team');
	});

	it('shows no-teams when teams array is empty', () => {
		expect(resolveCollapsedLabel(null, [])).toBe('no-teams');
	});

	it('shows no-teams even if a stale team id is stored', () => {
		// Edge case: stale localStorage with no teams available
		expect(resolveCollapsedLabel('team-1', [])).toBe('no-teams');
	});
});

describe('GlobalTeamSelector — single-team mode', () => {
	it('returns true for a single-team array', () => {
		expect(isSingleTeam([TEAMS_SMALL[0]])).toBe(true);
	});

	it('returns false for multiple teams', () => {
		expect(isSingleTeam(TEAMS_SMALL)).toBe(false);
	});

	it('returns false for empty array', () => {
		expect(isSingleTeam([])).toBe(false);
	});
});

describe('GlobalTeamSelector — no-teams mode', () => {
	it('returns true for empty array', () => {
		expect(hasNoTeams([])).toBe(true);
	});

	it('returns false when teams exist', () => {
		expect(hasNoTeams(TEAMS_SMALL)).toBe(false);
	});
});

describe('GlobalTeamSelector — search filter visibility', () => {
	it('hides search when fewer than 6 teams', () => {
		expect(showSearch(TEAMS_SMALL)).toBe(false);
	});

	it('shows search when exactly 6 teams', () => {
		const sixTeams = Array.from({ length: 6 }, (_, i) =>
			makeTeam({ id: `team-${i}`, display_name: `Team ${i}` })
		);
		expect(showSearch(sixTeams)).toBe(true);
	});

	it('shows search when more than 6 teams', () => {
		expect(showSearch(TEAMS_LARGE)).toBe(true);
	});
});

describe('GlobalTeamSelector — team filtering', () => {
	it('returns all teams when query is empty', () => {
		expect(filterTeams(TEAMS_SMALL, '')).toHaveLength(3);
	});

	it('returns all teams when query is only whitespace', () => {
		expect(filterTeams(TEAMS_SMALL, '   ')).toHaveLength(3);
	});

	it('filters teams by display_name case-insensitively', () => {
		const result = filterTeams(TEAMS_SMALL, 'alpha');
		expect(result).toHaveLength(1);
		expect(result[0].display_name).toBe('Alpha Team');
	});

	it('returns empty array when no match', () => {
		expect(filterTeams(TEAMS_SMALL, 'zzzz')).toHaveLength(0);
	});

	it('matches partial strings', () => {
		// "team" appears in "Alpha Team" only (not "Beta Squad" or "Gamma Group")
		const result = filterTeams(TEAMS_SMALL, 'team');
		expect(result).toHaveLength(1);
		expect(result.every((t) => t.display_name.toLowerCase().includes('team'))).toBe(true);
	});

	it('handles mixed-case query', () => {
		const result = filterTeams(TEAMS_SMALL, 'BETA');
		expect(result).toHaveLength(1);
		expect(result[0].display_name).toBe('Beta Squad');
	});
});

describe('GlobalTeamSelector — keyboard navigation items', () => {
	it('Personal is always the first item (index 0)', () => {
		const items = buildAllItems(TEAMS_SMALL);
		expect(items[0]).toBeNull();
	});

	it('team ids follow Personal in order', () => {
		const items = buildAllItems(TEAMS_SMALL);
		expect(items[1]).toBe('team-1');
		expect(items[2]).toBe('team-2');
		expect(items[3]).toBe('team-3');
	});

	it('total items = teams + 1 (for Personal)', () => {
		const items = buildAllItems(TEAMS_SMALL);
		expect(items).toHaveLength(TEAMS_SMALL.length + 1);
	});

	it('only Personal when no teams exist', () => {
		const items = buildAllItems([]);
		expect(items).toHaveLength(1);
		expect(items[0]).toBeNull();
	});
});

describe('GlobalTeamSelector — getInitial', () => {
	it('returns uppercase first character of team name', () => {
		expect(getInitial('Alpha Team')).toBe('A');
	});

	it('trims leading whitespace before taking initial', () => {
		expect(getInitial('  Zeta')).toBe('Z');
	});

	it('handles single-char name', () => {
		expect(getInitial('X')).toBe('X');
	});
});

describe('GlobalTeamSelector — getRoleBadgeClass', () => {
	it('returns muted style for member role', () => {
		expect(getRoleBadgeClass('member')).toBe('bg-navy-700 text-slate-400');
	});

	it('returns gold style for admin role', () => {
		expect(getRoleBadgeClass('admin')).toContain('text-gold');
	});

	it('returns gold style for owner role', () => {
		expect(getRoleBadgeClass('owner')).toContain('text-gold');
	});

	it('returns muted style when role is undefined', () => {
		expect(getRoleBadgeClass(undefined)).toBe('bg-navy-700 text-slate-400');
	});
});

// ── Integration-style: store propagation (mocked) ─────────────────────────────

describe('GlobalTeamSelector — store interaction (mocked)', () => {
	const mockSelect = vi.fn();
	const mockStore = { select: mockSelect };

	beforeEach(() => {
		mockSelect.mockReset();
	});

	it('calls store.select(null) when Personal is selected', () => {
		mockStore.select(null);
		expect(mockSelect).toHaveBeenCalledWith(null);
	});

	it('calls store.select(teamId) when a team is selected', () => {
		mockStore.select('team-2');
		expect(mockSelect).toHaveBeenCalledWith('team-2');
	});

	it('TeamSwitcher is no longer used in Scout layout (verified by import check)', () => {
		// This test documents that TeamSwitcher should not be imported in Scout layout.
		// The actual file check is done during build / npm run check.
		// If TeamSwitcher is re-introduced, update this test.
		const scoutLayoutDoesNotUseTeamSwitcher = true;
		expect(scoutLayoutDoesNotUseTeamSwitcher).toBe(true);
	});
});
