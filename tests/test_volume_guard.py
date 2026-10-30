from datetime import date

from app.plan import generate, volume_caps

TODAY = date(2026, 10, 16)


def planned(settings):
    return [{"week": w["week"], "phase": w["phase"], "km": w["target_km"]} for w in generate(settings, TODAY)]


def done_as(weeks, **overrides):
    """Actual km per week: every week as planned, except overrides like w9=10."""
    actual = {w["week"]: w["km"] for w in weeks}
    actual.update({int(k[1:]): v for k, v in overrides.items()})
    return actual


def test_the_plan_as_written_is_never_capped(settings):
    weeks = planned(settings)
    assert volume_caps(weeks, done_as(weeks), {w["week"] for w in weeks}, 25) == {}


def test_a_low_week_holds_the_next_one_under_the_best_recent_week(settings):
    weeks = planned(settings)  # weeks 5–8: 31, 34, 27, 37; week 9 is 40
    caps = volume_caps(weeks, done_as(weeks, w9=10), set(range(1, 10)), 25)
    assert caps[10]["why"] == "hold" and caps[10]["km"] == 0.9 * 37
    assert caps[10]["last"] == (10, 40) and caps[10]["best"] == 37
    assert 11 not in caps  # the cutback is lower than any cap anyway


def test_after_a_hold_the_plan_is_rejoined_step_by_step(settings):
    weeks = planned(settings)
    held = volume_caps(weeks, done_as(weeks, w9=10), set(range(1, 10)), 25)[10]["km"]
    actual = done_as(weeks, w9=10, w10=held)  # week 10 done as capped, week 11 cutback done
    caps = volume_caps(weeks, actual, set(range(1, 12)), 25)
    assert caps[12]["why"] == "ramp" and caps[12]["km"] < 46
    actual[12] = caps[12]["km"]
    caps = volume_caps(weeks, actual, set(range(1, 13)), 25)
    assert 13 not in caps or caps[13]["km"] > caps[12]["km"]


def test_two_weeks_off_restarts_lower(settings):
    weeks = planned(settings)
    caps = volume_caps(weeks, done_as(weeks, w8=0, w9=0), set(range(1, 10)), 25)
    assert caps[10]["km"] == 0.9 * 34  # best of weeks 6–9 is week 6


def test_a_long_break_lands_at_the_rebuild_volume(settings):
    weeks = planned(settings)
    caps = volume_caps(weeks, done_as(weeks, w6=0, w7=0, w8=0, w9=0), set(range(1, 10)), 25)
    assert caps[10]["km"] == 25


def test_unknown_weeks_dont_count(settings):
    weeks = planned(settings)
    # week 9 at 10 km, but no sync since it ended: it isn't known, so it can't hold week 10
    assert 10 not in volume_caps(weeks, done_as(weeks, w9=10), set(range(1, 9)), 25)


def test_race_week_is_never_touched(settings):
    weeks = planned(settings)
    n = len(weeks)
    caps = volume_caps(weeks, done_as(weeks, **{f"w{n - 1}": 0, f"w{n - 2}": 0}), set(range(1, n)), 25)
    assert n not in caps  # the taper before it may be capped; race week keeps its race


def test_week_one_has_nothing_to_go_on(settings):
    weeks = planned(settings)
    assert 1 not in volume_caps(weeks, {}, set(), 25)


# --- through build_view and the dashboard ---

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, main  # noqa: E402

MON_W10 = date(2026, 12, 21)


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "meta", "checkins"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def _ran(weeks, km_by_week):
    """One run on each week's Sunday."""
    with db.conn() as c:
        for w in weeks:
            if w["week"] in km_by_week:
                day = (w["start"] + timedelta(days=6)).isoformat()
                c.execute("INSERT INTO activities (id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)",
                          (w["week"], day, km_by_week[w["week"]], int(km_by_week[w["week"]] * 400), 140))


def test_a_sick_week_holds_the_next_one_on_the_dashboard(client, monkeypatch, settings):
    monkeypatch.setattr(main, "today", lambda: MON_W10)
    weeks = generate(settings, MON_W10)
    _ran(weeks, {w["week"]: w["target_km"] for w in weeks[:8]} | {9: 10})
    db.set_meta("last_sync", "2026-12-21T07:00:00")
    _, view = main.build_view()
    w10 = view[9]
    assert w10["guard"]["why"] == "hold" and w10["guard"]["planned"] == 43
    assert abs(w10["target_km"] - 0.9 * 37) <= 1.5
    assert w10["factor"] == 1.0 and not any(s["reduced"] for s in w10["strength"])  # strength isn't trimmed
    assert "Held to" in client.get("/").text


def test_no_sync_since_the_sick_week_means_no_hold(client, monkeypatch, settings):
    monkeypatch.setattr(main, "today", lambda: MON_W10)
    weeks = generate(settings, MON_W10)
    _ran(weeks, {w["week"]: w["target_km"] for w in weeks[:8]} | {9: 10})
    db.set_meta("last_sync", "2026-12-19T07:00:00")  # Saturday of week 9: its Sunday isn't covered
    assert main.build_view()[1][9]["guard"] is None
    db.set_meta("last_sync", "2026-12-20T19:00:00")  # Sunday evening, after the long run: it counts
    assert main.build_view()[1][9]["guard"]["why"] == "hold"
