from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.pace_engine import fmt_pace, from_result, parse_time

GOAL = parse_time("3:59:00")


def test_a_result_within_reach_keeps_marathon_pace_clear_of_threshold(settings):
    r = from_result(settings["paces"], GOAL, 5, parse_time("25:30"))
    p = r["paces"]
    assert [fmt_pace(p[k]) for k in ("easy", "long", "tempo", "interval")] == ["7:02", "6:44", "5:37", "5:06"]
    # goal pace 5:41 is only 4 s off threshold today, so MP work sits 10 s slower than threshold for now
    assert r["verdict"] == "within reach" and r["mp_source"] == "threshold"
    assert p["marathon"] == p["tempo"] + 10 and p["tempo"] <= p["subthreshold"] < p["marathon"]


def test_paces_stay_in_order(settings):
    for km, t in ((5, "22:00"), (5, "25:30"), (5, "26:30"), (5, "30:00"), (10, "48:00"), (21.0975, "1:59:00")):
        p = from_result(settings["paces"], GOAL, km, parse_time(t))["paces"]
        assert p["interval"] < p["tempo"] <= p["subthreshold"] < p["marathon"] < p["long"] < p["easy"], (km, t)


def test_an_ambitious_goal_trains_at_the_predicted_pace(settings):
    r = from_result(settings["paces"], GOAL, 5, parse_time("26:30"))
    assert r["verdict"] == "ambitious" and r["mp_source"] == "result"
    assert fmt_pace(r["paces"]["marathon"]) == "6:09" and r["paces"]["subthreshold"] == r["paces"]["marathon"] - 9


def test_a_fast_result_is_on_track(settings):
    r = from_result(settings["paces"], GOAL, 10, parse_time("48:00"))
    assert r["verdict"] == "on track" and r["mp_source"] == "goal"
    assert r["paces"]["marathon"] == settings["paces"]["marathon"]


MON_W3 = date(2026, 11, 2)


def _clear():
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM results")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def test_logged_result_sets_the_paces_from_its_day(client, monkeypatch, settings):
    monkeypatch.setattr(main, "today", lambda: MON_W3)
    r = client.post("/result", data={"date": "2026-11-01", "km": "5", "time": "25:30"}, follow_redirects=False)
    assert r.status_code == 303
    s, _ = main.build_view()
    assert fmt_pace(s["paces"]["easy"]) == "7:02" and s["result"]["verdict"] == "within reach"
    page = client.get("/").text
    assert "Within reach" in page and "25:30" in page
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 31))  # before the result: settings paces
    s, _ = main.build_view()
    assert s["paces"] == settings["paces"] and s.get("result") is None


def test_bad_results_are_refused_and_can_be_deleted(client, monkeypatch, settings):
    monkeypatch.setattr(main, "today", lambda: MON_W3)
    for data in ({"date": "2026-11-01", "km": "5", "time": "soon"}, {"date": "2026-11-09", "km": "5", "time": "25:30"},
                 {"date": "2026-11-01", "km": "7", "time": "25:30"}):
        client.post("/result", data=data)
    assert db.results() == []
    client.post("/result", data={"date": "2026-11-01", "km": "10", "time": "53:00"})
    client.post("/result/delete", data={"date": "2026-11-01"})
    assert db.results() == [] and main.build_view()[0]["paces"] == settings["paces"]
