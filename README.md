# hokie-rec

## Setup

1. Create a `.env` file, and copy the contents of `.env.example` into it.
2. Within the `/backend` folder, create a python venv, then run `pip install -r requirements.txt`
3. Within the `/frontend` folder, run `npm install`

## Running the backend

1. With the docker engine running, run `docker compose up -d` from the root directory.
2. To seed data, run `npm run seed` (fresh databases only).

   **Account logins:** From `/backend` with the venv active, run:

   ```powershell
   python migrate.py
   python seed_demo_accounts.py --development
   ```

   `migrate.py` brings an existing database up to date (authentication tables, roster rules, and the Phase III schema in `db/phase3.sql`) without losing data; it is safe to rerun. On a pre-Phase III database it moves roster limits into `Sport` and drops the derived columns `League.league_name`, `Game.game_type` and `ScoreReport.is_forfeit`, and stops without changes if any of them disagrees with the data that replaces it. All 135 seeded users (`simvt0001`–`simvt0135`) use password `hokie`. Add `--reset` to the account-seeding command to replace existing demo passwords; sign-up accounts are unaffected.

3. From `/backend` (venv active), run `uvicorn main:app --reload`. The terminal prints the DB connection on startup.
4. Open http://localhost:8000/docs to try every endpoint in the browser.
5. Tests: `python -m unittest` from `/backend`. They build a throwaway schema from `db/*.sql` inside the dev database and drop it afterwards, so your data is untouched.

   **Local demo dates:** registration and roster changes follow each league's real dates (roster lock dates are Blacksburg dates). If every seeded league is closed when you demo, open the Spring leagues in your local DB:

   ```sql
   UPDATE League SET reg_open_at = NOW() - INTERVAL '1 day' WHERE term = 'Spring 2027';
   ```

   Officials can only answer an assignment before its game starts, and the seeded playoff games are in October 2026. To demo accept/decline (e.g. as `simvt0121`), move the scheduled games forward. They all start after every completed game, so the shift can't double-book a facility. Setting the time zone keeps the Blacksburg kickoff times across the daylight-saving change:

   ```sql
   SET timezone = 'America/New_York';
   UPDATE Game SET start_time = start_time + INTERVAL '5 weeks', end_time = end_time + INTERVAL '5 weeks' WHERE status = 'scheduled';
   ```

   If registering a team fails with `null value in column "status"`, your Docker volume predates the schema's column defaults. Recreate it (this deletes local data): `docker compose down -v`, then repeat steps 1–2.

## API (base URL `http://localhost:8000`)

Sign in first: the browser keeps a session cookie, and every write also needs the `X-Requested-With: HokieRec` header (the frontend's `api()` adds it). "Captain" means the captain of that team.

| Method | Path | Body / query | Who | Notes |
|---|---|---|---|---|
| POST | `/api/auth/sign-up` | `{vt_pid, first_name, last_name, email, phone, password}` | anyone | Creates a player and signs in. 201 |
| POST | `/api/auth/login` | `{vt_pid, password}` | anyone | 200 → user; 429 after 10 failed tries in 15 min |
| GET | `/api/auth/me` | | signed in | Current user; 401 if not signed in |
| POST | `/api/auth/logout` | | anyone | 204 |
| GET | `/api/health` | | anyone | `{status, version, database, leagues, teams}` |
| GET | `/api/leagues` | `?sport=Soccer&term=Fall 2026` (both optional) | anyone | S1. Leagues with `team_count` |
| GET | `/api/teams` | `?league_id=1` (optional) | anyone | Team directory with league, captain and `member_count` |
| POST | `/api/teams` | `{league_id, team_name}` | active player | S2. You become captain. 409 outside the registration window or if you're already on a team in that league. 201 → `{team_id}` |
| GET | `/api/teams/{team_id}` | | anyone | Team, league roster limits (`min_roster_size`, `max_roster_size`, `roster_lock_date`, `roster_locked`) and `roster` |
| PATCH | `/api/teams/{team_id}` | `{team_name}` | captain | S3. 200 → `{team_id, team_name}` |
| DELETE | `/api/teams/{team_id}` | | captain | Roster rows cascade; 409 if the team has games. 204 |
| POST | `/api/teams/{team_id}/invites` | `{vt_pid}` | captain | Invite by PID before the lock date. 404 unknown PID; 409 if already invited/on the team, suspended, or on another team in the league. Reuses a former member's row. 201 |
| DELETE | `/api/teams/{team_id}/invites/{player_id}` | | captain | S4. Withdraw a pending invite, any time. A former member's withdrawn re-invite is kept as `removed`. 204 |
| GET | `/api/me/invites` | | signed in | Your pending invites with team, league, captain, `active_count`, `max_roster_size`, lock date |
| POST | `/api/teams/{team_id}/invite/accept` | | invitee | Join before the lock date if the team isn't full; declines your other pending invites in that league. 204 |
| POST | `/api/teams/{team_id}/invite/decline` | | invitee | Any time. 204 |
| DELETE | `/api/teams/{team_id}/members/{player_id}` | | captain | Remove an active member (not the captain) before the lock date; row kept as `removed`. 204 |
| POST | `/api/teams/{team_id}/leave` | | active member | Leave before the lock date; the captain must hand off first. 204 |
| PUT | `/api/teams/{team_id}/captain` | `{user_id}` | captain | Hand off to an active member, any time. 200 → `{team_id, captain_id}` |
| GET | `/api/games` | `?league_id=1&team_id=4` (both optional) | anyone | Schedule and results, oldest first. Teams are null for an undecided playoff game; scores come from the game's newest score report |
| GET | `/api/me/assignments` | | signed in | Your officiating assignments with game details, `assignment_status` and `can_respond`; `[]` for non-officials |
| POST | `/api/assignments/{assignment_id}/accept` | | assigned official | Only while `assigned` and before the game starts. 404 if it isn't yours; 409 if already answered or started. 204 |
| POST | `/api/assignments/{assignment_id}/decline` | | assigned official | Same rules as accept. A declined official can't submit the game's score. 204 |
| GET | `/api/reports/standings` | `?league_id=1` | anyone | Report 1. Regular-season W/L/T and points per team; forfeit = loss for the forfeiting team. 404 if no league |
| GET | `/api/reports/participation` | `?term=Fall 2026` (optional) | anyone | Report 2. Teams, active players, pending invites, avg roster, games played/left per league |

Schema (Phase III): roster limits live on `Sport`; a league's display name (`league_name`, e.g. "Coed Soccer, Recreational, Fall 2026") and its sport's limits come from the `LeagueView` view. A game is a playoff game when `playoff_round` is set, a score report is a forfeit when `forfeit_team_id` is set, and standings use the newest report per game (`LatestScoreReport` view). Triggers in `db/phase3.sql` enforce that only the game's assigned official (not one who declined) submits a score report, reports are never edited, a forfeit names one of the game's teams, a game's teams play in its league, officials are assigned and file incidents, and admins assign officials and review incidents.

Roster statuses: `invited` → `active`, `declined`, `removed` or `left`. Two database triggers (`db/roster.sql`) also enforce that a captain is always an active member of their team and that a player is active on at most one team per league.

Errors always come back as `{"detail": "readable message"}`: 401 not signed in, 403 not allowed, 404 not found, 409 a broken rule (e.g. duplicate team name, roster locked, team full), 422 bad input.

## Running the frontend

1. `cd frontend`
2. `npm install`
3. `npm run dev`, then open http://localhost:5173 (the backend only allows this origin)
