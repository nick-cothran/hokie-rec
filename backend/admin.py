"""Administrator-only account management."""

from typing import Annotated, Literal
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import SignUp, User, create_account, current_user
from database import db

router = APIRouter(prefix="/api/admin", tags=["Administration"])


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Only administrators can do that.")
    return user


Admin = Annotated[dict, Depends(require_admin)]


def require_season_dates(conn, league_id: int, start: datetime, end: datetime):
    row = conn.execute("""
        SELECT start_date, end_date,
               (%s::timestamptz AT TIME ZONE 'America/New_York')::date AS first_date,
               (%s::timestamptz AT TIME ZONE 'America/New_York')::date AS last_date
        FROM League WHERE league_id = %s
    """, (start, end, league_id)).fetchone()
    if not row:
        raise HTTPException(404, "League not found.")
    if row['first_date'] < row['start_date'] or row['last_date'] > row['end_date']:
        raise HTTPException(422, "Regular-season games must fit within the league's season dates (Eastern time).")


def require_no_bracket(conn, league_id: int):
    if conn.execute("SELECT 1 FROM Game WHERE league_id = %s AND playoff_round IS NOT NULL LIMIT 1", (league_id,)).fetchone():
        raise HTTPException(409, "The league already has a playoff bracket. Remove it before adding regular-season games.")


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
        require_no_bracket(conn, body.league_id)
        require_season_dates(conn, body.league_id, body.start_time, body.end_time)
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


class GameReschedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: int = Field(gt=0)
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("Game times must include a time zone.")
        if self.end_time <= self.start_time:
            raise ValueError("The end time must be after the start time.")
        return self


@router.put("/games/{game_id}/schedule")
def reschedule_game(game_id: int, body: GameReschedule, admin: Admin):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        game = conn.execute("SELECT * FROM Game WHERE game_id = %s FOR UPDATE", (game_id,)).fetchone()
        if not game:
            raise HTTPException(404, "Game not found.")
        if game['status'] != 'scheduled' or game['start_time'] <= datetime.now(timezone.utc):
            raise HTTPException(409, "Only future scheduled games can be rescheduled.")
        if game['playoff_round'] is not None:
            raise HTTPException(409, "Playoff games cannot be rescheduled individually. Manage the bracket from the league page.")
        if body.start_time <= datetime.now(timezone.utc):
            raise HTTPException(422, "The new start time must be in the future.")
        if not conn.execute("SELECT 1 FROM Facility WHERE facility_id = %s", (body.facility_id,)).fetchone():
            raise HTTPException(404, "Facility not found.")
        require_season_dates(conn, game['league_id'], body.start_time, body.end_time)
        teams = [team for team in (game['home_team_id'], game['away_team_id']) if team is not None]
        if conn.execute("""
            SELECT 1 FROM Game WHERE game_id <> %s AND status <> 'cancelled' AND start_time < %s AND end_time > %s
              AND (facility_id = %s OR home_team_id = ANY(%s) OR away_team_id = ANY(%s)) LIMIT 1
        """, (game_id, body.end_time, body.start_time, body.facility_id, teams, teams)).fetchone():
            raise HTTPException(409, "The facility or one of the teams is already scheduled during that time.")
        if conn.execute("""
            SELECT 1 FROM OfficiatingAssignment mine
            JOIN OfficiatingAssignment other ON other.official_id = mine.official_id AND other.game_id <> mine.game_id
            JOIN Game other_game ON other_game.game_id = other.game_id
            WHERE mine.game_id = %s AND mine.status <> 'declined' AND other.status <> 'declined'
              AND other_game.status <> 'cancelled' AND other_game.start_time < %s AND other_game.end_time > %s LIMIT 1
        """, (game_id, body.end_time, body.start_time)).fetchone():
            raise HTTPException(409, "An assigned official has another game at that time. Remove or reassign them first.")
        try:
            conn.execute("UPDATE Game SET facility_id = %s, start_time = %s, end_time = %s WHERE game_id = %s",
                         (body.facility_id, body.start_time, body.end_time, game_id))
        except UniqueViolation:
            raise HTTPException(409, "A game already occupies that facility and start time.") from None
        # Officials must respond to a changed assignment again.
        conn.execute("UPDATE OfficiatingAssignment SET status = 'assigned' WHERE game_id = %s AND status = 'accepted'", (game_id,))
    return {"game_id": game_id}


