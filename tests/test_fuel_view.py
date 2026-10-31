from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "checkins", "moves"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 31))
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def long_run(weeks, n):
    return next(wo for wo in weeks[n - 1]["workouts"] if wo["type"] == "long")


def test_long_run_notes_on_the_plan(client):
    _, weeks = main.build_view()
    assert all(long_run(weeks, n)["fuel"] is None for n in (1, 2, 3, 4, 7))
    assert "(2 gels)" in long_run(weeks, 5)["fuel"]
    peak = long_run(weeks, 18)["fuel"]
    assert "(5 gels)" in peak and "marathon-pace part" in peak
    assert all(wo["fuel"] is None for w in weeks for wo in w["workouts"] if wo["type"] != "long")


def test_trimmed_long_run_follows_its_km(client):
    with db.conn() as c:
        c.execute("INSERT INTO checkins (week, feel, pain, note, created) VALUES (4, 3, 5, '', 'x')")
    _, weeks = main.build_view()
    lr = long_run(weeks, 5)
    assert lr["km"] == 11 and lr["fuel"] is None


def test_race_has_no_long_run_note(client):
    _, weeks = main.build_view()
    assert all(wo["fuel"] is None for wo in weeks[-1]["workouts"])


def test_note_shows_on_this_week_and_plan(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 16))
    assert "Fuel practice:" in client.get("/").text
    assert "Fuel: 2 gels" in client.get("/plan").text
