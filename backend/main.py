import psycopg

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from database import db
from admin import Admin, router as admin_router
from auth import AuthenticatedUser, router as auth_router
from incidents import router as incidents_router
from scores import router as scores_router
from profiles import router as profiles_router
from playoffs import router as playoffs_router
from standings import bracket_seed_order, league_standings


@asynccontextmanager
async def lifespan(app):
    info = health()
    print(f"Connected to {info['version'].split(' on ')[0]} (database: {info['database']}), "
          f"{info['leagues']} leagues, {info['teams']} teams")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(incidents_router)
app.include_router(scores_router)
app.include_router(profiles_router)
app.include_router(playoffs_router)
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    # A custom header forces cross-origin browser writes through CORS preflight.
    # Check Origin too: SameSite alone does not protect against sibling origins.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if request.headers.get("x-requested-with") != "HokieRec" or (origin is not None and origin not in ALLOWED_ORIGINS):
            return JSONResponse(status_code=403, content={"detail": "Request could not be verified. Refresh the page and try again."})
    response = await call_next(request)
    if request.url.path.startswith("/api/auth/") or request.url.path.endswith("/eligibility") or request.url.path in ("/api/me/profile", "/api/me/teams", "/api/me/games", "/api/me/membership-history"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Allow requests from the React development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
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
    # Raised by the triggers in db/roster.sql
    "team_captain_on_roster": "A team's captain must be an active member of its roster.",
    "roster_one_team_per_league": "A player can be on only one team per league.",
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
    model_config = ConfigDict(extra="forbid")

    league_id: int
    team_name: TeamName


class Invite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vt_pid: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class NewCaptain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int


class TeamRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_name: TeamName

class NewAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: int
    official_id: int
    position: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)] = "referee"


class PlayerSuspension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suspended_until: date | None


# Today on campus; roster lock dates are Blacksburg calendar dates
LOCAL_TODAY = "(NOW() AT TIME ZONE 'America/New_York')::date"


def fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def ineligible_reason(conn, user_id: int, league_id: int) -> str | None:
    """Why this user can't be active on a team in this league, or None."""
    row = conn.execute(f"""
        SELECT role = 'player' AND is_active AS player,
               CASE WHEN suspended_until >= {LOCAL_TODAY} THEN suspended_until END AS suspended_until,
               EXISTS (SELECT 1 FROM RosterMembership r JOIN Team t ON t.team_id = r.team_id
                       WHERE r.user_id = u.user_id AND r.status = 'active' AND t.league_id = %s) AS in_league
        FROM Users u WHERE user_id = %s
    """, (league_id, user_id)).fetchone()
    if not row["player"]:
        return "Only active players can join teams."
    if row["suspended_until"]:
        return "Suspended players can't join teams."  # never reveal the disciplinary end date
    if row["in_league"]:
        return "Already on a team in this league."
    return None


def team_rules(conn, team_id: int, *, for_update: bool = False) -> dict:
    """The team with its league's roster rules. for_update serializes roster changes on this team."""
    team = conn.execute(f"""
        SELECT t.team_id, t.team_name, t.captain_id, t.league_id, l.min_roster_size, l.max_roster_size,
               l.roster_lock_date, {LOCAL_TODAY} >= l.roster_lock_date AS roster_locked
        FROM Team t JOIN LeagueView l ON l.league_id = t.league_id
        WHERE t.team_id = %s {"FOR UPDATE OF t" if for_update else ""}
    """, (team_id,)).fetchone()
    if team is None:
        raise HTTPException(404, "Team not found.")
    # Counted after the lock so concurrent accepts see each other's commits
    team["active_count"] = conn.execute(
        "SELECT COUNT(*) AS n FROM RosterMembership WHERE team_id = %s AND status = 'active'", (team_id,)).fetchone()["n"]
    return team


def require_team_captain(team: dict, user: dict):
    if team["captain_id"] != user["user_id"]:
        raise HTTPException(403, "Only the team captain can do that.")


def require_unlocked(team: dict):
    if team["roster_locked"]:
        raise HTTPException(409, f"The roster is locked (lock date {fmt_date(team['roster_lock_date'])}).")

