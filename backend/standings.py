"""Regular-season standings, shared by the standings report and playoff seeding."""


def league_standings(conn, league_id: int) -> list[dict]:
    """Each team's record from its games' latest score reports; a forfeit is a loss for the
    forfeiting team. Best record first (wins, then point difference, then name)."""
    return conn.execute("""
        WITH sides AS (
            SELECT g.home_team_id AS team_id, s.home_score AS pf, s.away_score AS pa, s.forfeit_team_id
            FROM Game g JOIN LatestScoreReport s ON s.game_id = g.game_id
            WHERE g.league_id = %(league_id)s AND g.playoff_round IS NULL
            UNION ALL
            SELECT g.away_team_id, s.away_score, s.home_score, s.forfeit_team_id
            FROM Game g JOIN LatestScoreReport s ON s.game_id = g.game_id
            WHERE g.league_id = %(league_id)s AND g.playoff_round IS NULL
        ), results AS (
            SELECT team_id, pf, pa,
                   CASE WHEN forfeit_team_id IS NOT NULL THEN CASE WHEN forfeit_team_id = team_id THEN 'L' ELSE 'W' END
                        WHEN pf > pa THEN 'W' WHEN pf < pa THEN 'L' ELSE 'T' END AS result
            FROM sides  -- every report holds a result (scorereport_has_result in db/phase3.sql)
        )
        SELECT t.team_id, t.team_name, t.status AS team_status,
               COUNT(r.result) AS played,
               COUNT(*) FILTER (WHERE r.result = 'W') AS wins,
               COUNT(*) FILTER (WHERE r.result = 'L') AS losses,
               COUNT(*) FILTER (WHERE r.result = 'T') AS ties,
               COALESCE(SUM(r.pf), 0) AS points_for,
               COALESCE(SUM(r.pa), 0) AS points_against,
               COALESCE(SUM(r.pf), 0) - COALESCE(SUM(r.pa), 0) AS point_diff
        FROM Team t LEFT JOIN results r ON r.team_id = t.team_id
        WHERE t.league_id = %(league_id)s
        GROUP BY t.team_id
        ORDER BY wins DESC, point_diff DESC, t.team_name
    """, {"league_id": league_id}).fetchall()
