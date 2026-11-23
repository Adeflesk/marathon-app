from datetime import date, timedelta

import pytest

from app import db, main, scorecard
from tests.test_summaries import clean, lifted, ran  # noqa: F401  (clean is an autouse fixture)

START = date(2026, 10, 19)  # plan week 1


@pytest.fixture(autouse=True)
def no_tests():
    """test_summaries' clean() leaves ankle_tests alone; these tests write to it."""
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM ankle_tests")
    yield
    with db.conn() as c:
        c.execute("DELETE FROM ankle_tests")


def view(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)
    return main.build_view()


def do_week(monkeypatch, n, pace=405, hr=150, long_drift=0, share=1.0, long_km=None):
    """Run week n's planned runs (share of each), easy at `pace`, the long run at the same pace."""
    _, weeks = view(monkeypatch, date(2027, 3, 1))
    w = weeks[n - 1]
    for wo in w["workouts"]:
        if wo["km"] <= 0 or wo.get("skipped"):
            continue
        km = round((long_km if (long_km and wo["type"] == "long") else wo["km"]) * share, 1)
        ran(wo["date"].isoformat(), km, pace, hr=hr, drift_hr=long_drift if wo["type"] == "long" else 0)


def checkin(week, feel, pain=0):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO checkins(week, feel, pain, note, created) VALUES (?,?,?,?,?)",
                  (week, feel, pain, "", "2026-10-01T00:00:00"))


def synced_to(day):
    db.set_meta("last_sync", f"{day}T23:00:00")


def running(monkeypatch, day, n):
    s, weeks = view(monkeypatch, day)
    return {r["key"]: r for r in scorecard.running_rows(weeks, n - 1, s, s["paces"]["easy"])}


def test_fitness_up_when_heart_rate_drops(monkeypatch):
    for n, hr in ((1, 150), (2, 150), (3, 150), (4, 146)):
        do_week(monkeypatch, n, hr=hr)
    synced_to("2026-11-15")
    rows = running(monkeypatch, date(2026, 11, 16), 4)
    assert rows["fitness"]["arrow"] == "up" and rows["fitness"]["group"] == "running" and rows["fitness"]["past"]


def test_fitness_down_when_heart_rate_rises(monkeypatch):
    for n, hr in ((1, 150), (2, 150), (3, 153)):
        do_week(monkeypatch, n, hr=hr)
    assert running(monkeypatch, date(2026, 11, 9), 3)["fitness"]["arrow"] == "down"


def test_fitness_dash_with_one_prior_week(monkeypatch):
    for n in (1, 2):
        do_week(monkeypatch, n)
    assert running(monkeypatch, date(2026, 11, 2), 2)["fitness"]["arrow"] is None


def test_long_run_down_on_drift(monkeypatch):
    do_week(monkeypatch, 1, long_drift=14)
    assert running(monkeypatch, date(2026, 10, 26), 1)["long"]["arrow"] == "down"


def test_long_run_up_when_longest_and_steady(monkeypatch):
    do_week(monkeypatch, 1, long_km=8)
    do_week(monkeypatch, 2, long_km=10)
    assert running(monkeypatch, date(2026, 11, 2), 2)["long"]["arrow"] == "up"


def test_long_run_flat_when_steady_not_longest(monkeypatch):
    do_week(monkeypatch, 1, long_km=10)
    do_week(monkeypatch, 2, long_km=10)
    assert running(monkeypatch, date(2026, 11, 2), 2)["long"]["arrow"] == "flat"


def test_plan_done_dash_when_not_synced(monkeypatch):
    do_week(monkeypatch, 1)
    synced_to("2026-10-22")  # before week 1 ended
    rows = running(monkeypatch, date(2026, 10, 27), 1)
    assert rows["plan"]["arrow"] is None and not rows["plan"]["past"]


def test_plan_done_thresholds(monkeypatch):
    synced_to("2026-11-15")
    for share, arrow in ((1.0, "up"), (0.86, "flat"), (0.7, "down")):
        clean_runs()
        do_week(monkeypatch, 1, share=share)
        assert running(monkeypatch, date(2026, 10, 27), 1)["plan"]["arrow"] == arrow, share


def clean_runs():
    with db.conn() as c:
        c.execute("DELETE FROM activities")
        c.execute("DELETE FROM run_details")


def test_feel_down_at_two_or_below(monkeypatch):
    do_week(monkeypatch, 1)
    checkin(1, 2)
    assert running(monkeypatch, date(2026, 10, 27), 1)["feel"]["arrow"] == "down"


def test_feel_dash_without_checkin_or_history(monkeypatch):
    do_week(monkeypatch, 1)
    assert running(monkeypatch, date(2026, 10, 27), 1)["feel"]["arrow"] is None
    checkin(1, 4)
    assert running(monkeypatch, date(2026, 10, 27), 1)["feel"]["arrow"] is None  # nothing before to compare


def test_feel_against_prior_weeks(monkeypatch):
    for n in (1, 2, 3):
        checkin(n, 4)
    checkin(4, 3)
    assert running(monkeypatch, date(2026, 11, 16), 4)["feel"]["arrow"] == "down"
    checkin(4, 5)
    assert running(monkeypatch, date(2026, 11, 16), 4)["feel"]["arrow"] == "up"
    checkin(4, 4)
    assert running(monkeypatch, date(2026, 11, 16), 4)["feel"]["arrow"] == "flat"


