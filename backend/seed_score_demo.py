"""Provision a repeatable, development-only game ready for official score entry."""

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from database import db
from seed_demo_accounts import seed_demo_accounts

OFFICIAL_PID = "simvt0121"
ADMIN_PID = "simvt0133"


def seed_score_demo(*, new_game: bool = False, ensure_upcoming: bool = False) -> int:
    # Existing demo passwords are preserved; no registered account is changed.
    seed_demo_accounts()
    year = datetime.now(ZoneInfo("America/New_York")).year
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:score-demo'))")
        if ensure_upcoming:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('hokie-rec:game-scheduling'))")
        people = {row["vt_pid"]: row for row in conn.execute("""
            SELECT user_id, vt_pid, role, is_active FROM Users
            WHERE vt_pid = ANY(%s)
        """, ([OFFICIAL_PID, ADMIN_PID, "simvt0001", "simvt0002"],)).fetchall()}
        expected = {OFFICIAL_PID: "official", ADMIN_PID: "admin", "simvt0001": "player", "simvt0002": "player"}
        if any(pid not in people or people[pid]["role"] != role or not people[pid]["is_active"]
               for pid, role in expected.items()):
            raise ValueError("The seeded demo official, admin, and players must exist and be active with their original roles.")
        sport = conn.execute("SELECT sport_id FROM Sport WHERE sport_name = 'Soccer'").fetchone()
        if sport is None:
            raise ValueError("Run the sports seed before preparing the scoring demo.")
        conn.execute("""
            INSERT INTO League (sport_id, category, skill_level, term, start_date, end_date,
                                reg_open_at, reg_close_at, roster_lock_date)
            VALUES (%s, 'Open', 'Recreational', %s, CURRENT_DATE - 30, CURRENT_DATE + 30,
                    NOW() - INTERVAL '30 days', NOW() + INTERVAL '30 days', CURRENT_DATE + 31)
            ON CONFLICT (sport_id, category, skill_level, term) DO NOTHING
        """, (sport["sport_id"], f"Scoring Demo {year}"))
        league_id = conn.execute("""
            SELECT league_id FROM League WHERE sport_id = %s AND category = 'Open'
                AND skill_level = 'Recreational' AND term = %s
        """, (sport["sport_id"], f"Scoring Demo {year}")).fetchone()["league_id"]
        teams = []
        for name, pid in (("Demo Maroon", "simvt0001"), ("Demo Orange", "simvt0002")):
            captain = people[pid]["user_id"]
            created = conn.execute("""
                INSERT INTO Team (league_id, captain_id, team_name) VALUES (%s, %s, %s)
                ON CONFLICT (league_id, team_name) DO NOTHING RETURNING team_id
            """, (league_id, captain, name)).fetchone()
            team_id = created["team_id"] if created else conn.execute(
                "SELECT team_id FROM Team WHERE league_id = %s AND team_name = %s", (league_id, name)).fetchone()["team_id"]
            if created:
                conn.execute("""
                    INSERT INTO RosterMembership (team_id, user_id, status, joined_at)
                    VALUES (%s, %s, 'active', NOW())
                """, (team_id, captain))
            teams.append(team_id)
        conn.execute("""
            INSERT INTO Facility (facility_name, location) VALUES ('Demo Scoring Field', 'Local scoring demonstration')
            ON CONFLICT (facility_name) DO NOTHING
        """)
        facility_id = conn.execute("SELECT facility_id FROM Facility WHERE facility_name = 'Demo Scoring Field'").fetchone()["facility_id"]
        existing = conn.execute("""
            SELECT game_id FROM Game WHERE league_id = %s AND facility_id = %s
                AND home_team_id = %s AND away_team_id = %s AND end_time <= NOW() ORDER BY game_id DESC LIMIT 1
        """, (league_id, facility_id, *teams)).fetchone()
        if existing and not new_game:
            game_id = existing["game_id"]
        else:
            # Older slots avoid collisions on repeat demos. Every game has ended,
            # but starts scheduled and unreported so the first result is testable.
            game_id = conn.execute("""
                INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
                SELECT %s, %s, %s, %s,
                       LEAST(COALESCE(MIN(start_time), NOW()), NOW()) - INTERVAL '1 day',
                       LEAST(COALESCE(MIN(start_time), NOW()), NOW()) - INTERVAL '23 hours'
                FROM Game WHERE facility_id = %s RETURNING game_id
            """, (league_id, facility_id, *teams, facility_id)).fetchone()["game_id"]
            conn.execute("""
                INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
                VALUES (%s, %s, %s, 'referee', 'accepted')
            """, (game_id, people[OFFICIAL_PID]["user_id"], people[ADMIN_PID]["user_id"]))
        upcoming_id = None
        if ensure_upcoming:
            if conn.execute("SELECT 1 FROM Game WHERE league_id = %s AND playoff_round IS NOT NULL LIMIT 1", (league_id,)).fetchone():
                raise ValueError("The demo league has a playoff bracket; its regular-season schedule was not changed.")
            for team_id, pid in zip(teams, ("simvt0001", "simvt0002")):
                if not conn.execute("SELECT 1 FROM RosterMembership WHERE team_id = %s AND user_id = %s AND status = 'active'", (team_id, people[pid]['user_id'])).fetchone():
                    raise ValueError("The demo players must be active on their demo teams to prepare an upcoming game.")
            upcoming = conn.execute("""
                SELECT g.game_id FROM Game g JOIN OfficiatingAssignment a ON a.game_id = g.game_id
                WHERE g.league_id = %s AND g.facility_id = %s AND g.home_team_id = %s AND g.away_team_id = %s
                  AND g.status = 'scheduled' AND g.start_time > NOW() AND a.official_id = %s AND a.status = 'assigned'
                ORDER BY g.start_time LIMIT 1
            """, (league_id, facility_id, *teams, people[OFFICIAL_PID]['user_id'])).fetchone()
            if upcoming:
                upcoming_id = upcoming['game_id']
            else:
                slot = conn.execute("""
                    SELECT start_time, start_time + INTERVAL '1 hour' AS end_time FROM (
                        SELECT (((NOW() AT TIME ZONE 'America/New_York')::date + day_offset)::timestamp + INTERVAL '18 hours')
                               AT TIME ZONE 'America/New_York' AS start_time
                        FROM generate_series(1, 30) AS day_offset
                    ) candidate JOIN League l ON l.league_id = %s
                    WHERE (candidate.start_time AT TIME ZONE 'America/New_York')::date BETWEEN l.start_date AND l.end_date
                      AND NOT EXISTS (
                          SELECT 1 FROM Game g WHERE g.status <> 'cancelled'
                            AND g.start_time < candidate.start_time + INTERVAL '1 hour' AND g.end_time > candidate.start_time
                            AND (g.facility_id = %s OR g.home_team_id = ANY(%s) OR g.away_team_id = ANY(%s)
                                 OR EXISTS (SELECT 1 FROM OfficiatingAssignment a WHERE a.game_id = g.game_id AND a.official_id = %s AND a.status <> 'declined'))
                      ) ORDER BY candidate.start_time LIMIT 1
                """, (league_id, facility_id, teams, teams, people[OFFICIAL_PID]['user_id'])).fetchone()
                if not slot:
                    raise ValueError("No free demo slot was found within the league's season in the next 30 days; existing data was not changed.")
                upcoming_id = conn.execute("""
                    INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING game_id
                """, (league_id, facility_id, *teams, slot['start_time'], slot['end_time'])).fetchone()['game_id']
                conn.execute("""
                    INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
                    VALUES (%s, %s, %s, 'referee', 'assigned')
                """, (upcoming_id, people[OFFICIAL_PID]['user_id'], people[ADMIN_PID]['user_id']))
    print(f"Scoring demo game {game_id}: Demo Maroon vs Demo Orange. Official: {OFFICIAL_PID}; admin: {ADMIN_PID}.")
    print(f"Open /games/{game_id}/score after signing in. Existing results are preserved; use --new-game for a fresh unscored game.")
    if upcoming_id is not None:
        print(f"Upcoming demo game {upcoming_id}: sign in as simvt0001 to see it under Your games or simvt0121 to respond to the assignment.")
    return game_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True,
                        help="Acknowledge that this is a development database.")
    parser.add_argument("--new-game", action="store_true", help="Add a fresh unscored game without changing prior reports.")
    parser.add_argument("--upcoming", action="store_true", help="Also ensure there is an upcoming game for the demo players and official.")
    args = parser.parse_args()
    try:
        seed_score_demo(new_game=args.new_game, ensure_upcoming=args.upcoming)
    except ValueError as error:
        parser.error(str(error))
