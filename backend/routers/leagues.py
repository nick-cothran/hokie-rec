"""League browsing and registration availability."""

from fastapi import APIRouter

from constants import LOCAL_TODAY
from database import db

router = APIRouter()


# S1: browse leagues by sport and term
@router.get("/api/leagues")
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
