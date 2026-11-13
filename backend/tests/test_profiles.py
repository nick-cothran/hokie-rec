"""Profile integration tests run in a disposable schema, never in application data."""

import unittest
import uuid
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql as pgsql
from psycopg.conninfo import make_conninfo

import database
from routers.auth import password_hasher
from main import app

PASSWORD = "Profile test password 2026"
BASE_URL = None
TEST_URL = None
TEST_SCHEMA = "hokie_rec_profiles_" + uuid.uuid4().hex


def setUpModule():
    global BASE_URL, TEST_URL, PASSWORD_HASH
    # Resolve at execution time: other integration modules switch the same factory.
    BASE_URL = database.DATABASE_URL
    TEST_URL = make_conninfo(BASE_URL, options=f"-c search_path={TEST_SCHEMA}", connect_timeout=5)
    with psycopg.connect(BASE_URL, connect_timeout=5) as conn:
        conn.execute(pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(TEST_SCHEMA)))
    try:
        with psycopg.connect(TEST_URL) as conn:
            for name in ("schema", "auth", "roster", "phase3", "final_features", "seed"):
                conn.execute((Path(__file__).resolve().parents[2] / f"db/{name}.sql").read_text())
        PASSWORD_HASH = password_hasher.hash(PASSWORD)
        database.DATABASE_URL = TEST_URL
    except Exception:
        tearDownModule()
        raise


def tearDownModule():
    database.DATABASE_URL = BASE_URL
    with psycopg.connect(BASE_URL, connect_timeout=5) as conn:
        conn.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(pgsql.Identifier(TEST_SCHEMA)))


