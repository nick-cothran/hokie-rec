"""Apply the additive authentication migration to an existing database."""

from pathlib import Path

from database import db


def migrate():
    with db() as conn:
        conn.execute((Path(__file__).resolve().parents[1] / "db" / "auth.sql").read_text())


if __name__ == "__main__":
    migrate()
    print("Authentication tables are ready. Existing data was preserved.")
