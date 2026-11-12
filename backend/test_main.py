# Integration tests use a disposable PostgreSQL schema; existing application data is untouched.
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from psycopg import sql as pgsql
from psycopg.conninfo import make_conninfo
import database

BASE_URL = database.DATABASE_URL
TEST_SCHEMA = "hokie_rec_test_" + uuid.uuid4().hex
database.DATABASE_URL = make_conninfo(BASE_URL, options=f"-c search_path={TEST_SCHEMA}")
DATABASE_URL = database.DATABASE_URL

import main
from main import app
from auth import COOKIE_NAME, password_hasher, token_hash

PASSWORD = "Test-only-password-2026"


def setUpModule():
    with psycopg.connect(BASE_URL) as conn:
        conn.execute(pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(TEST_SCHEMA)))
    try:
        root = Path(__file__).resolve().parents[1]
        with psycopg.connect(DATABASE_URL) as conn:
            for name in ("schema", "auth", "roster", "phase3", "seed"):
                conn.execute((root / f"db/{name}.sql").read_text())
            # The API tests use the newest league; open its registration and roster for them.
            conn.execute("""UPDATE League SET reg_open_at = NOW() - INTERVAL '1 day', reg_close_at = NOW() + INTERVAL '30 days',
                            roster_lock_date = CURRENT_DATE + 30 WHERE league_id = (SELECT MAX(league_id) FROM League)""")
            conn.execute("INSERT INTO UserCredentials (user_id, password_hash) SELECT user_id, %s FROM Users",
                         (password_hasher.hash(PASSWORD),))
    except Exception:
        tearDownModule()
        raise


def tearDownModule():
    with psycopg.connect(BASE_URL) as conn:
        conn.execute(pgsql.SQL("DROP SCHEMA {} CASCADE").format(pgsql.Identifier(TEST_SCHEMA)))
    database.DATABASE_URL = BASE_URL

client = TestClient(app, headers={"X-Requested-With": "HokieRec"})


def sign_in(user_id):
    pid = sql("SELECT vt_pid FROM Users WHERE user_id = %s", (user_id,))[0][0]
    response = client.post("/api/auth/login", json={"vt_pid": pid, "password": PASSWORD})
    if response.status_code != 200:
        raise AssertionError(response.text)


def sql(query, params=()):
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def eligible_players(n):
    return [r[0] for r in sql(
        "SELECT user_id FROM Users WHERE role = 'player' AND is_active "
        "AND (suspended_until IS NULL OR suspended_until < CURRENT_DATE) ORDER BY user_id LIMIT %s", (n,))]