@app.get("/api/health")
def health():
    with db() as conn:
        row = conn.execute("""
            SELECT version() AS version, current_database() AS database,
                   (SELECT COUNT(*) FROM League) AS leagues, (SELECT COUNT(*) FROM Team) AS teams
        """).fetchone()
    return {"status": "connected", **row}


# S1: browse leagues by sport and term
@app.get("/api/leagues")
def list_leagues(sport: str | None = None, term: str | None = None):
    with db() as conn:
        return conn.execute(f"""
            SELECT l.league_id, l.league_name, l.sport_name, l.category, l.skill_level, l.term, l.min_roster_size,
                   l.start_date, l.end_date, l.reg_open_at, l.reg_close_at,
                   (NOW() BETWEEN l.reg_open_at AND l.reg_close_at AND {LOCAL_TODAY} < l.roster_lock_date
                    AND NOT EXISTS (SELECT 1 FROM Game pg WHERE pg.league_id = l.league_id AND pg.playoff_round IS NOT NULL)) AS registration_open,
                   CASE
                     WHEN EXISTS (SELECT 1 FROM Game pg WHERE pg.league_id = l.league_id AND pg.playoff_round IS NOT NULL)
                          OR {LOCAL_TODAY} >= l.roster_lock_date OR NOW() > l.reg_close_at THEN 'closed'
                     WHEN NOW() < l.reg_open_at AND l.reg_open_at < (l.roster_lock_date::timestamp AT TIME ZONE 'America/New_York') THEN 'upcoming'
                     WHEN NOW() BETWEEN l.reg_open_at AND l.reg_close_at THEN 'open'
                     ELSE 'closed'
                   END AS registration_status,
                   (SELECT COUNT(*) FROM Team t WHERE t.league_id = l.league_id) AS team_count
            FROM LeagueView l
            WHERE (%(sport)s::text IS NULL OR l.sport_name = %(sport)s)
              AND (%(term)s::text IS NULL OR l.term = %(term)s)
            ORDER BY l.start_date, l.league_name
        """, {"sport": sport, "term": term}).fetchall()


# S2: register a team; the captain's roster row goes in the same transaction
@app.post("/api/teams", status_code=201)
def register_team(body: NewTeam, user: AuthenticatedUser):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        eligible = conn.execute(f"""
            SELECT 1 FROM Users WHERE user_id = %s AND role = 'player' AND is_active
              AND (suspended_until IS NULL OR suspended_until < {LOCAL_TODAY})
        """, (user["user_id"],)).fetchone()
        if not eligible:
            raise HTTPException(403, "Only active, non-suspended players can register a team.")
        # Lock the player so two registrations at once can't both pass the league check
        conn.execute("SELECT 1 FROM Users WHERE user_id = %s FOR UPDATE", (user["user_id"],))
        open_now = conn.execute(f"""SELECT (NOW() BETWEEN reg_open_at AND reg_close_at AND {LOCAL_TODAY} < roster_lock_date
                   AND NOT EXISTS (SELECT 1 FROM Game pg WHERE pg.league_id = League.league_id AND pg.playoff_round IS NOT NULL)) AS open
                   FROM League WHERE league_id = %s""",
                                (body.league_id,)).fetchone()
        if open_now is not None and not open_now["open"]:  # unknown league falls through to the FK's 409
            raise HTTPException(409, "Registration for this league is not open.")
        if reason := ineligible_reason(conn, user["user_id"], body.league_id):
            raise HTTPException(409, reason)
        # status and registered_at come from their column DEFAULTs ('active', NOW())
        team = conn.execute("""
            INSERT INTO Team (league_id, captain_id, team_name)
            VALUES (%s, %s, %s)
            RETURNING team_id
        """, (body.league_id, user["user_id"], body.team_name)).fetchone()
        conn.execute("""
            INSERT INTO RosterMembership (team_id, user_id, status, invited_at, joined_at)
            VALUES (%s, %s, 'active', NOW(), NOW())
        """, (team["team_id"], user["user_id"]))
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
            JOIN LeagueView l ON l.league_id = t.league_id
            JOIN Users u ON u.user_id = t.captain_id
            LEFT JOIN RosterMembership r ON r.team_id = t.team_id
            WHERE (%(league_id)s::int IS NULL OR t.league_id = %(league_id)s)
            GROUP BY t.team_id, l.league_id, l.league_name, l.sport_name, l.term, l.start_date, u.user_id
            ORDER BY l.start_date, l.league_name, t.team_name
        """, {"league_id": league_id}).fetchall()


@app.get("/api/me/teams")
def my_teams(user: AuthenticatedUser):
    with db() as conn:
        return conn.execute("""
            SELECT t.team_id, t.team_name, t.status, l.league_id, l.league_name, l.sport_name, l.term,
                   u.first_name AS captain_first_name, u.last_name AS captain_last_name,
                   t.captain_id = %(user_id)s AS is_captain,
                   COUNT(r.membership_id) FILTER (WHERE r.status = 'active') AS member_count
            FROM Team t
            JOIN RosterMembership mine ON mine.team_id = t.team_id AND mine.user_id = %(user_id)s AND mine.status = 'active'
            JOIN LeagueView l ON l.league_id = t.league_id
            JOIN Users u ON u.user_id = t.captain_id
            LEFT JOIN RosterMembership r ON r.team_id = t.team_id
            GROUP BY t.team_id, l.league_id, l.league_name, l.sport_name, l.term, l.start_date, u.user_id
            ORDER BY l.start_date DESC, l.league_name, t.team_name
        """, {"user_id": user["user_id"]}).fetchall()


@app.get("/api/teams/{team_id}")
def get_team(team_id: int):
    with db() as conn:
        team = conn.execute(f"""
            SELECT t.team_id, t.team_name, t.status, t.captain_id, l.league_id, l.league_name,
                   l.min_roster_size, l.max_roster_size, l.roster_lock_date,
                   {LOCAL_TODAY} >= l.roster_lock_date AS roster_locked
            FROM Team t JOIN LeagueView l ON l.league_id = t.league_id
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


