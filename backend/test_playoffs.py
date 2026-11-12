"""Playoff bracket generation and winner advancement; every write stays in a disposable schema."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql as pgsql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

import database
from auth import password_hasher
from main import app
from playoffs import bracket_order

PASSWORD = "Playoff test password"
BASE_URL = None
TEST_SCHEMA = "hokie_playoffs_test_" + uuid.uuid4().hex


def sql(query, params=()):
    with database.db() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else None


def setUpModule():
    global BASE_URL
    BASE_URL = database.DATABASE_URL
    with psycopg.connect(BASE_URL) as conn:
        conn.execute(pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(TEST_SCHEMA)))
    database.DATABASE_URL = make_conninfo(BASE_URL, options=f"-c search_path={TEST_SCHEMA}")
    try:
        root = Path(__file__).resolve().parents[1]
        with database.db() as conn:
            for name in ("schema", "auth", "roster", "phase3", "seed"):
                conn.execute((root / f"db/{name}.sql").read_text())
            conn.execute("""
                INSERT INTO UserCredentials (user_id, password_hash)
                SELECT user_id, %s FROM Users WHERE vt_pid = ANY(%s)
            """, (password_hasher.hash(PASSWORD), ['simvt0001', 'simvt0121', 'simvt0133']))
    except Exception:
        tearDownModule()
        raise


def tearDownModule():
    if BASE_URL is not None:
        with psycopg.connect(BASE_URL) as conn:
            conn.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(pgsql.Identifier(TEST_SCHEMA)))
        database.DATABASE_URL = BASE_URL


def league(sport):
    return sql("SELECT league_id FROM LeagueView WHERE term = 'Fall 2026' AND sport_name = %s", (sport,))[0]['league_id']


def playoff_games(league_id):
    return sql("""
        SELECT game_id, playoff_round, home_team_id, away_team_id, next_game_id, start_time, end_time, facility_id
        FROM Game WHERE league_id = %s AND playoff_round IS NOT NULL ORDER BY playoff_round, start_time, game_id
    """, (league_id,))


class PlayoffCase(unittest.TestCase):
    def setUp(self):
        sql("DELETE FROM AuthLoginAttempt")
        self.admin = self.client_for('simvt0133')
        self.facility = sql("INSERT INTO Facility (facility_name, location) VALUES (%s, 'Test') RETURNING facility_id",
                            ('Playoff test ' + uuid.uuid4().hex[:10],))[0]['facility_id']
        self.start = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)

    def client_for(self, pid=None):
        client = TestClient(app, headers={'X-Requested-With': 'HokieRec'})
        self.addCleanup(client.close)
        if pid:
            response = client.post('/api/auth/login', json={'vt_pid': pid, 'password': PASSWORD})
            self.assertEqual(response.status_code, 200, response.text)
        return client

    def generate(self, league_id, client=None, **overrides):
        body = {'team_count': 4, 'facility_id': self.facility, 'start_time': self.start.isoformat(), **overrides}
        return (client or self.admin).post(f'/api/admin/leagues/{league_id}/playoffs', json=body)

    def remove(self, league_id, client=None):
        return (client or self.admin).delete(f'/api/admin/leagues/{league_id}/playoffs')


class BracketOrderTest(unittest.TestCase):
    def test_top_seeds_meet_only_in_the_final(self):
        self.assertEqual(bracket_order(2), [1, 2])
        self.assertEqual(bracket_order(4), [1, 4, 2, 3])
        self.assertEqual(bracket_order(8), [1, 8, 4, 5, 2, 7, 3, 6])


class GenerateBracketTest(PlayoffCase):
    def test_replaces_seeded_bracket_with_one_seeded_from_standings(self):
        league_id = league('Basketball')
        self.assertEqual(self.remove(league_id).status_code, 204)
        self.assertEqual(playoff_games(league_id), [])

        response = self.generate(league_id, days_between_rounds=3)
        self.assertEqual(response.status_code, 201, response.text)
        standings = [row['team_id'] for row in self.admin.get('/api/reports/standings',
                                                              params={'league_id': league_id}).json()]
        self.assertEqual([s['team_id'] for s in response.json()['seeds']], standings)

        semi1, semi2, final = playoff_games(league_id)
        self.assertEqual((semi1['playoff_round'], semi2['playoff_round'], final['playoff_round']), (1, 1, 2))
        self.assertEqual((semi1['home_team_id'], semi1['away_team_id']), (standings[0], standings[3]))
        self.assertEqual((semi2['home_team_id'], semi2['away_team_id']), (standings[1], standings[2]))
        self.assertEqual((final['home_team_id'], final['away_team_id'], final['next_game_id']), (None, None, None))
        self.assertEqual((semi1['next_game_id'], semi2['next_game_id']), (final['game_id'], final['game_id']))
        # Back to back on the facility, games as long as the league's regular-season games
        length = semi1['end_time'] - semi1['start_time']
        self.assertEqual(length, timedelta(minutes=70))
        self.assertEqual(semi1['start_time'], self.start)
        self.assertEqual(semi2['start_time'], self.start + length + timedelta(minutes=30))
        self.assertEqual(final['start_time'], self.start + timedelta(days=3))
        self.assertEqual(response.json()['games'][2]['round_name'], 'Final')

        # One bracket per league
        self.assertEqual(self.generate(league_id).status_code, 409)

    def test_two_team_bracket_is_a_single_final(self):
        league_id = league('Volleyball')
        self.remove(league_id)
        response = self.generate(league_id, team_count=2)
        self.assertEqual(response.status_code, 201, response.text)
        (final,) = playoff_games(league_id)
        seeds = [s['team_id'] for s in response.json()['seeds']]
        self.assertEqual((final['home_team_id'], final['away_team_id'], final['next_game_id']), (*seeds, None))

    def test_refuses_brackets_that_cannot_be_played(self):
        league_id = league('Flag Football')
        self.remove(league_id)
        self.assertEqual(self.generate(league_id, team_count=8).status_code, 409)  # only 4 teams
        self.assertEqual(self.generate(league_id, team_count=3).status_code, 422)
        self.assertEqual(self.generate(league_id, start_time=(self.start - timedelta(days=60)).isoformat()).status_code, 422)
        self.assertEqual(self.generate(league_id, start_time='2026-12-01T18:00:00').status_code, 422)  # no time zone

        # The facility is taken during the first semifinal
        other = league('Soccer')
        busy = sql("""
            INSERT INTO Game (league_id, facility_id, start_time, end_time)
            VALUES (%s, %s, %s, %s) RETURNING game_id
        """, (other, self.facility, self.start + timedelta(minutes=15), self.start + timedelta(minutes=45)))[0]['game_id']
        self.assertEqual(self.generate(league_id).status_code, 409)
        sql("DELETE FROM Game WHERE game_id = %s", (busy,))

        # A regular-season game without a result
        teams = [r['team_id'] for r in sql("SELECT team_id FROM Team WHERE league_id = %s LIMIT 2", (league_id,))]
        unplayed = sql("""
            INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
            VALUES (%s, %s, %s, %s, NOW() + INTERVAL '1 day', NOW() + INTERVAL '25 hours') RETURNING game_id
        """, (league_id, self.facility, *teams))[0]['game_id']
        response = self.generate(league_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('regular season', response.json()['detail'])
        sql("DELETE FROM Game WHERE game_id = %s", (unplayed,))

        self.assertEqual(playoff_games(league_id), [])
        self.assertEqual(self.generate(league_id).status_code, 201)

    def test_only_admins_manage_brackets(self):
        league_id = league('Ultimate Frisbee')
        for client in (self.client_for(), self.client_for('simvt0001'), self.client_for('simvt0121')):
            self.assertIn(self.remove(league_id, client).status_code, (401, 403))
            self.assertIn(self.generate(league_id, client).status_code, (401, 403))
        self.assertEqual(len(playoff_games(league_id)), 3)
        self.assertEqual(self.generate(999999).status_code, 404)
        self.assertEqual(self.remove(999999).status_code, 404)


class AdvancementTest(PlayoffCase):
    """Uses the seeded Soccer bracket: two semifinals that have ended, and a final in December."""

    def setUp(self):
        super().setUp()
        self.league = league('Soccer')
        self.semi1, self.semi2, self.final = playoff_games(self.league)
        self.official = self.client_for('simvt0121')
        sql("""
            INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
            SELECT g, u.user_id, a.user_id, 'referee', 'accepted'
            FROM unnest(%s::int[]) g, Users u, Users a WHERE u.vt_pid = 'simvt0121' AND a.vt_pid = 'simvt0133'
            ON CONFLICT (game_id, official_id) DO UPDATE SET status = 'accepted'
        """, ([self.semi1['game_id'], self.semi2['game_id'], self.final['game_id']],))

    def submit(self, game, payload):
        return self.official.post(f"/api/games/{game['game_id']}/score-reports", json=payload)

    def final_teams(self):
        row = sql("SELECT home_team_id, away_team_id FROM Game WHERE game_id = %s", (self.final['game_id'],))[0]
        return row['home_team_id'], row['away_team_id']

    def test_winners_fill_the_final_and_corrections_follow(self):
        self.assertEqual(self.submit(self.semi1, {'home_score': 2, 'away_score': 2}).status_code, 422)  # ties don't advance
        self.assertEqual(self.final_teams(), (None, None))

        self.assertEqual(self.submit(self.semi1, {'home_score': 3, 'away_score': 1}).status_code, 201)
        self.assertEqual(self.final_teams(), (self.semi1['home_team_id'], None))
        forfeit = {'forfeit_team_id': self.semi2['home_team_id']}
        self.assertEqual(self.submit(self.semi2, forfeit).status_code, 201)
        self.assertEqual(self.final_teams(), (self.semi1['home_team_id'], self.semi2['away_team_id']))

        # A correction before the final is played moves the other team through
        self.assertEqual(self.submit(self.semi1, {'home_score': 0, 'away_score': 1}).status_code, 201)
        self.assertEqual(self.final_teams(), (self.semi1['away_team_id'], self.semi2['away_team_id']))

        # A bracket with results can't be removed
        self.assertEqual(self.remove(self.league).status_code, 409)

        # Once the final has a result, a semifinal correction can't change who advanced
        sql("UPDATE Game SET start_time = NOW() - INTERVAL '2 hours', end_time = NOW() - INTERVAL '1 hour' WHERE game_id = %s",
            (self.final['game_id'],))
        self.assertEqual(self.submit(self.final, {'home_score': 4, 'away_score': 0}).status_code, 201)
        response = self.submit(self.semi1, {'home_score': 5, 'away_score': 0})
        self.assertEqual(response.status_code, 409)
        self.assertIn('next round', response.json()['detail'])
        self.assertEqual(self.final_teams(), (self.semi1['away_team_id'], self.semi2['away_team_id']))
        # Same winner is still fine
        self.assertEqual(self.submit(self.semi1, {'home_score': 0, 'away_score': 3}).status_code, 201)


class FeederOrderTest(PlayoffCase):
    def test_earlier_semifinal_fills_home_even_with_a_higher_game_id(self):
        league_id = league('Dodgeball')
        self.remove(league_id)
        self.assertEqual(self.generate(league_id).status_code, 201)
        early, late, final = playoff_games(league_id)
        # Swap the semifinal times so the later-inserted game kicks off first
        sql("UPDATE Game SET start_time = start_time - INTERVAL '40 days', end_time = end_time - INTERVAL '40 days' WHERE game_id = %s",
            (late['game_id'],))
        sql("UPDATE Game SET start_time = start_time - INTERVAL '39 days', end_time = end_time - INTERVAL '39 days' WHERE game_id = %s",
            (early['game_id'],))
        self.assertGreater(late['game_id'], early['game_id'])
        official = self.client_for('simvt0121')
        sql("""
            INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
            SELECT %s, u.user_id, a.user_id, 'referee', 'accepted' FROM Users u, Users a
            WHERE u.vt_pid = 'simvt0121' AND a.vt_pid = 'simvt0133'
        """, (late['game_id'],))
        response = official.post(f"/api/games/{late['game_id']}/score-reports", json={'home_score': 2, 'away_score': 1})
        self.assertEqual(response.status_code, 201, response.text)
        row = sql("SELECT home_team_id, away_team_id FROM Game WHERE game_id = %s", (final['game_id'],))[0]
        self.assertEqual((row['home_team_id'], row['away_team_id']), (late['home_team_id'], None))


if __name__ == '__main__':
    unittest.main()
