# hokie-rec

## Setup

1. Create a `.env` file, and copy the contents of `.env.example` into it.
2. Within the `/backend` folder, create a python venv, then run `pip install -r requirements.txt`
3. Within the `/frontend` folder, run `npm install`

## Running the backend

1. With the docker engine running, run `docker compose up -d` from the root directory.
2. To seed data, run `npm run seed`.
3. From `/backend` (venv active), run `uvicorn main:app --reload`. The terminal prints the DB connection on startup.
4. Open http://localhost:8000/docs to try every endpoint in the browser.
5. Tests (needs the seeded DB): `python -m unittest` from `/backend`. They write to the dev DB and delete only the "Test ..." teams they create.

## API (base URL `http://localhost:8000`)

There is no login yet: the UI's "Choose user" page (`/sign-in`) picks an "acting as" user from `GET /api/users` and sends that `user_id`.

| Method | Path | Body / query | Notes |
|---|---|---|---|
| GET | `/api/health` | | `{status, version, database, leagues, teams}` for the connection card |
| GET | `/api/users` | | `user_id, first_name, last_name, role` for the "acting as" picker |
| GET | `/api/leagues` | `?sport=Soccer&term=Fall 2026` (both optional) | S1. Leagues with `team_count` |
| GET | `/api/teams` | `?league_id=1` (optional) | Team directory with league, captain and `member_count` |
| POST | `/api/teams` | `{league_id, team_name, user_id}` | S2. `user_id` becomes captain. 201 → `{team_id}` |
| GET | `/api/teams/{team_id}` | | Team, league and `roster` |
| PATCH | `/api/teams/{team_id}` | `{team_name, user_id}` | S3. Captain only. 200 → `{team_id, team_name}` |
| DELETE | `/api/teams/{team_id}` | `?user_id=` | Captain only. Roster rows cascade; 409 if the team has games (RESTRICT). 204 |
| DELETE | `/api/teams/{team_id}/invites/{player_id}` | `?user_id=` | S4. Captain only, pending invites only. 204 |
| GET | `/api/reports/standings` | `?league_id=1` | Report 1. Regular-season W/L/T and points per team; forfeit = loss for the forfeiting team. 404 if no league |
| GET | `/api/reports/participation` | `?term=Fall 2026` (optional) | Report 2. Teams, active players, pending invites, avg roster, games played/left per league |

Errors always come back as `{"detail": "readable message"}`: 409 for a broken DB rule (e.g. duplicate team name in a league), 403 not allowed, 404 not found, 422 bad input.

## Running the frontend

1. `cd frontend`
2. `npm install`
3. `npm run dev`, then open http://localhost:5173 (the backend only allows this origin)