class TeamCase(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        self.captain, self.other = eligible_players(2)
        sign_in(self.captain)
        self.league_id = sql("SELECT league_id FROM League ORDER BY league_id DESC LIMIT 1")[0][0]
        self.name = f"Test {uuid.uuid4().hex[:8]}"

    def tearDown(self):
        sql("DELETE FROM Team WHERE team_name LIKE %s", (self.name + "%",))  # roster rows cascade

    def register(self, name=None, user_id=None):
        if user_id is not None:
            sign_in(user_id)
        return client.post("/api/teams", json={
            "league_id": self.league_id, "team_name": name or self.name})

    def adjust_league(self, assignments):
        # Change the test league's rules for one test; restored afterwards
        old = sql("SELECT reg_open_at, reg_close_at, roster_lock_date FROM League WHERE league_id = %s",
                  (self.league_id,))[0]
        sql(f"UPDATE League SET {assignments} WHERE league_id = %s", (self.league_id,))
        self.addCleanup(sql, "UPDATE League SET reg_open_at = %s, reg_close_at = %s, roster_lock_date = %s "
                             "WHERE league_id = %s", (*old, self.league_id))

    def adjust_sport(self, assignments):
        # Roster limits live on Sport; the test league is its sport's only league, so no other league changes
        sport_id, *old = sql("SELECT sport_id, min_roster_size, max_roster_size FROM Sport JOIN League USING (sport_id) "
                             "WHERE league_id = %s", (self.league_id,))[0]
        sql(f"UPDATE Sport SET {assignments} WHERE sport_id = %s", (sport_id,))
        self.addCleanup(sql, "UPDATE Sport SET min_roster_size = %s, max_roster_size = %s WHERE sport_id = %s",
                        (*old, sport_id))



class ApiTest(TeamCase):
    def test_leagues_report_open_closed_and_upcoming_registration(self):
        def registration():
            response = client.get("/api/leagues")
            self.assertEqual(response.status_code, 200)
            return next(row for row in response.json() if row["league_id"] == self.league_id)

        self.adjust_league("reg_open_at = NOW() - INTERVAL '2 days', reg_close_at = NOW() - INTERVAL '1 day'")
        closed = registration()
        self.assertFalse(closed["registration_open"])
        self.assertIn("reg_open_at", closed)
        self.assertIn("reg_close_at", closed)

        self.adjust_league("reg_open_at = NOW() + INTERVAL '1 day', reg_close_at = NOW() + INTERVAL '2 days'")
        self.assertFalse(registration()["registration_open"])
        self.assertEqual(self.register().status_code, 409)

        self.adjust_league("reg_open_at = NOW() - INTERVAL '1 day', reg_close_at = NOW() + INTERVAL '1 day'")
        self.assertTrue(registration()["registration_open"])
        self.assertEqual(self.register().status_code, 201)

    def test_seed_has_six_leagues_open_on_november_10(self):
        rows = sql("""
            SELECT sport_name,
                   TIMESTAMPTZ '2026-11-10 12:00:00-05:00' BETWEEN reg_open_at AND reg_close_at
            FROM LeagueView
            WHERE term = 'Spring 2027' AND reg_open_at = TIMESTAMPTZ '2026-11-01 09:00:00-05:00'
        """)
        self.assertEqual({row[0] for row in rows},
                         {'Soccer', 'Basketball', 'Volleyball', 'Flag Football', 'Ultimate Frisbee', 'Dodgeball'})
        self.assertTrue(all(row[1] for row in rows))

    def test_seed_demo_has_scoreable_semifinals_and_upcoming_finals(self):
        # As of Nov 10: semifinals are over but unscored (officials enter results in the app),
        # finals are still ahead with pending assignments (officials can accept or decline).
        rows = sql("""
            SELECT g.playoff_round, COUNT(DISTINCT g.game_id),
                   BOOL_AND(g.end_time < TIMESTAMPTZ '2026-11-10 12:00:00-05:00'),
                   BOOL_AND(g.start_time > TIMESTAMPTZ '2026-11-10 12:00:00-05:00'),
                   BOOL_AND(g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL),
                   COUNT(r.report_id), BOOL_AND(a.status = 'assigned')
            FROM Game g JOIN OfficiatingAssignment a ON a.game_id = g.game_id
            LEFT JOIN ScoreReport r ON r.game_id = g.game_id
            WHERE g.playoff_round IS NOT NULL GROUP BY g.playoff_round ORDER BY g.playoff_round
        """)
        self.assertEqual(rows, [(1, 12, True, False, True, 0, True), (2, 6, False, True, False, 0, True)])

    def test_s2_registration_closed_is_409(self):
        self.adjust_league("reg_close_at = NOW() - INTERVAL '1 minute'")
        r = self.register()
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Registration for this league is not open."))

    def test_s2_already_on_team_in_league_is_409(self):
        self.register()
        r = self.register(name=self.name + "b")
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Already on a team in this league."))

    def test_health_reports_connection(self):
        body = client.get("/api/health").json()
        self.assertEqual(body["status"], "connected")
        self.assertIn("PostgreSQL", body["version"])

    def test_user_picker_endpoint_removed(self):
        self.assertEqual(client.get("/api/users").status_code, 404)

    def test_s1_leagues_filter(self):
        rows = client.get("/api/leagues", params={"sport": "Soccer"}).json()
        self.assertTrue(rows)
        self.assertTrue(all(r["sport_name"] == "Soccer" for r in rows))
        self.assertIn("team_count", rows[0])
        self.assertGreater(len(client.get("/api/leagues").json()), len(rows))

    def test_teams_list_filters_by_league(self):
        team_id = self.register().json()["team_id"]
        rows = client.get("/api/teams", params={"league_id": self.league_id}).json()
        self.assertTrue(all(r["league_id"] == self.league_id for r in rows))
        mine = next(r for r in rows if r["team_id"] == team_id)
        self.assertEqual(mine["member_count"], 1)
        self.assertIn("captain_last_name", mine)
        self.assertGreaterEqual(len(client.get("/api/teams").json()), len(rows))

    def test_s2_register_team_adds_captain_to_roster(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        team = client.get(f"/api/teams/{r.json()['team_id']}").json()
        self.assertEqual(team["captain_id"], self.captain)
        self.assertEqual([(m["user_id"], m["status"]) for m in team["roster"]], [(self.captain, "active")])

    def test_s2_duplicate_name_is_readable_409(self):
        self.register()
        r = self.register(user_id=self.other)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "A team with that name already exists in this league.")

    def test_s2_unknown_league_is_readable_409(self):
        r = client.post("/api/teams", json={"league_id": 999999, "team_name": self.name})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "That league does not exist.")

    def test_s2_rejects_non_player(self):
        official = sql("SELECT user_id FROM Users WHERE role = 'official' LIMIT 1")[0][0]
        self.assertEqual(self.register(user_id=official).status_code, 403)

    def test_s2_rejects_suspended_player(self):
        previous = sql("SELECT suspended_until FROM Users WHERE user_id = %s", (self.other,))[0][0]
        sql("UPDATE Users SET suspended_until = CURRENT_DATE + 1 WHERE user_id = %s", (self.other,))
        try:
            self.assertEqual(self.register(user_id=self.other).status_code, 403)
        finally:
            sql("UPDATE Users SET suspended_until = %s WHERE user_id = %s", (previous, self.other))

    def test_bad_text_is_readable_422_not_500(self):
        r = client.get("/api/leagues", params={"sport": "a\x00"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("detail", r.json())

    def test_s2_rejects_blank_and_too_long_names(self):
        self.assertEqual(self.register(name="   ").status_code, 422)
        self.assertEqual(self.register(name="x" * 61).status_code, 422)

    def test_s3_captain_renames_team(self):
        team_id = self.register().json()["team_id"]
        r = client.patch(f"/api/teams/{team_id}", json={"team_name": self.name + "b"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get(f"/api/teams/{team_id}").json()["team_name"], self.name + "b")

    def test_s3_non_captain_cannot_rename(self):
        team_id = self.register().json()["team_id"]
        sign_in(self.other)
        r = client.patch(f"/api/teams/{team_id}", json={"team_name": self.name + "b"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client.get(f"/api/teams/{team_id}").json()["team_name"], self.name)

    def test_s3_missing_team_is_404(self):
        r = client.patch("/api/teams/999999", json={"team_name": self.name})
        self.assertEqual(r.status_code, 404)

    def test_s2_new_team_uses_column_defaults(self):
        team_id = self.register().json()["team_id"]
        status, registered_today = sql(
            "SELECT status, registered_at::date = CURRENT_DATE FROM Team WHERE team_id = %s", (team_id,))[0]
        self.assertEqual((status, registered_today), ("active", True))

    def test_delete_team_cascades_roster(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        r = client.delete(f"/api/teams/{team_id}")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 404)
        self.assertEqual(sql("SELECT COUNT(*) FROM RosterMembership WHERE team_id = %s", (team_id,))[0][0], 0)

    def test_delete_team_non_captain_forbidden(self):
        team_id = self.register().json()["team_id"]
        sign_in(self.other)
        r = client.delete(f"/api/teams/{team_id}")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 200)

    def test_delete_team_with_games_is_readable_409(self):
        team_id, captain_id = sql("""
            SELECT t.team_id, t.captain_id FROM Team t
            WHERE EXISTS (SELECT 1 FROM Game g WHERE t.team_id IN (g.home_team_id, g.away_team_id))
            ORDER BY t.team_id LIMIT 1""")[0]
        sign_in(captain_id)
        r = client.delete(f"/api/teams/{team_id}")
        self.assertEqual(r.status_code, 409)
        self.assertIn("can't be deleted", r.json()["detail"])
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 200)

    def invite(self, team_id, status="invited"):
        sql("INSERT INTO RosterMembership (team_id, user_id, status, invited_at) VALUES (%s, %s, %s, NOW())",
            (team_id, self.other, status))

    def test_s4_captain_withdraws_invite(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}")
        self.assertEqual(r.status_code, 204)
        roster = client.get(f"/api/teams/{team_id}").json()["roster"]
        self.assertNotIn(self.other, [m["user_id"] for m in roster])

    def test_s4_non_captain_cannot_withdraw(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        sign_in(self.other)
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(client.get(f"/api/teams/{team_id}").json()["roster"]), 2)

    def test_s4_active_member_is_not_deleted(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id, status="active")
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(client.get(f"/api/teams/{team_id}").json()["roster"]), 2)


def client_for(user_id):
    """A separate signed-in client, for tests that need two users at once."""
    other = TestClient(app, headers={"X-Requested-With": "HokieRec"})
    pid = sql("SELECT vt_pid FROM Users WHERE user_id = %s", (user_id,))[0][0]
    assert other.post("/api/auth/login", json={"vt_pid": pid, "password": PASSWORD}).status_code == 200
    return other


class RosterCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.third = eligible_players(3)[2]
        self.team_id = self.register().json()["team_id"]

    def pid(self, user_id):
        return sql("SELECT vt_pid FROM Users WHERE user_id = %s", (user_id,))[0][0]

    def invite_pid(self, user_id, team_id=None, pid=None):
        return client.post(f"/api/teams/{team_id or self.team_id}/invites", json={"vt_pid": pid or self.pid(user_id)})

    def status_of(self, user_id, team_id=None):
        rows = sql("SELECT status FROM RosterMembership WHERE team_id = %s AND user_id = %s", (team_id or self.team_id, user_id))
        return rows[0][0] if rows else None

    def accept(self, user_id, team_id=None):
        sign_in(user_id)
        return client.post(f"/api/teams/{team_id or self.team_id}/invite/accept")



class RosterTest(RosterCase):
    def test_captain_invites_by_pid(self):
        r = self.invite_pid(self.other)
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()["user_id"], r.json()["status"]), (self.other, "invited"))
        self.assertEqual(self.status_of(self.other), "invited")

    def test_invite_pid_is_normalized(self):
        self.assertEqual(self.invite_pid(self.other, pid=f"  {self.pid(self.other).upper()} ").status_code, 201)

    def test_invite_unknown_pid_404(self):
        r = self.invite_pid(None, pid="nosuchpid")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "No player with that PID."))

    def test_non_captain_cannot_invite_403(self):
        sign_in(self.other)
        self.assertEqual(self.invite_pid(self.third).status_code, 403)
        self.assertIsNone(self.status_of(self.third))

    def test_anonymous_invite_401(self):
        client.cookies.clear()
        self.assertEqual(self.invite_pid(self.other).status_code, 401)

    def test_invite_twice_409(self):
        self.invite_pid(self.other)
        r = self.invite_pid(self.other)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "That player is already invited to or on this team."))

    def test_invite_suspended_409(self):
        previous = sql("SELECT suspended_until FROM Users WHERE user_id = %s", (self.other,))[0][0]
        sql("UPDATE Users SET suspended_until = CURRENT_DATE + 3 WHERE user_id = %s", (self.other,))
        self.addCleanup(sql, "UPDATE Users SET suspended_until = %s WHERE user_id = %s", (previous, self.other))
        r = self.invite_pid(self.other)
        # Captains learn the player is suspended, never the disciplinary end date
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Suspended players can't join teams."))

    def test_invite_player_active_in_league_409(self):
        self.register(name=self.name + "b", user_id=self.other)  # other captains another team in this league
        sign_in(self.captain)
        r = self.invite_pid(self.other)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Already on a team in this league."))

    def test_invite_after_lock_409(self):
        self.adjust_league("roster_lock_date = CURRENT_DATE - 1")
        r = self.invite_pid(self.other)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["detail"].startswith("The roster is locked"))

    def test_my_invites_lists_pending_only(self):
        self.invite_pid(self.other)
        sign_in(self.other)
        rows = client.get("/api/me/invites").json()
        mine = [r for r in rows if r["team_id"] == self.team_id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["max_roster_size"], sql("SELECT max_roster_size FROM LeagueView WHERE league_id = %s",
                                                         (self.league_id,))[0][0])
        self.assertEqual((mine[0]["active_count"], mine[0]["roster_locked"]), (1, False))
        self.accept(self.other)
        self.assertEqual([r for r in client.get("/api/me/invites").json() if r["team_id"] == self.team_id], [])

    def test_my_invites_requires_sign_in(self):
        client.cookies.clear()
        self.assertEqual(client.get("/api/me/invites").status_code, 401)

    def test_accept_makes_active_and_declines_others(self):
        team_b = self.register(name=self.name + "b", user_id=self.third).json()["team_id"]
        self.invite_pid(self.other, team_id=team_b)
        sign_in(self.captain)
        self.invite_pid(self.other)
        self.assertEqual(self.accept(self.other).status_code, 204)
        self.assertEqual(self.status_of(self.other), "active")
        self.assertEqual(self.status_of(self.other, team_b), "declined")
        self.assertIsNotNone(sql("SELECT joined_at FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                                 (self.team_id, self.other))[0][0])

    def test_accept_without_invite_404(self):
        r = self.accept(self.other)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "You don't have a pending invite to this team."))

    def test_accept_full_team_409(self):
        self.invite_pid(self.other)
        self.adjust_sport("max_roster_size = 1, min_roster_size = 0")
        r = self.accept(self.other)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "This team is full (1/1)."))
        self.assertEqual(self.status_of(self.other), "invited")

    def test_accept_after_lock_409(self):
        self.invite_pid(self.other)
        self.adjust_league("roster_lock_date = (NOW() AT TIME ZONE 'America/New_York')::date")  # locked on the day itself
        self.assertEqual(self.accept(self.other).status_code, 409)
        self.assertEqual(self.status_of(self.other), "invited")

    def test_decline_after_lock_ok(self):
        self.invite_pid(self.other)
        self.adjust_league("roster_lock_date = CURRENT_DATE - 1")
        sign_in(self.other)
        self.assertEqual(client.post(f"/api/teams/{self.team_id}/invite/decline").status_code, 204)
        self.assertEqual(self.status_of(self.other), "declined")

    def test_decline_without_invite_404(self):
        sign_in(self.other)
        r = client.post(f"/api/teams/{self.team_id}/invite/decline")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "You don't have a pending invite to this team."))

    def test_reinvite_reuses_row(self):
        self.invite_pid(self.other)
        sign_in(self.other)
        client.post(f"/api/teams/{self.team_id}/invite/decline")
        before = sql("SELECT membership_id FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                     (self.team_id, self.other))[0][0]
        sign_in(self.captain)
        self.assertEqual(self.invite_pid(self.other).status_code, 201)
        after = sql("SELECT membership_id, status FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                    (self.team_id, self.other))
        self.assertEqual(after, [(before, "invited")])

    def test_withdraw_reinvite_keeps_history(self):
        sql("INSERT INTO RosterMembership (team_id, user_id, status, invited_at, joined_at, left_at) "
            "VALUES (%s, %s, 'left', NOW(), NOW(), NOW())", (self.team_id, self.other))
        self.invite_pid(self.other)
        self.assertEqual(client.delete(f"/api/teams/{self.team_id}/invites/{self.other}").status_code, 204)
        self.assertEqual(self.status_of(self.other), "removed")

    def test_withdraw_reinvite_keeps_left_date(self):
        sql("INSERT INTO RosterMembership (team_id, user_id, status, invited_at, joined_at, left_at) "
            "VALUES (%s, %s, 'left', NOW(), NOW() - INTERVAL '30 days', '2026-10-01 12:00+00')", (self.team_id, self.other))
        self.invite_pid(self.other)
        client.delete(f"/api/teams/{self.team_id}/invites/{self.other}")
        self.assertEqual(str(sql("SELECT left_at::date FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                                 (self.team_id, self.other))[0][0]), "2026-10-01")

    def test_withdraw_during_accept_never_reports_false_join(self):
        # Pause accept right after its invite check, then withdraw; the outcome must be consistent either way
        self.invite_pid(self.other)
        checked, withdrawn = threading.Event(), threading.Event()
        real = main.ineligible_reason

        def paused(*args):
            checked.set()
            withdrawn.wait(1)
            return real(*args)

        player, captain = client_for(self.other), client_for(self.captain)
        with patch.object(main, "ineligible_reason", paused), ThreadPoolExecutor(2) as pool:
            accept = pool.submit(player.post, f"/api/teams/{self.team_id}/invite/accept")
            checked.wait(5)
            withdraw = pool.submit(lambda: (captain.delete(f"/api/teams/{self.team_id}/invites/{self.other}"), withdrawn.set()))
            accept_code, withdraw_code = accept.result().status_code, withdraw.result()[0].status_code
        status = self.status_of(self.other)
        if accept_code == 204:
            self.assertEqual((status, withdraw_code), ("active", 404))
        else:
            self.assertEqual((accept_code, withdraw_code, status), (404, 204, None))

    def test_concurrent_accepts_fill_last_spot_once(self):
        self.invite_pid(self.other)
        self.invite_pid(self.third)
        self.adjust_sport("max_roster_size = 2, min_roster_size = 0")
        clients = [client_for(self.other), client_for(self.third)]
        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(lambda c: c.post(f"/api/teams/{self.team_id}/invite/accept").status_code, clients))
        self.assertEqual(sorted(codes), [204, 409])
        self.assertEqual(sql("SELECT COUNT(*) FROM RosterMembership WHERE team_id = %s AND status = 'active'",
                             (self.team_id,))[0][0], 2)


class CaptainActionTest(RosterCase):
    def setUp(self):
        super().setUp()
        self.invite_pid(self.other)
        self.accept(self.other)
        sign_in(self.captain)

    def remove(self, player_id):
        return client.delete(f"/api/teams/{self.team_id}/members/{player_id}")

    def leave(self, user_id):
        sign_in(user_id)
        return client.post(f"/api/teams/{self.team_id}/leave")

    def hand_off(self, user_id):
        return client.put(f"/api/teams/{self.team_id}/captain", json={"user_id": user_id})

    def test_team_detail_has_roster_limits(self):
        team = client.get(f"/api/teams/{self.team_id}").json()
        for key in ("min_roster_size", "max_roster_size", "roster_lock_date"):
            self.assertIn(key, team)
        self.assertIs(team["roster_locked"], False)

    def test_captain_removes_member(self):
        self.assertEqual(self.remove(self.other).status_code, 204)
        self.assertEqual(sql("SELECT status, left_at IS NOT NULL FROM RosterMembership WHERE team_id = %s AND user_id = %s",
                             (self.team_id, self.other)), [("removed", True)])

    def test_captain_cannot_remove_self_409(self):
        r = self.remove(self.captain)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "The captain can't be removed. Hand off captaincy first."))

    def test_remove_non_member_404(self):
        r = self.remove(self.third)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "That player isn't an active member of this team."))

    def test_non_captain_cannot_remove_403(self):
        sign_in(self.other)
        self.assertEqual(self.remove(self.captain).status_code, 403)

    def test_anonymous_remove_401(self):
        client.cookies.clear()
        self.assertEqual(self.remove(self.other).status_code, 401)

    def test_remove_after_lock_409(self):
        self.adjust_league("roster_lock_date = CURRENT_DATE - 1")
        self.assertEqual(self.remove(self.other).status_code, 409)
        self.assertEqual(self.status_of(self.other), "active")

    def test_member_leaves(self):
        self.assertEqual(self.leave(self.other).status_code, 204)
        self.assertEqual(self.status_of(self.other), "left")

    def test_captain_cannot_leave_409(self):
        r = self.leave(self.captain)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Hand off captaincy before leaving the team."))

    def test_non_member_cannot_leave_404(self):
        r = self.leave(self.third)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "You aren't an active member of this team."))

    def test_leave_after_lock_409(self):
        self.adjust_league("roster_lock_date = CURRENT_DATE - 1")
        self.assertEqual(self.leave(self.other).status_code, 409)

    def test_handoff_to_active_member(self):
        r = self.hand_off(self.other)
        self.assertEqual((r.status_code, r.json()), (200, {"team_id": self.team_id, "captain_id": self.other}))

    def test_handoff_to_non_member_409(self):
        r = self.hand_off(self.third)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "The new captain must be an active member of this team."))

    def test_non_captain_cannot_handoff_403(self):
        sign_in(self.other)
        self.assertEqual(self.hand_off(self.other).status_code, 403)
        self.assertEqual(client.get(f"/api/teams/{self.team_id}").json()["captain_id"], self.captain)

    def test_handoff_after_lock_ok(self):
        self.adjust_league("roster_lock_date = CURRENT_DATE - 1")
        self.assertEqual(self.hand_off(self.other).status_code, 200)

    def test_handoff_then_leave(self):
        self.hand_off(self.other)
        self.assertEqual(self.remove(self.other).status_code, 403)
        self.assertEqual(self.leave(self.captain).status_code, 204)
        team = client.get(f"/api/teams/{self.team_id}").json()
        self.assertEqual(team["captain_id"], self.other)
        self.assertEqual(self.status_of(self.captain), "left")


