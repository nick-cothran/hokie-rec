# Game Schedule and Official Assignments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public games/results view, and officials who can see, accept or decline their assignments and reach the rosters of their games.

**Architecture:** Three endpoints in `backend/main.py` written like the existing ones (plain SQL via `db()`, `AuthenticatedUser`, `HTTPException`), and a rebuilt `Schedule.tsx` that uses `useApi`/`api` like `Teams.tsx` and `Reports.tsx`. No schema change.

**Tech Stack:** FastAPI, psycopg 3, PostgreSQL 17, React 19 + react-router 7, TypeScript, unittest.

**Spec:** `docs/superpowers/specs/2026-11-09-schedule-and-officials-design.md`

## Global Constraints

- Pending assignment status is `assigned`; accept sets `accepted`, decline sets `declined`; nothing else changes status.
- An official answers only while `status = 'assigned'` and `Game.start_time > NOW()`.
- Error copy, verbatim: `You don't have that assignment.` (404), `You've already answered this assignment.` (409), `This game has already started.` (409).
- Games and team rosters are public; assignments are visible only to their own official.
- Times display in `America/New_York`.
- Backend tests run with `cd backend && .venv/bin/python -m unittest`; they build a throwaway schema with the seed.

## Review Focus

- Two tabs answering the same assignment at once: exactly one wins, the other gets 409 (single conditional UPDATE; test answers twice).
- An official guessing another official's `assignment_id`: 404, and the status must not change (test asserts both).
- An undecided playoff game (null teams) in the games list and the assignments panel: renders "TBD", no broken `/teams/null` link (frontend check in Task 4).
- A game whose newest score report has no scores and no forfeit: result shows the game status, not `null–null` (Task 4 `result()` helper).
- A league with no games: the table shows an empty-state line, not an empty table (Task 4).

---

### Task 1: `GET /api/games`

**Files:**
- Modify: `backend/main.py` (new endpoint after `hand_off_captaincy`)
- Test: `backend/test_main.py` (new `GamesTest` class before `TriggerTest`)

**Interfaces:**
- Produces: module constant `GAME_COLUMNS: str` (the SELECT list + FROM/JOINs below, aliased `g`), reused by Task 2. Endpoint `list_games(league_id: int | None = None, team_id: int | None = None) -> list[dict]`.

`GAME_COLUMNS` selects `g.game_id, g.league_id, l.league_name, g.start_time, g.end_time, f.facility_name, f.location, g.home_team_id, h.team_name AS home_team_name, g.away_team_id, a.team_name AS away_team_name, g.playoff_round, g.next_game_id, g.status, s.home_score, s.away_score, s.forfeit_team_id` from `Game g JOIN LeagueView l ON l.league_id = g.league_id JOIN Facility f ON f.facility_id = g.facility_id LEFT JOIN Team h ON h.team_id = g.home_team_id LEFT JOIN Team a ON a.team_id = g.away_team_id LEFT JOIN LatestScoreReport s ON s.game_id = g.game_id`.

