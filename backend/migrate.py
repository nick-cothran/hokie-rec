"""Bring an existing database up to date: auth tables, roster rules, and the Phase III schema."""

from pathlib import Path

from database import db


def migrate():
    with db() as conn:
        for name in ("auth.sql", "roster.sql", "phase3.sql"):
            conn.execute((Path(__file__).resolve().parents[1] / "db" / name).read_text())


if __name__ == "__main__":
    migrate()
    print("Auth tables, roster rules, and the Phase III schema are ready. Existing data was preserved.")
