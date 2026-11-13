"""Official assignments and administrator coverage management."""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from database import db
from routers.admin import Admin
from routers.auth import AuthenticatedUser
from routers.games import GAME_COLUMNS, GAME_JOINS

router = APIRouter()


class NewAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: int
    official_id: int
    position: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)] = "referee"


# The signed-in official's assignments; anyone else has none
@router.get("/api/me/assignments")
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


@router.post("/api/assignments/{assignment_id}/accept", status_code=204)
def accept_assignment(assignment_id: int, user: AuthenticatedUser):
    answer_assignment(assignment_id, user, "accepted")


@router.post("/api/assignments/{assignment_id}/decline", status_code=204)
def decline_assignment(assignment_id: int, user: AuthenticatedUser):
    answer_assignment(assignment_id, user, "declined")

@router.get("/api/admin/officials")
def list_officials(user: Admin):
    with db() as conn:
        return conn.execute("""
            SELECT user_id, first_name, last_name, vt_pid
            FROM Users WHERE role = 'official' AND is_active
            ORDER BY last_name, first_name, user_id
        """).fetchall()


@router.get("/api/admin/games/coverage")
def game_coverage(user: Admin, league_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT g.game_id, COUNT(a.assignment_id) FILTER (WHERE a.status <> 'declined' AND u.is_active AND u.role = 'official') AS assigned_count
            FROM Game g LEFT JOIN OfficiatingAssignment a ON a.game_id = g.game_id
            LEFT JOIN Users u ON u.user_id = a.official_id
            WHERE g.league_id = %s AND g.status = 'scheduled'
            GROUP BY g.game_id ORDER BY g.start_time, g.game_id
        """, (league_id,)).fetchall()

@router.post("/api/admin/assignments", status_code=201)
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


@router.get("/api/admin/games/{game_id}/assignments")
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


@router.delete("/api/admin/assignments/{assignment_id}", status_code=204)
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
