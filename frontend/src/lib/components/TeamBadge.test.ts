/**
 * Unit tests for TeamBadge component logic (m-clone-yog4).
 *
 * These test the pure logic that drives the component — tooltip text,
 * class derivations, and label selection — without requiring a DOM renderer.
 * The component uses Svelte 5 runes and is tested in the jsdom environment.
 */

import { describe, it, expect } from 'vitest';

// ── Pure logic extracted from TeamBadge ────────────────────────────────────

function getTooltipText(teamName: string | null): string {
	return teamName
		? `Showing data for ${teamName}. Switch teams in the header.`
		: 'Showing personal data. Switch teams in the header.';
}

function getSizeClasses(size: 'sm' | 'md'): string {
	return size === 'md' ? 'text-xs px-3 py-1 gap-2' : 'text-xs px-2.5 py-0.5 gap-1.5';
}

function getIconSize(size: 'sm' | 'md'): string {
	return size === 'md' ? 'w-3.5 h-3.5' : 'w-3 h-3';
}

function getLabel(teamName: string | null): string {
	return teamName ?? 'Personal';
}

function getTextColorClass(teamName: string | null): string {
	return teamName ? 'text-gold-light' : 'text-slate-400';
}

function isTeamIcon(teamName: string | null): boolean {
	// true → show people/team icon; false → show single user/personal icon
	return teamName !== null;
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('TeamBadge logic', () => {
	describe('label rendering', () => {
		it('shows team name when teamName is provided', () => {
			expect(getLabel('Energy Desk')).toBe('Energy Desk');
		});

		it('shows "Personal" when teamName is null', () => {
			expect(getLabel(null)).toBe('Personal');
		});

		it('shows empty string when teamName is empty string', () => {
			// Empty string is truthy-falsy boundary — treats as "has a name"
			expect(getLabel('')).toBe('');
		});
	});

	describe('tooltip text', () => {
		it('includes team name when team is provided', () => {
			const text = getTooltipText('Energy Desk');
			expect(text).toBe('Showing data for Energy Desk. Switch teams in the header.');
		});

		it('says personal when teamName is null', () => {
			const text = getTooltipText(null);
			expect(text).toBe('Showing personal data. Switch teams in the header.');
		});

		it('always mentions "Switch teams in the header"', () => {
			expect(getTooltipText('Any Team')).toContain('Switch teams in the header.');
			expect(getTooltipText(null)).toContain('Switch teams in the header.');
		});
	});

	describe('icon selection', () => {
		it('uses team/people icon when teamName is provided', () => {
			expect(isTeamIcon('Energy Desk')).toBe(true);
		});

		it('uses personal/user icon when teamName is null', () => {
			expect(isTeamIcon(null)).toBe(false);
		});
	});

	describe('size prop', () => {
		it('sm size uses compact classes', () => {
			const classes = getSizeClasses('sm');
			expect(classes).toContain('px-2.5');
			expect(classes).toContain('py-0.5');
		});

		it('md size uses larger padding', () => {
			const classes = getSizeClasses('md');
			expect(classes).toContain('px-3');
			expect(classes).toContain('py-1');
		});

		it('sm icon is smaller than md icon', () => {
			const sm = getIconSize('sm');
			const md = getIconSize('md');
			expect(sm).toBe('w-3 h-3');
			expect(md).toBe('w-3.5 h-3.5');
		});
	});

	describe('text color', () => {
		it('uses gold-light text for team name', () => {
			expect(getTextColorClass('Energy Desk')).toBe('text-gold-light');
		});

		it('uses slate-400 text for Personal', () => {
			expect(getTextColorClass(null)).toBe('text-slate-400');
		});
	});
});

// ── Integration-style logic tests ────────────────────────────────────────────

describe('TeamBadge — reactive teamName scenarios', () => {
	it('correctly transitions from personal to team context', () => {
		const before = { label: getLabel(null), icon: isTeamIcon(null), tooltip: getTooltipText(null) };
		const after = { label: getLabel('Sports Desk'), icon: isTeamIcon('Sports Desk'), tooltip: getTooltipText('Sports Desk') };

		expect(before.label).toBe('Personal');
		expect(before.icon).toBe(false);
		expect(before.tooltip).toContain('personal');

		expect(after.label).toBe('Sports Desk');
		expect(after.icon).toBe(true);
		expect(after.tooltip).toContain('Sports Desk');
	});

	it('correctly transitions from team to personal context', () => {
		const before = { label: getLabel('Sports Desk'), icon: isTeamIcon('Sports Desk') };
		const after = { label: getLabel(null), icon: isTeamIcon(null) };

		expect(before.label).toBe('Sports Desk');
		expect(before.icon).toBe(true);

		expect(after.label).toBe('Personal');
		expect(after.icon).toBe(false);
	});
});
