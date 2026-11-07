"""view.build_view and view.dashboard are pure: they run on hand-made facts, with no database or server."""
import copy
from datetime import date, timedelta

from app import db, strength, view
from app.config import load_settings

TUE_W3 = date(2026, 11, 3)


def facts(**over) -> view.Facts:
    base = dict(settings=load_settings(), actual={}, details={}, checkins={}, moves=[], goals=[], results=[],
                logs=[], checks=[], tests=[], snacks=[], fuel_days=set(), last_sync=None,
                equipment=strength.load_equipment())
    return view.Facts(**{**base, **over})


def test_builds_without_touching_the_database(monkeypatch):
    def no_db():
        raise AssertionError("build_view opened the database")
    monkeypatch.setattr(db, "conn", no_db)
    run = {"km": 6.2, "seconds": 2480, "hr": [140], "main": {"id": 1, "km": 6.2, "seconds": 2480}}
    s, weeks = view.build_view(facts(actual={"2026-11-02": run}), TUE_W3)
    monday = weeks[2]["workouts"][0]
    assert monday["date"] == date(2026, 11, 2) and monday["actual_km"] == 6.2
    assert weeks[2]["is_current"] and weeks[2]["actual_km"] == 6.2


def test_leaves_the_facts_as_they_were():
    f = facts(goals=[{"date": "2026-11-01", "goal_time": "4:09:00"}],
              results=[{"date": "2026-11-01", "km": 5.0, "seconds": 1560}])
    before = copy.deepcopy(f.settings)
    s, _ = view.build_view(f, TUE_W3)
    assert s["goal_time"] == "4:09:00" and s["paces"] != before["paces"]
    assert f.settings == before  # the goal and result changed the view's settings, not the facts'


def test_a_check_in_trims_the_next_week():
    plain = view.build_view(facts(), TUE_W3)[1]
    rough = view.build_view(facts(checkins={2: {"week": 2, "feel": 3, "pain": 5, "note": ""}}), TUE_W3)[1]
    assert rough[2]["factor"] == 0.8 and rough[2]["target_km"] < plain[2]["target_km"]


def page(t=TUE_W3, expires=None, **over):
    s, weeks = view.build_view(facts(**over), t)
    return view.dashboard(s, weeks, t, [], expires)


def test_this_week_without_a_server():
    p = page()
    assert p["week"]["week"] == 3 and p["prev_week"]["week"] == 2
    assert p["next_run"]["date"] == date(2026, 11, 4)  # Tuesday is a rest day: Wednesday's session is next
    assert p["profile"]["current"] == 2 and p["profile"]["actual"][3] is None  # nothing ahead of today
    assert p["days_left"] == (date(2027, 3, 14) - TUE_W3).days


def test_todays_run_stays_next_until_it_syncs():
    wed = date(2026, 11, 4)
    assert page(wed)["next_run"]["date"] == wed
    run = {"km": 8.0, "seconds": 3000, "hr": [], "main": {"id": 1, "km": 8.0, "seconds": 3000}}
    assert page(wed, actual={wed.isoformat(): run})["next_run"]["date"] > wed


def test_on_a_day_with_two_runs_the_longer_is_next():
    # Saturday's easy run moved onto Sunday's long run
    p = page(date(2026, 11, 7), moves=[{"date": "2026-11-07", "session": "run", "new_date": "2026-11-08"}])
    sunday = [wo for wo in p["week"]["workouts"] if wo["date"] == date(2026, 11, 8)]
    assert len(sunday) == 2 and p["next_run"] is max(sunday, key=lambda wo: wo["km"])


def test_token_warning_only_in_the_last_week():
    assert page(expires=TUE_W3 + timedelta(days=8))["token_warning"] is None
    assert page(expires=TUE_W3 + timedelta(days=7))["token_warning"]["days"] == 7
    assert page(expires=TUE_W3 - timedelta(days=1))["token_warning"]["days"] == -1  # ran out: still shown
