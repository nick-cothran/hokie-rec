"""Administrator-only account management."""

from typing import Annotated, Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import SignUp, User, create_account, current_user
from database import db

router = APIRouter(prefix="/api/admin", tags=["Administration"])


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Only administrators can do that.")
    return user


Admin = Annotated[dict, Depends(require_admin)]


class NewAccount(SignUp):
    # Same validation as sign-up, plus the role an administrator chooses
    role: Literal["player", "official", "admin"]


@router.get("/users")
def list_users(admin: Admin):
    with db() as conn:
        return conn.execute("""
            SELECT user_id, vt_pid, first_name, last_name, email, role, is_active, created_at
            FROM Users ORDER BY last_name, first_name, user_id
        """).fetchall()


@router.post("/users", response_model=User, status_code=201)
def create_user(body: NewAccount, admin: Admin):
    # The administrator stays signed in as themselves; the new person signs in with
    # the initial password and can change it from their account page.
    try:
        with db() as conn:
            return create_account(conn, body, body.role)
    except UniqueViolation:
        raise HTTPException(409, "That PID or email is already registered.") from None


class NewGame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league_id: int = Field(gt=0)
    facility_id: int = Field(gt=0)
    home_team_id: int = Field(gt=0)
    away_team_id: int = Field(gt=0)
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def validate_game(self):
        if self.home_team_id == self.away_team_id:
            raise ValueError("Choose two different teams.")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("Game times must include a time zone.")
        if self.end_time <= self.start_time:
            raise ValueError("The end time must be after the start time.")
        return self


@router.get("/facilities")
def list_facilities(admin: Admin):
    with db() as conn:
        return conn.execute("SELECT facility_id, facility_name, location FROM Facility ORDER BY facility_name").fetchall()


@router.post("/games", status_code=201)
def create_game(body: NewGame, admin: Admin):
    with db() as conn:
        # Serialize all scheduling requests so overlapping inserts cannot race.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        if body.start_time <= datetime.now(timezone.utc):
            raise HTTPException(422, "The game must start in the future.")
        league = conn.execute("SELECT league_id FROM League WHERE league_id = %s", (body.league_id,)).fetchone()
        facility = conn.execute("SELECT facility_id FROM Facility WHERE facility_id = %s", (body.facility_id,)).fetchone()
        if not league or not facility:
            raise HTTPException(404, "League or facility not found.")
        teams = conn.execute("SELECT team_id FROM Team WHERE league_id = %s AND status = 'active' AND team_id = ANY(%s)",
                             (body.league_id, [body.home_team_id, body.away_team_id])).fetchall()
        if len(teams) != 2:
            raise HTTPException(422, "Both teams must be active teams in the selected league.")
        conflict = conn.execute("""
            SELECT facility_id = %s AS facility_conflict FROM Game
            WHERE status <> 'cancelled' AND start_time < %s AND end_time > %s
              AND (facility_id = %s OR home_team_id = ANY(%s) OR away_team_id = ANY(%s)) LIMIT 1
        """, (body.facility_id, body.end_time, body.start_time, body.facility_id,
               [body.home_team_id, body.away_team_id], [body.home_team_id, body.away_team_id])).fetchone()
        if conflict:
            raise HTTPException(409, "The facility or one of the teams is already scheduled during that time.")
        try:
            return conn.execute("""
                INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING game_id
            """, (body.league_id, body.facility_id, body.home_team_id, body.away_team_id,
                   body.start_time, body.end_time)).fetchone()
        except UniqueViolation:
            raise HTTPException(409, "A game already occupies that facility and start time.") from None
