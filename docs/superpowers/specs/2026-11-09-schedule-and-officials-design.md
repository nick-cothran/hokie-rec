# Game schedule and official assignments: design

Date: 2026-11-09. Branch `schedule-officials`, stacked on `roster-management` (PR 4).

Sources: Phase III report (assignments "stay pending until the official accepts or declines"; only the assigned official submits scores) and the repo audit of 2026-11-09.

## Confirmed requirements

- Anyone can browse games and results by league (the Schedule page is a placeholder today; there is no games endpoint).
- An official sees their own assignments, accepts or declines each one, and can open the rosters of the teams in their games.
- An official answers once: only while the assignment is pending (`assigned`) and before the game starts.
- Assignments appear in a "Your assignments" panel on the Schedule page, shown only to officials.
- The Phase III schema already matches Figure 4 (checked: 10 relations, keys, nullability, constraints, triggers). Only `Team.team_name` and `Facility.facility_name` differ from the figure's `name`; they stay as they are.

## Supported assumptions

- The schedule is public, like standings and team pages.
- Seed status `assigned` is the pending state. Accept sets `accepted`, decline sets `declined`; `completed` rows are never changed. The score-report trigger already ignores `declined` assignments.
- Rosters stay on the existing public `GET /api/teams/{id}`; officials reach them through links.
- Game times are shown in Blacksburg time (`America/New_York`).

## API (backend/main.py)

### `GET /api/games?league_id=&team_id=` (anyone)

Both filters optional. One row per game, ordered by `start_time, game_id`:
`game_id, league_id, league_name, start_time, end_time, facility_name, location, home_team_id, home_team_name, away_team_id, away_team_name, playoff_round, next_game_id, status, home_score, away_score, forfeit_team_id`.
Team columns are null for an undecided playoff game. Scores come from `LEFT JOIN LatestScoreReport`, so a corrected score shows the newest report and a game without a report has null scores. `team_id` matches either side.

### `GET /api/me/assignments` (signed in)

The caller's own rows from `OfficiatingAssignment` (`official_id = caller`), with the same game fields as above plus `assignment_id, position, status` and `can_respond` (`status = 'assigned' AND start_time > NOW()`). Ordered by `start_time`. A non-official gets `[]`.

### `POST /api/assignments/{assignment_id}/accept` and `/decline` (signed in, 204)

One conditional `UPDATE ... WHERE assignment_id = %s AND official_id = caller AND status = 'assigned' AND game.start_time > NOW()`, so a double click or two tabs can't both change it. When no row changes:
- 404 "You don't have that assignment." when it doesn't exist or belongs to someone else (same wording either way, as invites do).
- 409 "You've already answered this assignment." when it's no longer `assigned`.
- 409 "This game has already started." otherwise.

## Frontend

- `api.ts`: `Game` and `Assignment` types.
- `Schedule.tsx`:
  - `Assignments` panel for `user.role === 'official'`: each row shows date/time, league, facility, position, both teams linked to `/teams/{id}`, status, and Accept/Decline when `can_respond`. Errors show inline; the list reloads after an answer.
  - League picker (from `GET /api/leagues`, as Reports does) and a games table: when, where, home vs away (links), round label ("Final" for a playoff game that feeds no later game, otherwise "Playoff round N"; blank for regular season), result (`3–1`, `Forfeit: <team>`, or the status).
- No new route or nav link.

## Cleanup from the audit

- Finding 3: delete `require_captain`; `rename_team` and `delete_team` use `require_team_captain(team_rules(conn, team_id), user)` (same 404/403 behavior).

## Demo data

Every seeded pending assignment belongs to an October 2026 game that has already started, so none can be answered. README gets a snippet that moves scheduled games forward (they all start after every completed game, so a uniform shift keeps `UNIQUE(facility_id, start_time)`):

```sql
UPDATE Game SET start_time = start_time + INTERVAL '5 weeks', end_time = end_time + INTERVAL '5 weeks' WHERE status = 'scheduled';
```

## Testing

TDD in `backend/test_main.py`:
- Games: league filter, team filter (either side), latest report wins, forfeit row, undecided playoff game with null teams.
- Assignments: anonymous 401 on all three; list shows only the caller's rows; player gets `[]`; accept and decline set the status; another official's assignment 404; unknown id 404; answering twice 409; started game 409; anonymous accept 401.
- Frontend: `tsc -b`, `oxlint`, and a browser click-through as an official (`simvt0121`) and anonymously.

## Open decisions

- Open decision: who may undo or reassign a declined assignment? — admins (new admin UI), the official, or nobody — interim: nobody in the app; an admin edits the database.
- Open decision: should sign-in lockout be per PID (today) or per PID and IP (audit finding 4)? — keep, or key on PID + client IP — interim: unchanged.

## Rulings

- Ruling: keep everything in `main.py` (only auth has its own router; three endpoints don't justify another).
- Ruling: keep `team_name`/`facility_name` column names rather than renaming to the figure's `name`.