- [ ] **Step 1: Write the failing tests** (`class GamesTest(unittest.TestCase)`, anonymous `client` after `client.cookies.clear()` in `setUp`)
  - `test_games_filter_by_league`: pick the league with the most games; every row's `league_id` equals it and `len` equals `SELECT COUNT(*) FROM Game WHERE league_id = %s`; rows sorted by `start_time`.
  - `test_games_filter_by_team_either_side`: for a team with games, every row has the team as `home_team_id` or `away_team_id`; count equals the SQL count of either side.
  - `test_games_show_latest_score`: insert a newer `ScoreReport` (by that game's non-declined assigned official, scores 9 and 8) for a completed game; the row shows `home_score == 9, away_score == 8`; cleanup deletes the report.
  - `test_games_forfeit_row`: for a game whose latest report has `forfeit_team_id`, the row's `forfeit_team_id` matches.
  - `test_undecided_playoff_game_has_null_teams`: a game with `home_team_id IS NULL` comes back with `home_team_name is None` and the league filter still includes it.
- [ ] **Step 2: Run** `.venv/bin/python -m unittest test_main.GamesTest` → FAIL (404 for the route).
- [ ] **Step 3: Implement** `GAME_COLUMNS` and `list_games` with the `%(x)s::int IS NULL OR ...` filter pattern used by `list_teams`; `team_id` matches `g.home_team_id` or `g.away_team_id`; `ORDER BY g.start_time, g.game_id`.
- [ ] **Step 4: Run** `.venv/bin/python -m unittest test_main.GamesTest` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Add public games endpoint with latest scores"`

### Task 2: Official assignments

**Files:**
- Modify: `backend/main.py` (after `list_games`)
- Test: `backend/test_main.py` (new `AssignmentTest` class)

**Interfaces:**
- Consumes: `GAME_COLUMNS` from Task 1.
- Produces: `my_assignments(user) -> list[dict]` at `GET /api/me/assignments`, selecting `oa.assignment_id, oa.position, oa.status AS assignment_status, (oa.status = 'assigned' AND g.start_time > NOW()) AS can_respond` plus `GAME_COLUMNS` (whose `status` stays the game's status), joined from `OfficiatingAssignment oa`, filtered `oa.official_id = caller`, ordered `g.start_time`. `accept_assignment` / `decline_assignment` at `POST /api/assignments/{assignment_id}/accept|decline` (204) both call `answer_assignment(conn, assignment_id: int, user_id: int, status: str) -> None`.

- [ ] **Step 1: Write the failing tests.** `setUp`: official `o1 = simvt0121`'s user_id, `o2 = simvt0122`, admin `simvt0133`; insert a future game (`league_id` of Coed Soccer Fall 2026, any facility, null teams, `start_time = NOW() + INTERVAL '7 days' + random minutes`, `end_time = start_time + INTERVAL '1 hour'`, `playoff_round = 3`) and an `assigned` assignment for `o1`; `addCleanup` deletes the game (assignments cascade).
  - `test_anonymous_gets_401` for GET and both POSTs.
  - `test_lists_only_own_assignments`: as `o1`, the new `assignment_id` is in the list with `can_respond is True`; every row's assignment belongs to `o1` (compare with SQL ids); as `o2` it is absent.
  - `test_player_gets_empty_list`: a player's list is `[]`.
  - `test_accept_sets_accepted`: `o1` accepts → 204, DB status `accepted`.
  - `test_decline_sets_declined`: `o1` declines → 204, DB status `declined`.
  - `test_other_officials_assignment_is_404`: `o2` accepts `o1`'s → 404 `You don't have that assignment.`, status still `assigned`; unknown id `999999` → 404.
  - `test_answering_twice_is_409`: accept then decline → 409 `You've already answered this assignment.`, status stays `accepted`.
  - `test_started_game_is_409`: move the game to `NOW() - INTERVAL '1 hour'` → accept 409 `This game has already started.`, `can_respond is False` in the list.
- [ ] **Step 2: Run** `.venv/bin/python -m unittest test_main.AssignmentTest` → FAIL.
- [ ] **Step 3: Implement.** `answer_assignment`: `UPDATE OfficiatingAssignment oa SET status = %s FROM Game g WHERE g.game_id = oa.game_id AND oa.assignment_id = %s AND oa.official_id = %s AND oa.status = 'assigned' AND g.start_time > NOW()`; if `rowcount == 0`, read `oa.status, g.start_time > NOW() AS upcoming` for that id and official and raise 404 / 409 already answered / 409 started, in that order.
- [ ] **Step 4: Run** the class → PASS; then the full suite → OK.
- [ ] **Step 5: Commit** `git commit -m "Let officials see, accept and decline their assignments"`

### Task 3: One captain check (audit finding 3)

**Files:** Modify `backend/main.py` (`require_captain`, `rename_team`, `delete_team`).

- [ ] **Step 1:** Delete `require_captain`; in `rename_team` and `delete_team` call `require_team_captain(team_rules(conn, team_id), user)`.
- [ ] **Step 2: Run** `.venv/bin/python -m unittest` → OK (existing `test_s3_non_captain_cannot_rename`, `test_s3_missing_team_is_404`, `test_delete_team_non_captain_forbidden` cover 403/404).
- [ ] **Step 3: Commit** `git commit -m "Use one captain check for rename and delete"`

### Task 4: Schedule page

**Files:**
- Modify: `frontend/src/api.ts` (types), `frontend/src/components/Schedule.tsx` (rewrite), `frontend/src/styles/Schedule.css` (only if needed; reuse `data-table`, `panel`, `invite-list`, `filters`, `pill` classes)

**Interfaces:**
- Consumes: `GET /api/games`, `GET /api/me/assignments`, POST accept/decline from Tasks 1–2.
- Produces: `type Game` (fields of `GAME_COLUMNS`; `start_time`/`end_time: string`, nullable team fields and scores as `| null`) and `type Assignment = Game & { assignment_id: number; position: string; assignment_status: string; can_respond: boolean }` in `api.ts`.

- [ ] **Step 1:** Add the types and two helpers in `Schedule.tsx`: `when(iso: string): string` (`toLocaleString(undefined, { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })`) and `result(g: Game): string` (forfeit → `Forfeit: <forfeiting team name>`; both scores non-null → `3–1`; else the game status).
- [ ] **Step 2:** `TeamLink({ id, name })` renders `TBD` text when `id` is null, else `<Link to={/teams/id}>`. `Assignments` panel (rendered only when `user?.role === 'official'`): list rows with `when`, league, facility, position, `TeamLink` vs `TeamLink`, status pill, Accept/Decline buttons when `can_respond`, errors inline, `reload()` after an answer; empty list → "No assignments yet."
- [ ] **Step 3:** League picker as in `Reports.tsx` (`?league=` param, default first league with teams) and a games table: When, Where, Home, Away, Round (`next_game_id === null && playoff_round !== null` → `Final`; `playoff_round` → `Playoff round N`; else blank), Result. No games → "No games scheduled for this league yet."
- [ ] **Step 4: Run** `cd frontend && npx tsc -b && npm run lint` → no output errors.
- [ ] **Step 5: Browser check** (servers already running): anonymous `/schedule` shows the table for the default league with scores; sign in as `simvt0121` / `hokie` → panel lists assignments; after the README demo SQL, Accept on one game → status `accepted` and buttons gone; team links open rosters; no console errors.
- [ ] **Step 6: Commit** `git commit -m "Show schedule, results and official assignments"`

### Task 5: Docs

**Files:** Modify `README.md`.

- [ ] **Step 1:** Add rows to the API table: `GET /api/games` (anyone, `?league_id=&team_id=`), `GET /api/me/assignments` (signed in), `POST /api/assignments/{assignment_id}/accept` and `/decline` (assigned official, pending and before start, 204; 404/409 copy from Global Constraints).
- [ ] **Step 2:** Under "Local demo dates", add the spec's snippet: `UPDATE Game SET start_time = start_time + INTERVAL '5 weeks', end_time = end_time + INTERVAL '5 weeks' WHERE status = 'scheduled';` with one sentence on why.
- [ ] **Step 3:** Factual check: every path and status in the new rows matches `main.py`. Commit `git commit -m "Document games and assignment endpoints"`