class GamesTest(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()

    def test_games_filter_by_league(self):
        league_id, n = sql("SELECT league_id, COUNT(*) FROM Game GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 1")[0]
        games = client.get(f"/api/games?league_id={league_id}").json()
        self.assertEqual(len(games), n)
        self.assertTrue(all(g["league_id"] == league_id for g in games))
        self.assertEqual([g["start_time"] for g in games], sorted(g["start_time"] for g in games))

    def test_games_filter_by_team_either_side(self):
        team_id = sql("SELECT home_team_id FROM Game WHERE home_team_id IS NOT NULL LIMIT 1")[0][0]
        n = sql("SELECT COUNT(*) FROM Game WHERE %s IN (home_team_id, away_team_id)", (team_id,))[0][0]
        games = client.get(f"/api/games?team_id={team_id}").json()
        self.assertEqual(len(games), n)
        self.assertTrue(all(team_id in (g["home_team_id"], g["away_team_id"]) for g in games))
        self.assertTrue(any(g["away_team_id"] == team_id for g in games))

    def test_games_show_latest_score(self):
        game_id, official = sql("""
            SELECT g.game_id, oa.official_id FROM Game g JOIN OfficiatingAssignment oa ON oa.game_id = g.game_id
            WHERE g.status = 'completed' AND oa.status <> 'declined' ORDER BY g.game_id LIMIT 1""")[0]
        report_id = sql("""INSERT INTO ScoreReport (game_id, submitted_by, home_score, away_score, submitted_at)
                           VALUES (%s, %s, 9, 8, NOW() + INTERVAL '1 day') RETURNING report_id""", (game_id, official))[0][0]
        self.addCleanup(sql, "DELETE FROM ScoreReport WHERE report_id = %s", (report_id,))
        league_id = sql("SELECT league_id FROM Game WHERE game_id = %s", (game_id,))[0][0]
        game = next(g for g in client.get(f"/api/games?league_id={league_id}").json() if g["game_id"] == game_id)
        self.assertEqual((game["home_score"], game["away_score"]), (9, 8))

    def test_games_forfeit_row(self):
        game_id, forfeit = sql("SELECT game_id, forfeit_team_id FROM LatestScoreReport WHERE forfeit_team_id IS NOT NULL LIMIT 1")[0]
        game = next(g for g in client.get(f"/api/games?team_id={forfeit}").json() if g["game_id"] == game_id)
        self.assertEqual(game["forfeit_team_id"], forfeit)

    def test_undecided_playoff_game_has_null_teams(self):
        game_id, league_id = sql("SELECT game_id, league_id FROM Game WHERE home_team_id IS NULL LIMIT 1")[0]
        game = next(g for g in client.get(f"/api/games?league_id={league_id}").json() if g["game_id"] == game_id)
        self.assertIsNone(game["home_team_name"])
        self.assertIsNotNone(game["playoff_round"])


class AssignmentTest(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        uid = lambda pid: sql("SELECT user_id FROM Users WHERE vt_pid = %s", (pid,))[0][0]
        self.o1, self.o2, admin = uid("simvt0121"), uid("simvt0122"), uid("simvt0133")
        self.game_id = sql("""
            INSERT INTO Game (league_id, facility_id, start_time, end_time, playoff_round)
            SELECT league_id, (SELECT MIN(facility_id) FROM Facility), NOW() + INTERVAL '7 days', NOW() + INTERVAL '7 days 1 hour', 3
            FROM Game ORDER BY game_id LIMIT 1 RETURNING game_id""")[0][0]
        self.addCleanup(sql, "DELETE FROM Game WHERE game_id = %s", (self.game_id,))  # assignments cascade
        self.assignment_id = sql("""INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
                                    VALUES (%s, %s, %s, 'referee', 'assigned') RETURNING assignment_id""",
                                 (self.game_id, self.o1, admin))[0][0]

    def answer(self, user_id, action, assignment_id=None):
        sign_in(user_id)
        return client.post(f"/api/assignments/{assignment_id or self.assignment_id}/{action}")

    def status(self):
        return sql("SELECT status FROM OfficiatingAssignment WHERE assignment_id = %s", (self.assignment_id,))[0][0]

    def test_anonymous_gets_401(self):
        self.assertEqual(client.get("/api/me/assignments").status_code, 401)
        for action in ("accept", "decline"):
            self.assertEqual(client.post(f"/api/assignments/{self.assignment_id}/{action}").status_code, 401)

    def test_lists_only_own_assignments(self):
        sign_in(self.o1)
        rows = client.get("/api/me/assignments").json()
        mine = {r[0] for r in sql("SELECT assignment_id FROM OfficiatingAssignment WHERE official_id = %s", (self.o1,))}
        self.assertEqual({r["assignment_id"] for r in rows}, mine)
        row = next(r for r in rows if r["assignment_id"] == self.assignment_id)
        self.assertEqual((row["assignment_status"], row["can_respond"], row["has_ended"], row["game_id"]),
                         ("assigned", True, False, self.game_id))
        sign_in(self.o2)
        self.assertNotIn(self.assignment_id, [r["assignment_id"] for r in client.get("/api/me/assignments").json()])

    def test_player_gets_empty_list(self):
        sign_in(eligible_players(1)[0])
        self.assertEqual(client.get("/api/me/assignments").json(), [])

    def test_accept_sets_accepted(self):
        self.assertEqual(self.answer(self.o1, "accept").status_code, 204)
        self.assertEqual(self.status(), "accepted")

    def test_decline_sets_declined(self):
        self.assertEqual(self.answer(self.o1, "decline").status_code, 204)
        self.assertEqual(self.status(), "declined")

    def test_other_officials_assignment_is_404(self):
        response = self.answer(self.o2, "accept")
        self.assertEqual((response.status_code, response.json()["detail"]), (404, "You don't have that assignment."))
        self.assertEqual(self.status(), "assigned")
        self.assertEqual(self.answer(self.o1, "accept", 999999).status_code, 404)

    def test_demoted_official_cannot_answer(self):
        sql("UPDATE Users SET role = 'player' WHERE user_id = %s", (self.o1,))
        self.addCleanup(sql, "UPDATE Users SET role = 'official' WHERE user_id = %s", (self.o1,))
        self.assertEqual(self.answer(self.o1, "accept").status_code, 404)
        self.assertEqual(self.status(), "assigned")

    def test_answering_twice_is_409(self):
        self.answer(self.o1, "accept")
        response = self.answer(self.o1, "decline")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, "You've already answered this assignment."))
        self.assertEqual(self.status(), "accepted")

    def test_started_game_is_409(self):
        sql("UPDATE Game SET start_time = NOW() - INTERVAL '1 hour', end_time = NOW() WHERE game_id = %s", (self.game_id,))
        response = self.answer(self.o1, "accept")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, "This game has already started."))
        row = next(r for r in client.get("/api/me/assignments").json() if r["assignment_id"] == self.assignment_id)
        self.assertFalse(row["can_respond"])