@app.get("/api/teams/{team_id}/eligibility")
def roster_eligibility(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id)
        if user['role'] != 'admin' and team['captain_id'] != user['user_id']:
            raise HTTPException(403, "Only the captain or an administrator can view roster eligibility.")
        return conn.execute(f"""
            SELECT r.user_id, (u.suspended_until >= {LOCAL_TODAY}) IS TRUE AS suspended
            FROM RosterMembership r JOIN Users u ON u.user_id = r.user_id
            WHERE r.team_id = %s AND r.status = 'active'
        """, (team_id,)).fetchall()


# S3: the captain renames their team
@app.patch("/api/teams/{team_id}")
def rename_team(team_id: int, body: TeamRename, user: AuthenticatedUser):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        team = team_rules(conn, team_id, for_update=True)
        require_team_captain(team, user)
        before_seeds = bracket_seed_order(conn, team['league_id'])
        updated = conn.execute(
            "UPDATE Team SET team_name = %s WHERE team_id = %s RETURNING team_id, team_name",
            (body.team_name, team_id),
        ).fetchone()
        if before_seeds is not None and before_seeds != bracket_seed_order(conn, team['league_id']):
            raise HTTPException(409, "This name would change playoff seed order. Remove the unplayed bracket before renaming the team.")
        return updated


# The captain deletes their team: roster rows CASCADE, a team with games is blocked by RESTRICT (409)
@app.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        require_team_captain(team_rules(conn, team_id), user)
        conn.execute("DELETE FROM Team WHERE team_id = %s", (team_id,))


# S4: the captain withdraws a pending invite, any time. A former member's re-invite becomes
# 'removed' instead of being deleted, keeping their joined_at/left_at history.
@app.delete("/api/teams/{team_id}/invites/{player_id}", status_code=204)
def withdraw_invite(team_id: int, player_id: int, user: AuthenticatedUser):
    with db() as conn:
        # Same Team lock as accept, so a withdraw and an accept can't interleave
        require_team_captain(team_rules(conn, team_id, for_update=True), user)
        changed = conn.execute("""
            DELETE FROM RosterMembership
            WHERE team_id = %s AND user_id = %s AND status = 'invited' AND joined_at IS NULL
        """, (team_id, player_id)).rowcount or conn.execute("""
            UPDATE RosterMembership SET status = 'removed'
            WHERE team_id = %s AND user_id = %s AND status = 'invited'
        """, (team_id, player_id)).rowcount
    if not changed:
        raise HTTPException(404, "No pending invite for that player on this team.")


