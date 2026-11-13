"""Team registration, rosters, invitations, and membership history."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from constants import LOCAL_TODAY
from database import db
from routers.admin import Admin
from routers.auth import AuthenticatedUser
from standings import bracket_seed_order

router = APIRouter()


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

# S2: register a team; the captain's roster row goes in the same transaction
@router.post("/api/teams", status_code=201)
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
@router.get("/api/teams")
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


@router.get("/api/me/teams")
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


@router.get("/api/teams/{team_id}")
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


@router.get("/api/teams/{team_id}/eligibility")
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
@router.patch("/api/teams/{team_id}")
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
@router.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        require_team_captain(team_rules(conn, team_id), user)
        conn.execute("DELETE FROM Team WHERE team_id = %s", (team_id,))


# S4: the captain withdraws a pending invite, any time. A former member's re-invite becomes
# 'removed' instead of being deleted, keeping their joined_at/left_at history.
@router.delete("/api/teams/{team_id}/invites/{player_id}", status_code=204)
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
@router.post("/api/teams/{team_id}/invites", status_code=201)
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
@router.get("/api/me/invites")
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
@router.post("/api/teams/{team_id}/invite/accept", status_code=204)
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
@router.post("/api/teams/{team_id}/invite/decline", status_code=204)
def decline_invite(team_id: int, user: AuthenticatedUser):
    with db() as conn:
        declined = conn.execute("""
            UPDATE RosterMembership SET status = 'declined'
            WHERE team_id = %s AND user_id = %s AND status = 'invited'
        """, (team_id, user["user_id"])).rowcount
    if not declined:
        raise HTTPException(404, "You don't have a pending invite to this team.")


# The captain removes an active member; the row stays as history
@router.delete("/api/teams/{team_id}/members/{player_id}", status_code=204)
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
@router.post("/api/teams/{team_id}/leave", status_code=204)
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
@router.put("/api/teams/{team_id}/captain")
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


@router.put("/api/admin/teams/{team_id}/captain")
def admin_reassign_captain(team_id: int, body: NewCaptain, user: Admin):
    with db() as conn:
        team = team_rules(conn, team_id, for_update=True)
        if body.user_id == team['captain_id']:
            raise HTTPException(409, "This player is already captain.")
        if not conn.execute("SELECT 1 FROM RosterMembership WHERE team_id = %s AND user_id = %s AND status = 'active'", (team_id, body.user_id)).fetchone():
            raise HTTPException(409, "The new captain must be an active member of this team.")
        return conn.execute("UPDATE Team SET captain_id = %s WHERE team_id = %s RETURNING team_id, captain_id", (body.user_id, team_id)).fetchone()


@router.get("/api/me/membership-history")
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
