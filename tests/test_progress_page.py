from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, main


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "strength_logs", "results", "goals", "checkins"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def test_progress_page_without_a_result(client, monkeypatch):
    on(monkeypatch, date(2026, 10, 30))
    page = client.get("/progress")
    assert page.status_code == 200
    assert "Not enough to call yet" in page.text and 'href="/progress"' in page.text


def test_progress_page_with_a_stretch(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 2))
    db.save_result("2026-11-01", 5.0, 1590)  # 26:30
    page = client.get("/progress").text
    assert "3:59 is a stretch" in page
    assert "predicts <strong>4:20</strong>" in page  # rounded up, like the prediction card
    assert 'name="goal" value="4:09:00"' in page and "Train for 4:09" in page


def test_goal_change_shows_on_the_page(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 2))
    db.save_result("2026-11-01", 5.0, 1590)
    r = client.post("/goal", data={"goal": "4:09:00"}, follow_redirects=True)
    assert "Goal changed to 4:09" in r.text and "Back to 3:59" in r.text
    assert "from 3:59 to 4:09" in r.text


def test_this_week_shows_last_weeks_summary_monday_and_tuesday(client, monkeypatch):
    with db.conn() as c:
        c.execute("INSERT INTO activities (id, date, km, seconds, avg_hr) VALUES (1, '2026-10-25', 10, 3950, 150)")
    for day, shown in ((date(2026, 10, 26), True), (date(2026, 10, 27), True), (date(2026, 10, 28), False)):
        on(monkeypatch, day)
        page = client.get("/").text
        assert ("Last week, week 1" in page) is shown, day


def test_progress_renders_every_day(client, monkeypatch):
    db.save_result("2026-12-05", 5.0, 1530)
    day = date(2026, 10, 12)
    while day <= date(2027, 3, 21):
        on(monkeypatch, day)
        assert client.get("/progress").status_code == 200, day
        day += timedelta(days=3)
