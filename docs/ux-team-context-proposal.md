# UX Proposal: Team Context Visibility Across Playbook Research

**Author:** UX Design Lead  
**Date:** 2026-04-01  
**Status:** APPROVED by CEO (2026-04-01)  
**Addresses:** CEO pain points re: team tabs, KG team ambiguity, comment/report team attribution

---

## 1. Executive Summary

Users cannot tell which team they are operating under because team context is confined to a single pill-button row inside the Scout layout and is entirely absent from the Knowledge Graph, comments, and shared reports. This proposal introduces four coordinated changes: a persistent global team selector in the header (replacing the horizontal pill pattern that breaks at scale), ambient team indicators on every KG page, team attribution badges on comments, and named team tags on shared reports. Together these changes make team context always visible without dominating the interface.

---

## 2. Problem Analysis

### 2.1 What Is Broken

| Surface | Current Behavior | Impact |
|---------|-----------------|--------|
| **Team Switcher** | Horizontal row of pill buttons inside Scout layout only. Wraps awkwardly at 4+ teams. Not rendered anywhere else in the app. | CEO: "looks weird with multiple teams" |
| **KG Entity List** | Reads `scoutTeam` store once in `onMount` via imperative `get()`. No team name displayed anywhere on the page. | Users see entities but have no idea which team's data they are viewing |
| **KG Explorer** | Shows a tiny 10px "Team Graph" / "All Graphs" pill in the toolbar. No team NAME shown, no switcher. | CEO: "it isn't obvious what team I clicked or that team even matters" |
| **KG Conflicts** | Calls `kgApi.getConflicts()` with NO team_id. Shows all conflicts globally. | Users cannot distinguish which team's conflicts they are resolving |
| **Comments** | `Comment` model has no `team_id` field. Displays `author_name` only. | CEO: "which team shared it!" |
| **Shared Reports** | Shows generic "Team only" badge with people icon. Does NOT display which team(s). Team names only visible inside the ShareModal configuration. | Recipients cannot tell which team the report came from |
| **Global Header** | Shows nav links (Teams, Scout, KG) + notifications + user. No team context. | No persistent indicator of the active team anywhere in the chrome |

### 2.2 Root Cause

Team context is treated as a local concern of the Scout layout rather than a global application state. The `scoutTeamStore` uses `localStorage` persistence, meaning it is invisible to the UI chrome and every non-Scout page must independently discover it. There is no single source of truth rendered in the header, so each page either ignores team context or reinvents a tiny local indicator.

### 2.3 User Stories Showing the Confusion

**Story 1 -- The Multi-Team Analyst**
> Maria belongs to "Energy Desk," "Macro Research," and "Credit." She opens the KG entity list to review extraction quality. The page loads data for whichever team ID was last saved in localStorage from a Scout session she ran an hour ago. She sees 400 entities and assumes they are from Energy Desk but they are actually from Credit. She flags several entities for deletion. The wrong team's graph loses data.

**Story 2 -- The Report Reader**
> James receives a Slack link to a shared report. He opens it and sees "Team only" in the metadata row. He belongs to three teams. He has no idea which team shared this report, whether he should forward it to his team's channel, or whether his team even has access.

**Story 3 -- The Comment Reviewer**
> Priya opens a shared research session to read feedback. She sees four comments from different authors. Two of those authors belong to multiple teams. She cannot tell whether the feedback is from the "Equities" team review or the "Fixed Income" team review, because the comment UI shows only author names with no team context.

**Story 4 -- The Pill-Button Overflow**
> Ahmed belongs to seven teams. The horizontal pill row in Scout wraps onto two lines, pushing the page navigation off screen. The active gold pill is on the second row, hidden below the fold on narrower screens. He does not see it and assumes he is on "Personal."

---

## 3. Proposed Solutions

### 3A. Global Team Context Indicator

#### Concept: Header Team Dropdown

Replace the Scout-only pill-button row with a single, persistent team selector in the global header, positioned between the navigation links and the user section. This becomes the **one canonical place** where team context is shown and changed across the entire application.

