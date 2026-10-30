import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "marathon.db"))


def conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def backup_bytes() -> bytes:
    """A consistent snapshot of the whole database, as the bytes of a SQLite file."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "backup.db"
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target.read_bytes()


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
            CREATE TABLE IF NOT EXISTS strength_logs (
                date TEXT NOT NULL,
                exercise TEXT NOT NULL,
                weight_kg REAL,
                level TEXT,
                rung INTEGER DEFAULT 0,
                reps TEXT,
                target_reps INTEGER,
                rating TEXT,
                ankle_pain INTEGER,
                created TEXT,
                PRIMARY KEY (date, exercise)
            );
            CREATE TABLE IF NOT EXISTS snack_logs (
                date TEXT NOT NULL,
                item TEXT NOT NULL,
                PRIMARY KEY (date, item)
            );
            CREATE TABLE IF NOT EXISTS ankle_tests (
                date TEXT NOT NULL,
                test TEXT NOT NULL,
                injured REAL NOT NULL,
                other REAL,
                PRIMARY KEY (date, test)
            );
            CREATE TABLE IF NOT EXISTS ankle_checks (
                date TEXT PRIMARY KEY,
                worse INTEGER NOT NULL,
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS results (
                date TEXT PRIMARY KEY,
                km REAL NOT NULL,
                seconds INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS moves (
                date TEXT NOT NULL,
                session TEXT NOT NULL,
                new_date TEXT,
                created TEXT,
                PRIMARY KEY (date, session)
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


def save_log(row: dict) -> None:
    """Insert or replace one exercise log; `reps` is a list stored as JSON."""
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO strength_logs (date, exercise, weight_kg, level, rung, reps, target_reps,"
            " rating, ankle_pain, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row["date"], row["exercise"], row.get("weight_kg"), row.get("level"), row.get("rung", 0),
             json.dumps(row.get("reps", [])), row.get("target_reps"), row.get("rating"),
             row.get("ankle_pain"), row.get("created")),
        )


def logs(exercise: str | None = None) -> list[dict]:
    """Strength logs, newest first, optionally for one exercise."""
    sql, args = "SELECT * FROM strength_logs", ()
    if exercise is not None:
        sql, args = sql + " WHERE exercise = ?", (exercise,)
    with conn() as c:
        rows = c.execute(sql + " ORDER BY date DESC, exercise", args).fetchall()
    return [{**dict(r), "reps": json.loads(r["reps"] or "[]")} for r in rows]


def toggle_snack(day: str, item: str) -> None:
    with conn() as c:
        if c.execute("DELETE FROM snack_logs WHERE date = ? AND item = ?", (day, item)).rowcount == 0:
            c.execute("INSERT INTO snack_logs (date, item) VALUES (?, ?)", (day, item))


def snacks() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT date, item FROM snack_logs ORDER BY date, item")]


def save_test(day: str, test: str, injured: float, other: float | None) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO ankle_tests (date, test, injured, other) VALUES (?,?,?,?)",
                  (day, test, injured, other))


def tests() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ankle_tests ORDER BY date, test")]


def save_check(day: str, worse: bool, note: str = "") -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO ankle_checks (date, worse, note) VALUES (?,?,?)",
                  (day, int(worse), note))


def checks() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ankle_checks ORDER BY date")]


def save_move(day: str, session: str, new_date: str | None) -> None:
    """A session ("run", "A" or "B") planned on `day` moved to `new_date`, or skipped when it is None."""
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO moves (date, session, new_date, created) VALUES (?,?,?,?)",
                  (day, session, new_date, datetime.now().isoformat(timespec="seconds")))


def delete_move(day: str, session: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM moves WHERE date = ? AND session = ?", (day, session))


def moves() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM moves ORDER BY date, session")]


def save_result(day: str, km: float, seconds: int) -> None:
    """A race or time trial; one per day."""
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO results (date, km, seconds) VALUES (?,?,?)", (day, km, seconds))


def delete_result(day: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM results WHERE date = ?", (day,))


def results() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM results ORDER BY date")]


def set_meta(key: str, value: str) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))


def get_meta(key: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
