from datetime import date

from app import db, main, scorecard
from tests.test_summaries import clean, ran  # noqa: F401  (clean is an autouse fixture)

START = date(2026, 10, 19)  # plan week 1


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