class IncidentApiTest(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        uid = lambda pid: sql("SELECT user_id FROM Users WHERE vt_pid = %s", (pid,))[0][0]
        self.official = uid("simvt0121")
        self.other_official = uid("simvt0122")
        self.player = uid("simvt0001")
        self.admin = uid("simvt0133")
        self.game_id = sql("""
            INSERT INTO Game (league_id, facility_id, start_time, end_time, playoff_round)
            SELECT league_id, (SELECT MIN(facility_id) FROM Facility),
                   NOW() + INTERVAL '7 days', NOW() + INTERVAL '7 days 1 hour', 3
            FROM Game ORDER BY game_id LIMIT 1 RETURNING game_id
        """)[0][0]
        self.addCleanup(sql, "DELETE FROM Game WHERE game_id = %s", (self.game_id,))
        sql("""
            INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status)
            VALUES (%s, %s, %s, 'referee', 'assigned')
        """, (self.game_id, self.official, self.admin))

    def file_report(self, user_id=None, payload=None):
        sign_in(user_id or self.official)
        return client.post(f"/api/games/{self.game_id}/incident-reports", json=payload or {
            "incident_type": "conduct", "description": "A test incident", "involved_user_pid": "simvt0001",
        })

    def test_assigned_official_files_and_admin_resolves_report(self):
        response = self.file_report()
        self.assertEqual(response.status_code, 201, response.text)
        report_id = response.json()["incident_id"]
        self.addCleanup(sql, "DELETE FROM IncidentReport WHERE incident_id = %s", (report_id,))

        own = client.get("/api/incidents")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.headers["cache-control"], "no-store")
        report = next(item for item in own.json() if item["incident_id"] == report_id)
        self.assertEqual((report["status"], report["incident_type"], report["involved_user_id"]),
                         ("open", "conduct", self.player))

        sign_in(self.admin)
        all_reports = client.get("/api/incidents")
        self.assertIn(report_id, [item["incident_id"] for item in all_reports.json()])
        resolved = client.patch(f"/api/incidents/{report_id}", json={"status": "reviewed"})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["reviewed_by"], self.admin)
        repeated = client.patch(f"/api/incidents/{report_id}", json={"status": "dismissed"})
        self.assertEqual(repeated.status_code, 409)

    def test_players_and_unassigned_officials_cannot_file(self):
        self.assertEqual(client.get("/api/incidents").status_code, 401)
        self.assertEqual(self.file_report(self.player).status_code, 403)
        self.assertEqual(self.file_report(self.other_official).status_code, 403)
        sign_in(self.player)
        self.assertEqual(client.get("/api/incidents").status_code, 403)

    def test_declined_and_cancelled_games_cannot_receive_reports(self):
        sql("UPDATE OfficiatingAssignment SET status = 'declined' WHERE game_id = %s", (self.game_id,))
        self.assertEqual(self.file_report().status_code, 403)
        sql("UPDATE OfficiatingAssignment SET status = 'assigned' WHERE game_id = %s", (self.game_id,))
        sql("UPDATE Game SET status = 'cancelled' WHERE game_id = %s", (self.game_id,))
        response = self.file_report()
        self.assertEqual(response.status_code, 409)

    def test_invalid_person_pid_is_reported_as_not_found(self):
        response = self.file_report(payload={
            "incident_type": "conduct", "description": "A test incident", "involved_user_pid": "unknown-pid",
        })
        self.assertEqual(response.status_code, 404)


