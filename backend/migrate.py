"""Apply the additive auth and roster migrations to an existing database."""

from pathlib import Path

from database import db


def migrate():
    with db() as conn:
        for name in ("auth.sql", "roster.sql"):
            conn.execute((Path(__file__).resolve().parents[1] / "db" / name).read_text())


if __name__ == "__main__":
    migrate()
    print("Auth tables and roster rules are ready. Existing data was preserved.")
