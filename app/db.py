import json
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
            CREATE TABLE IF NOT EXISTS run_details (
                id INTEGER PRIMARY KEY,
                splits TEXT NOT NULL,
                laps TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkins (
                week INTEGER PRIMARY KEY,
                feel INTEGER NOT NULL,
                pain INTEGER NOT NULL,
                note TEXT DEFAULT '',
                created TEXT NOT NULL
            );
            """
        )


def run_details(ids: list[int]) -> dict[int, dict]:
    """Stored Smashrun km splits and laps by activity id: {id: {"splits": [...], "laps": [...]}}."""
    if not ids:
        return {}
    with conn() as c:
        rows = c.execute(f"SELECT id, splits, laps FROM run_details WHERE id IN ({','.join('?' * len(ids))})", ids)
        return {r["id"]: {"splits": json.loads(r["splits"]), "laps": json.loads(r["laps"])} for r in rows}