class TriggerTest(unittest.TestCase):
    def test_captain_cannot_lose_active_row(self):
        team_id, captain = sql("SELECT team_id, captain_id FROM Team ORDER BY team_id LIMIT 1")[0]
        with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
            sql("UPDATE RosterMembership SET status = 'left' WHERE team_id = %s AND user_id = %s", (team_id, captain))
        self.assertEqual(ctx.exception.diag.constraint_name, "team_captain_on_roster")

    def test_second_active_roster_in_league_rejected(self):
        player, a, b = sql("""
            SELECT r.user_id, r.team_id, t2.team_id FROM RosterMembership r
            JOIN Team t1 ON t1.team_id = r.team_id
            JOIN Team t2 ON t2.league_id = t1.league_id AND t2.team_id <> t1.team_id
            WHERE r.status = 'active' AND r.user_id <> t1.captain_id
              AND NOT EXISTS (SELECT 1 FROM RosterMembership x WHERE x.team_id = t2.team_id AND x.user_id = r.user_id)
            LIMIT 1""")[0]
        with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
            sql("INSERT INTO RosterMembership (team_id, user_id, status, joined_at) VALUES (%s, %s, 'active', NOW())",
                (b, player))
        self.assertEqual(ctx.exception.diag.constraint_name, "roster_one_team_per_league")