#### Layout

```
[P Logo] Playbook Research          [Teams] [Scout] [KG]  |  [TeamDropdown v]  [Bell] [Theme] [UserName]
                                                               ^^^^^^^^^^^^^
                                                               NEW COMPONENT
```

The team selector sits to the right of the nav links, separated by a vertical divider, and to the left of notifications. It is always visible when the user is authenticated.

#### Component: `GlobalTeamSelector`

**Collapsed state (default):**
- A compact button showing: `[TeamInitial circle] Team Name [chevron-down]`
- The team initial circle uses a gold background with navy text (matching the logo style)
- If "Personal" mode: shows `[User icon] Personal [chevron-down]`
- Width: auto, capped at `max-w-44` with text truncation for long team names
- Height: matches the existing nav link height (`py-1 text-xs`)

**Expanded state (dropdown):**
- A floating panel anchored below the button, `w-64`, with `bg-navy-900 border border-navy-600 rounded-xl shadow-2xl`
- Sections:
  1. **Personal** -- always first, with a user icon. Shows "Your personal workspace" in muted subtext.
  2. **Teams** -- scrollable list (max-height: 320px) of team rows. Each row shows:
     - Team initial circle (`w-6 h-6 rounded-md bg-navy-700` with gold initial letter)
     - Team display name
     - User's role in that team as a muted suffix (`(admin)`, `(member)`)
     - Checkmark icon on the currently active team
  3. **Footer** -- "Manage Teams" link pointing to `/teams`, styled as a subtle gold text link with a right arrow.

**Active state styling:**
- The active team row has `bg-gold/5 border-l-2 border-gold` as a left accent bar
- The collapsed button shows a `ring-1 ring-gold/30` subtle glow when a team (not personal) is active

**Scales to 10+ teams:**
- The scrollable list handles any number of teams gracefully
- A search/filter input appears automatically when the user has 6+ teams: a small `input` at the top of the dropdown with placeholder "Filter teams..." that filters the list client-side
- Single-team users see a simpler version: just the team name in the button, no dropdown chevron. Clicking navigates to `/teams/[slug]` directly rather than opening a dropdown.

#### Interaction Flow

1. User clicks the team selector button.
2. Dropdown opens with focus trapped inside (Escape closes, Tab cycles through items).
3. User clicks a team row (or presses Enter on a focused row).
4. Dropdown closes.
5. The `scoutTeam` store updates.
6. A brief loading indicator (skeleton pulse on the button for 300ms) appears while downstream pages react to the store change.
7. All listening pages re-fetch data for the new team.

#### States

| State | Visual |
|-------|--------|
| **No teams** | Button reads "No teams" in muted text, chevron links to `/teams` with tooltip "Create a team" |
| **Personal mode** | User silhouette icon + "Personal" label, no gold ring |
| **Active team** | Gold initial circle + team name + subtle gold ring on button |
| **Hover (collapsed)** | `hover:bg-navy-800` background transition |
| **Hover (dropdown row)** | `hover:bg-navy-800` row highlight |
| **Loading (after switch)** | 2px gold progress bar under the header, or skeleton pulse on the button text |
| **Team removed** | If stored team ID not found in user's teams, auto-fallback to Personal, show a toast: "You were removed from [Team Name]" |

#### Responsive Behavior

- **Desktop (>768px):** Full team name shown in the button, dropdown opens below.
- **Tablet (768px):** Team initial circle only (no name), dropdown opens below.
- **Mobile (<640px):** Team initial circle only, dropdown opens as a bottom sheet (`fixed bottom-0 left-0 right-0`) with a drag handle, covering the lower half of the screen. This avoids the tiny dropdown problem on touch devices.

#### Accessibility

- Button has `aria-haspopup="listbox"` and `aria-expanded` toggled
- Dropdown has `role="listbox"`, each team row has `role="option"` with `aria-selected`
- Keyboard: Arrow keys navigate options, Enter selects, Escape closes
- Screen reader announcement on selection: "Switched to [Team Name] team"
- Focus returns to the trigger button on close

