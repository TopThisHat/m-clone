# Team Context UX Overhaul

## Problem
Team context is invisible across most of the application. The horizontal pill-button TeamSwitcher only exists in the Scout layout, doesn't scale past 4 teams, and is absent from KG pages, comments, and shared reports. Users cannot tell which team's data they're viewing or which team shared content.

## Solution
Four coordinated changes:
1. **Global Team Selector** — dropdown in the header replacing pill buttons
2. **KG Page Team Badges** — ambient team indicator on all KG pages with reactive data fetching
3. **Shared Report Team Tags** — named team tags replacing generic "Team only" badge
4. **Comment Team Pills** — color-coded team attribution on comments

## CEO Decisions
- KG requires team membership (no personal mode)
- Color-coded comment pills approved
- Mobile: bottom-sheet pattern
- No notification backfill
- Single-team users: static display

## Full Design
See `docs/ux-team-context-proposal.md` for complete visual specs, interaction design, and technical feasibility.