class AuthTest(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        sql("DELETE FROM AuthSession")
        sql("DELETE FROM AuthLoginAttempt")
        self.user_id = sql("SELECT user_id FROM Users WHERE vt_pid = 'simvt0001'")[0][0]

    def login(self, pid="simvt0001", password=PASSWORD):
        return client.post("/api/auth/login", json={"vt_pid": pid, "password": password})

    def test_login_cookie_and_identity(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"user_id", "first_name", "last_name", "role"})
        self.assertEqual(response.json()["user_id"], self.user_id)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Path=/api", cookie)
        self.assertEqual(response.headers["cache-control"], "no-store")
        token = client.cookies.get(COOKIE_NAME)
        self.assertEqual(sql("SELECT token_hash FROM AuthSession")[0][0], token_hash(token))
        self.assertNotEqual(token, token_hash(token))
        self.assertEqual(client.get("/api/auth/me").json(), response.json())

    def test_pid_normalized(self):
        self.assertEqual(self.login(pid="  SIMVT0001  ").status_code, 200)

    def test_invalid_credentials_have_same_message(self):
        wrong = self.login(password="wrong-password")
        unknown = self.login(pid="unknown")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(sql("SELECT COUNT(*) FROM AuthSession")[0][0], 0)

    def test_no_credentials_cannot_login(self):
        sql("DELETE FROM UserCredentials WHERE user_id = %s", (self.user_id,))
        try:
            self.assertEqual(self.login().status_code, 401)
        finally:
            sql("INSERT INTO UserCredentials VALUES (%s, %s)", (self.user_id, password_hasher.hash(PASSWORD)))

    def test_inactive_user_cannot_login_or_use_session(self):
        self.login()
        sql("UPDATE Users SET is_active = FALSE WHERE user_id = %s", (self.user_id,))
        try:
            self.assertEqual(client.get("/api/auth/me").status_code, 401)
            self.assertEqual(self.login().status_code, 401)
        finally:
            sql("UPDATE Users SET is_active = TRUE WHERE user_id = %s", (self.user_id,))

    def test_session_expires_and_forged_cookie_fails(self):
        self.login()
        sql("UPDATE AuthSession SET expires_at = NOW() - INTERVAL '1 second'")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, "forged", path="/api")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_logout_revokes_token_and_is_idempotent(self):
        self.login()
        token = client.cookies.get(COOKIE_NAME)
        self.assertEqual(client.post("/api/auth/logout").status_code, 204)
        self.assertIsNone(client.cookies.get(COOKIE_NAME))
        client.cookies.set(COOKIE_NAME, token, path="/api")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(client.post("/api/auth/logout").status_code, 204)

    def test_login_rotates_previous_session(self):
        self.login()
        old = client.cookies.get(COOKIE_NAME)
        self.login()
        self.assertNotEqual(client.cookies.get(COOKIE_NAME), old)
        self.assertEqual(sql("SELECT COUNT(*) FROM AuthSession WHERE token_hash = %s", (token_hash(old),))[0][0], 0)

    def test_login_throttling_and_window_reset(self):
        for _ in range(10):
            self.assertEqual(self.login(password="wrong").status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "900")
        sql("UPDATE AuthLoginAttempt SET window_start = NOW() - INTERVAL '16 minutes'")
        self.assertEqual(self.login().status_code, 200)

    def test_browser_csrf_and_cors(self):
        payload = {"vt_pid": "simvt0001", "password": PASSWORD}
        with TestClient(app) as browser:
            self.assertEqual(browser.post("/api/auth/login", json=payload).status_code, 403)
        self.assertEqual(client.post("/api/auth/login", json=payload,
                                    headers={"Origin": "https://evil.example"}).status_code, 403)
        response = client.post("/api/auth/login", json=payload, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_anonymous_writes_rejected_even_with_user_id(self):
        cases = [
            ("POST", "/api/teams", {"league_id": 1, "team_name": "Forged", "user_id": self.user_id}),
            ("PATCH", "/api/teams/1", {"team_name": "Forged", "user_id": self.user_id}),
            ("DELETE", f"/api/teams/1?user_id={self.user_id}", None),
            ("DELETE", f"/api/teams/1/invites/2?user_id={self.user_id}", None),
        ]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):
                self.assertEqual(client.request(method, path, json=body).status_code, 401)

    def test_authenticated_user_cannot_forge_captain(self):
        team_id = sql("SELECT team_id FROM Team WHERE captain_id = %s LIMIT 1", (self.user_id,))[0][0]
        other = sql("SELECT user_id FROM Users WHERE vt_pid = 'simvt0002'")[0][0]
        sign_in(other)
        self.assertEqual(client.patch(f"/api/teams/{team_id}", json={"team_name": "Forged", "user_id": self.user_id}).status_code, 422)
        self.assertEqual(client.patch(f"/api/teams/{team_id}", json={"team_name": "Forged"}).status_code, 403)
        self.assertEqual(client.delete(f"/api/teams/{team_id}?user_id={self.user_id}").status_code, 403)

    def test_auth_migration_is_rerunnable(self):
        from migrate import migrate
        migrate()
        migrate()
        self.assertEqual(sql("SELECT COUNT(*) FROM Users")[0][0], 135)

    def test_demo_setup_preserves_existing_credentials_and_reset_revokes(self):
        from seed_demo_accounts import seed_demo_accounts
        before = sql("SELECT password_hash FROM UserCredentials WHERE user_id = %s", (self.user_id,))[0][0]
        seed_demo_accounts("Replacement-demo-pass")
        self.assertEqual(sql("SELECT password_hash FROM UserCredentials WHERE user_id = %s", (self.user_id,))[0][0], before)
        self.login()
        seed_demo_accounts("Replacement-demo-pass", reset=True)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login(password="Replacement-demo-pass").status_code, 200)
        hashes = sql("SELECT password_hash FROM UserCredentials")
        self.assertEqual(len(hashes), 135)
        self.assertEqual(len({row[0] for row in hashes}), 135)
        self.assertTrue(all(password_hasher.verify("Replacement-demo-pass", row[0]) for row in hashes))
        # Restore fixture passwords for subsequent tests.
        sql("UPDATE UserCredentials SET password_hash = %s", (password_hasher.hash(PASSWORD),))