#### What It Replaces

The existing `TeamSwitcher.svelte` pill-button component is **removed from the Scout layout** and **not rendered anywhere else**. The `(scout)/+layout.svelte` file's top bar simplifies to just the page nav (Campaigns, Entities, Attributes) since team context is now in the global header above.

---

### 3B. KG Page Team Context

#### Concept: Ambient Team Badge + Reactive Data

Add a team context badge to the page header area of every KG page, and make all data fetching reactive to the global team store.

#### KG Entity List (`/knowledge-graph`)

**Current:**
```
Knowledge Graph                                    [Explore Graph] [View Conflicts]
Entities and relationships extracted from research sessions.
```

**Proposed:**
```
Knowledge Graph                                    [Explore Graph] [View Conflicts]
Entities and relationships extracted from research sessions.
[TeamBadge: "Energy Desk" or "Personal"]
```

The `TeamBadge` is a small inline element below the subtitle:
- Appearance: `text-xs px-2.5 py-0.5 rounded-full border border-navy-600 bg-navy-800`
- Icon: small team icon (people silhouette) or user icon (for Personal) at 12px, inline before the name
- Team name in `text-gold-light` for active team, `text-slate-400` for Personal
- Not clickable (the header dropdown is the canonical place to switch; duplicating controls causes confusion)
- Tooltip on hover: "Showing data for [Team Name]. Switch teams in the header."

**Reactive data fetching:**
- Replace the imperative `get(scoutTeam)` call in `onMount` with a `$effect` block that re-fetches entities and stats whenever `$scoutTeam` changes.
- Show a brief skeleton/loading state during the re-fetch (reuse existing `loading` state).
- The stats cards (Entities, Relationships, Entity Types, Conflicts) update with the new team's numbers.

#### KG Explorer (`/knowledge-graph/explore`)

**Current toolbar snippet:**
```
[Team Graph / All Graphs pill]  [Search...]  [Filters...]
```

**Proposed toolbar:**
- Remove the tiny "Team Graph / All Graphs" pill entirely.
- Add the same `TeamBadge` component to the left of the search bar in the toolbar.
- The badge shows the actual team name: `"Energy Desk Graph"` or `"Personal Graph"`.
- On team switch via the header, the graph re-renders with a brief fade transition (opacity 0.3 for 200ms, then back to 1.0) while new data loads.

#### KG Conflicts (`/knowledge-graph/conflicts`)

**Current:**
```
<-- Knowledge Graph
Relationship Conflicts
When new research contradicts existing relationships, conflicts are recorded here.
```

**Proposed:**
```
<-- Knowledge Graph
Relationship Conflicts
When new research contradicts existing relationships, conflicts are recorded here.
[TeamBadge: "Energy Desk"]
```

- Same `TeamBadge` component.
- The `kgApi.getConflicts()` call must be updated to accept and pass `team_id`.
- The page must reactively re-fetch when the team changes.
- **Requires backend change:** the `/api/kg/conflicts` endpoint needs a `team_id` query parameter (already identified in the archived KG team-gate proposal).

#### Component: `TeamBadge`

A single shared component used on all KG pages (and potentially elsewhere):

```
Props:
  teamName: string | null   -- null means "Personal"
  size: 'sm' | 'md'         -- 'sm' for inline use, 'md' for page headers
  showTooltip: boolean       -- default true

Renders:
  <span class="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full
               border border-navy-600 bg-navy-800">
    <Icon />  <!-- people icon for team, user icon for personal -->
    <span class="text-gold-light">{teamName ?? 'Personal'}</span>
  </span>
```

---

### 3C. Comment Team Attribution

#### Concept: Subtle Team Tag on Comment Author Line

Add a team context indicator to each comment without cluttering the thread flow.

#### Current Comment Rendering (from `CommentThread.svelte`)

Each comment shows:
```
[Avatar] AuthorName                           [timestamp]
Comment body text...
[Reactions] [Reply] [Edit/Delete]
```

The `Comment` interface has no `team_id` or `team_name` field.

#### Proposed Comment Rendering

