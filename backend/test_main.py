# Runs against the seeded Docker DB: `python -m unittest` from /backend
import unittest
import uuid

import psycopg
from fastapi.testclient import TestClient

from main import DATABASE_URL, app

client = TestClient(app)


def sql(query, params=()):
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def eligible_players(n):
    return [r[0] for r in sql(
        "SELECT user_id FROM Users WHERE role = 'player' AND is_active "
        "AND (suspended_until IS NULL OR suspended_until < CURRENT_DATE) ORDER BY user_id LIMIT %s", (n,))]


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.captain, self.other = eligible_players(2)
        self.league_id = sql("SELECT league_id FROM League ORDER BY league_id DESC LIMIT 1")[0][0]
        self.name = f"Test {uuid.uuid4().hex[:8]}"

    def tearDown(self):
        sql("DELETE FROM Team WHERE team_name LIKE %s", (self.name + "%",))  # roster rows cascade

    def register(self, name=None, user_id=None):
        return client.post("/api/teams", json={
            "league_id": self.league_id, "team_name": name or self.name, "user_id": user_id or self.captain})

    def test_health_reports_connection(self):
        body = client.get("/api/health").json()
        self.assertEqual(body["status"], "connected")
        self.assertIn("PostgreSQL", body["version"])

    def test_users_list_hides_contact_info(self):
        user = client.get("/api/users").json()[0]
        self.assertNotIn("email", user)
        self.assertNotIn("phone", user)

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
        r = client.post("/api/teams", json={"league_id": 999999, "team_name": self.name, "user_id": self.captain})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "That league does not exist.")

    def test_s2_rejects_non_player(self):
        official = sql("SELECT user_id FROM Users WHERE role = 'official' LIMIT 1")[0][0]
        self.assertEqual(self.register(user_id=official).status_code, 403)

    def test_s2_rejects_suspended_player(self):
        suspended = sql("SELECT user_id FROM Users WHERE role = 'player' AND suspended_until >= CURRENT_DATE LIMIT 1")
        if not suspended:
            self.skipTest("no currently suspended player in seed data")
        self.assertEqual(self.register(user_id=suspended[0][0]).status_code, 403)

    def test_bad_text_is_readable_422_not_500(self):
        r = client.get("/api/leagues", params={"sport": "a\x00"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("detail", r.json())

    def test_s2_rejects_blank_and_too_long_names(self):
        self.assertEqual(self.register(name="   ").status_code, 422)
        self.assertEqual(self.register(name="x" * 61).status_code, 422)

    def test_s3_captain_renames_team(self):
        team_id = self.register().json()["team_id"]
        r = client.patch(f"/api/teams/{team_id}", json={"user_id": self.captain, "team_name": self.name + "b"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get(f"/api/teams/{team_id}").json()["team_name"], self.name + "b")

    def test_s3_non_captain_cannot_rename(self):
        team_id = self.register().json()["team_id"]
        r = client.patch(f"/api/teams/{team_id}", json={"user_id": self.other, "team_name": self.name + "b"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client.get(f"/api/teams/{team_id}").json()["team_name"], self.name)

    def test_s3_missing_team_is_404(self):
        r = client.patch("/api/teams/999999", json={"user_id": self.captain, "team_name": self.name})
        self.assertEqual(r.status_code, 404)

    def test_s2_new_team_uses_column_defaults(self):
        team_id = self.register().json()["team_id"]
        status, registered_today = sql(
            "SELECT status, registered_at::date = CURRENT_DATE FROM Team WHERE team_id = %s", (team_id,))[0]
        self.assertEqual((status, registered_today), ("active", True))

    def test_delete_team_cascades_roster(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        r = client.delete(f"/api/teams/{team_id}", params={"user_id": self.captain})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 404)
        self.assertEqual(sql("SELECT COUNT(*) FROM RosterMembership WHERE team_id = %s", (team_id,))[0][0], 0)

    def test_delete_team_non_captain_forbidden(self):
        team_id = self.register().json()["team_id"]
        r = client.delete(f"/api/teams/{team_id}", params={"user_id": self.other})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 200)

    def test_delete_team_with_games_is_readable_409(self):
        team_id, captain_id = sql("""
            SELECT t.team_id, t.captain_id FROM Team t
            WHERE EXISTS (SELECT 1 FROM Game g WHERE t.team_id IN (g.home_team_id, g.away_team_id))
            ORDER BY t.team_id LIMIT 1""")[0]
        r = client.delete(f"/api/teams/{team_id}", params={"user_id": captain_id})
        self.assertEqual(r.status_code, 409)
        self.assertIn("can't be deleted", r.json()["detail"])
        self.assertEqual(client.get(f"/api/teams/{team_id}").status_code, 200)

    def invite(self, team_id, status="invited"):
        sql("INSERT INTO RosterMembership (team_id, user_id, status, invited_at) VALUES (%s, %s, %s, NOW())",
            (team_id, self.other, status))

    def test_s4_captain_withdraws_invite(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}", params={"user_id": self.captain})
        self.assertEqual(r.status_code, 204)
        roster = client.get(f"/api/teams/{team_id}").json()["roster"]
        self.assertNotIn(self.other, [m["user_id"] for m in roster])

    def test_s4_non_captain_cannot_withdraw(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id)
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}", params={"user_id": self.other})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(client.get(f"/api/teams/{team_id}").json()["roster"]), 2)

    def test_s4_active_member_is_not_deleted(self):
        team_id = self.register().json()["team_id"]
        self.invite(team_id, status="active")
        r = client.delete(f"/api/teams/{team_id}/invites/{self.other}", params={"user_id": self.captain})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(client.get(f"/api/teams/{team_id}").json()["roster"]), 2)


if __name__ == "__main__":
    unittest.main()