def test_mp_dash_without_mp_work(monkeypatch):
    do_week(monkeypatch, 1)
    assert running(monkeypatch, date(2026, 10, 27), 1)["mp"]["arrow"] is None


def test_running_row_keys_in_order(monkeypatch):
    do_week(monkeypatch, 1)
    s, weeks = view(monkeypatch, date(2026, 10, 27))
    assert [r["key"] for r in scorecard.running_rows(weeks, 0, s, s["paces"]["easy"])] == \
        ["fitness", "long", "plan", "mp", "form", "feel"]


# --- strength and ankle ---

def strength(monkeypatch, day, n):
    s, weeks = view(monkeypatch, day)
    return {r["key"]: r for r in scorecard.strength_rows(weeks, n - 1, weeks[0]["ankle_state"])}


def test_strength_done_all_up(monkeypatch):
    lifted("2026-10-20", "calf_raise_bent")
    lifted("2026-10-22", "box_squat")
    row = strength(monkeypatch, date(2026, 10, 27), 1)["sessions"]
    assert row["arrow"] == "up" and row["group"] == "strength" and not row["past"]


def test_strength_done_none_is_down(monkeypatch):
    assert strength(monkeypatch, date(2026, 10, 27), 1)["sessions"]["arrow"] == "down"


def test_strength_done_ignores_skipped(monkeypatch):
    lifted("2026-10-22", "box_squat")
    db.save_move("2026-10-20", "B", None)
    assert strength(monkeypatch, date(2026, 10, 27), 1)["sessions"]["arrow"] == "up"
    db.save_move("2026-10-22", "A", None)
    assert strength(monkeypatch, date(2026, 10, 27), 1)["sessions"]["arrow"] is None


def lift(day, kg, exercise="box_squat"):
    db.save_log({"date": day, "exercise": exercise, "weight_kg": kg, "reps": [8, 8], "rating": "right",
                 "ankle_pain": 1})


def test_loads_up_when_weight_rises(monkeypatch):
    lift("2026-10-22", 40)
    lift("2026-11-19", 45)
    row = strength(monkeypatch, date(2026, 11, 23), 5)["loads"]
    assert row["arrow"] == "up" and row["past"]


def test_loads_down_when_weight_drops(monkeypatch):
    lift("2026-10-22", 45)
    lift("2026-11-19", 40)
    assert strength(monkeypatch, date(2026, 11, 23), 5)["loads"]["arrow"] == "down"


def test_loads_held_is_flat_in_build_and_up_in_cutback(monkeypatch):
    lift("2026-10-22", 40)
    lift("2026-11-19", 40)
    assert strength(monkeypatch, date(2026, 11, 23), 5)["loads"]["arrow"] == "flat"
    lift("2026-12-03", 40)  # week 7 is a cutback
    assert strength(monkeypatch, date(2026, 12, 7), 7)["loads"]["arrow"] == "up"


def test_loads_dash_without_history(monkeypatch):
    assert strength(monkeypatch, date(2026, 10, 27), 1)["loads"]["arrow"] is None


def weekly_lifts(first, last):
    d = first
    while d <= last:
        lifted(d.isoformat(), "calf_raise_bent")
        d += timedelta(days=7)


def test_stages_down_when_hop_steps_back(monkeypatch):
    db.save_test("2026-10-20", "pogo_trial", 1, None)  # stage 0 from 21 Oct, stage 1 from 4 Nov
    weekly_lifts(date(2026, 10, 20), date(2026, 12, 1))
    db.save_check("2026-12-02", True, "sore")  # week 7: steps back to 0
    rows = strength(monkeypatch, date(2026, 12, 7), 7)
    assert rows["stages"]["arrow"] == "down" and rows["stages"]["past"]


def test_stages_early_weeks_compare_with_plan_start(monkeypatch):
    db.save_test("2026-10-20", "pogo_trial", 1, None)
    weekly_lifts(date(2026, 10, 20), date(2026, 10, 27))
    assert strength(monkeypatch, date(2026, 11, 2), 2)["stages"]["arrow"] in ("flat", "up")


def test_ankle_down_on_trigger_in_week(monkeypatch):
    db.save_check("2026-10-23", True, "sore")
    row = strength(monkeypatch, date(2026, 10, 27), 1)["ankle"]
    assert row["arrow"] == "down" and not row["past"]


def test_ankle_flat_without_trigger(monkeypatch):
    assert strength(monkeypatch, date(2026, 10, 27), 1)["ankle"]["arrow"] == "flat"


def test_ankle_up_when_tests_meet_more_targets(monkeypatch):
    db.save_test("2026-10-21", "calf_raises", 20, 30)
    db.save_test("2026-11-11", "calf_raises", 26, 30)  # week 4 is a test week
    assert strength(monkeypatch, date(2026, 11, 16), 4)["ankle"]["arrow"] == "up"


def test_snacks_thresholds(monkeypatch):
    for days, arrow in ((4, "up"), (2, "flat"), (1, "down")):
        with db.conn() as c:
            c.execute("DELETE FROM snack_logs")
        for k in range(days):
            db.toggle_snack((START + timedelta(days=k)).isoformat(), "band_eversion")
        assert strength(monkeypatch, date(2026, 10, 27), 1)["snacks"]["arrow"] == arrow, days


def test_strength_row_keys_in_order(monkeypatch):
    s, weeks = view(monkeypatch, date(2026, 10, 27))
    assert [r["key"] for r in scorecard.strength_rows(weeks, 0, weeks[0]["ankle_state"])] == \
        ["sessions", "loads", "stages", "ankle", "snacks"]
