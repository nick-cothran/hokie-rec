"""Score workflow integration tests; every write stays in a disposable schema."""

import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg import sql as pgsql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

import database
from auth import password_hasher
from main import app

PASSWORD = "Scoring test password"
BASE_URL = None
TEST_SCHEMA = "hokie_scores_test_" + uuid.uuid4().hex


def sql(query, params=()):
    with database.db() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else None


def setUpModule():
    global BASE_URL
    # Resolve the base here, not at import: test_main also switches the shared
    # factory during its own module's tests and restores it in tearDownModule.
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
            """, (password_hasher.hash(PASSWORD), ['simvt0001', 'simvt0002', 'simvt0121', 'simvt0122', 'simvt0133']))
    except Exception:
        tearDownModule()
        raise


def tearDownModule():
    if BASE_URL is not None:
        with psycopg.connect(BASE_URL) as conn:
            conn.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(pgsql.Identifier(TEST_SCHEMA)))
        database.DATABASE_URL = BASE_URL


class ScoreReportingTest(unittest.TestCase):
    def setUp(self):
        sql("DELETE FROM AuthLoginAttempt")
        self.people = {row['vt_pid']: row['user_id'] for row in sql("SELECT user_id, vt_pid FROM Users")}
        self.official = self.people['simvt0121']
        self.league = sql("SELECT league_id FROM LeagueView WHERE term = 'Fall 2026' AND sport_name = 'Soccer'")[0]['league_id']
        teams = sql("SELECT team_id FROM Team WHERE league_id = %s ORDER BY team_id LIMIT 2", (self.league,))
        self.home, self.away = [row['team_id'] for row in teams]
        self.facility = sql("INSERT INTO Facility (facility_name, location) VALUES (%s, 'Test') RETURNING facility_id",
                            ('Score test ' + uuid.uuid4().hex[:10],))[0]['facility_id']
        self.game = sql("""
            INSERT INTO Game (league_id, facility_id, home_team_id, away_team_id, start_time, end_time)
            VALUES (%s, %s, %s, %s, NOW() - INTERVAL '3 hours', NOW() - INTERVAL '1 hour') RETURNING game_id
        """, (self.league, self.facility, self.home, self.away))[0]['game_id']
        sql("""
            INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
            VALUES (%s, %s, %s, 'referee', 'accepted')
        """, (self.game, self.official, self.people['simvt0133']))
        self.client = self.client_for('simvt0121')

    def tearDown(self):
        sql("DELETE FROM Game WHERE game_id = %s", (self.game,))
        sql("DELETE FROM Facility WHERE facility_id = %s", (self.facility,))

    def client_for(self, pid=None):
        client = TestClient(app, headers={'X-Requested-With': 'HokieRec'})
        self.addCleanup(client.close)
        if pid:
            response = client.post('/api/auth/login', json={'vt_pid': pid, 'password': PASSWORD})
            self.assertEqual(response.status_code, 200, response.text)
        return client

    @property
    def path(self):
        return f'/api/games/{self.game}/score-reports'

    def submit(self, payload=None, client=None):
        return (client or self.client).post(self.path, json=payload if payload is not None else {'home_score': 4, 'away_score': 2})

    def history(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def reports(self):
        return sql('SELECT * FROM ScoreReport WHERE game_id = %s ORDER BY report_id', (self.game,))

    def standings(self):
        response = self.client.get('/api/reports/standings', params={'league_id': self.league})
        self.assertEqual(response.status_code, 200)
        return {row['team_id']: row for row in response.json()}

    def participation(self):
        return next(row for row in self.client.get('/api/reports/participation').json() if row['league_id'] == self.league)

    def test_first_result_records_session_official_and_completes_game(self):
        self.assertTrue(self.history()['can_submit'])
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.text)
        report = self.reports()[0]
        self.assertEqual(report['submitted_by'], self.official)
        self.assertEqual((report['home_score'], report['away_score']), (4, 2))
        self.assertEqual(sql('SELECT status FROM Game WHERE game_id = %s', (self.game,))[0]['status'], 'completed')
        context = self.history()
        self.assertEqual(context['reports'][0]['report_id'], response.json()['report_id'])
        self.assertTrue(context['reports'][0]['is_current'])
        self.assertEqual(self.client.get(self.path).headers['cache-control'], 'no-store')

    def test_zero_and_tied_scores_are_valid(self):
        self.assertEqual(self.submit({'home_score': 0, 'away_score': 0}).status_code, 201)
        self.assertEqual(self.reports()[0]['home_score'], 0)

    def test_maximum_postgres_integer_score_is_valid(self):
        self.assertEqual(self.submit({'home_score': 2147483647, 'away_score': 0}).status_code, 201)

    def test_corrections_append_and_preserve_original(self):
        self.submit()
        original = self.reports()[0]
        self.assertEqual(self.submit({'home_score': 1, 'away_score': 5}).status_code, 201)
        rows = self.reports()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], original)
        history = self.history()['reports']
        self.assertEqual([row['is_current'] for row in history], [True, False])
        self.assertEqual((history[0]['home_score'], history[0]['away_score']), (1, 5))

    def test_schedule_and_reports_use_latest_correction_once(self):
        before = self.standings()
        participation = self.participation()
        self.submit()
        self.submit({'home_score': 1, 'away_score': 5})
        after = self.standings()
        self.assertEqual(after[self.home]['played'], before[self.home]['played'] + 1)
        self.assertEqual(after[self.home]['losses'], before[self.home]['losses'] + 1)
        self.assertEqual(after[self.home]['wins'], before[self.home]['wins'])
        self.assertEqual(after[self.away]['wins'], before[self.away]['wins'] + 1)
        game = next(row for row in self.client.get('/api/games', params={'league_id': self.league}).json() if row['game_id'] == self.game)
        self.assertEqual((game['home_score'], game['away_score'], game['status']), (1, 5, 'completed'))
        updated = self.participation()
        self.assertEqual(updated['games_played'], participation['games_played'] + 1)
        self.assertEqual(updated['games_remaining'], participation['games_remaining'] - 1)

    def test_forfeit_and_correction_back_to_scores(self):
        before = self.standings()
        self.assertEqual(self.submit({'forfeit_team_id': self.home}).status_code, 201)
        report = self.reports()[0]
        self.assertIsNone(report['home_score'])
        self.assertIsNone(report['away_score'])
        self.assertEqual(self.standings()[self.home]['losses'], before[self.home]['losses'] + 1)
        self.assertEqual(self.submit({'home_score': 3, 'away_score': 1}).status_code, 201)
        self.assertEqual(self.standings()[self.home]['losses'], before[self.home]['losses'])
        self.assertEqual(self.standings()[self.home]['wins'], before[self.home]['wins'] + 1)

    def test_away_forfeit_counts_as_home_win(self):
        before = self.standings()
        self.assertEqual(self.submit({'forfeit_team_id': self.away}).status_code, 201)
        self.assertEqual(self.standings()[self.home]['wins'], before[self.home]['wins'] + 1)

    def test_invalid_score_payloads_rejected_without_writes(self):
        payloads = [
            {}, {'home_score': 1}, {'away_score': 2}, {'home_score': None, 'away_score': None},
            {'home_score': -1, 'away_score': 0}, {'home_score': 1.5, 'away_score': 0},
            {'home_score': 1.0, 'away_score': 0}, {'home_score': True, 'away_score': 0},
            {'home_score': '2', 'away_score': 0}, {'home_score': 2147483648, 'away_score': 0},
            {'forfeit_team_id': False}, {'forfeit_team_id': 0}, {'forfeit_team_id': 1.2},
            {'forfeit_team_id': self.home, 'home_score': 2, 'away_score': 0},
            {'home_score': 1, 'away_score': 0, 'submitted_by': self.people['simvt0133']},
            {'home_score': 1, 'away_score': 0, 'user_id': self.official},
            {'home_score': 1, 'away_score': 0, 'is_forfeit': True},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.submit(payload).status_code, 422)
        self.assertEqual(self.reports(), [])

    def test_forfeit_must_name_a_participating_team(self):
        outsider = sql('SELECT team_id FROM Team WHERE team_id NOT IN (%s, %s) LIMIT 1', (self.home, self.away))[0]['team_id']
        self.assertEqual(self.submit({'forfeit_team_id': outsider}).status_code, 422)
        self.assertEqual(self.reports(), [])

    def test_anonymous_cannot_read_or_submit(self):
        client = self.client_for()
        self.assertEqual(client.get(self.path).status_code, 401)
        self.assertEqual(self.submit(client=client).status_code, 401)

    def test_players_and_admins_cannot_submit(self):
        for pid in ('simvt0001', 'simvt0133'):
            with self.subTest(pid=pid):
                self.assertEqual(self.submit(client=self.client_for(pid)).status_code, 403)
        self.assertEqual(self.reports(), [])

    def test_admin_history_is_read_only(self):
        self.submit()
        response = self.client_for('simvt0133').get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_submit'])
        self.assertEqual(len(response.json()['reports']), 1)

    def test_player_and_unassigned_official_cannot_read_history(self):
        for pid in ('simvt0001', 'simvt0122'):
            self.assertEqual(self.client_for(pid).get(self.path).status_code, 403)

    def test_unassigned_official_cannot_submit(self):
        self.assertEqual(self.submit(client=self.client_for('simvt0122')).status_code, 403)

    def test_declined_assignment_cannot_submit_but_can_read_history(self):
        sql("UPDATE OfficiatingAssignment SET status = 'declined' WHERE game_id = %s", (self.game,))
        self.assertEqual(self.submit().status_code, 403)
        self.assertFalse(self.history()['can_submit'])

    def test_inactive_and_demoted_officials_cannot_submit(self):
        sql('UPDATE Users SET is_active = FALSE WHERE user_id = %s', (self.official,))
        try:
            self.assertEqual(self.submit().status_code, 401)
        finally:
            sql('UPDATE Users SET is_active = TRUE WHERE user_id = %s', (self.official,))
        sql("UPDATE Users SET role = 'player' WHERE user_id = %s", (self.official,))
        try:
            self.assertEqual(self.submit().status_code, 403)
        finally:
            sql("UPDATE Users SET role = 'official' WHERE user_id = %s", (self.official,))

    def test_unknown_game_is_404(self):
        self.assertEqual(self.client.get('/api/games/2147483647/score-reports').status_code, 404)
        self.assertEqual(self.client.post('/api/games/2147483647/score-reports', json={'home_score': 1, 'away_score': 0}).status_code, 404)

    def test_cancelled_game_is_rejected(self):
        sql("UPDATE Game SET status = 'cancelled' WHERE game_id = %s", (self.game,))
        self.assertEqual(self.submit().status_code, 409)
        self.assertFalse(self.history()['can_submit'])

    def test_undecided_teams_are_rejected(self):
        sql('UPDATE Game SET away_team_id = NULL WHERE game_id = %s', (self.game,))
        self.assertEqual(self.submit().status_code, 409)
        self.assertFalse(self.history()['can_submit'])

    def test_game_before_scheduled_end_is_rejected(self):
        sql("UPDATE Game SET end_time = NOW() + INTERVAL '1 hour' WHERE game_id = %s", (self.game,))
        self.assertEqual(self.submit().status_code, 409)
        self.assertFalse(self.history()['can_submit'])

    def test_csrf_protection_applies(self):
        self.assertEqual(self.client.post(self.path, json={'home_score': 1, 'away_score': 0}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.client.headers.pop('X-Requested-With')
        self.assertEqual(self.submit().status_code, 403)

    def test_existing_reports_have_no_edit_or_delete_endpoints(self):
        self.submit()
        before = self.reports()
        for method in ('PATCH', 'PUT', 'DELETE'):
            self.assertEqual(self.client.request(method, self.path, json={'home_score': 99, 'away_score': 0}).status_code, 405)
        self.assertEqual(self.reports(), before)

    def test_failure_to_complete_game_rolls_back_report(self):
        sql(f"ALTER TABLE Game ADD CONSTRAINT test_completion_block CHECK (game_id <> {self.game} OR status <> 'completed')")
        try:
            self.assertEqual(self.submit().status_code, 409)
            self.assertEqual(self.reports(), [])
            self.assertEqual(sql('SELECT status FROM Game WHERE game_id = %s', (self.game,))[0]['status'], 'scheduled')
        finally:
            sql('ALTER TABLE Game DROP CONSTRAINT test_completion_block')

    def test_concurrent_reports_preserve_both_and_have_one_current_result(self):
        clients = [self.client_for('simvt0121'), self.client_for('simvt0121')]
        def submit(index):
            return self.submit({'home_score': index + 1, 'away_score': 0}, client=clients[index])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        self.assertEqual([response.status_code for response in responses], [201, 201])
        rows = self.history()['reports']
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row['is_current'] for row in rows), 1)
        self.assertEqual(rows[0]['report_id'], max(response.json()['report_id'] for response in responses))


class DemoScoreSeedTest(unittest.TestCase):
    def test_fixture_is_idempotent_preserves_scores_and_can_add_fresh_game(self):
        from seed_score_demo import seed_score_demo
        first = seed_score_demo()
        self.assertEqual(seed_score_demo(), first)
        self.assertEqual(sql('SELECT COUNT(*) AS n FROM ScoreReport WHERE game_id = %s', (first,))[0]['n'], 0)
        row = sql("""
            SELECT g.status, g.end_time < NOW() AS ended, oa.status AS assignment_status,
                   u.vt_pid FROM Game g JOIN OfficiatingAssignment oa USING (game_id)
            JOIN Users u ON u.user_id = oa.official_id WHERE g.game_id = %s
        """, (first,))[0]
        self.assertEqual(row['vt_pid'], 'simvt0121')
        self.assertTrue(row['ended'])
        self.assertEqual(row['status'], 'scheduled')
        self.assertEqual(row['assignment_status'], 'accepted')
        with TestClient(app, headers={'X-Requested-With': 'HokieRec'}) as client:
            self.assertEqual(client.post('/api/auth/login', json={'vt_pid': 'simvt0121', 'password': PASSWORD}).status_code, 200)
            self.assertEqual(client.post(f'/api/games/{first}/score-reports', json={'home_score': 2, 'away_score': 1}).status_code, 201)
        self.assertEqual(seed_score_demo(), first)
        second = seed_score_demo(new_game=True)
        self.assertNotEqual(first, second)
        self.assertEqual(sql('SELECT COUNT(*) AS n FROM ScoreReport WHERE game_id = %s', (first,))[0]['n'], 1)
        self.assertEqual(sql('SELECT COUNT(*) AS n FROM ScoreReport WHERE game_id = %s', (second,))[0]['n'], 0)
        self.assertEqual(sql('SELECT COUNT(*) AS n FROM Users')[0]['n'], 135)


if __name__ == '__main__':
    unittest.main()
