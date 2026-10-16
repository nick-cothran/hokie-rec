import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

# Load environment variables from the project root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]


def db():
    # Commits when the `with` block ends, rolls back if it raises
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


@asynccontextmanager
async def lifespan(app):
    info = health()
    print(f"Connected to {info['version'].split(' on ')[0]} (database: {info['database']}), "
          f"{info['leagues']} leagues, {info['teams']} teams")
    yield


app = FastAPI(lifespan=lifespan)

# Allow requests from the React development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRIENDLY_ERRORS = {
    "team_league_id_team_name_key": "A team with that name already exists in this league.",
    "team_league_id_fkey": "That league does not exist.",
    # Game and ScoreReport reference Team with ON DELETE RESTRICT
    "game_home_team_id_fkey": "This team has games on the schedule or in the results, so it can't be deleted.",
    "game_away_team_id_fkey": "This team has games on the schedule or in the results, so it can't be deleted.",
    "scorereport_forfeit_team_id_fkey": "This team has score reports on record, so it can't be deleted.",
}


@app.exception_handler(psycopg.errors.IntegrityError)
def integrity_error(request, e):
    message = FRIENDLY_ERRORS.get(e.diag.constraint_name, e.diag.message_primary)
    return JSONResponse(status_code=409, content={"detail": message})


@app.exception_handler(psycopg.DataError)
def data_error(request, e):
    # Bad values pydantic can't catch (NUL bytes, out-of-range ids); some are raised client-side with no diag
    return JSONResponse(status_code=422, content={"detail": e.diag.message_primary or str(e)})


TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class NewTeam(BaseModel):
    league_id: int
    team_name: TeamName
    user_id: int  # shortcut: caller says who they are (no login), add real auth if this leaves the class demo


class TeamRename(BaseModel):
    team_name: TeamName
    user_id: int


def require_captain(conn, team_id, user_id):
    team = conn.execute("SELECT captain_id FROM Team WHERE team_id = %s", (team_id,)).fetchone()
    if team is None:
        raise HTTPException(404, "Team not found.")
    if team["captain_id"] != user_id:
        raise HTTPException(403, "Only the team captain can do that.")


@app.get("/api/health")
def health():
    with db() as conn:
        row = conn.execute("""
            SELECT version() AS version, current_database() AS database,
                   (SELECT COUNT(*) FROM League) AS leagues, (SELECT COUNT(*) FROM Team) AS teams
        """).fetchone()
    return {"status": "connected", **row}


@app.get("/api/users")
def list_users():
    with db() as conn:
        return conn.execute(
            "SELECT user_id, first_name, last_name, role FROM Users ORDER BY last_name, first_name"
        ).fetchall()


# S1: browse leagues by sport and term
@app.get("/api/leagues")
def list_leagues(sport: str | None = None, term: str | None = None):
    with db() as conn:
        return conn.execute("""
            SELECT l.league_id, l.league_name, l.sport_name, l.category, l.skill_level, l.term,
                   COUNT(t.team_id) AS team_count
            FROM League l LEFT JOIN Team t ON t.league_id = l.league_id
            WHERE (%(sport)s::text IS NULL OR l.sport_name = %(sport)s)
              AND (%(term)s::text IS NULL OR l.term = %(term)s)
            GROUP BY l.league_id
            ORDER BY l.league_name
        """, {"sport": sport, "term": term}).fetchall()


# S2: register a team; the captain's roster row goes in the same transaction
@app.post("/api/teams", status_code=201)
def register_team(body: NewTeam):
    with db() as conn:
        eligible = conn.execute("""
            SELECT 1 FROM Users WHERE user_id = %s AND role = 'player' AND is_active
              AND (suspended_until IS NULL OR suspended_until < CURRENT_DATE)
        """, (body.user_id,)).fetchone()
        if not eligible:
            raise HTTPException(403, "Only active, non-suspended players can register a team.")
        # status and registered_at come from their column DEFAULTs ('active', NOW())
        team = conn.execute("""
            INSERT INTO Team (league_id, captain_id, team_name)
            VALUES (%s, %s, %s)
            RETURNING team_id
        """, (body.league_id, body.user_id, body.team_name)).fetchone()
        conn.execute("""
            INSERT INTO RosterMembership (team_id, user_id, status, invited_at, joined_at)
            VALUES (%s, %s, 'active', NOW(), NOW())
        """, (team["team_id"], body.user_id))
    return team


# Team directory: lets the UI reach a team without typing its id
@app.get("/api/teams")
def list_teams(league_id: int | None = None):
    with db() as conn:
        return conn.execute("""
            SELECT t.team_id, t.team_name, t.status, l.league_id, l.league_name, l.sport_name, l.term,
                   u.first_name AS captain_first_name, u.last_name AS captain_last_name,
                   COUNT(r.membership_id) FILTER (WHERE r.status = 'active') AS member_count
            FROM Team t
            JOIN League l ON l.league_id = t.league_id
            JOIN Users u ON u.user_id = t.captain_id
            LEFT JOIN RosterMembership r ON r.team_id = t.team_id
            WHERE (%(league_id)s::int IS NULL OR t.league_id = %(league_id)s)
            GROUP BY t.team_id, l.league_id, u.user_id
            ORDER BY l.league_name, t.team_name
        """, {"league_id": league_id}).fetchall()


@app.get("/api/teams/{team_id}")
def get_team(team_id: int):
    with db() as conn:
        team = conn.execute("""
            SELECT t.team_id, t.team_name, t.status, t.captain_id, l.league_id, l.league_name
            FROM Team t JOIN League l ON l.league_id = t.league_id
            WHERE t.team_id = %s
        """, (team_id,)).fetchone()
        if team is None:
            raise HTTPException(404, "Team not found.")
        team["roster"] = conn.execute("""
            SELECT u.user_id, u.first_name, u.last_name, r.status
            FROM RosterMembership r JOIN Users u ON u.user_id = r.user_id
            WHERE r.team_id = %s
            ORDER BY r.status, u.last_name
        """, (team_id,)).fetchall()
    return team


# S3: the captain renames their team
@app.patch("/api/teams/{team_id}")
def rename_team(team_id: int, body: TeamRename):
    with db() as conn:
        require_captain(conn, team_id, body.user_id)
        return conn.execute(
            "UPDATE Team SET team_name = %s WHERE team_id = %s RETURNING team_id, team_name",
            (body.team_name, team_id),
        ).fetchone()


# The captain deletes their team: roster rows CASCADE, a team with games is blocked by RESTRICT (409)
@app.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: int, user_id: int):
    with db() as conn:
        require_captain(conn, team_id, user_id)
        conn.execute("DELETE FROM Team WHERE team_id = %s", (team_id,))


# S4: the captain withdraws a pending invite; active and former members keep their rows
@app.delete("/api/teams/{team_id}/invites/{player_id}", status_code=204)
def withdraw_invite(team_id: int, player_id: int, user_id: int):
    with db() as conn:
        require_captain(conn, team_id, user_id)
        deleted = conn.execute("""
            DELETE FROM RosterMembership
            WHERE team_id = %s AND user_id = %s AND status = 'invited'
        """, (team_id, player_id)).rowcount
    if not deleted:
        raise HTTPException(404, "No pending invite for that player on this team.")
