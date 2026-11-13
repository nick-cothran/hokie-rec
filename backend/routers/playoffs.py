"""Playoff brackets: an administrator generates a single-elimination bracket from the
regular-season standings, and each playoff result moves its winner into the next round
(see advance_winner, called by score entry)."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, model_validator

from routers.admin import Admin
from database import db
from standings import league_standings

router = APIRouter(prefix="/api/admin/leagues", tags=["Playoffs"])

# Time between the end of one game and the start of the next on the same facility
TURNOVER = timedelta(minutes=30)


class NewBracket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_count: Literal[2, 4, 8]
    facility_id: int = Field(gt=0)
    start_time: datetime
    days_between_rounds: int = Field(default=7, ge=1, le=14)

    @model_validator(mode="after")
    def validate_start(self):
        if self.start_time.tzinfo is None:
            raise ValueError("The start time must include a time zone.")
        return self


def bracket_order(size: int) -> list[int]:
    """Seeds in bracket order, so neighbors meet in round 1 and the top two seeds can only
    meet in the final: 4 → [1, 4, 2, 3]; 8 → [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [seed for s in order for seed in (s, total - s)]
    return order


def round_name(rounds_left: int) -> str:
    return {1: "Final", 2: "Semifinal", 3: "Quarterfinal"}.get(rounds_left, f"Round of {2 ** rounds_left}")


@router.post("/{league_id}/playoffs", status_code=201)
def generate_bracket(league_id: int, body: NewBracket, admin: Admin):
    with db() as conn:
        # The same lock as one-off scheduling, so two requests can't book one slot
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        if body.start_time <= datetime.now(timezone.utc):
            raise HTTPException(422, "The playoffs must start in the future.")
        if not conn.execute("SELECT 1 FROM League WHERE league_id = %s", (league_id,)).fetchone():
            raise HTTPException(404, "League not found.")
        if not conn.execute("SELECT 1 FROM Facility WHERE facility_id = %s", (body.facility_id,)).fetchone():
            raise HTTPException(404, "Facility not found.")
        if conn.execute("SELECT 1 FROM Game WHERE league_id = %s AND playoff_round IS NOT NULL LIMIT 1",
                        (league_id,)).fetchone():
            raise HTTPException(409, "This league already has a playoff bracket. Remove it first to generate a new one.")
        season = conn.execute("""
            SELECT COUNT(*) FILTER (WHERE status = 'scheduled') AS unplayed,
                   MAX(end_time) AS last_end,
                   mode() WITHIN GROUP (ORDER BY end_time - start_time) AS game_length
            FROM Game WHERE league_id = %s AND playoff_round IS NULL AND status <> 'cancelled'
        """, (league_id,)).fetchone()
        if season["unplayed"]:
            raise HTTPException(409, f"Finish the regular season first: {season['unplayed']} game(s) still need a result.")
        if season["last_end"] is not None and body.start_time < season["last_end"]:
            raise HTTPException(422, "The playoffs must start after the last regular-season game.")

        seeds = [t for t in league_standings(conn, league_id) if t["team_status"] == "active"]
        if len(seeds) < body.team_count:
            raise HTTPException(409, f"Only {len(seeds)} active team(s) in this league; choose a smaller bracket.")
        seeds = seeds[:body.team_count]

        # Plan every game first: round 1 holds the seeded matchups, later rounds wait for winners.
        # Games in a round are back to back on the facility; each round is days_between_rounds apart.
        length = season["game_length"] or timedelta(hours=1)
        rounds = body.team_count.bit_length() - 1
        order = bracket_order(body.team_count)
        plan = []  # (round, index in round, home, away, start)
        for r in range(1, rounds + 1):
            day = body.start_time + timedelta(days=body.days_between_rounds * (r - 1))
            for i in range(body.team_count >> r):
                home = away = None
                if r == 1:
                    home, away = seeds[order[2 * i] - 1]["team_id"], seeds[order[2 * i + 1] - 1]["team_id"]
                plan.append((r, i, home, away, day + i * (length + TURNOVER)))

        for _, _, home, away, start in plan:
            teams = [t for t in (home, away) if t is not None]
            if conn.execute("""
                SELECT 1 FROM Game WHERE status <> 'cancelled' AND start_time < %s AND end_time > %s
                  AND (facility_id = %s OR home_team_id = ANY(%s) OR away_team_id = ANY(%s)) LIMIT 1
            """, (start + length, start, body.facility_id, teams, teams)).fetchone():
                raise HTTPException(409, "The facility or a team is already booked during one of the playoff games. "
                                         "Choose another facility or start time.")

        # Insert from the final back to round 1 so each game can point at the game its winner plays
        # next. Within a round, the upper half of the bracket starts first, which is how
        # advance_winner knows the upper feeder's winner is the home team.
        ids: dict[tuple[int, int], int] = {}
        try:
            for r, i, home, away, start in sorted(plan, key=lambda g: (-g[0], g[1])):
                ids[(r, i)] = conn.execute("""
                    INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, next_game_id,
                                      start_time, end_time, playoff_round)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING game_id
                """, (league_id, body.facility_id, home, away, ids.get((r + 1, i // 2)),
                      start, start + length, r)).fetchone()["game_id"]
        except UniqueViolation:
            raise HTTPException(409, "A game already starts on that facility at one of the playoff times.") from None

    return {
        "league_id": league_id,
        "seeds": [{"seed": n, "team_id": t["team_id"], "team_name": t["team_name"]} for n, t in enumerate(seeds, 1)],
        "games": [{"game_id": ids[(r, i)], "round": r, "round_name": round_name(rounds - r + 1),
                   "home_team_id": home, "away_team_id": away, "start_time": start}
                  for r, i, home, away, start in plan],
    }


@router.delete("/{league_id}/playoffs", status_code=204)
def remove_bracket(league_id: int, admin: Admin):
    """Removes a bracket nobody has played yet (and its officiating assignments)."""
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        games = conn.execute("""
            SELECT g.game_id, EXISTS (SELECT 1 FROM ScoreReport s WHERE s.game_id = g.game_id) AS scored
            FROM Game g WHERE g.league_id = %s AND g.playoff_round IS NOT NULL FOR UPDATE
        """, (league_id,)).fetchall()
        if not games:
            raise HTTPException(404, "This league has no playoff bracket.")
        if any(g["scored"] for g in games):
            raise HTTPException(409, "Playoff results have already been entered, so the bracket can't be removed.")
        try:
            # next_game_id is ON DELETE SET NULL, so the order of deletes doesn't matter
            conn.execute("DELETE FROM Game WHERE game_id = ANY(%s)", ([g["game_id"] for g in games],))
        except ForeignKeyViolation:
            raise HTTPException(409, "A playoff game has an incident report, so the bracket can't be removed.") from None


def playoff_winner(game: dict, home_score: int | None, away_score: int | None, forfeit_team_id: int | None) -> int | None:
    if forfeit_team_id is not None:
        return game["away_team_id"] if forfeit_team_id == game["home_team_id"] else game["home_team_id"]
    if home_score == away_score:
        return None
    return game["home_team_id"] if home_score > away_score else game["away_team_id"]


def advance_winner(conn, game: dict, winner_id: int) -> None:
    """Puts a playoff game's winner into the next round. The feeder that starts first (then the
    lower game_id) fills the home slot. Call before inserting the report: a correction that changes the winner is
    refused once the next game has a result."""
    next_id = game["next_game_id"]
    feeders = [row["game_id"] for row in conn.execute(
        "SELECT game_id FROM Game WHERE next_game_id = %s ORDER BY start_time, game_id", (next_id,)).fetchall()]
    slot = "home_team_id" if feeders.index(game["game_id"]) == 0 else "away_team_id"
    nxt = conn.execute(f"""
        SELECT {slot} AS current, start_time, end_time, EXISTS (SELECT 1 FROM ScoreReport s WHERE s.game_id = g.game_id) AS scored
        FROM Game g WHERE g.game_id = %s FOR UPDATE
    """, (next_id,)).fetchone()
    if nxt["current"] == winner_id:
        return
    if nxt["scored"]:
        raise HTTPException(409, "The next round already has a result, so this correction can't change who advanced.")
    if conn.execute("""
        SELECT 1 FROM Game WHERE game_id <> %s AND status <> 'cancelled'
          AND %s IN (home_team_id, away_team_id) AND start_time < %s AND end_time > %s LIMIT 1
    """, (next_id, winner_id, nxt['end_time'], nxt['start_time'])).fetchone():
        raise HTTPException(409, "The winning team has another game at the next round's time. Reschedule that game before submitting this result.")
    conn.execute(f"UPDATE Game SET {slot} = %s WHERE game_id = %s", (winner_id, next_id))
