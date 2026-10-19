import pytest

from app import db


@pytest.fixture(autouse=True)
def fresh_tables():
    db.init()
    with db.conn() as c:
        for t in ("strength_logs", "snack_logs", "ankle_tests", "ankle_checks"):
            c.execute(f"DELETE FROM {t}")


def row(**kw):
    base = {"date": "2026-10-22", "exercise": "box_squat", "weight_kg": 20.0, "level": None, "rung": 0,
            "reps": [8, 8, 7], "target_reps": 8, "rating": "ok", "ankle_pain": None,
            "created": "2026-10-22T10:00:00"}
    return {**base, **kw}


def test_log_roundtrip():
    db.save_log(row())
    (got,) = db.logs("box_squat")
    assert got["reps"] == [8, 8, 7]
    assert got["weight_kg"] == 20.0
    assert got["ankle_pain"] is None


def test_log_replaces_same_day():
    db.save_log(row(weight_kg=20.0))
    db.save_log(row(weight_kg=22.5))
    got = db.logs("box_squat")
    assert len(got) == 1
    assert got[0]["weight_kg"] == 22.5


def test_logs_newest_first_and_filter():
    db.save_log(row(date="2026-10-20"))
    db.save_log(row(date="2026-10-22"))
    db.save_log(row(date="2026-10-21", exercise="lunge"))
    assert [r["date"] for r in db.logs()] == ["2026-10-22", "2026-10-21", "2026-10-20"]
    assert [r["date"] for r in db.logs("box_squat")] == ["2026-10-22", "2026-10-20"]


def test_snack_toggle():
    db.toggle_snack("2026-10-22", "calf_raise")
    assert [(s["date"], s["item"]) for s in db.snacks()] == [("2026-10-22", "calf_raise")]
    db.toggle_snack("2026-10-22", "calf_raise")
    assert db.snacks() == []


def test_tests_and_checks_ordered():
    db.save_test("2026-10-25", "heel_raise", 18, 25)
    db.save_test("2026-10-18", "heel_raise", 15, None)
    assert [t["date"] for t in db.tests()] == ["2026-10-18", "2026-10-25"]
    assert db.tests()[0]["other"] is None
    db.save_check("2026-10-25", True, "sore")
    db.save_check("2026-10-18", False)
    got = db.checks()
    assert [c["date"] for c in got] == ["2026-10-18", "2026-10-25"]
    assert got[1]["worse"] == 1 and got[1]["note"] == "sore"