def sql(query, params=()):
    with psycopg.connect(TEST_URL) as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else None


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, headers={"X-Requested-With": "HokieRec"})
        self.addCleanup(self.client.close)
        self.prefix = "profile_" + uuid.uuid4().hex[:12]
        self.people = []
        for suffix in ("self", "other"):
            pid = f"{self.prefix}_{suffix}"
            user_id = sql("""
                INSERT INTO Users (vt_pid, first_name, last_name, email, phone, role)
                VALUES (%s, 'Original', 'Name', %s, '540-555-0100', 'player') RETURNING user_id
            """, (pid, pid + "@example.com"))[0][0]
            sql("INSERT INTO UserCredentials (user_id, password_hash) VALUES (%s, %s)", (user_id, PASSWORD_HASH))
            self.people.append((user_id, pid))
        self.user_id, self.pid = self.people[0]
        self.other_id, self.other_pid = self.people[1]
        self.addCleanup(sql, "DELETE FROM Users WHERE user_id IN (%s, %s)", (self.user_id, self.other_id))
        self.sign_in()

    def sign_in(self):
        self.assertEqual(self.client.post("/api/auth/login", json={"vt_pid": self.pid, "password": PASSWORD}).status_code, 200)

    def payload(self, **changes):
        return {"first_name": "Updated", "last_name": "Person", "email": self.pid + "_new@example.com",
                "phone": "+1 (540) 555-0199", **changes}

    def save(self, **changes):
        return self.client.put("/api/me/profile", json=self.payload(**changes))

    def test_get_returns_only_own_profile_and_no_secrets(self):
        response = self.client.get("/api/me/profile", params={"user_id": self.other_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(set(response.json()), {"user_id", "vt_pid", "first_name", "last_name", "email", "phone", "role", "created_at"})
        self.assertEqual(response.json()["user_id"], self.user_id)
        self.assertEqual(response.json()["email"], self.pid + "@example.com")

    def test_save_normalizes_fields_and_refreshes_session_identity(self):
        response = self.save(first_name="  Updated  ", last_name="  Person  ", email=self.pid.upper() + "@EXAMPLE.COM",
                             phone="  +1 (540) 555-0199  ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        profile = response.json()
        self.assertEqual((profile["first_name"], profile["last_name"], profile["email"], profile["phone"]),
                         ("Updated", "Person", self.pid + "@example.com", "+1 (540) 555-0199"))
        self.assertEqual(self.client.get("/api/me/profile").json(), profile)
        self.assertEqual(self.client.get("/api/auth/me").json()["first_name"], "Updated")

    def test_all_account_roles_can_edit_their_own_profile(self):
        for role in ("player", "official", "admin"):
            with self.subTest(role=role):
                sql("UPDATE Users SET role = %s WHERE user_id = %s", (role, self.user_id))
                self.assertEqual(self.client.get("/api/me/profile").status_code, 200)
                response = self.save()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["role"], role)

    def test_phone_can_be_removed_and_added_again(self):
        self.assertIsNone(self.save(phone=None).json()["phone"])
        self.assertIsNone(self.client.get("/api/me/profile").json()["phone"])
        response = self.save(phone="540-555-0199")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "540-555-0199")

    def test_legacy_profile_with_no_phone_loads(self):
        sql("UPDATE Users SET phone = NULL WHERE user_id = %s", (self.user_id,))
        response = self.client.get("/api/me/profile")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["phone"])

    def test_duplicate_email_is_case_insensitive_and_rolls_back_all_changes(self):
        before = self.client.get("/api/me/profile").json()
        response = self.save(email=self.other_pid.upper() + "@EXAMPLE.COM")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/me/profile").json(), before)
        self.assertEqual(sql("SELECT first_name FROM Users WHERE user_id = %s", (self.other_id,))[0][0], "Original")

    def test_invalid_contact_details_are_rejected_without_changes(self):
        before = self.client.get("/api/me/profile").json()
        for changes in ({"first_name": "  "}, {"last_name": "x" * 51}, {"first_name": "Bad\nName"},
                        {"last_name": "Bad\x00Name"}, {"first_name": None}, {"email": "bad-email"},
                        {"email": "x" * 90 + "@example.com"}, {"phone": "--- ---"}, {"phone": "abc1234567"},
                        {"phone": "123456"}, {"phone": "1" * 21}, {"phone": ""}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save(**changes).status_code, 422)
                self.assertEqual(self.client.get("/api/me/profile").json(), before)

    def test_identity_credentials_and_disciplinary_fields_cannot_be_changed(self):
        before = self.client.get("/api/me/profile").json()
        for changes in ({"user_id": self.other_id}, {"vt_pid": "new_pid"}, {"role": "admin"},
                        {"is_active": False}, {"suspended_until": "2099-01-01"}, {"password": "changed"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save(**changes).status_code, 422)
        self.assertEqual(self.client.get("/api/me/profile").json(), before)

    def test_every_editable_field_must_be_present(self):
        for field in self.payload():
            body = self.payload()
            del body[field]
            with self.subTest(field=field):
                self.assertEqual(self.client.put("/api/me/profile", json=body).status_code, 422)

    def test_anonymous_expired_and_inactive_sessions_cannot_read_or_edit(self):
        for state in ("anonymous", "expired", "inactive"):
            with self.subTest(state=state):
                if state == "anonymous":
                    self.client.cookies.clear()
                else:
                    self.sign_in()
                    if state == "expired":
                        sql("UPDATE AuthSession SET expires_at = NOW() - INTERVAL '1 second' WHERE user_id = %s", (self.user_id,))
                    else:
                        sql("UPDATE Users SET is_active = FALSE WHERE user_id = %s", (self.user_id,))
                for method in ("get", "put"):
                    response = self.client.get("/api/me/profile") if method == "get" else self.save()
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(sql("SELECT first_name FROM Users WHERE user_id = %s", (self.user_id,))[0][0], "Original")

    def test_writes_require_csrf_header_and_trusted_origin(self):
        with TestClient(app, cookies=self.client.cookies) as browser:
            self.assertEqual(browser.put("/api/me/profile", json=self.payload()).status_code, 403)
        self.assertEqual(self.client.put("/api/me/profile", json=self.payload(),
                                        headers={"Origin": "https://untrusted.example"}).status_code, 403)

    def test_profile_edit_preserves_password_and_other_sessions(self):
        before = sql("SELECT password_hash FROM UserCredentials WHERE user_id = %s", (self.user_id,))[0][0]
        with TestClient(app, headers={"X-Requested-With": "HokieRec"}) as other_browser:
            self.assertEqual(other_browser.post("/api/auth/login", json={"vt_pid": self.pid, "password": PASSWORD}).status_code, 200)
            self.assertEqual(self.save().status_code, 200)
            self.assertEqual(other_browser.get("/api/auth/me").json()["first_name"], "Updated")
        self.assertEqual(sql("SELECT password_hash FROM UserCredentials WHERE user_id = %s", (self.user_id,))[0][0], before)
        self.client.post("/api/auth/logout")
        self.sign_in()
        self.assertEqual(self.client.get("/api/auth/me").json()["first_name"], "Updated")

    def test_profile_edit_preserves_membership_and_updates_captain_display(self):
        with psycopg.connect(TEST_URL) as conn:
            team_id = conn.execute("""
                INSERT INTO Team (league_id, captain_id, team_name)
                SELECT MIN(league_id), %s, %s FROM League RETURNING team_id
            """, (self.user_id, self.prefix)).fetchone()[0]
            conn.execute("INSERT INTO RosterMembership (team_id, user_id, status, joined_at) VALUES (%s, %s, 'active', NOW())",
                         (team_id, self.user_id))
        self.addCleanup(sql, "DELETE FROM Team WHERE team_id = %s", (team_id,))
        self.assertEqual(self.save().status_code, 200)
        team = self.client.get(f"/api/teams/{team_id}").json()
        self.assertEqual(team["captain_id"], self.user_id)
        self.assertEqual(next(person for person in team["roster"] if person["user_id"] == self.user_id)["first_name"], "Updated")
        directory = next(team for team in self.client.get("/api/teams").json() if team["team_id"] == team_id)
        self.assertEqual((directory["captain_first_name"], directory["captain_last_name"]), ("Updated", "Person"))


if __name__ == "__main__":
    unittest.main()