```
[Avatar] AuthorName  [TeamPill]               [timestamp]
Comment body text...
[Reactions] [Reply] [Edit/Delete]
```

The `TeamPill` is:
- A tiny inline badge next to the author name: `text-[10px] px-1.5 py-0 rounded bg-navy-700 text-slate-500`
- Shows the team abbreviation or short name (e.g., "Energy" not "Energy Desk Research Team")
- If the comment has no team context (personal workspace), no pill is shown (clean default)
- If all comments in a thread belong to the same team, the team pill is shown only on the first comment, with a subtle "Same team" tooltip on subsequent ones (reduces visual noise)

#### Color Coding (Optional Enhancement)

For users in 2+ teams, assign each team a subtle color from a fixed palette. The team pill background uses this color at 10% opacity:

| Team Index | Color Token | Pill Style |
|------------|-------------|------------|
| 0 | gold | `bg-gold/10 text-gold` |
| 1 | blue | `bg-blue-500/10 text-blue-300` |
| 2 | green | `bg-green-500/10 text-green-300` |
| 3 | purple | `bg-purple-500/10 text-purple-300` |
| 4+ | slate | `bg-slate-600/10 text-slate-400` |

This color coding is purely cosmetic and supplementary -- the team name text is always the primary identifier.

#### Interaction

- Hovering the team pill shows a tooltip: "[Team Full Name] -- [Author's role]"
- Clicking the team pill does nothing (it is informational, not navigational)
- Screen readers: `aria-label="Posted from [Team Name] team"`

#### Backend Requirement

The `Comment` model and API must be extended:
- Add `team_id` (nullable UUID) and `team_name` (nullable string) to the comment record
- When a comment is created, if the session is shared with a team and the author is posting from a team context, stamp the `team_id`
- The `GET /api/sessions/{id}/comments` response includes `team_name` on each comment
- Existing comments (before migration) will have `team_id = null` and show no pill

---

### 3D. Shared Report Team Attribution

#### Concept: Replace "Team only" With Named Team Tags

Show exactly which team(s) a report is shared with, everywhere the report metadata appears.

#### Current Shared Report Header (from `/share/[id]/+page.svelte`)

```
[Date] . [Reading time]                          [Team only badge]
Session Title
Session query
```

The "Team only" badge:
```html
<span class="ml-auto flex items-center gap-1 text-[10px] text-slate-500 
             border border-navy-700 rounded-full px-2 py-0.5">
  <PeopleIcon />
  Team only
</span>
```

#### Proposed Shared Report Header

```
[Date] . [Reading time]                    [TeamTag: "Energy Desk"] [TeamTag: "Macro"]
Session Title
Session query
```

**Single team shared:**
- Replace "Team only" with a single named tag: `[PeopleIcon] Energy Desk`
- Same size and position as the current badge
- Style: `border-gold/30 text-gold-light bg-gold/5` to visually distinguish from the generic badge

**Multiple teams shared:**
- Show up to 2 team name tags inline
- If shared with 3+ teams: show 2 tags + `+N more` overflow indicator
- Clicking `+N more` expands to show all team tags (inline, wrapping to next line if needed)

**Public reports:**
- Keep the existing "Public" badge with globe icon, no change needed

