"""Shared PostgreSQL connection factory."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


def db():
    # The connection context commits on success and rolls back on exceptions.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)