# The captain invites a player by PID. A former member's row is reused (UNIQUE(team_id, user_id)).
@app.post("/api/teams/{team_id}/invites", status_code=201)
def invite_player(team_id: int, body: Invite, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id)
        require_team_captain(team, user)
        require_unlocked(team)
        player = conn.execute("SELECT user_id, first_name, last_name FROM Users WHERE LOWER(vt_pid) = %s",
                              (body.vt_pid.lower(),)).fetchone()
        if player is None:
            raise HTTPException(404, "No player with that PID.")
        existing = conn.execute("SELECT status FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                                (team_id, player["user_id"])).fetchone()
        if existing and existing["status"] in ("invited", "active"):
            raise HTTPException(409, "That player is already invited to or on this team.")
        if reason := ineligible_reason(conn, player["user_id"], team["league_id"]):
            raise HTTPException(409, reason)
        if existing:
            conn.execute("""
                UPDATE RosterMembership SET status = 'invited', invited_at = NOW()
                WHERE team_id = %s AND user_id = %s
            """, (team_id, player["user_id"]))
        else:
            conn.execute("""
                INSERT INTO RosterMembership (team_id, user_id, status, invited_at) VALUES (%s, %s, 'invited', NOW())
            """, (team_id, player["user_id"]))
    return {**player, "status": "invited"}


# The signed-in user's pending invites, for the Teams page
@app.get("/api/me/invites")
def my_invites(user: AuthenticatedUser):
    with db() as conn:
        return conn.execute(f"""
            SELECT t.team_id, t.team_name, l.league_id, l.league_name,
                   u.first_name AS captain_first_name, u.last_name AS captain_last_name,
                   l.roster_lock_date, {LOCAL_TODAY} >= l.roster_lock_date AS roster_locked,
                   (SELECT COUNT(*) FROM RosterMembership a WHERE a.team_id = t.team_id AND a.status = 'active') AS active_count,
                   l.max_roster_size
            FROM RosterMembership r
            JOIN Team t ON t.team_id = r.team_id
            JOIN LeagueView l ON l.league_id = t.league_id
            JOIN Users u ON u.user_id = t.captain_id
            WHERE r.user_id = %s AND r.status = 'invited'
            ORDER BY l.roster_lock_date, t.team_name
        """, (user["user_id"],)).fetchall()


def require_pending_invite(conn, team_id: int, user_id: int):
    if not conn.execute("SELECT 1 FROM RosterMembership WHERE team_id = %s AND user_id = %s AND status = 'invited'",
                        (team_id, user_id)).fetchone():
        raise HTTPException(404, "You don't have a pending invite to this team.")


# The invitee joins. Their other pending invites in this league are declined, since they can't join those too.
@app.post("/api/teams/{team_id}/invite/accept", status_code=204)
def accept_invite(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        require_pending_invite(conn, team_id, user["user_id"])
        require_unlocked(team)
        if team["active_count"] >= team["max_roster_size"]:
            raise HTTPException(409, f"This team is full ({team['active_count']}/{team['max_roster_size']}).")
        conn.execute("SELECT 1 FROM Users WHERE user_id = %s FOR UPDATE", (user["user_id"],))
        if reason := ineligible_reason(conn, user["user_id"], team["league_id"]):
            raise HTTPException(409, reason)
        if not conn.execute("""
            UPDATE RosterMembership SET status = 'active', joined_at = NOW(), left_at = NULL
            WHERE team_id = %s AND user_id = %s AND status = 'invited'
        """, (team_id, user["user_id"])).rowcount:
            raise HTTPException(404, "You don't have a pending invite to this team.")
        conn.execute("""
            UPDATE RosterMembership SET status = 'declined'
            WHERE user_id = %s AND status = 'invited'
              AND team_id IN (SELECT team_id FROM Team WHERE league_id = %s AND team_id <> %s)
        """, (user["user_id"], team["league_id"], team_id))


# The invitee says no; allowed any time
@app.post("/api/teams/{team_id}/invite/decline", status_code=204)
def decline_invite(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        declined = conn.execute("""
            UPDATE RosterMembership SET status = 'declined'
            WHERE team_id = %s AND user_id = %s AND status = 'invited'
        """, (team_id, user["user_id"])).rowcount
    if not declined:
        raise HTTPException(404, "You don't have a pending invite to this team.")


# The captain removes an active member; the row stays as history
@app.delete("/api/teams/{team_id}/members/{player_id}", status_code=204)
def remove_member(team_id: int, player_id: int, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        require_team_captain(team, user)
        require_unlocked(team)
        if player_id == team["captain_id"]:
            raise HTTPException(409, "The captain can't be removed. Hand off captaincy first.")
        removed = conn.execute("""
            UPDATE RosterMembership SET status = 'removed', left_at = NOW()
            WHERE team_id = %s AND user_id = %s AND status = 'active'
        """, (team_id, player_id)).rowcount
    if not removed:
        raise HTTPException(404, "That player isn't an active member of this team.")


# An active member leaves before the roster lock date; the captain must hand off first
@app.post("/api/teams/{team_id}/leave", status_code=204)
def leave_team(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        if user["user_id"] == team["captain_id"]:
            raise HTTPException(409, "Hand off captaincy before leaving the team.")
        require_unlocked(team)
        left = conn.execute("""
            UPDATE RosterMembership SET status = 'left', left_at = NOW()
            WHERE team_id = %s AND user_id = %s AND status = 'active'
        """, (team_id, user["user_id"])).rowcount
    if not left:
        raise HTTPException(404, "You aren't an active member of this team.")


# The captain hands captaincy to an active member. Allowed after the lock date: the roster doesn't change.
@app.put("/api/teams/{team_id}/captain")
def hand_off_captaincy(team_id: int, body: NewCaptain, user: AuthenticatedUser):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        require_team_captain(team, user)
        if body.user_id == team["captain_id"]:
            raise HTTPException(409, "You're already the captain.")
        if not conn.execute("SELECT 1 FROM RosterMembership WHERE team_id = %s AND user_id = %s AND status = 'active'",
                            (team_id, body.user_id)).fetchone():
            raise HTTPException(409, "The new captain must be an active member of this team.")
        return conn.execute("UPDATE Team SET captain_id = %s WHERE team_id = %s RETURNING team_id, captain_id",
                            (body.user_id, team_id)).fetchone()


@app.put("/api/admin/teams/{team_id}/captain")
def admin_reassign_captain(team_id: int, body: NewCaptain, user: Admin):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        if body.user_id == team['captain_id']:
            raise HTTPException(409, "This player is already captain.")
        if not conn.execute("SELECT 1 FROM RosterMembership WHERE team_id = %s AND user_id = %s AND status = 'active'", (team_id, body.user_id)).fetchone():
            raise HTTPException(409, "The new captain must be an active member of this team.")
        return conn.execute("UPDATE Team SET captain_id = %s WHERE team_id = %s RETURNING team_id, captain_id", (body.user_id, team_id)).fetchone()


@app.get("/api/me/membership-history")
def membership_history(user: AuthenticatedUser):
    with db() as conn:
        return conn.execute("""
            SELECT p.period_id, p.team_id, COALESCE(t.team_name, p.team_name) AS team_name,
                   COALESCE(l.league_name, p.league_name) AS league_name,
                   COALESCE(p.end_reason, 'active') AS status, p.joined_at, p.left_at
            FROM MembershipPeriod p LEFT JOIN Team t ON t.team_id = p.team_id
            LEFT JOIN LeagueView l ON l.league_id = t.league_id
            WHERE p.user_id = %s ORDER BY p.joined_at DESC, p.period_id DESC
        """, (user['user_id'],)).fetchall()


# A game with its league, place, teams (null for an undecided playoff game) and latest score; alias g
GAME_COLUMNS = """
    g.game_id, g.league_id, l.league_name, g.start_time, g.end_time, f.facility_name, f.location,
    g.home_team_id, h.team_name AS home_team_name, g.away_team_id, a.team_name AS away_team_name,
    g.playoff_round, g.next_game_id, g.status, s.home_score, s.away_score, s.forfeit_team_id,
    -- The league's bracket size, so a playoff round can be named (final, semifinal, ...)
    (SELECT MAX(x.playoff_round) FROM Game x WHERE x.league_id = g.league_id) AS playoff_rounds
"""
GAME_JOINS = """
    JOIN LeagueView l ON l.league_id = g.league_id
    JOIN Facility f ON f.facility_id = g.facility_id
    LEFT JOIN Team h ON h.team_id = g.home_team_id
    LEFT JOIN Team a ON a.team_id = g.away_team_id
    LEFT JOIN LatestScoreReport s ON s.game_id = g.game_id
"""


# Schedule and results, by league or team
@app.get("/api/games")
def list_games(league_id: int | None = None, team_id: int | None = None):
    with db() as conn:
        return conn.execute(f"""
            SELECT {GAME_COLUMNS} FROM Game g {GAME_JOINS}
            WHERE (%(league_id)s::int IS NULL OR g.league_id = %(league_id)s)
              AND (%(team_id)s::int IS NULL OR %(team_id)s IN (g.home_team_id, g.away_team_id))
            ORDER BY g.start_time, g.game_id
        """, {"league_id": league_id, "team_id": team_id}).fetchall()


@app.get("/api/me/games")
def my_games(user: AuthenticatedUser):
    with db() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        membership = """EXISTS (
            SELECT 1 FROM RosterMembership r
            WHERE r.user_id = %(user_id)s AND r.status = 'active'
              AND r.team_id IN (g.home_team_id, g.away_team_id)
        )"""
        upcoming = conn.execute(f"""
            SELECT {GAME_COLUMNS} FROM Game g {GAME_JOINS}
            WHERE {membership} AND g.status = 'scheduled' AND g.end_time >= NOW()
            ORDER BY g.start_time, g.game_id
        """, {"user_id": user["user_id"]}).fetchall()
        recent = conn.execute(f"""
            SELECT {GAME_COLUMNS} FROM Game g {GAME_JOINS}
            WHERE {membership} AND g.status <> 'cancelled' AND g.end_time < NOW()
            ORDER BY g.start_time DESC, g.game_id DESC LIMIT 5
        """, {"user_id": user["user_id"]}).fetchall()
    return {"upcoming": upcoming, "recent": recent}


# The signed-in official's assignments; anyone else has none
@app.get("/api/me/assignments")
def my_assignments(user: AuthenticatedUser):
    with db() as conn:
        return conn.execute(f"""
            SELECT oa.assignment_id, oa.position, oa.status AS assignment_status,
                   oa.status = 'assigned' AND g.status = 'scheduled' AND g.start_time > NOW() AS can_respond,
                   g.end_time <= NOW() AS has_ended, {GAME_COLUMNS}
            FROM OfficiatingAssignment oa JOIN Game g ON g.game_id = oa.game_id {GAME_JOINS}
            WHERE oa.official_id = %s
            ORDER BY g.start_time, g.game_id
        """, (user["user_id"],)).fetchall()


def answer_assignment(assignment_id: int, user: dict, status: str):
    """The official answers a pending assignment once, before the game starts."""
    if user["role"] != "official":  # a demoted official keeps their rows but can't answer them
        raise HTTPException(404, "You don't have that assignment.")
    user_id = user["user_id"]
    with db() as conn:
        game = conn.execute("""
            SELECT g.status FROM Game g JOIN OfficiatingAssignment oa ON oa.game_id = g.game_id
            WHERE oa.assignment_id = %s AND oa.official_id = %s FOR UPDATE OF g
        """, (assignment_id, user_id)).fetchone()
        if game is None:
            raise HTTPException(404, "You don't have that assignment.")
        if game['status'] != 'scheduled':
            raise HTTPException(409, "This game is no longer scheduled.")
        # One conditional UPDATE, so two tabs answering at once can't both win
        if conn.execute("""
            UPDATE OfficiatingAssignment oa SET status = %s FROM Game g
            WHERE g.game_id = oa.game_id AND oa.assignment_id = %s AND oa.official_id = %s
              AND oa.status = 'assigned' AND g.start_time > NOW()
        """, (status, assignment_id, user_id)).rowcount:
            return
        row = conn.execute("""
            SELECT oa.status FROM OfficiatingAssignment oa
            WHERE oa.assignment_id = %s AND oa.official_id = %s
        """, (assignment_id, user_id)).fetchone()
    if row is None:  # same answer for someone else's assignment, so ids reveal nothing
        raise HTTPException(404, "You don't have that assignment.")
    if row["status"] != "assigned":
        raise HTTPException(409, "You've already answered this assignment.")
    raise HTTPException(409, "This game has already started.")


@app.post("/api/assignments/{assignment_id}/accept", status_code=204)
def accept_assignment(assignment_id: int, user: AuthenticatedUser):
    answer_assignment(assignment_id, user, "accepted")


@app.post("/api/assignments/{assignment_id}/decline", status_code=204)
def decline_assignment(assignment_id: int, user: AuthenticatedUser):
    answer_assignment(assignment_id, user, "declined")

@app.get("/api/admin/officials")
def list_officials(user: Admin):
    with db() as conn:
        return conn.execute("""
            SELECT user_id, first_name, last_name, vt_pid
            FROM Users WHERE role = 'official' AND is_active
            ORDER BY last_name, first_name, user_id
        """).fetchall()


@app.get("/api/admin/games/coverage")
def game_coverage(user: Admin, league_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT g.game_id, COUNT(a.assignment_id) FILTER (WHERE a.status <> 'declined' AND u.is_active AND u.role = 'official') AS assigned_count
            FROM Game g LEFT JOIN OfficiatingAssignment a ON a.game_id = g.game_id
            LEFT JOIN Users u ON u.user_id = a.official_id
            WHERE g.league_id = %s AND g.status = 'scheduled'
            GROUP BY g.game_id ORDER BY g.start_time, g.game_id
        """, (league_id,)).fetchall()

@app.post("/api/admin/assignments", status_code=201)
def create_assignment(body: NewAssignment, user: Admin):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        game = conn.execute("""
            SELECT status, end_time <= NOW() AS ended FROM Game WHERE game_id = %s FOR UPDATE
        """, (body.game_id,)).fetchone()
        if game is None:
            raise HTTPException(404, "Game not found.")
        if game["status"] not in ("scheduled", "completed"):
            raise HTTPException(409, "Assignments can only be created for scheduled or completed games.")
        if game['status'] == 'completed' and not game['ended']:
            raise HTTPException(409, "A completed game's scheduled end must have passed before assigning an official for a correction.")
        official = conn.execute("""
            SELECT 1 FROM Users WHERE user_id = %s AND role = 'official' AND is_active
        """, (body.official_id,)).fetchone()
        if official is None:
            raise HTTPException(409, "Choose an active official.")
        if game["status"] == "scheduled" and conn.execute("""
            SELECT 1 FROM OfficiatingAssignment a JOIN Game existing ON existing.game_id = a.game_id
            JOIN Game target ON target.game_id = %s
            WHERE a.official_id = %s AND a.status <> 'declined' AND existing.status <> 'cancelled'
              AND existing.game_id <> target.game_id
              AND existing.start_time < target.end_time AND existing.end_time > target.start_time LIMIT 1
        """, (body.game_id, body.official_id)).fetchone():
            raise HTTPException(409, "This official is assigned to another game at that time.")
        assignment = conn.execute("""
            INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
            VALUES (%s, %s, %s, %s, 'assigned')
            ON CONFLICT (game_id, official_id) DO NOTHING
            RETURNING assignment_id, game_id, official_id, position, status
        """, (body.game_id, body.official_id, user["user_id"], body.position)).fetchone()
        if assignment is None:
            raise HTTPException(409, "This official is already assigned to that game.") from None
        return assignment


@app.get("/api/admin/games/{game_id}/assignments")
def game_assignments(game_id: int, user: Admin):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM Game WHERE game_id = %s", (game_id,)).fetchone():
            raise HTTPException(404, "Game not found.")
        return conn.execute("""
            SELECT a.assignment_id, a.official_id, a.position, a.status,
                   u.first_name, u.last_name, u.vt_pid
            FROM OfficiatingAssignment a JOIN Users u ON u.user_id = a.official_id
            WHERE a.game_id = %s ORDER BY u.last_name, u.first_name, a.assignment_id
        """, (game_id,)).fetchall()


@app.delete("/api/admin/assignments/{assignment_id}", status_code=204)
def remove_assignment(assignment_id: int, user: Admin):
    with db() as conn:
        assignment = conn.execute("""
            SELECT g.game_id, a.official_id FROM Game g JOIN OfficiatingAssignment a ON a.game_id = g.game_id
            WHERE a.assignment_id = %s FOR UPDATE OF g, a
        """, (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(404, "Assignment not found.")
        if conn.execute("""
            SELECT 1 FROM ScoreReport WHERE game_id = %s AND submitted_by = %s
            UNION ALL SELECT 1 FROM IncidentReport WHERE game_id = %s AND filed_by = %s LIMIT 1
        """, (assignment['game_id'], assignment['official_id'], assignment['game_id'], assignment['official_id'])).fetchone():
            raise HTTPException(409, "This official has filed a report for the game; their assignment must be kept.")
        conn.execute("DELETE FROM OfficiatingAssignment WHERE assignment_id = %s", (assignment_id,))

@app.get("/api/admin/players")
def list_players(user: Admin, q: str = ""):
    search = f"%{q.strip()}%"
    with db() as conn:
        return conn.execute(f"""
            SELECT user_id, vt_pid, first_name, last_name, is_active,
                   CASE WHEN suspended_until >= {LOCAL_TODAY} THEN suspended_until END AS suspended_until
            FROM Users
            WHERE role = 'player'
              AND (vt_pid ILIKE %(q)s OR first_name ILIKE %(q)s OR last_name ILIKE %(q)s)
            ORDER BY last_name, first_name, user_id
            LIMIT 100
        """, {"q": search}).fetchall()

@app.patch("/api/admin/players/{player_id}/suspension", status_code=204)
def set_player_suspension(player_id: int, body: PlayerSuspension, user: Admin):
    with db() as conn:
        if body.suspended_until is not None:
            valid_date = conn.execute(f"SELECT %s >= {LOCAL_TODAY} AS valid", (body.suspended_until,)).fetchone()["valid"]
            if not valid_date:
                raise HTTPException(422, "Suspension must end today or later.")
        updated = conn.execute("""
            UPDATE Users SET suspended_until = %s
            WHERE user_id = %s AND role = 'player'
            RETURNING user_id
        """, (body.suspended_until, player_id)).fetchone()
    if updated is None:
        raise HTTPException(404, "Player not found.")


# Report 1: regular-season standings from each game's latest score report (LatestScoreReport view); a forfeit is a loss for the forfeiting team
@app.get("/api/reports/standings")
def standings(league_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM League WHERE league_id = %s", (league_id,)).fetchone():
            raise HTTPException(404, "League not found.")
        return league_standings(conn, league_id)


# Report 2: per-league participation and progress, optionally for one term
@app.get("/api/reports/participation")
def participation(term: str | None = None):
    with db() as conn:
        return conn.execute("""
            SELECT l.league_id, l.league_name, l.sport_name, l.term, l.max_roster_size,
                   COUNT(DISTINCT t.team_id) AS teams,
                   COUNT(DISTINCT r.user_id) FILTER (WHERE r.status = 'active') AS active_players,
                   COUNT(r.membership_id) FILTER (WHERE r.status = 'invited') AS pending_invites,
                   ROUND(COUNT(r.membership_id) FILTER (WHERE r.status = 'active')::numeric
                         / NULLIF(COUNT(DISTINCT t.team_id), 0), 1)::float AS avg_roster_size,
                   (SELECT COUNT(*) FROM Game g WHERE g.league_id = l.league_id AND g.status = 'completed') AS games_played,
                   (SELECT COUNT(*) FROM Game g WHERE g.league_id = l.league_id AND g.status = 'scheduled') AS games_remaining
            FROM LeagueView l
            LEFT JOIN Team t ON t.league_id = l.league_id
            LEFT JOIN RosterMembership r ON r.team_id = t.team_id
            WHERE (%(term)s::text IS NULL OR l.term = %(term)s)
            GROUP BY l.league_id, l.league_name, l.sport_name, l.term, l.max_roster_size, l.start_date
            ORDER BY l.start_date DESC, l.league_name
        """, {"term": term}).fetchall()
