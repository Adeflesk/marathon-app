import io
import json
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, garmin, main

THU, FRI, SAT, SUN = (date(2026, 10, d) for d in (22, 23, 24, 25))
TABLES = ("strength_logs", "snack_logs", "ankle_tests", "ankle_checks", "checkins", "activities", "run_details", "moves")


def _clear():
    db.init()
    with db.conn() as c:
        for t in TABLES:
            c.execute(f"DELETE FROM {t}")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day: date):
    monkeypatch.setattr(main, "today", lambda: day)


def run(day: date, km: float, rid: int, details=False):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO activities VALUES (?, ?, ?, ?, 145)", (rid, day.isoformat(), km, int(km * 400)))
        if details:
            sp = [{"distance": float(i), "seconds": 400 * i, "heartRate": 140} for i in range(1, int(km) + 1)]
            c.execute("INSERT OR REPLACE INTO run_details VALUES (?, ?, ?)", (rid, json.dumps(sp), "[]"))


def workouts_on(weeks, day):
    return [wo for w in weeks for wo in w["workouts"] if wo["date"] == day]


# --- Task 3: moves applied to the view ---

def test_moved_strength_is_tomorrows_card(client, monkeypatch):
    on(monkeypatch, FRI)
    db.save_move(THU.isoformat(), "A", FRI.isoformat())
    page = client.get("/")
    sess = page.context["strength_session"]
    assert sess["key"] == "A" and sess["date"] == FRI and sess["moved_from"] == THU
    client.post("/strength/log", data={"date": FRI.isoformat(), "exercise": "calf_raise_straight", "weight": "",
                                       "rung": "0", "target_reps": "12", "rep1": "12", "rating": "right"})
    _, weeks = main.build_view()
    a = next(s for s in weeks[0]["strength"] if s["key"] == "A")
    assert next(e for e in a["exercises"] if e["key"] == "calf_raise_straight")["log"] is not None
    on(monkeypatch, SAT)
    assert client.get("/").context["morning_check"] is True  # the morning after the new day


def test_skipped_run_out_of_target(client, monkeypatch):
    on(monkeypatch, SAT)
    db.save_move(SAT.isoformat(), "run", None)
    s, weeks = main.build_view()
    assert weeks[0]["target_km"] == 20.5
    assert client.get("/").context["next_run"]["date"] == SUN


def test_run_on_skipped_day_still_counts(client, monkeypatch):
    on(monkeypatch, SUN)
    db.save_move(SAT.isoformat(), "run", None)
    run(SAT, 4.5, 501)
    _, weeks = main.build_view()
    assert weeks[0]["actual_km"] == 4.5
    [sat] = workouts_on(weeks, SAT)
    assert sat["skipped"] and sat["compliance"] is None and sat["actual_km"] is None


def test_two_runs_one_day_share_actuals(client, monkeypatch):
    on(monkeypatch, SUN)
    db.save_move(SAT.isoformat(), "run", SUN.isoformat())
    run(SUN, 14.0, 502, details=True)
    _, weeks = main.build_view()
    pair = workouts_on(weeks, SUN)
    assert len(pair) == 2
    assert all(wo["actual_km"] == 14.0 and wo["compliance"] == round(100 * 14 / 14.5) for wo in pair)
    longer, shorter = sorted(pair, key=lambda wo: -wo["km"])
    assert longer["review"] is not None and shorter["review"] is None


def test_fit_route_picks_nth_run(client, monkeypatch):
    on(monkeypatch, SAT)
    db.save_move(SAT.isoformat(), "run", SUN.isoformat())
    a = client.get(f"/workout/{SUN.isoformat()}.fit?n=0")
    b = client.get(f"/workout/{SUN.isoformat()}.fit?n=1")
    assert a.status_code == b.status_code == 200 and a.content != b.content
    names = zipfile.ZipFile(io.BytesIO(client.get("/workouts/week/1.zip").content)).namelist()
    assert len(names) == len(set(names)) == 4


def test_skipped_run_has_no_fit(client, monkeypatch):
    on(monkeypatch, FRI)
    db.save_move(SAT.isoformat(), "run", None)
    assert client.get(f"/workout/{SAT.isoformat()}.fit").status_code == 404
    names = zipfile.ZipFile(io.BytesIO(client.get("/workouts/week/1.zip").content)).namelist()
    assert len(names) == 3