class SignUpTest(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        sql("DELETE FROM AuthLoginAttempt")
        self.pid = "signup_" + uuid.uuid4().hex[:16]
        self.details = {
            "vt_pid": self.pid, "first_name": "Test", "last_name": "Player",
            "email": self.pid + "@example.com", "phone": "540-555-0199",
            "password": "A new player password",
        }

    def tearDown(self):
        # Only remove profiles/teams created by this test, never seeded people.
        sql("DELETE FROM Team WHERE captain_id IN (SELECT user_id FROM Users WHERE LEFT(vt_pid, LENGTH(%s)) = %s)",
            (self.pid, self.pid))
        sql("DELETE FROM Users WHERE LEFT(vt_pid, LENGTH(%s)) = %s", (self.pid, self.pid))

    def register(self, **changes):
        return client.post("/api/auth/sign-up", json={**self.details, **changes})

    def test_signup_creates_player_credentials_and_session(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["role"], "player")
        self.assertEqual(set(response.json()), {"user_id", "first_name", "last_name", "role"})
        self.assertEqual(client.get("/api/auth/me").json(), response.json())
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        stored = sql("SELECT c.password_hash FROM UserCredentials c JOIN Users u USING (user_id) WHERE u.vt_pid = %s", (self.pid,))[0][0]
        self.assertNotEqual(stored, self.details["password"])
        self.assertTrue(password_hasher.verify(self.details["password"], stored))
        open_league = sql("SELECT MAX(league_id) FROM League")[0][0]
        team = client.post("/api/teams", json={"league_id": open_league, "team_name": self.pid})
        self.assertEqual(team.status_code, 201)
        self.assertEqual(client.get(f"/api/teams/{team.json()['team_id']}").json()["captain_id"], response.json()["user_id"])
        client.post("/api/auth/logout")
        login = client.post("/api/auth/login", json={"vt_pid": self.pid, "password": self.details["password"]})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user_id"], response.json()["user_id"])

    def test_signup_normalizes_identifiers_and_trims_names(self):
        self.assertEqual(self.register(vt_pid="  " + self.pid.upper() + "  ", email=self.details["email"].upper(),
                                       first_name=" Test ", last_name=" Player ").status_code, 201)
        row = sql("SELECT vt_pid, email, first_name, last_name FROM Users WHERE vt_pid = %s", (self.pid,))[0]
        self.assertEqual(row, (self.pid, self.details["email"], "Test", "Player"))

    def test_duplicate_pid_and_email_are_case_insensitive(self):
        self.assertEqual(self.register().status_code, 201)
        for changes in ({"vt_pid": self.pid.upper(), "email": "different@example.com"},
                        {"vt_pid": self.pid + "_other", "email": self.details["email"].upper()}):
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes).status_code, 409)
        self.assertEqual(sql("SELECT COUNT(*) FROM Users WHERE LEFT(vt_pid, LENGTH(%s)) = %s", (self.pid, self.pid))[0][0], 1)

    def test_cannot_claim_seeded_pid_or_email(self):
        before = sql("SELECT u.user_id, c.password_hash FROM Users u JOIN UserCredentials c USING (user_id) WHERE u.vt_pid = 'simvt0001'")[0]
        self.assertEqual(self.register(vt_pid="SIMVT0001").status_code, 422)
        self.assertEqual(self.register(email="JESSICA.THOMPSON.001@EXAMPLE.COM").status_code, 409)
        after = sql("SELECT u.user_id, c.password_hash FROM Users u JOIN UserCredentials c USING (user_id) WHERE u.vt_pid = 'simvt0001'")[0]
        self.assertEqual(before, after)

    def test_privileged_fields_rejected(self):
        for changes in ({"role": "admin"}, {"role": "official"}, {"user_id": 1}, {"is_active": False}):
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes).status_code, 422)

    def test_signup_validation(self):
        for changes in ({"password": "hokie"}, {"password": "x" * 129}, {"email": "not-an-email"},
                        {"email": "x" * 90 + "@example.com"}, {"phone": "--- ---"}, {"phone": "not-a-number"},
                        {"first_name": "   "}, {"last_name": "x" * 51}, {"first_name": "a\x00b"},
                        {"vt_pid": "bad pid"}, {"vt_pid": "x" * 41}):
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes).status_code, 422)
        self.assertEqual(sql("SELECT COUNT(*) FROM Users WHERE vt_pid = %s", (self.pid,))[0][0], 0)

    def test_signup_requires_browser_csrf_header_and_trusted_origin(self):
        with TestClient(app) as browser:
            self.assertEqual(browser.post("/api/auth/sign-up", json=self.details).status_code, 403)
        self.assertEqual(client.post("/api/auth/sign-up", json=self.details,
                                    headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_signup_rate_limit_is_shared_across_pids(self):
        for number in range(10):
            self.assertEqual(self.register(vt_pid=self.pid + str(number)).status_code, 201 if number == 0 else 409)
        response = self.register(vt_pid=self.pid + "blocked")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "900")
        sql("UPDATE AuthLoginAttempt SET window_start = NOW() - INTERVAL '16 minutes'")
        self.assertEqual(self.register(vt_pid=self.pid + "unblocked", email=self.pid + "_other@example.com").status_code, 201)

    def test_concurrent_signups_cannot_duplicate_accounts(self):
        def signup_once(_):
            with TestClient(app, headers={"X-Requested-With": "HokieRec"}) as browser:
                return browser.post("/api/auth/sign-up", json=self.details).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(signup_once, range(2))), [201, 409])
        self.assertEqual(sql("SELECT COUNT(*) FROM Users u JOIN UserCredentials c USING (user_id) WHERE u.vt_pid = %s", (self.pid,))[0][0], 1)

    def test_signup_is_atomic_if_session_creation_fails(self):
        with patch("auth.issue_session", side_effect=RuntimeError("Simulated session failure")):
            with self.assertRaises(RuntimeError):
                self.register()
        self.assertEqual(sql("SELECT COUNT(*) FROM Users WHERE vt_pid = %s", (self.pid,))[0][0], 0)

    def test_demo_reset_does_not_change_registered_users(self):
        from seed_demo_accounts import DEMO_PASSWORD, seed_demo_accounts
        self.assertEqual(self.register().status_code, 201)
        original_hash = sql("SELECT c.password_hash FROM UserCredentials c JOIN Users u USING (user_id) WHERE u.vt_pid = %s", (self.pid,))[0][0]
        self.assertEqual(seed_demo_accounts(reset=True), 135)
        self.assertEqual(sql("SELECT c.password_hash FROM UserCredentials c JOIN Users u USING (user_id) WHERE u.vt_pid = %s", (self.pid,))[0][0], original_hash)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        for number in range(1, 136):
            pid = f"simvt{number:04d}"
            with self.subTest(pid=pid):
                response = client.post("/api/auth/login", json={"vt_pid": pid, "password": DEMO_PASSWORD})
                self.assertEqual(response.status_code, 200)
        self.assertEqual(seed_demo_accounts(), 0)
        sql("UPDATE UserCredentials SET password_hash = %s WHERE user_id IN (SELECT user_id FROM Users WHERE vt_pid LIKE 'simvt%%')",
            (password_hasher.hash(PASSWORD),))
class ReportTest(unittest.TestCase):
    def setUp(self):
        # The league with the most forfeits, so the forfeit rule is exercised
        self.league_id = sql("""
            SELECT g.league_id FROM Game g JOIN ScoreReport s ON s.game_id = g.game_id
            GROUP BY g.league_id ORDER BY COUNT(s.forfeit_team_id) DESC, g.league_id LIMIT 1""")[0][0]

    def test_standings_totals_add_up(self):
        r = client.get("/api/reports/standings", params={"league_id": self.league_id})
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        team_count = sql("SELECT COUNT(*) FROM Team WHERE league_id = %s", (self.league_id,))[0][0]
        self.assertEqual(len(rows), team_count)
        for t in rows:
            self.assertEqual(t["wins"] + t["losses"] + t["ties"], t["played"])
            self.assertEqual(t["point_diff"], t["points_for"] - t["points_against"])
        self.assertEqual(sum(t["wins"] for t in rows), sum(t["losses"] for t in rows))
        reported = sql("""
            SELECT COUNT(*) FROM Game g JOIN ScoreReport s ON s.game_id = g.game_id
            WHERE g.league_id = %s AND g.playoff_round IS NULL""", (self.league_id,))[0][0]
        self.assertEqual(sum(t["played"] for t in rows), 2 * reported)

    def test_standings_sorted_by_wins_then_diff(self):
        rows = client.get("/api/reports/standings", params={"league_id": self.league_id}).json()
        keys = [(t["wins"], t["point_diff"]) for t in rows]
        self.assertEqual(keys, sorted(keys, reverse=True))

    def test_standings_forfeit_is_a_loss(self):
        forfeits = sql("""
            SELECT s.forfeit_team_id, COUNT(*) FROM Game g JOIN ScoreReport s ON s.game_id = g.game_id
            WHERE g.league_id = %s AND s.forfeit_team_id IS NOT NULL GROUP BY 1""", (self.league_id,))
        if not forfeits:
            self.skipTest("no forfeits in seed data")
        rows = {t["team_id"]: t for t in client.get(
            "/api/reports/standings", params={"league_id": self.league_id}).json()}
        for team_id, n in forfeits:
            self.assertGreaterEqual(rows[team_id]["losses"], n)

    def test_standings_skips_incomplete_latest_report(self):
        def played():
            rows = client.get("/api/reports/standings", params={"league_id": self.league_id}).json()
            return sum(t["played"] for t in rows), sum(t["ties"] for t in rows)

        before = played()
        game_id, official = sql("""
            SELECT g.game_id, oa.official_id FROM Game g JOIN OfficiatingAssignment oa ON oa.game_id = g.game_id
            WHERE g.league_id = %s AND g.status = 'completed' LIMIT 1""", (self.league_id,))[0]
        # A newer report wins, so one with no scores and no forfeit hides the game's real result
        report_id = sql("""INSERT INTO ScoreReport (game_id, submitted_by, submitted_at)
                           VALUES (%s, %s, NOW()) RETURNING report_id""", (game_id, official))[0][0]
        try:
            after = played()
            self.assertEqual(after[0], before[0] - 2)
            self.assertLessEqual(after[1], before[1])
        finally:
            sql("DELETE FROM ScoreReport WHERE report_id = %s", (report_id,))

    def test_standings_unknown_league_is_404(self):
        self.assertEqual(client.get("/api/reports/standings", params={"league_id": 999999}).status_code, 404)

    def test_participation_matches_league_list(self):
        rows = client.get("/api/reports/participation", params={"term": "Fall 2026"}).json()
        leagues = {l["league_id"]: l for l in client.get("/api/leagues", params={"term": "Fall 2026"}).json()}
        self.assertEqual({r["league_id"] for r in rows}, set(leagues))
        for r in rows:
            self.assertEqual(r["teams"], leagues[r["league_id"]]["team_count"])
            games = sql("SELECT COUNT(*) FROM Game WHERE league_id = %s", (r["league_id"],))[0][0]
            self.assertEqual(r["games_played"] + r["games_remaining"], games)
            active = sql("""
                SELECT COUNT(DISTINCT rm.user_id) FROM RosterMembership rm JOIN Team t ON t.team_id = rm.team_id
                WHERE t.league_id = %s AND rm.status = 'active'""", (r["league_id"],))[0][0]
            self.assertEqual(r["active_players"], active)

    def test_participation_without_term_lists_every_league(self):
        rows = client.get("/api/reports/participation").json()
        self.assertEqual(len(rows), len(client.get("/api/leagues").json()))


