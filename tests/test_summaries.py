import json
from datetime import date

import pytest

from app import db, main, progress


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "strength_logs", "snack_logs", "ankle_checks", "checkins",
                      "results", "goals", "moves", "meta"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture(autouse=True)
def clean():
    _clear()
    yield
    _clear()


def ran(day, km, pace, hr=145, drift_hr=0, id_=None):
    """A synced run with km splits: steady heart rate, rising by drift_hr over the second half."""
    id_ = id_ or int(day.replace("-", ""))
    splits, n = [], int(km)
    for i in range(1, n + 1):
        splits.append({"distance": i, "seconds": pace * i, "heartRate": hr + (drift_hr if i > n / 2 else 0)})
    if km > n:
        splits.append({"distance": km, "seconds": pace * km, "heartRate": hr})
    with db.conn() as c:
        c.execute("INSERT INTO activities (id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)",
                  (id_, day, km, int(pace * km), hr))
        c.execute("INSERT INTO run_details (id, splits, laps) VALUES (?,?,?)", (id_, json.dumps(splits), "[]"))


def lifted(day, exercise, pain=1):
    db.save_log({"date": day, "exercise": exercise, "reps": [15, 15], "rating": "right", "ankle_pain": pain})


def week_one(pace=405, long_drift=0):
    for day, km in (("2026-10-19", 4.5), ("2026-10-21", 6), ("2026-10-24", 4.5)):
        ran(day, km, pace)
    ran("2026-10-25", 10, 395, drift_hr=long_drift)
    lifted("2026-10-20", "calf_raise_bent")  # Tuesday B
    lifted("2026-10-22", "box_squat")  # Thursday A


def summaries(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)
    s, weeks = main.build_view()
    return progress.summaries(weeks, s, weeks[0]["ankle_state"], db.results(), day)


def test_week_one_summary(monkeypatch):
    week_one(pace=390)  # easy runs at 6:30 against 6:45
    out = summaries(monkeypatch, date(2026, 10, 27))
    assert [x["week"] for x in out] == [1]
    w1 = out[0]
    assert (w1["planned"], w1["done"]) == (25, 25)
    assert any("Long run" in x for x in w1["sentences"])
    assert any("2 of 2" in x for x in w1["sentences"])
    assert w1["next"].startswith("Keep easy runs at 6:45/km")


def test_no_summary_for_current_week(monkeypatch):
    week_one()
    assert [x["week"] for x in summaries(monkeypatch, date(2026, 10, 28))] == [1]
    assert summaries(monkeypatch, date(2026, 10, 21)) == []


def test_low_week_focus(monkeypatch):
    ran("2026-12-16", 10, 405)  # week 9: 10 of 40 km
    db.set_meta("last_sync", "2026-12-20T19:00:00")
    out = summaries(monkeypatch, date(2026, 12, 21))
    assert out[0]["week"] == 9 and out[0]["next"].startswith("Ease back in")
    assert not any("Not synced" in x for x in out[0]["sentences"])


def test_unsynced_week_says_so_and_claims_no_hold(monkeypatch):
    ran("2026-12-16", 10, 405)
    db.set_meta("last_sync", "2026-12-17T07:00:00")  # before week 9 ended
    w9 = summaries(monkeypatch, date(2026, 12, 21))[0]
    assert "Not synced since this week ended, so runs may be missing." in w9["sentences"]
    assert not w9["next"].startswith("Ease back in")


def test_one_snack_day_reads_right(monkeypatch):
    week_one()
    db.toggle_snack("2026-10-19", "band_eversion")
    w1 = summaries(monkeypatch, date(2026, 10, 27))[0]
    assert "Ankle snacks on 1 day." in w1["sentences"]


def test_ankle_focus_wins(monkeypatch):
    week_one(pace=390)
    db.save_check("2026-10-23", True, "sore")
    assert summaries(monkeypatch, date(2026, 10, 27))[0]["next"].startswith("Ankle first")


def test_snacks_focus(monkeypatch):
    week_one()
    for day in ("2026-10-19", "2026-10-21"):
        db.toggle_snack(day, "band_eversion")
    w1 = summaries(monkeypatch, date(2026, 10, 27))[0]
    assert w1["next"] == "Tick 4 snack days next week: 2 this week."


def test_long_run_drift_focus(monkeypatch):
    week_one(long_drift=14)
    assert summaries(monkeypatch, date(2026, 10, 27))[0]["next"].startswith("Start the long run slower")


def test_all_good(monkeypatch):
    week_one()
    for day in ("2026-10-19", "2026-10-21", "2026-10-23", "2026-10-24"):
        db.toggle_snack(day, "band_eversion")
    assert summaries(monkeypatch, date(2026, 10, 27))[0]["next"] == "Keep doing what you're doing."
