from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main

MON_W3 = date(2026, 11, 2)


def _clear():
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM goals")
        c.execute("DELETE FROM results")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: MON_W3)
    with TestClient(main.app) as c:
        yield c
    _clear()


def _goal(client, goal):
    return client.post("/goal", data={"goal": goal}, follow_redirects=False)


def test_changing_the_goal_moves_marathon_pace(client):
    assert _goal(client, "4:09:00").status_code == 303
    s, _ = main.build_view()
    assert s["goal_time"] == "4:09:00"
    assert s["paces"]["marathon"] == 354 and s["paces"]["subthreshold"] == 345
    assert "4:09:00" in client.get("/").text


def test_back_to_the_settings_goal_restores_exact_paces(client, settings):
    _goal(client, "4:09:00")
    _goal(client, "3:59:00")
    s, _ = main.build_view()
    assert s["goal_time"] == "3:59:00" and s["paces"] == settings["paces"]  # 341, not 340
    assert [(g["from"], g["to"]) for g in s["goal_changes"]] == [("3:59:00", "4:09:00"), ("4:09:00", "3:59:00")]


def test_bad_goals_are_refused(client):
    for goal in ("soon", "1:00:00", "9:00:00"):
        _goal(client, goal)
    assert db.goals() == []


def test_goal_change_with_a_result(client):
    db.save_result("2026-11-01", 5.0, 1590)  # 26:30
    _goal(client, "4:09:00")
    s, _ = main.build_view()
    assert s["result"]["verdict"] == "within reach" and s["result"]["mp_source"] == "threshold"
    assert s["paces"]["marathon"] == s["paces"]["tempo"] + 10


def test_back_follows_a_later_settings_goal(client, monkeypatch, tmp_path):
    _goal(client, "4:09:00")
    _goal(client, "3:59:00")  # back to the settings goal
    from app import config
    f = tmp_path / "settings.json"
    f.write_text('{"goal_time": "4:00:00"}')
    monkeypatch.setattr(config, "SETTINGS_PATH", f)
    s, _ = main.build_view()
    assert s["goal_time"] == "4:00:00" and s["paces"]["marathon"] == 341  # the settings' pace, untouched
