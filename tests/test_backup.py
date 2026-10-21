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