class SchemaRulesTest(unittest.TestCase):
    """Phase III rules the database enforces on its own."""

    def setUp(self):
        self.game_id, self.home, self.away, self.official = sql("""
            SELECT g.game_id, g.home_team_id, g.away_team_id, oa.official_id
            FROM Game g JOIN OfficiatingAssignment oa ON oa.game_id = g.game_id
            WHERE g.playoff_round IS NULL ORDER BY g.game_id LIMIT 1""")[0]
        self.player = eligible_players(1)[0]
        self.admin = sql("SELECT user_id FROM Users WHERE role = 'admin' LIMIT 1")[0][0]
        self.other_official = sql("""
            SELECT user_id FROM Users WHERE role = 'official'
              AND user_id NOT IN (SELECT official_id FROM OfficiatingAssignment WHERE game_id = %s) LIMIT 1""",
            (self.game_id,))[0][0]

    def run_sql(self, *steps):
        # Every step runs in one transaction that is always rolled back, so nothing is left behind
        with psycopg.connect(DATABASE_URL) as conn:
            try:
                for query, params in steps:
                    conn.execute(query, params)
            finally:
                conn.rollback()

    def assertRejected(self, constraint, *steps):
        with self.assertRaises(psycopg.errors.IntegrityError) as caught:
            self.run_sql(*steps)
        self.assertEqual(caught.exception.diag.constraint_name, constraint)

    def report(self, submitted_by, forfeit_team_id=None):
        return ("INSERT INTO ScoreReport (game_id, submitted_by, forfeit_team_id, home_score, away_score) "
                "VALUES (%s, %s, %s, 1, 0)", (self.game_id, submitted_by, forfeit_team_id))

    def test_derived_columns_are_gone(self):
        columns = {(t, c) for t, c in sql("""SELECT table_name, column_name FROM information_schema.columns
                                             WHERE table_schema = current_schema()""")}
        for dropped in [("league", "league_name"), ("league", "sport_name"), ("league", "min_roster_size"),
                        ("league", "max_roster_size"), ("game", "game_type"), ("scorereport", "is_forfeit")]:
            self.assertNotIn(dropped, columns)
        self.assertIn(("league", "sport_id"), columns)

    def test_league_name_is_built_from_its_columns(self):
        for l in client.get("/api/leagues").json():
            self.assertEqual(l["league_name"], f"{l['category']} {l['sport_name']}, {l['skill_level']}, {l['term']}")

    def test_same_league_cannot_be_created_twice(self):
        self.assertRejected("league_sport_id_category_skill_level_term_key", ("""
            INSERT INTO League (sport_id, category, skill_level, term, start_date, end_date, reg_open_at,
                                reg_close_at, roster_lock_date)
            SELECT sport_id, category, skill_level, term, start_date, end_date, reg_open_at, reg_close_at,
                   roster_lock_date FROM League LIMIT 1""", ()))

    def test_phone_is_optional(self):
        self.run_sql(("INSERT INTO Users (vt_pid, first_name, last_name, email, role) "
                      "VALUES ('nophone1', 'No', 'Phone', 'nophone1@example.com', 'player')", ()))

    def test_assigned_official_submits_score(self):
        self.run_sql(self.report(self.official), self.report(self.official, self.home))

    def test_only_the_assigned_official_submits_score(self):
        for user_id in (self.player, self.admin, self.other_official):
            with self.subTest(user_id=user_id):
                self.assertRejected("scorereport_by_assigned_official", self.report(user_id))

    def test_declined_official_cannot_submit_score(self):
        self.assertRejected("scorereport_by_assigned_official",
                            ("UPDATE OfficiatingAssignment SET status = 'declined' WHERE game_id = %s AND official_id = %s",
                             (self.game_id, self.official)),
                            self.report(self.official))

    def test_forfeit_team_must_play_in_the_game(self):
        outsider = sql("SELECT team_id FROM Team WHERE team_id NOT IN (%s, %s) LIMIT 1", (self.home, self.away))[0][0]
        self.assertRejected("scorereport_forfeit_team_in_game", self.report(self.official, outsider))

    def test_score_reports_are_never_edited(self):
        self.assertRejected("scorereport_no_edits",
                            ("UPDATE ScoreReport SET home_score = home_score + 1 WHERE game_id = %s", (self.game_id,)))

    def test_game_teams_belong_to_its_league(self):
        outsider = sql("SELECT team_id FROM Team WHERE league_id <> (SELECT league_id FROM Game WHERE game_id = %s) LIMIT 1",
                       (self.game_id,))[0][0]
        self.assertRejected("game_teams_in_league",
                            ("UPDATE Game SET away_team_id = %s WHERE game_id = %s", (outsider, self.game_id)))

    def test_assignment_roles(self):
        assign = "INSERT INTO OfficiatingAssignment (game_id, official_id, assigned_by, position, status) VALUES (%s, %s, %s, 'referee', 'pending')"
        self.run_sql((assign, (self.game_id, self.other_official, self.admin)))
        self.assertRejected("assignment_official_role", (assign, (self.game_id, self.player, self.admin)))
        self.assertRejected("assignment_by_admin", (assign, (self.game_id, self.other_official, self.official)))

    def test_incident_roles(self):
        incident = ("INSERT INTO IncidentReport (game_id, filed_by, reviewed_by, incident_type, description) "
                    "VALUES (%s, %s, %s, 'conduct', 'Test')")
        self.run_sql((incident, (self.game_id, self.official, self.admin)), (incident, (self.game_id, self.official, None)))
        self.assertRejected("incident_filed_by_official", (incident, (self.game_id, self.player, None)))
        self.assertRejected("incident_reviewed_by_admin", (incident, (self.game_id, self.official, self.official)))


if __name__ == "__main__":
    unittest.main()
