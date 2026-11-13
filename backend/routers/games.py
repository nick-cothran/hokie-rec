"""Game schedules and the signed-in player's games."""

from fastapi import APIRouter

from database import db
from routers.auth import AuthenticatedUser

router = APIRouter()


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
@router.get("/api/games")
def list_games(league_id: int | None = None, team_id: int | None = None):
    with db() as conn:
        return conn.execute(f"""
            SELECT {GAME_COLUMNS} FROM Game g {GAME_JOINS}
            WHERE (%(league_id)s::int IS NULL OR g.league_id = %(league_id)s)
              AND (%(team_id)s::int IS NULL OR %(team_id)s IN (g.home_team_id, g.away_team_id))
            ORDER BY g.start_time, g.game_id
        """, {"league_id": league_id, "team_id": team_id}).fetchall()


@router.get("/api/me/games")
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