def test_moved_run_keeps_own_factor(client, monkeypatch):
    on(monkeypatch, SUN)
    with db.conn() as c:  # week 1 check-in, pain 5: week 2 runs at 0.8
        c.execute("INSERT INTO checkins(week, feel, pain, note, created) VALUES (1, 3, 5, '', 'x')")
    db.save_move(SUN.isoformat(), "run", "2026-10-26")
    _, weeks = main.build_view()
    moved = next(wo for wo in weeks[1]["workouts"] if wo.get("moved_from") == SUN)
    assert moved["km"] == 10
    assert sum(wo["km"] for wo in weeks[0]["workouts"]) == weeks[0]["target_km"] == 15


# --- Task 4: buttons, the clash warning and the routes ---

def post_move(client, day, session, confirm="", orig=None):
    data = {"date": day.isoformat(), "session": session, "confirm": confirm}
    if orig:
        data["orig"] = orig.isoformat()
    return client.post("/move", data=data, follow_redirects=False)


def test_move_strength_no_clash(client, monkeypatch):
    on(monkeypatch, THU)
    r = post_move(client, THU, "A")
    assert r.status_code == 303 and "confirm" not in r.headers["location"]
    [m] = db.moves()
    assert (m["date"], m["session"], m["new_date"]) == ("2026-10-22", "A", "2026-10-23")


def test_move_run_onto_long_run_warns(client, monkeypatch):
    on(monkeypatch, SAT)
    r = post_move(client, SAT, "run")
    assert r.status_code == 303 and "confirm=run" in r.headers["location"]
    assert db.moves() == []
    page = client.get(r.headers["location"]).text
    assert "Sunday already has your long run" in page
    assert "Better to skip Saturday" in page
    assert 'value="skip"' in page and 'value="move"' in page


def test_skip_and_move_anyway(client, monkeypatch):
    on(monkeypatch, SAT)
    post_move(client, SAT, "run", confirm="skip")
    assert db.moves()[0]["new_date"] is None
    _clear()
    post_move(client, SAT, "run", confirm="move")
    assert db.moves()[0]["new_date"] == SUN.isoformat()


def test_move_twice_then_undo(client, monkeypatch):
    on(monkeypatch, THU)
    post_move(client, THU, "A")
    on(monkeypatch, FRI)
    post_move(client, FRI, "A", orig=THU)
    [m] = db.moves()
    assert (m["date"], m["new_date"]) == (THU.isoformat(), SAT.isoformat())
    r = client.post("/move/undo", data={"date": THU.isoformat(), "session": "A"}, follow_redirects=False)
    assert r.status_code == 303 and db.moves() == []
    _, weeks = main.build_view()
    assert next(s for s in weeks[0]["strength"] if s["key"] == "A")["date"] == THU


def test_move_rejects_bad_requests(client, monkeypatch):
    on(monkeypatch, FRI)
    for day, session in ((THU, "A"), (FRI, "X"), (FRI, "run"), (date(2027, 3, 13), "run"), (FRI, "B")):
        r = post_move(client, day, session)
        assert r.status_code == 303 and "msg=" in r.headers["location"], (day, session)
    r = client.post("/move", data={"date": "nonsense", "session": "run"}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert db.moves() == []


def test_no_move_button_once_done(client, monkeypatch):
    on(monkeypatch, THU)
    db.save_log({"date": THU.isoformat(), "exercise": "rdl", "weight_kg": 40.0, "reps": [8, 8], "target_reps": 8,
                 "rating": "right"})
    page = client.get("/").text
    assert 'name="session" value="A"' not in page
    r = post_move(client, THU, "A")
    assert "msg=" in r.headers["location"] and db.moves() == []


def test_buttons_render(client, monkeypatch):
    on(monkeypatch, THU)
    page = client.get("/").text
    assert "Move to tomorrow" in page and 'name="session" value="A"' in page
    post_move(client, THU, "A")
    on(monkeypatch, FRI)
    page = client.get("/").text
    assert "Moved from Thursday" in page and 'action="/move/undo"' in page


def test_skipped_shows_with_undo(client, monkeypatch):
    on(monkeypatch, SAT)
    post_move(client, SAT, "run", confirm="skip")
    page = client.get("/").text
    assert "Skipped" in page and 'action="/move/undo"' in page
