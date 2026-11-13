"""Assigned-official score entry, append-only corrections, and report history."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import AuthenticatedUser
from database import db
from playoffs import advance_winner, playoff_winner
from standings import bracket_seed_order

router = APIRouter(prefix="/api/games", tags=["Score reports"])
Score = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]
TeamId = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]


class NewScoreReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_score: Score | None = None
    away_score: Score | None = None
    forfeit_team_id: TeamId | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if self.forfeit_team_id is None:
            if self.home_score is None or self.away_score is None:
                raise ValueError("Enter both final scores, or select a forfeiting team.")
        elif self.home_score is not None or self.away_score is not None:
            raise ValueError("A forfeit must name the forfeiting team without final scores.")
        return self


def game_details(conn, game_id: int, *, lock: bool = False) -> dict:
    game = conn.execute(f"""
        SELECT g.game_id, g.league_id, l.league_name, g.status, g.start_time, g.end_time,
               g.playoff_round, g.next_game_id,
               EXISTS (SELECT 1 FROM Game pg WHERE pg.league_id = g.league_id AND pg.playoff_round IS NOT NULL) AS bracket_exists,
               g.home_team_id, h.team_name AS home_team_name,
               g.away_team_id, a.team_name AS away_team_name,
               f.facility_name, f.location, g.end_time <= clock_timestamp() AS has_ended
        FROM Game g JOIN LeagueView l ON l.league_id = g.league_id
        JOIN Facility f ON f.facility_id = g.facility_id
        LEFT JOIN Team h ON h.team_id = g.home_team_id
        LEFT JOIN Team a ON a.team_id = g.away_team_id
        WHERE g.game_id = %s {"FOR UPDATE OF g" if lock else ""}
    """, (game_id,)).fetchone()
    if game is None:
        raise HTTPException(404, "Game not found.")
    return game


def submission_block(game: dict, user: dict, assignment: dict | None) -> str | None:
    if user["role"] != "official" or assignment is None:
        return "Only an official assigned to this game can submit its result."
    if assignment["status"] == "declined":
        return "You declined this assignment and cannot submit its result."
    if game["status"] == "cancelled":
        return "Cancelled games cannot receive score reports."
    if game["status"] not in ("scheduled", "completed"):
        return "This game is not available for scoring."
    if game["home_team_id"] is None or game["away_team_id"] is None:
        return "Both teams must be decided before a result can be submitted."
    if not game["has_ended"]:
        return "Results can only be submitted after the game's scheduled end."
    return None


def report_history(conn, game_id: int) -> list[dict]:
    return conn.execute("""
        SELECT r.report_id, r.home_score, r.away_score, r.forfeit_team_id,
               r.submitted_at, r.submitted_by, u.first_name, u.last_name,
               ROW_NUMBER() OVER (ORDER BY r.submitted_at DESC, r.report_id DESC) = 1 AS is_current
        FROM ScoreReport r JOIN Users u ON u.user_id = r.submitted_by
        WHERE r.game_id = %s ORDER BY r.submitted_at DESC, r.report_id DESC
    """, (game_id,)).fetchall()


@router.get("/{game_id}/score-reports")
def get_score_reports(game_id: int, response: Response, user: AuthenticatedUser):
    response.headers["Cache-Control"] = "no-store"
    # One snapshot keeps the current result and history consistent during a correction.
    with db() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        game = game_details(conn, game_id)
        assignment = conn.execute("SELECT status FROM OfficiatingAssignment WHERE game_id = %s AND official_id = %s",
                                  (game_id, user["user_id"])).fetchone()
        if user["role"] != "admin" and (user["role"] != "official" or assignment is None):
            raise HTTPException(403, "Only this game's officials or administrators can view its score reports.")
        reason = submission_block(game, user, assignment)
        return {"game": game, "reports": report_history(conn, game_id),
                "can_submit": reason is None, "blocked_reason": reason}


@router.post("/{game_id}/score-reports", status_code=201)
def submit_score_report(game_id: int, body: NewScoreReport, user: AuthenticatedUser):
    if user["role"] != "official":
        raise HTTPException(403, "Only an official assigned to this game can submit its result.")
    with db() as conn:
        # Serialize standings and advancement with bracket and schedule changes.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        # Serializes submissions with corrections and ordinary administrator game
        # updates. Hold the assignment too, so a concurrent decline cannot race us.
        game = game_details(conn, game_id, lock=True)
        assignment = conn.execute("""
            SELECT status FROM OfficiatingAssignment WHERE game_id = %s AND official_id = %s FOR SHARE
        """, (game_id, user["user_id"])).fetchone()
        reason = submission_block(game, user, assignment)
        if reason:
            raise HTTPException(403 if assignment is None or assignment["status"] == "declined" else 409, reason)
        if body.forfeit_team_id is not None and body.forfeit_team_id not in (game["home_team_id"], game["away_team_id"]):
            raise HTTPException(422, "The forfeiting team must be one of this game's two teams.")
        before_seeds = bracket_seed_order(conn, game['league_id']) if game['playoff_round'] is None else None
        if game["playoff_round"] is not None:
            winner = playoff_winner(game, body.home_score, body.away_score, body.forfeit_team_id)
            if winner is None:
                raise HTTPException(422, "A playoff game needs a winner. Enter the score after the tiebreaker.")
            if game["next_game_id"] is not None:
                advance_winner(conn, game, winner)
        report = conn.execute("""
            INSERT INTO ScoreReport (game_id, submitted_by, home_score, away_score, forfeit_team_id, submitted_at)
            VALUES (%s, %s, %s, %s, %s, clock_timestamp())
            RETURNING report_id, submitted_at
        """, (game_id, user["user_id"], body.home_score, body.away_score, body.forfeit_team_id)).fetchone()
        if before_seeds is not None:
            if before_seeds != bracket_seed_order(conn, game['league_id']):
                raise HTTPException(409, "This result would change playoff seeds. An administrator must remove the unplayed bracket before you submit it. Once playoffs have results, this correction is unavailable.")
        # In the same transaction: participation uses status; standings use reports.
        conn.execute("UPDATE Game SET status = 'completed' WHERE game_id = %s", (game_id,))
    return {"game_id": game_id, **report}
