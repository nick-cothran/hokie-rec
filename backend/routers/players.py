"""Administrator player search and suspension management."""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from constants import LOCAL_TODAY
from database import db
from routers.admin import Admin

router = APIRouter()


class PlayerSuspension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suspended_until: date | None


@router.get("/api/admin/players")
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

@router.patch("/api/admin/players/{player_id}/suspension", status_code=204)
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
