import pytest

from app import db


@pytest.fixture(autouse=True)
def clean():
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM moves")
    yield


def test_move_roundtrip():
    db.save_move("2026-10-22", "A", "2026-10-23")
    [row] = db.moves()
    assert (row["date"], row["session"], row["new_date"]) == ("2026-10-22", "A", "2026-10-23")
    assert row["created"]


def test_skip_is_null():
    db.save_move("2026-10-24", "run", None)
    assert db.moves()[0]["new_date"] is None


def test_move_twice_keeps_original():
    db.save_move("2026-10-22", "A", "2026-10-23")
    db.save_move("2026-10-22", "A", "2026-10-24")
    [row] = db.moves()
    assert (row["date"], row["new_date"]) == ("2026-10-22", "2026-10-24")


def test_delete_move():
    db.save_move("2026-10-22", "A", "2026-10-23")
    db.delete_move("2026-10-22", "A")
    assert db.moves() == []
