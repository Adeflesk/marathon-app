import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ankle, db, main
from app.config import load_settings
from app.plan import generate

D0 = date(2026, 10, 19)  # plan week 1, a Monday
TABLES = ("strength_logs", "snack_logs", "ankle_tests", "ankle_checks", "checkins", "activities", "run_details")


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


def session(weeks, n, key):
    return next(x for x in weeks[n - 1]["strength"] if x["key"] == key)


def exercise(sess, key):
    return next(e for e in sess["exercises"] if e["key"] == key)


def test_log_post_saves_and_redirects(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=3))
    r = client.post("/strength/log", data={
        "date": "2026-10-22", "exercise": "rdl", "weight": "40", "level": "", "rung": "0", "target_reps": "8",
        "rep1": "10", "rep2": "9", "rep3": "", "rep4": "", "rep5": "", "rating": "right", "ankle_pain": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/#ex-rdl"
    [row] = db.logs("rdl")
    assert row["date"] == "2026-10-22" and row["weight_kg"] == 40.0
    assert row["reps"] == [10, 9] and row["target_reps"] == 8 and row["rating"] == "right"
    assert row["ankle_pain"] is None and row["level"] is None and row["created"]


def test_logged_exercise_shows_done_and_next_suggestion(client, monkeypatch):
    thu = D0 + timedelta(days=3)
    on(monkeypatch, thu)
    client.post("/strength/log", data={"date": thu.isoformat(), "exercise": "rdl", "weight": "40", "rung": "0",
                                       "target_reps": "8", "rep1": "10", "rep2": "10", "rating": "easy"})
    _, weeks = main.build_view()
    today_rdl = exercise(session(weeks, 1, "A"), "rdl")
    assert today_rdl["log"]["weight_kg"] == 40.0 and today_rdl["log"]["rating"] == "easy"
    nxt = exercise(session(weeks, 2, "A"), "rdl")
    assert nxt["log"] is None
    assert nxt["suggestion"]["weight"] == 45.0  # one 5 kg step up from an easy 40 kg at the top of the range
    page = client.get("/")
    assert page.context["strength_session"]["key"] == "A"


def test_snack_toggle_post(client, monkeypatch):
    mon = D0
    on(monkeypatch, mon)
    _, weeks = main.build_view()
    snack = weeks[0]["snack"][mon]
    assert snack["items"] == ankle.BALANCE_STAGES[0] and snack["done"] == set()
    assert sorted(weeks[0]["snack"]) == [D0 + timedelta(days=n) for n in (0, 2, 4, 5)]  # Mon, Wed, Fri, Sat
    r = client.post("/snack", data={"date": mon.isoformat(), "item": "eyes_open_stance"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#snack"
    _, weeks = main.build_view()
    assert weeks[0]["snack"][mon]["done"] == {"eyes_open_stance"}
    assert client.get("/").context["snack_today"]["done"] == {"eyes_open_stance"}
    client.post("/snack", data={"date": mon.isoformat(), "item": "eyes_open_stance"})
    assert db.snacks() == []
    # race week: only the first two items
    assert len(weeks[-1]["snack"][weeks[-1]["start"]]["items"]) == 2


def test_morning_check_post_raises_flag(client, monkeypatch):
    fri = D0 + timedelta(days=4)
    on(monkeypatch, fri)
    db.save_log({"date": (fri - timedelta(days=1)).isoformat(), "exercise": "calf_raise_straight",
                 "weight_kg": 10.0, "reps": [12, 12], "target_reps": 12, "rating": "right"})
    page = client.get("/")
    assert page.context["morning_check"] is True and page.context["ankle_flag"] is None
    r = client.post("/ankle/check", data={"date": fri.isoformat(), "worse": "1", "note": "stiff"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#ankle-check"
    assert db.checks() == [{"date": fri.isoformat(), "worse": 1, "note": "stiff"}]
    page = client.get("/")
    assert page.context["morning_check"] is False
    assert page.context["ankle_flag"] == fri + timedelta(days=7)
    _, weeks = main.build_view()
    assert session(weeks, 2, "A")["reduced"] is True  # the following Thursday
    assert session(weeks, 3, "A")["reduced"] is False  # the flag is down by then


def test_wed_bad_trims_thursday(client, monkeypatch):
    s = load_settings()
    wk8 = generate(s, D0)[7]
    q = next(x for x in wk8["workouts"] if "steps" in x)
    on(monkeypatch, q["date"])
    _, weeks = main.build_view()
    assert session(weeks, 8, "A")["reduced"] is False
    laps = [{"lapType": "warmup", "endDuration": 800, "endDistance": 2.0}]
    dur, dist = 800, 2.0
    for _ in range(4):  # every rep about 75 s/km slow
        dur, dist = dur + 400, dist + 1.0
        laps.append({"lapType": "work", "endDuration": dur, "endDistance": dist})
        dur, dist = dur + 60, dist + 0.15
        laps.append({"lapType": "recovery", "endDuration": dur, "endDistance": dist})
    with db.conn() as c:
        c.execute("INSERT INTO activities VALUES (902, ?, 7.6, 3200, 150)", (q["date"].isoformat(),))
        c.execute("INSERT INTO run_details VALUES (902, ?, ?)",
                  (json.dumps([{"distance": 1.0, "seconds": 400, "heartRate": 140}]), json.dumps(laps)))
    _, weeks = main.build_view()
    assert next(x for x in weeks[7]["workouts"] if "steps" in x)["review"]["verdict"] == "bad"
    thu = session(weeks, 8, "A")
    assert thu["reduced"] is True and "Wednesday" in thu["note"]
    assert session(weeks, 9, "A")["reduced"] is False


def test_tests_post_and_due_clears(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=1))
    page = client.get("/")
    assert page.context["tests_due"] is True
    assert page.context["injured_side"] == "right" and page.context["hop_stage"] is None
    data = {"date": D0.isoformat(), "pogo_trial_injured": "1", "pogo_trial_other": "",
            "calf_raises_injured": "22", "calf_raises_other": "27",
            "eyes_closed_balance_injured": "18", "eyes_closed_balance_other": "30",
            "y_balance_ant_injured": "60", "y_balance_ant_other": "70",
            "y_balance_pm_injured": "85", "y_balance_pm_other": "100",
            "y_balance_pl_injured": "85", "y_balance_pl_other": "100",
            "single_hop_injured": "", "single_hop_other": ""}
    r = client.post("/ankle/tests", data=data, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#tests"
    rows = {t["test"]: t for t in db.tests()}
    assert set(rows) == {"pogo_trial", "calf_raises", "eyes_closed_balance", "y_balance_ant", "y_balance_pm",
                         "y_balance_pl"}
    assert rows["pogo_trial"]["other"] is None and rows["calf_raises"]["other"] == 27.0
    page = client.get("/")
    assert page.context["tests_due"] is False
    assert page.context["hop_stage"] == 0  # pain-free pogo trial yesterday, fine morning