@router.post("/games/{game_id}/cancel", status_code=204)
def cancel_game(game_id: int, admin: Admin):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        game = conn.execute("SELECT status, start_time, playoff_round FROM Game WHERE game_id = %s FOR UPDATE", (game_id,)).fetchone()
        if not game:
            raise HTTPException(404, "Game not found.")
        if game['status'] != 'scheduled' or game['start_time'] <= datetime.now(timezone.utc):
            raise HTTPException(409, "Only future scheduled games can be cancelled.")
        if game['playoff_round'] is not None:
            raise HTTPException(409, "Playoff games cannot be cancelled individually. Manage the bracket from the league page.")
        conn.execute("UPDATE Game SET status = 'cancelled' WHERE game_id = %s", (game_id,))


class GenerateSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: int = Field(gt=0)
    start_time: datetime
    duration_minutes: int = Field(ge=1, le=1440)
    interval_minutes: int = Field(ge=1, le=10080)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.start_time.tzinfo is None:
            raise ValueError("The start time must include a time zone.")
        if self.interval_minutes < self.duration_minutes:
            raise ValueError("The interval must be at least the game duration.")
        return self


@router.post("/leagues/{league_id}/generate-schedule", status_code=201)
def generate_schedule(league_id: int, body: GenerateSchedule, admin: Admin):
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        if body.start_time <= datetime.now(timezone.utc):
            raise HTTPException(422, "The first game must start in the future.")
        league = conn.execute("SELECT start_date, end_date FROM League WHERE league_id = %s", (league_id,)).fetchone()
        if not league:
            raise HTTPException(404, "League not found.")
        if not conn.execute("SELECT 1 FROM Facility WHERE facility_id = %s", (body.facility_id,)).fetchone():
            raise HTTPException(404, "Facility not found.")
        require_no_bracket(conn, league_id)
        if conn.execute("SELECT 1 FROM Game WHERE league_id = %s AND playoff_round IS NULL AND status <> 'cancelled' LIMIT 1", (league_id,)).fetchone():
            raise HTTPException(409, "This league already has regular-season games. Schedule additional games individually.")
        teams = [r['team_id'] for r in conn.execute("SELECT team_id FROM Team WHERE league_id = %s AND status = 'active' ORDER BY team_id", (league_id,)).fetchall()]
        if not 2 <= len(teams) <= 32:
            raise HTTPException(422, "A league needs between 2 and 32 active teams.")
        last_end = body.start_time + timedelta(minutes=((len(teams) * (len(teams) - 1) // 2) - 1) * body.interval_minutes + body.duration_minutes)
        dates = conn.execute("SELECT (%s::timestamptz AT TIME ZONE 'America/New_York')::date AS first_date, (%s::timestamptz AT TIME ZONE 'America/New_York')::date AS last_date", (body.start_time, last_end)).fetchone()
        if dates['first_date'] < league['start_date'] or dates['last_date'] > league['end_date']:
            raise HTTPException(422, "All generated games must fit within the league's season dates.")
        count = 0
        for index, home in enumerate(teams):
            for away in teams[index + 1:]:
                start = body.start_time + timedelta(minutes=count * body.interval_minutes)
                end = start + timedelta(minutes=body.duration_minutes)
                if conn.execute("""SELECT 1 FROM Game WHERE status <> 'cancelled' AND start_time < %s AND end_time > %s
                    AND (facility_id = %s OR home_team_id = ANY(%s) OR away_team_id = ANY(%s)) LIMIT 1""",
                    (end, start, body.facility_id, [home, away], [home, away])).fetchone():
                    raise HTTPException(409, "A facility or team is already scheduled during the proposed times; no games were created.")
                try:
                    conn.execute("""INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
                        VALUES (%s, %s, %s, %s, %s, %s)""", (league_id, body.facility_id, home, away, start, end))
                except UniqueViolation:
                    raise HTTPException(409, "A game already occupies a proposed facility and time; no games were created.") from None
                count += 1
        return {"games_created": count}


class SportSetup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sport_name: str = Field(min_length=1, max_length=50)
    min_roster_size: int = Field(ge=0)
    max_roster_size: int = Field(ge=1)

    @model_validator(mode="after")
    def check_sizes(self):
        if self.min_roster_size > self.max_roster_size:
            raise ValueError("Minimum roster size cannot exceed the maximum.")
        return self


class FacilitySetup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    facility_name: str = Field(min_length=1, max_length=60)
    location: str = Field(min_length=1, max_length=100)


class LeagueSetup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sport_id: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=10)
    skill_level: str = Field(min_length=1, max_length=20)
    term: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    reg_open_at: datetime
    reg_close_at: datetime
    roster_lock_date: date

    @model_validator(mode="after")
    def check_dates(self):
        if self.reg_open_at.tzinfo is None or self.reg_close_at.tzinfo is None:
            raise ValueError("Registration times must include a time zone.")
        if self.reg_open_at >= self.reg_close_at or self.start_date > self.end_date:
            raise ValueError("Check the registration and season date ranges.")
        return self


SETUP = {
    "sports": ("Sport", "sport_id", SportSetup),
    "leagues": ("League", "league_id", LeagueSetup),
    "facilities": ("Facility", "facility_id", FacilitySetup),
}


def setup_type(kind):
    if kind not in SETUP:
        raise HTTPException(404, "Unknown setup section.")
    return SETUP[kind]


@router.get("/setup/{kind}")
def list_setup(kind: str, admin: Admin):
    table, identifier, _ = setup_type(kind)
    with db() as conn:
        return conn.execute(f"SELECT * FROM {table} ORDER BY {identifier}").fetchall()


@router.post("/setup/{kind}", status_code=201)
def create_setup(kind: str, body: dict, admin: Admin):
    return save_setup(kind, None, body)


@router.put("/setup/{kind}/{item_id}")
def update_setup(kind: str, item_id: int, body: dict, admin: Admin):
    return save_setup(kind, item_id, body)


def save_setup(kind, item_id, body):
    from pydantic import ValidationError
    table, identifier, model = setup_type(kind)
    try:
        values = model.model_validate(body).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(error["msg"] for error in exc.errors())) from None
    try:
        with db() as conn:
            if kind == 'leagues':
                conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
            if item_id is not None:
                current = conn.execute(f"SELECT * FROM {table} WHERE {identifier} = %s FOR UPDATE", (item_id,)).fetchone()
                if not current:
                    raise HTTPException(404, "Item not found.")
                if kind == "leagues" and current["sport_id"] != values["sport_id"] and conn.execute(
                    "SELECT 1 FROM Team WHERE league_id = %s UNION ALL SELECT 1 FROM Game WHERE league_id = %s LIMIT 1", (item_id, item_id)
                ).fetchone():
                    raise HTTPException(409, "A league with teams or games cannot change sport.")
                if kind == 'leagues' and (current['start_date'] != values['start_date'] or current['end_date'] != values['end_date']) and conn.execute("""
                    SELECT 1 FROM Game WHERE league_id = %s AND playoff_round IS NULL AND status <> 'cancelled'
                    AND ((start_time AT TIME ZONE 'America/New_York')::date < %s OR (end_time AT TIME ZONE 'America/New_York')::date > %s) LIMIT 1
                """, (item_id, values['start_date'], values['end_date'])).fetchone():
                    raise HTTPException(409, "The new season dates would leave an existing regular-season game outside the season.")
                if kind == "sports" and conn.execute("""
                    SELECT 1 FROM Team t JOIN League l ON l.league_id=t.league_id
                    JOIN RosterMembership r ON r.team_id=t.team_id AND r.status='active'
                    WHERE l.sport_id=%s GROUP BY t.team_id HAVING COUNT(*) > %s LIMIT 1
                """, (item_id, values["max_roster_size"])).fetchone():
                    raise HTTPException(409, "An existing roster exceeds this maximum.")
                assignments = ", ".join(f"{column} = %s" for column in values)
                conn.execute(f"UPDATE {table} SET {assignments} WHERE {identifier} = %s", (*values.values(), item_id))
                return {identifier: item_id}
            columns = ", ".join(values)
            placeholders = ", ".join(["%s"] * len(values))
            return conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING {identifier}", tuple(values.values())).fetchone()
    except UniqueViolation:
        raise HTTPException(409, "An item with these details already exists.") from None
    except ForeignKeyViolation:
        raise HTTPException(409, "The selected sport does not exist.") from None


@router.delete("/setup/{kind}/{item_id}", status_code=204)
def delete_setup(kind: str, item_id: int, admin: Admin):
    table, identifier, _ = setup_type(kind)
    try:
        with db() as conn:
            if not conn.execute(f"DELETE FROM {table} WHERE {identifier} = %s RETURNING {identifier}", (item_id,)).fetchone():
                raise HTTPException(404, "Item not found.")
    except ForeignKeyViolation:
        raise HTTPException(409, "This item is in use and cannot be deleted.") from None
