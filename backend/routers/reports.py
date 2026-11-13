"""League standings and participation reports."""

from fastapi import APIRouter, HTTPException

from database import db
from standings import league_standings

router = APIRouter()


# Report 1: regular-season standings from each game's latest score report (LatestScoreReport view); a forfeit is a loss for the forfeiting team
@router.get("/api/reports/standings")
def standings(league_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM League WHERE league_id = %s", (league_id,)).fetchone():
            raise HTTPException(404, "League not found.")
        return league_standings(conn, league_id)


# Report 2: per-league participation and progress, optionally for one term
@router.get("/api/reports/participation")
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
