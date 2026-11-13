"""Migration tests use an isolated schema and never alter the application's tables."""
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import database


class FinalFeatureMigrationTest(unittest.TestCase):
    def test_upgrades_seeded_database_twice_without_losing_history(self):
        name = 'hokie_upgrade_test_' + uuid.uuid4().hex
        with psycopg.connect(database.DATABASE_URL) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        try:
            conninfo = make_conninfo(database.DATABASE_URL, options=f'-c search_path={name}')
            root = Path(__file__).resolve().parents[1] / 'db'
            with psycopg.connect(conninfo) as conn:
                for script in ('schema', 'auth', 'roster', 'phase3', 'seed'):
                    conn.execute((root / f'{script}.sql').read_text())
                former_id = conn.execute("SELECT membership_id FROM RosterMembership WHERE status = 'left' LIMIT 1").fetchone()[0]
                conn.execute('UPDATE RosterMembership SET left_at = NULL WHERE membership_id = %s', (former_id,))
                expected = conn.execute('SELECT COUNT(*) FROM RosterMembership WHERE joined_at IS NOT NULL').fetchone()[0]
                self.assertGreater(expected, 0)
                migration = (root / 'final_features.sql').read_text()
                conn.commit()
                conn.execute(migration)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM MembershipPeriod').fetchone()[0], expected)
                self.assertEqual(conn.execute('SELECT end_reason, left_at FROM MembershipPeriod WHERE membership_id = %s', (former_id,)).fetchone(), ('left', None))
                conn.commit()
                for script in ('auth', 'roster', 'phase3', 'final_features'):
                    conn.execute((root / f'{script}.sql').read_text())
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM MembershipPeriod').fetchone()[0], expected)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM Team').fetchone()[0], 24)
        finally:
            with psycopg.connect(database.DATABASE_URL) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
