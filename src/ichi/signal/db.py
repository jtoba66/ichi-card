"""PostgreSQL connection helper."""
from __future__ import annotations
import os

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get(
    "ICHI_DATABASE_URL",
    "postgresql://ichi:ichi@localhost/ichi_signals"
)


def get_conn():
    """Return a plain psycopg2 connection."""
    return psycopg2.connect(DATABASE_URL)


def dict_conn():
    """Connection whose cursors return RealDict rows."""
    return psycopg2.connect(DATABASE_URL)