**Private reports (the viewer's own):**
- Show no team badge (already correct)

#### Component: `TeamShareTags`

```
Props:
  teamNames: string[]       -- list of team display_names the session is shared with
  maxVisible: number         -- default 2, how many to show before "+N more"

Renders:
  If teamNames.length === 0:  nothing
  If teamNames.length <= maxVisible:
    {#each teamNames as name}
      <span class="inline-flex items-center gap-1 text-[10px] px-2 py-0.5
                   rounded-full border border-gold/30 text-gold-light bg-gold/5">
        <PeopleIcon class="w-2.5 h-2.5" />
        {name}
      </span>
    {/each}
  If teamNames.length > maxVisible:
    Show first `maxVisible` tags + <button>+{remaining} more</button>
    On click, expand all
```

#### Data Requirement

The shared report page (`/share/[id]`) already fetches session data from `+page.server.ts`. The session response must be extended to include:
- `shared_team_names: string[]` -- list of team display names the session is shared with
- This can be JOINed from the existing `session_team_shares` table through `teams`
- The backend already tracks which teams a session is shared with (see `shareSessionToTeam` / `getSessionTeams` in the API)

#### Where Team Tags Appear

1. **Share page header** (`/share/[id]`) -- replaces "Team only" badge
2. **Team library page** (`/teams/[slug]/library`) -- each session card should show team name (but since the user is already on a team page, this is lower priority)
3. **Notification items** -- the "A session was shared with your team" notification should include the team name: "A session was shared with Energy Desk"
4. **Dashboard session list** -- if sessions appear on a dashboard, team tags provide context

---

## 4. Visual Specifications

### 4.1 Global Team Selector -- Collapsed Button

```
Container:  inline-flex items-center gap-2 px-2 py-1 rounded-lg
            border border-navy-600 hover:border-navy-500
            bg-navy-800/50 hover:bg-navy-800
            cursor-pointer transition-all duration-150
            max-w-44

Initial:    w-5 h-5 rounded-md bg-gold flex items-center justify-center
            text-navy text-[10px] font-bold

Name:       text-xs text-slate-300 truncate

Chevron:    w-3 h-3 text-slate-500 transition-transform
            (rotates 180deg when open)

Active ring (when team selected, not Personal):
            ring-1 ring-gold/20
```

### 4.2 Global Team Selector -- Dropdown Panel

```
Container:  fixed (or absolute, depending on header stacking context)
            w-64 mt-1
            bg-navy-900 border border-navy-600 rounded-xl
            shadow-[0_8px_32px_rgba(0,0,0,0.5)]
            z-50
            max-h-[calc(100vh-80px)] overflow-hidden flex flex-col

Search      (shown when 6+ teams):
            px-3 pt-3 pb-2
            input: bg-navy-800 border border-navy-700 rounded-lg
                   text-xs text-slate-300 placeholder-slate-600
                   px-2.5 py-1.5 w-full
                   focus:border-gold/50 focus:outline-none

Divider:    border-t border-navy-700

Team list:  overflow-y-auto flex-1 py-1

Team row:   flex items-center gap-2.5 px-3 py-2 rounded-lg mx-1
            hover:bg-navy-800 cursor-pointer transition-colors

            Active row:
            bg-gold/5 border-l-2 border-l-gold

            Initial circle:
            w-6 h-6 rounded-md bg-navy-700 flex items-center justify-center
            text-[10px] font-medium text-gold

            Name: text-sm text-slate-300 flex-1 truncate
            Role: text-[10px] text-slate-600
            Checkmark (active): w-3.5 h-3.5 text-gold

Footer:     px-3 py-2.5 border-t border-navy-700
            "Manage Teams" link:
            text-xs text-gold hover:text-gold-light transition-colors
            flex items-center gap-1
```

### 4.3 Team Badge (KG Pages)

```
Container:  inline-flex items-center gap-1.5
            text-xs px-2.5 py-0.5 rounded-full
            border border-navy-600 bg-navy-800/80

Icon:       w-3 h-3 text-slate-500 (people icon for team, user icon for personal)

Text:       text-gold-light font-medium (for team)
            text-slate-400 (for personal)
```

### 4.4 Comment Team Pill

```
Container:  inline-flex items-center gap-1
            text-[10px] leading-none
            px-1.5 py-0.5 rounded
            bg-navy-700 border border-navy-700

Text:       text-slate-500 (default)
            Colored variant: text-gold (team index 0), text-blue-300 (1), etc.
            Background variant: bg-gold/10, bg-blue-500/10, etc.

Position:   Immediately after author_name, before the timestamp
            Vertically centered with the author name baseline
```

### 4.5 Shared Report Team Tags

```
Tag:        inline-flex items-center gap-1
            text-[10px] px-2 py-0.5
            rounded-full
            border border-gold/30
            bg-gold/5
            text-gold-light

Icon:       w-2.5 h-2.5 (people silhouette)

Overflow:   text-[10px] text-slate-500 hover:text-gold cursor-pointer
            "+2 more" -- click to expand

Position:   ml-auto in the metadata row, replacing "Team only"
            Wraps naturally on narrow screens
```

### 4.6 Color Palette Reference

All colors used in this proposal map to existing design tokens:

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-navy` | `#0a1628` | Page background |
| `bg-navy-900` | `#060e1a` | Dropdown panel background |
| `bg-navy-800` | `#0d1e38` | Card/badge background |
| `bg-navy-700` | `#112548` | Borders, secondary backgrounds |
| `bg-navy-600` | `#1a3660` | Border highlights |
| `text-gold` | `#c9a84c` | Active team accent, primary emphasis |
| `text-gold-light` | `#e4c97e` | Team names in badges |
| `text-slate-300` | -- | Primary text in dropdowns |
| `text-slate-400` | -- | Secondary text, personal mode |
| `text-slate-500` | -- | Muted labels, timestamps |
| `text-slate-600` | -- | Roles, dividers |

---

## 5. Interaction Design

### 5.1 Team Switching Flow

```
User clicks GlobalTeamSelector
  --> Dropdown opens (150ms fade + translateY(-4px) animation)
  --> Focus moves to currently active option

User clicks a different team
  --> Dropdown closes (100ms fade out)
  --> scoutTeam store updates
  --> GlobalTeamSelector button shows brief skeleton pulse (300ms)
  --> All subscribed pages react:
      - KG Entity List:  shows skeleton table, re-fetches, renders
      - KG Explorer:     graph fades to 30% opacity, re-fetches, fades back in
      - KG Conflicts:    shows loading text, re-fetches, renders
      - Scout pages:     re-filter campaigns/entities for new team (existing behavior)
  --> A 2px gold progress bar appears under the header during re-fetch
  --> On completion: progress bar fades out, data renders
  --> Screen reader announcement: "Switched to Energy Desk. Loading team data."
  --> On data loaded: "Energy Desk data loaded. 342 entities."
```

**Total perceived latency target:** Under 500ms for cached team data, under 2s for cold fetches.

### 5.2 Loading States During Team Data Refresh

| Page | Loading State |
|------|--------------|
| KG Entity List | Stats cards show `--` with subtle pulse animation. Entity list shows 5 skeleton rows (gray bars). |
| KG Explorer | Graph canvas stays visible but dims to 30% opacity. A small spinner appears center-canvas. |
| KG Conflicts | Existing conflicts fade out. "Loading conflicts..." text with spinner. |
| Scout Campaigns | Campaign cards show skeleton state (existing pattern). |
| Comments | No reload needed -- comments are per-session, not per-team. |
| Shared Reports | No reload needed -- report content is per-session. |

### 5.3 Edge Cases

#### User removed from a team
- On next page load or team-list fetch, the stored `scoutTeam` ID will not match any team in the user's list.
- The `onMount` validation in `(scout)/+layout.svelte` already handles this by calling `scoutTeam.select(null)`.
- Extend this validation to the global header: if stored team ID is not in `data.teams`, auto-select Personal.
- Show a toast notification: "You are no longer a member of [Team Name]. Switched to Personal."
- The toast uses existing notification patterns: `bg-navy-800 border border-amber-600/30 text-slate-300` with an amber warning icon.

#### Team deleted
- Same behavior as "user removed from team" -- the team ID will not appear in the user's team list.
- Auto-fallback to Personal with toast.

#### Single-team user
- The GlobalTeamSelector button shows the team name but no dropdown chevron.
- Clicking the button navigates to `/teams/[slug]` (the team detail page) rather than opening a dropdown.
- Rationale: single-team users do not need a switcher, but they should still see which team they are on and have quick access to team settings.

#### User with no teams
- The GlobalTeamSelector button shows "No teams" in muted text.
- Clicking navigates to `/teams` where they can create or join a team.
- KG pages show a gate/prompt: "Join or create a team to access Knowledge Graph data." (Aligns with the archived KG team-gate proposal.)

#### Rapid team switching
- Debounce: if the user switches teams twice within 300ms, only the final selection triggers a data fetch.
- Cancel in-flight requests: use `AbortController` per fetch so stale responses do not overwrite fresh data.

#### Offline / network error during switch
- If the data fetch fails after switching, show the team name in the badge with a warning icon and "Failed to load data. Retry?" link.
- The previous team's data remains visible (do not blank the page).

---

## 6. Technical Feasibility Notes

### 6.1 Frontend-Only Changes (Low Risk)

| Change | Files | Effort |
|--------|-------|--------|
| Create `GlobalTeamSelector.svelte` component | New component | Medium |
| Add `GlobalTeamSelector` to root `+layout.svelte` header | `src/routes/+layout.svelte` | Small |
| Pass `data.teams` from root layout server to header | `src/routes/+layout.server.ts` | Small (may already fetch user, add teams) |
| Remove `TeamSwitcher` from Scout layout | `src/routes/(scout)/+layout.svelte` | Trivial |
| Create `TeamBadge.svelte` shared component | New component | Small |
| Add `TeamBadge` to KG entity list page header | `src/routes/(app)/knowledge-graph/+page.svelte` | Small |
| Add `TeamBadge` to KG explore toolbar | `src/routes/(app)/knowledge-graph/explore/+page.svelte` | Small |
| Add `TeamBadge` to KG conflicts page header | `src/routes/(app)/knowledge-graph/conflicts/+page.svelte` | Small |
| Make KG entity list data fetching reactive | `src/routes/(app)/knowledge-graph/+page.svelte` | Medium (replace `onMount`+`get()` with `$effect`) |
| Create `TeamShareTags.svelte` component | New component | Small |
| Replace "Team only" badge on share page | `src/routes/share/[id]/+page.svelte` | Small |
| Create KG layout server loader for teams data | New `(app)/knowledge-graph/+layout.server.ts` | Small |

### 6.2 Backend Changes Required

| Change | Files | Effort |
|--------|-------|--------|
| Add `team_id`, `team_name` to Comment model and creation endpoint | `app/routes/comments.py`, DB migration | Medium |
| Add `shared_team_names` to session detail response | `app/routes/sessions.py`, join query | Small |
| Add `team_id` parameter to `GET /api/kg/conflicts` | `app/routes/kg.py`, SQL join | Medium |
| Add `team_id` parameter to `GET /api/kg/deal-partners` | `app/routes/kg.py`, SQL filter | Medium |
| Add `team_id` parameter to `GET /api/kg/entities/{id}/relationships` | `app/routes/kg.py` | Small |
| Fix cross-team write auth on relationship edit/delete | `app/routes/kg.py` | Small (security fix) |
| Ensure root layout server fetches teams list | `src/routes/+layout.server.ts` (frontend SSR) | Small |

### 6.3 Reusable Existing Components and Patterns

- **Team initial circle:** Already used in `ShareModal.svelte` (line 223-224) -- extract into a shared `TeamAvatar` mini-component.
- **Dropdown pattern:** Can reference the existing `SearchOverlay` for focus-trap and keyboard nav patterns.
- **Skeleton loading:** Existing `LoadingSpinner` component; adapt for skeleton rows.
- **Toast notifications:** If a toast system exists, use it; otherwise, this is a good time to add a lightweight one using Svelte's `{#if}` transitions.
- **`scoutTeamStore`:** Remains the single source of truth. No store changes needed -- all components subscribe to the same store.

### 6.4 What the Archived KG Team-Gate Proposal Already Covers

The proposal at `openspec/changes/archive/2026-03-24-kg-team-gate-and-switcher/proposal.md` already identified several of the same backend gaps (conflicts team scoping, deal partners team scoping, entity relationships team scoping, relationship edit auth fix, reactive data fetching). This UX proposal is complementary -- it defines the visual and interaction design for the frontend surfaces, while the archived proposal defines the backend API and security changes. Both should be implemented together.

---

## 7. Implementation Priority

Ordered by **user impact** (how directly it addresses CEO pain points) and **effort** (how much work is required).

### Phase 1: Global Team Selector (HIGH impact, MEDIUM effort)
**Addresses:** "tabs for team is not implemented well -- looks weird with multiple teams"

1. Create `GlobalTeamSelector.svelte` with dropdown, keyboard nav, responsive behavior
2. Add teams fetch to root `+layout.server.ts` (or reuse if present)
3. Render `GlobalTeamSelector` in root `+layout.svelte` header
4. Remove `TeamSwitcher` from `(scout)/+layout.svelte`
5. Validate with 1, 5, and 10+ team scenarios

**Estimated effort:** 2-3 days frontend  
**Backend dependency:** None (teams API already exists)

### Phase 2: KG Page Team Context (HIGH impact, MEDIUM effort)
**Addresses:** "on the KG page, it isn't obvious what team I clicked or that team even matters"

1. Create `TeamBadge.svelte` shared component
2. Add KG layout server loader (`+layout.server.ts`) to provide teams data
3. Add `TeamBadge` to KG entity list, explorer, and conflicts pages
4. Make KG entity list data fetching reactive (`$effect` replacing `onMount` + `get()`)
5. Make KG explorer re-fetch graph data on team change
6. Backend: add `team_id` to conflicts and deal-partners endpoints

**Estimated effort:** 3-4 days frontend, 1-2 days backend  
**Backend dependency:** Conflicts and deal-partners team scoping

### Phase 3: Shared Report Team Attribution (MEDIUM impact, LOW effort)
**Addresses:** "which team shared it!"

1. Create `TeamShareTags.svelte` component
2. Backend: add `shared_team_names` to session detail response
3. Replace "Team only" badge on share page with `TeamShareTags`
4. Update notification text to include team name

**Estimated effort:** 1 day frontend, 0.5 days backend  
**Backend dependency:** Session response extension

### Phase 4: Comment Team Attribution (MEDIUM impact, MEDIUM effort)
**Addresses:** "which team shared it!" (comments context)

1. Backend: add `team_id` / `team_name` to Comment model, migration, creation endpoint
2. Frontend: add team pill to comment rendering in `CommentThread.svelte`
3. Implement optional color coding for multi-team users
4. Existing comments show no pill (graceful null handling)

**Estimated effort:** 1 day frontend, 1 day backend (migration + endpoint changes)  
**Backend dependency:** Comment model extension, DB migration

### Summary Timeline

| Phase | What | Impact | Effort | Dependencies |
|-------|------|--------|--------|--------------|
| 1 | Global Team Selector | HIGH | 2-3 days | None |
| 2 | KG Team Context | HIGH | 4-6 days | Backend API changes |
| 3 | Report Team Tags | MEDIUM | 1.5 days | Backend response extension |
| 4 | Comment Team Pills | MEDIUM | 2 days | DB migration |

**Total estimated effort: 10-13 days** to address all three CEO pain points comprehensively.

Phases 1 and 3 can be parallelized (no shared dependencies). Phase 2 backend work can begin concurrently with Phase 1 frontend work. Phase 4 is independent and can be done last.

---

## 8. CEO Decisions (Resolved 2026-04-01)

1. **KG requires team membership:** YES. Users without a team see a gate/prompt to join or create one. No "Personal" KG mode. This aligns with the backend's hard team isolation model.

2. **Color-coded team pills on comments:** YES. Use the color palette from Section 3C (gold, blue, green, purple, slate fallback). Adds scanability for multi-team users.

3. **Mobile team selector: Bottom sheet.** The bottom-sheet pattern provides better touch targets and is consistent with native mobile patterns. Full-page selector would be overkill for a simple team switch.

4. **No notification backfill.** Only new notifications going forward will include team names. Existing notifications remain as-is to avoid migration complexity.

5. **Single-team users: Static display with click-through.** The header button shows the team name as static text (no chevron, no dropdown). Clicking navigates to `/teams/[slug]` for team settings. This reduces UI noise for the majority of users who belong to one team.
