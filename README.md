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

   `migrate.py` brings an existing database up to date (authentication tables, roster rules, and the Phase III schema in `db/phase3.sql`) without losing data; it is safe to rerun. On a pre-Phase III database it moves roster limits into `Sport` and drops the derived columns `League.league_name`, `Game.game_type` and `ScoreReport.is_forfeit`, and stops without changes if any of them disagrees with the data that replaces it. All 135 seeded users (`simvt0001`–`simvt0135`) use password `hokie`. The administrators are `simvt0133`–`simvt0135`; sign in as one and open **Admin** to create officials and other administrators. Anyone can change their password from **Account**. Add `--reset` to the account-seeding command to replace existing demo passwords; sign-up accounts are unaffected.

   **Profile:** Open **Account** to edit your first name, last name, email, and optional phone number. Saved names appear immediately in the header and on rosters. PID and role are read-only; password changes remain available on the profile page. No additional migration or seeding is needed.

   **Schedule a game:** Sign in as an administrator and open **Schedule → Schedule a game**. Choose two active teams in the same league, a facility, and future start/end times in your device's time zone. The application checks for overlapping team and facility bookings. This creates one regular-season game; assigning officials is a separate step.

3. From `/backend` (venv active), run `uvicorn main:app --reload`. The terminal prints the DB connection on startup.
4. Open http://localhost:8000/docs to try every endpoint in the browser.
5. Tests: `python -m unittest` from `/backend`. They build a throwaway schema from `db/*.sql` inside the dev database and drop it afterwards, so your data is untouched.

   **Demo walkthrough (no SQL needed):** the seed is dated so every feature can be shown through the app, as of mid-November 2026:

   - **Register a team:** six Spring 2027 leagues (one per Fall sport) opened registration on Nov 1. Sign in as any player, e.g. `simvt0001`.
   - **Enter a result:** the Fall semifinals (Oct 19–24) are over but unscored. Sign in as an official, e.g. `simvt0121`, open **Schedule** and click **Enter result** on a semifinal. Submitting again records a correction; the history keeps every report.
   - **Accept or decline an assignment:** the Fall championship games are on Dec 5–6. As the same official, use **Accept** / **Decline** on the final.

   After pulling a seed change, rebuild your local database so you get the new dates: `docker compose down -v`, then repeat steps 1–2 (this deletes local data).

   If registering a team fails with `null value in column "status"`, your Docker volume predates the schema's column defaults. Recreate it (this deletes local data): `docker compose down -v`, then repeat steps 1–2.

## API (base URL `http://localhost:8000`)

