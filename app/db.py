import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "marathon.db"))


def conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                km REAL NOT NULL,
                seconds INTEGER NOT NULL,
                avg_hr INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_act_date ON activities(date);
            CREATE TABLE IF NOT EXISTS checkins (
                week INTEGER PRIMARY KEY,
                feel INTEGER NOT NULL,
                pain INTEGER NOT NULL,
                note TEXT DEFAULT '',
                created TEXT NOT NULL
            );
            """
        )
