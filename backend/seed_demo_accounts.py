"""Explicit, development-only credential provisioning for fictional seeded people."""

import argparse
from getpass import getpass

from auth import password_hasher, token_hash
from database import db

# Exact identifiers from db/seed.sql; never provision arbitrary registered users.
DEMO_PIDS = tuple(f"simvt{number:04d}" for number in range(1, 136))
DEMO_PASSWORD = "hokie"


def seed_demo_accounts(password: str = DEMO_PASSWORD, *, reset: bool = False):
    if not 1 <= len(password) <= 128:
        raise ValueError("Use a demo password between 1 and 128 characters.")
    changed_count = 0
    with db() as conn:
        users = conn.execute("""
            SELECT u.user_id, u.vt_pid, c.user_id IS NOT NULL AS has_credentials
            FROM Users u LEFT JOIN UserCredentials c ON c.user_id = u.user_id
            WHERE u.vt_pid = ANY(%s) AND u.email LIKE '%%@example.com'
            ORDER BY u.vt_pid
        """, (list(DEMO_PIDS),)).fetchall()
        if len(users) != len(DEMO_PIDS):
            raise ValueError("Seeded demo people are missing. Run the data seed first.")
        for user in users:
            if user["has_credentials"] and not reset:
                continue
            # Each hash gets its own random salt, even with a shared demo password.
            conflict = "DO UPDATE SET password_hash = EXCLUDED.password_hash" if reset else "DO NOTHING"
            changed = conn.execute(f"""
                INSERT INTO UserCredentials (user_id, password_hash) VALUES (%s, %s)
                ON CONFLICT (user_id) {conflict} RETURNING user_id
            """, (user["user_id"], password_hasher.hash(password))).fetchone()
            if changed and reset:
                conn.execute("DELETE FROM AuthSession WHERE user_id = %s", (user["user_id"],))
                conn.execute("DELETE FROM AuthLoginAttempt WHERE identifier_hash = %s", (token_hash(user["vt_pid"]),))
            changed_count += int(changed is not None)
    print(f"Demo logins: {len(users)} total, {changed_count} updated, {len(users) - changed_count} unchanged.")
    return changed_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", required=True,
                        help="Acknowledge that the target database is for development only.")
    parser.add_argument("--reset", action="store_true", help="Replace all seeded demo passwords and revoke their sessions.")
    parser.add_argument("--custom-password", action="store_true", help="Prompt for a password instead of the default 'hokie'.")
    args = parser.parse_args()
    password = DEMO_PASSWORD
    if args.custom_password:
        password = getpass("Demo password (1–128 characters, shared by all seeded accounts): ")
        if password != getpass("Confirm demo password: "):
            parser.error("Passwords do not match.")
    try:
        seed_demo_accounts(password, reset=args.reset)
    except ValueError as error:
        parser.error(str(error))