Sign in first: the browser keeps a session cookie, and every write also needs the `X-Requested-With: HokieRec` header (the frontend's `api()` adds it). "Captain" means the captain of that team.

| Method | Path | Body / query | Who | Notes |
|---|---|---|---|---|
| POST | `/api/auth/sign-up` | `{vt_pid, first_name, last_name, email, phone, password}` | anyone | Creates a player and signs in. 201 |
| POST | `/api/auth/login` | `{vt_pid, password}` | anyone | 200 → user; 429 after 10 failed tries in 15 min |
| GET | `/api/auth/me` | | signed in | Current user; 401 if not signed in |
| GET | `/api/me/profile` | | signed in | Own PID, name, contact details, role and join date. Private; never returns credentials or disciplinary information |
| PUT | `/api/me/profile` | `{first_name, last_name, email, phone}` | signed in | Updates only your own name/contact details. Send `phone: null` to remove it. 409 duplicate email; 422 invalid or extra fields. PID, role, and password cannot be changed here |
| POST | `/api/auth/logout` | | anyone | 204 |
| POST | `/api/auth/password` | `{current_password, new_password}` | signed in | New password 12–128 characters. 400 if the current password is wrong or unchanged; 429 after 10 wrong tries in 15 min. Signs out your other browsers and rotates this one's session. 204 |
| POST | `/api/auth/password/verify` | `{current_password}` | signed in | Checks the current password for the first step of changing it; shares the password-change attempt limit. 204 |
| GET | `/api/admin/users` | | admin | Every account: PID, name, email, role, `is_active`, `created_at` (never password hashes) |
| POST | `/api/admin/users` | `{vt_pid, first_name, last_name, email, phone, role, password}` | admin | Creates a `player`, `official` or `admin` with an initial password (same rules as sign-up). The admin stays signed in. 409 duplicate PID/email. 201 → user |
| GET | `/api/admin/facilities` | | admin | Facilities available for scheduling |
| POST | `/api/admin/games` | `{league_id, facility_id, home_team_id, away_team_id, start_time, end_time}` | admin | Creates a regular-season game; times must include a time zone. 409 if a team or facility overlaps another game. 201 → `{game_id}` |
| GET | `/api/health` | | anyone | `{status, version, database, leagues, teams}` |
| GET | `/api/leagues` | `?sport=Soccer&term=Fall 2026` (both optional) | anyone | S1. Leagues with `team_count` |
| GET | `/api/teams` | `?league_id=1` (optional) | anyone | Team directory with league, captain and `member_count` |
| GET | `/api/me/teams` | | signed in | Teams where the current user is an active roster member, including whether they are captain |
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
| GET | `/api/me/games` | | signed in | Upcoming/in-progress games and five most recent completed games for the current user's active teams |
| GET | `/api/me/assignments` | | signed in | Your officiating assignments with game details, `assignment_status`, `can_respond` and `has_ended` (the game is over, so its result can be entered); `[]` for non-officials |
| GET | `/api/games/{game_id}/score-reports` | | game's officials, admins | The game, every submitted report (newest is `is_current`), `can_submit` and `blocked_reason` |
| POST | `/api/games/{game_id}/score-reports` | `{home_score, away_score}` or `{forfeit_team_id}` | assigned official | After the game's scheduled end, with both teams decided, unless you declined. A later report is a correction; earlier ones are kept. Marks the game `completed`. 201 |
| POST | `/api/assignments/{assignment_id}/accept` | | assigned official | Only while `assigned` and before the game starts. 404 if it isn't yours; 409 if already answered or started. 204 |
| POST | `/api/assignments/{assignment_id}/decline` | | assigned official | Same rules as accept. A declined official can't submit the game's score. 204 |
| GET | `/api/incidents` | | official or admin | Private reports: an official sees reports they filed; admins see all reports |
| POST | `/api/games/{game_id}/incident-reports` | `{incident_type, description, involved_user_pid?}` | assigned official | Files an open report for an assigned game; optional PID identifies an involved user. 201 |
| PATCH | `/api/incidents/{incident_id}` | `{status: "reviewed" \| "dismissed"}` | admin | Resolves an open report and records the reviewing administrator. 409 if already resolved |
| GET | `/api/reports/standings` | `?league_id=1` | anyone | Report 1. Regular-season W/L/T and points per team; forfeit = loss for the forfeiting team. 404 if no league |
| GET | `/api/reports/participation` | `?term=Fall 2026` (optional) | anyone | Report 2. Teams, active players, pending invites, avg roster, games played/left per league |

Schema (Phase III): roster limits live on `Sport`; a league's display name (`league_name`, e.g. "Coed Soccer, Recreational, Fall 2026") and its sport's limits come from the `LeagueView` view. A game is a playoff game when `playoff_round` is set, a score report is a forfeit when `forfeit_team_id` is set, and standings use the newest report per game (`LatestScoreReport` view). Triggers in `db/phase3.sql` enforce that only the game's assigned official (not one who declined) submits a score report, reports are never edited, a forfeit names one of the game's teams, a game's teams play in its league, officials are assigned and file incidents, and admins assign officials and review incidents.

Incident reports are private to assigned officials and administrators. Officials may file reports for games assigned to them unless they declined or the game was cancelled. Administrators may mark an open report reviewed or dismissed; resolved reports cannot be changed through the API.

Roster statuses: `invited` → `active`, `declined`, `removed` or `left`. Two database triggers (`db/roster.sql`) also enforce that a captain is always an active member of their team and that a player is active on at most one team per league.

Errors always come back as `{"detail": "readable message"}`: 401 not signed in, 403 not allowed, 404 not found, 409 a broken rule (e.g. duplicate team name, roster locked, team full), 422 bad input.

## Running the frontend

1. `cd frontend`
2. `npm install`
3. `npm run dev`, then open http://localhost:5173 (the backend only allows this origin)
