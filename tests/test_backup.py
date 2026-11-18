import sqlite3

from fastapi.testclient import TestClient

from app import db, main


def test_backup_downloads_a_readable_copy(tmp_path):
    db.init()
    db.toggle_snack("2026-10-22", "backup_probe")
    try:
        with TestClient(main.app) as c:
            r = c.get("/backup.db")
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
        copy = tmp_path / "copy.db"
        copy.write_bytes(r.content)
        rows = sqlite3.connect(copy).execute(
            "SELECT item FROM snack_logs WHERE item = 'backup_probe'"
        ).fetchall()
        assert rows == [("backup_probe",)]
    finally:
        db.toggle_snack("2026-10-22", "backup_probe")


def test_backup_leaves_out_the_garmin_token_and_its_temp_file(tmp_path, monkeypatch):
    import tempfile

    db.init()
    db.set_meta("garmin_token", "secret-token")
    db.set_meta("garmin_token_exp", "1999999999")
    db.set_meta("backup_probe", "kept")
    made = []
    real = tempfile.mkstemp
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    try:
        with TestClient(main.app) as c:
            r = c.get("/backup.db")
        assert r.status_code == 200
        copy = tmp_path / "copy.db"
        copy.write_bytes(r.content)
        keys = {k for (k,) in sqlite3.connect(copy).execute("SELECT key FROM meta")}
        assert "backup_probe" in keys and not keys & {"garmin_token", "garmin_token_exp"}
        assert b"secret-token" not in r.content  # not left behind in a free page either
        assert db.get_meta("garmin_token") == "secret-token"  # the live database keeps it
        assert made and all(not __import__("os").path.exists(p) for _, p in made)  # removed after sending
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM meta WHERE key IN ('garmin_token', 'garmin_token_exp', 'backup_probe')")
